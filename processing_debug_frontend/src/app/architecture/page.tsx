"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ProviderChoice,
  RuntimePreflight,
  RuntimeProfile,
  RuntimeSession,
  RuntimeSessionRequest,
  deleteRuntimeSession,
  jsonFetch,
  storeRuntimeSessionId,
} from "@/lib/api";
import { CloudPreflightDiagnostics } from "@/components/CloudPreflightDiagnostics";
import { summarizeCloudPreflight } from "@/lib/preflight";

type StageKey = "transcription" | "media_embedding" | "text_embedding" | "caption" | "verification" | "query_decomposition" | "reranker";
type SecretName = "gemini_api_key" | "openai_api_key" | "nvidia_api_key";
type SecretValues = Record<SecretName, string>;
type StageOption = NonNullable<RuntimeProfile["provider_options"]>[string][number];

const STAGE_KEYS: StageKey[] = [
  "transcription",
  "media_embedding",
  "text_embedding",
  "caption",
  "verification",
  "query_decomposition",
  "reranker",
];

const FALLBACK_PROFILES: RuntimeProfile[] = [
  {
    id: "self-hosted-v1",
    label: "Self-hosted",
    mode: "self-hosted",
    description: "Local models and local Qdrant.",
    collection_name: "video_windows",
    defaults: {
      providers: Object.fromEntries(STAGE_KEYS.map((stage) => [stage, ["caption", "verification", "reranker"].includes(stage) ? "none" : "local"])),
    },
    provider_options: {
      transcription: [{ provider: "local", model: "faster-whisper-small", label: "Local Whisper" }],
      media_embedding: [{ provider: "local", model: "xclip-base-patch32 + clap-htsat-unfused", label: "Local X-CLIP + CLAP" }],
      text_embedding: [{ provider: "local", model: "BAAI/bge-m3", label: "Local BGE-M3" }],
      caption: [
        { provider: "none", model: "selection_only", label: "Selection only (no caption VLM)" },
        { provider: "local_qwen", model: "Qwen/Qwen2.5-VL-3B-Instruct", label: "Local Qwen2.5-VL-3B captioner (on-demand, laptop default)" },
      ],
      verification: [{ provider: "none", model: "disabled", label: "Disabled (evidence is optional at search time)" }],
      query_decomposition: [{ provider: "local", model: "local query model", label: "Local query model" }],
      reranker: [
        { provider: "none", model: "disabled", label: "Disabled (RRF recall only)" },
        { provider: "local_qwen", model: "Qwen/Qwen3-VL-Reranker-2B", label: "Qwen3-VL-Reranker-2B (local, on-demand)" },
      ],
    },
  },
  {
    id: "api-gemini-free-v1",
    label: "API-based",
    mode: "api-based",
    description: "Gemini APIs and managed Qdrant Cloud.",
    collection_name: "video_windows_api_gemini_free_v1",
    defaults: {
      providers: Object.fromEntries(STAGE_KEYS.map((stage) => [stage, "gemini"])),
    },
    provider_options: {
      ...Object.fromEntries(STAGE_KEYS.filter((stage) => stage !== "reranker").map((stage) => [stage, [{ provider: "gemini", model: stage === "media_embedding" || stage === "text_embedding" ? "gemini-embedding-2" : "gemini-3.5-flash-lite", label: "Gemini free default", credential_required: true, cost_label: "Free tier, subject to quota" }]])),
      reranker: [
        { provider: "none", model: "disabled", label: "Disabled (RRF recall only)" },
        { provider: "local_qwen", model: "Qwen/Qwen3-VL-Reranker-2B", label: "Qwen3-VL-Reranker-2B (local, on-demand)", cost_label: "Local GPU or CPU, model download on first use" },
      ],
    },
    requires_cloud_consent: true,
    free_default: true,
  },
];

const API_SUPPORTED_PROVIDERS: Partial<Record<StageKey, ProviderChoice[]>> = {
  transcription: ["gemini"],
  media_embedding: ["gemini"],
  text_embedding: ["gemini"],
  caption: ["gemini", "openai", "cosmos"],
  verification: ["gemini", "openai", "cosmos"],
  query_decomposition: ["gemini"],
  reranker: ["none", "local_qwen"],
};

const STAGE_COPY: Record<StageKey, { eyebrow: string; title: string; explanation: string; output: string }> = {
  transcription: {
    eyebrow: "Indexing",
    title: "Timestamped transcription",
    explanation: "Speech is transcribed once, then each window receives the matching timestamped text.",
    output: "transcript text",
  },
  media_embedding: {
    eyebrow: "Indexing",
    title: "Visual + audio vectors",
    explanation: "The same media stage emits independent visual and audio vectors. They stay separate in Qdrant.",
    output: "visual + audio",
  },
  text_embedding: {
    eyebrow: "Indexing",
    title: "Transcript embeddings",
    explanation: "Each window transcript is encoded in its own text channel, not mixed with media vectors.",
    output: "transcript vector",
  },
  caption: {
    eyebrow: "Indexing",
    title: "Caption VLM",
    explanation: "A bounded selection of windows receives a generated visual description and caption vector.",
    output: "caption + vector",
  },
  verification: {
    eyebrow: "Query",
    title: "Evidence + localisation",
    explanation: "Only the final few reranked regions are inspected to explain the match and refine a 2–5 second moment.",
    output: "evidence + time span",
  },
  query_decomposition: {
    eyebrow: "Query",
    title: "Query expansion",
    explanation: "Turns one request into visual, audio, transcript, and caption prompts for compatible encoders.",
    output: "four prompts",
  },
  reranker: {
    eyebrow: "Precision",
    title: "Multimodal reranker",
    explanation: "Scores raw query evidence, sampled frames, transcript, and caption for only the RRF candidate list. It produces a fresh relevance score.",
    output: "fresh relevance score",
  },
};

function optionKey(option: StageOption): string {
  return `${option.provider}\u0000${option.model}`;
}

function providerCredential(provider: string): SecretName | undefined {
  if (provider === "gemini") return "gemini_api_key";
  if (provider === "openai") return "openai_api_key";
  if (provider === "cosmos") return "nvidia_api_key";
  return undefined;
}

function credentialLabel(credential: SecretName): string {
  if (credential === "gemini_api_key") return "Gemini API key";
  if (credential === "openai_api_key") return "OpenAI API key";
  return "NVIDIA API key";
}

function profileDefaults(profile: RuntimeProfile): Record<StageKey, string> {
  const providers = profile.defaults?.providers as Record<string, unknown> | undefined;
  return Object.fromEntries(STAGE_KEYS.map((stage) => {
    const options = profile.provider_options?.[stage] ?? [];
    const provider = typeof providers?.[stage] === "string" ? providers[stage] : undefined;
    const option = options.find((item) => item.provider === provider) ?? options[0];
    return [stage, option ? optionKey(option) : ""];
  })) as Record<StageKey, string>;
}

function isApiProfile(profile: RuntimeProfile | undefined): boolean {
  return profile?.mode === "api-based" || profile?.mode === "api_based";
}

function isAvailableOption(profile: RuntimeProfile | undefined, stage: StageKey, option: StageOption): boolean {
  if (!isApiProfile(profile)) return true;
  return API_SUPPORTED_PROVIDERS[stage]?.includes(option.provider as ProviderChoice) ?? false;
}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

type ArchitectureStageCardProps = {
  stage: StageKey;
  profile: RuntimeProfile | undefined;
  selections: Record<StageKey, string>;
  selectedOptions: Record<StageKey, StageOption | undefined>;
  credentialOwners: Map<SecretName, StageKey>;
  secrets: SecretValues;
  onSelectStage: (stage: StageKey, value: string) => void;
  onSetSecret: (credential: SecretName, value: string) => void;
};

function ArchitectureStageCard({
  stage,
  profile,
  selections,
  selectedOptions,
  credentialOwners,
  secrets,
  onSelectStage,
  onSetSecret,
}: ArchitectureStageCardProps) {
  const copy = STAGE_COPY[stage];
  const options = (profile?.provider_options?.[stage] ?? []).filter((option) => isAvailableOption(profile, stage, option));
  const selected = selectedOptions[stage];
  const credential = providerCredential(selected?.provider ?? "");
  const ownsCredential = credential && credentialOwners.get(credential) === stage;
  const reranker = stage === "reranker";
  const localQwenCaption = stage === "caption" && selected?.provider === "local_qwen";
  const experimentalCaptionProvider = isApiProfile(profile) && stage === "caption" && selected?.provider !== "gemini";
  return <article className={`architecture-stage ${reranker ? "architecture-reranker" : ""}`} aria-labelledby={`${stage}-title`}>
    <p className="architecture-kicker">{copy.eyebrow}</p>
    <h3 id={`${stage}-title`}>{copy.title}</h3>
    <p>{copy.explanation}</p>
    <label className="field">
      Model choice
      <select value={selections[stage]} onChange={(event) => onSelectStage(stage, event.target.value)}>
        {options.map((option) => <option key={optionKey(option)} value={optionKey(option)}>{option.label} · {option.model}</option>)}
      </select>
      {selected?.cost_label && <span>{selected.cost_label}</span>}
    </label>
    {credential && ownsCredential && <label className="field architecture-secret">
      {credentialLabel(credential)}
      <input type="password" value={secrets[credential]} onChange={(event) => onSetSecret(credential, event.target.value)} autoComplete="off" spellCheck={false} placeholder="Held only until activation" />
      <span>Sent once to create an in-memory backend session, then cleared from this page.</span>
    </label>}
    {credential && !ownsCredential && <p className="architecture-key-note">Uses the selected {credentialLabel(credential)} from the first active {credential.replace("_api_key", "")} block.</p>}
    {experimentalCaptionProvider && <p className="architecture-readiness"><strong>Advanced selection:</strong> this caption provider requires paid credits and is not part of the free default. The core transcription and embedding stages remain Gemini-compatible.</p>}
    {reranker && selected?.provider === "local_qwen" && <p className="architecture-readiness"><strong>Readiness:</strong> the Qwen3-VL runner loads only on the first bounded rerank. If its local dependencies or model are unavailable, search safely returns the RRF shortlist and reports that state.</p>}
    {reranker && selected?.provider === "none" && <p className="architecture-readiness">Reranker disabled. Search returns the fused RRF candidate list without a precision stage.</p>}
    {localQwenCaption && <p className="architecture-readiness"><strong>Readiness:</strong> Qwen2.5-VL is a local captioner for selected indexing windows. It has no API key, but the first run downloads model weights and is much slower on CPU.</p>}
    <span className="architecture-output">Produces: {copy.output}</span>
  </article>;
}

export default function ArchitecturePage() {
  const router = useRouter();
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([]);
  const visibleProfiles = profiles.length ? profiles : FALLBACK_PROFILES;
  const [profileId, setProfileId] = useState("self-hosted-v1");
  const activeProfile = visibleProfiles.find((profile) => profile.id === profileId) ?? visibleProfiles[0];
  const apiBased = isApiProfile(activeProfile);
  const [selections, setSelections] = useState<Record<StageKey, string>>(() => profileDefaults(FALLBACK_PROFILES[0]));
  // Keep the intended choice stable while the public profile metadata request
  // is still in flight.  Without these refs, a quick profile/model selection
  // could be overwritten by the effect's initial self-hosted closure.
  const profileIdRef = useRef(profileId);
  const selectionsRef = useRef(selections);
  const [secrets, setSecrets] = useState<SecretValues>({ gemini_api_key: "", openai_api_key: "", nvidia_api_key: "" });
  const [qdrantUrl, setQdrantUrl] = useState("");
  const [qdrantApiKey, setQdrantApiKey] = useState("");
  const [cloudConsent, setCloudConsent] = useState(false);
  const [activationMessage, setActivationMessage] = useState("");
  const [error, setError] = useState("");
  const [runtimePreflight, setRuntimePreflight] = useState<RuntimePreflight>();
  const [runtimePreflightCheckedAt, setRuntimePreflightCheckedAt] = useState<string>();
  const [activating, setActivating] = useState(false);

  useEffect(() => {
    jsonFetch<{ profiles: RuntimeProfile[] }>("/api/runtime/profiles")
      .then(({ profiles: nextProfiles }) => {
        if (nextProfiles.length) {
          const selectedProfile = nextProfiles.find((profile) => profile.id === profileIdRef.current) ?? nextProfiles[0];
          const defaults = profileDefaults(selectedProfile);
          const nextSelections = Object.fromEntries(STAGE_KEYS.map((stage) => {
            const prior = selectionsRef.current[stage];
            const stillSupported = (selectedProfile.provider_options?.[stage] ?? [])
              .some((option) => optionKey(option) === prior);
            return [stage, stillSupported ? prior : defaults[stage]];
          })) as Record<StageKey, string>;
          setProfiles(nextProfiles);
          profileIdRef.current = selectedProfile.id;
          selectionsRef.current = nextSelections;
          setProfileId(selectedProfile.id);
          setSelections(nextSelections);
        }
      })
      .catch(() => setActivationMessage("Profile metadata is unavailable, showing the built-in contract preview."));
    // Load the public, non-secret model contract once. API keys are never fetched.
  }, []);

  const selectedOptions = useMemo(() => Object.fromEntries(STAGE_KEYS.map((stage) => {
    const option = (activeProfile?.provider_options?.[stage] ?? []).find((item) => optionKey(item) === selections[stage]);
    return [stage, option];
  })) as Record<StageKey, StageOption | undefined>, [activeProfile, selections]);

  const credentialOwners = useMemo(() => {
    const owners = new Map<SecretName, StageKey>();
    STAGE_KEYS.forEach((stage) => {
      const credential = providerCredential(selectedOptions[stage]?.provider ?? "");
      if (credential && !owners.has(credential)) owners.set(credential, stage);
    });
    return owners;
  }, [selectedOptions]);

  function chooseProfile(nextProfile: RuntimeProfile) {
    const nextSelections = profileDefaults(nextProfile);
    profileIdRef.current = nextProfile.id;
    selectionsRef.current = nextSelections;
    setProfileId(nextProfile.id);
    setSelections(nextSelections);
    setError("");
    setActivationMessage("");
    setRuntimePreflight(undefined);
    setRuntimePreflightCheckedAt(undefined);
  }

  function selectStage(stage: StageKey, value: string) {
    const nextSelections = { ...selectionsRef.current, [stage]: value };
    selectionsRef.current = nextSelections;
    setSelections(nextSelections);
    setError("");
  }

  function setSecret(credential: SecretName, value: string) {
    setSecrets((current) => ({ ...current, [credential]: value }));
  }

  async function activate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeProfile) return;
    setError("");
    setActivationMessage("");
    setRuntimePreflight(undefined);
    setRuntimePreflightCheckedAt(undefined);

    const providers = Object.fromEntries(STAGE_KEYS.map((stage) => [stage, selectedOptions[stage]?.provider])) as RuntimeSessionRequest["providers"];
    const models = Object.fromEntries(STAGE_KEYS.map((stage) => [stage, selectedOptions[stage]?.model ?? ""]));

    if (!apiBased) {
      setActivating(true);
      try {
        // A self-hosted session has no credentials.  It simply carries the
        // selected local reranker/model contract to Search without using
        // browser persistence for a configuration object.
        const session = await jsonFetch<RuntimeSession>("/api/runtime/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile_id: activeProfile.id, providers, models } satisfies RuntimeSessionRequest),
        });
        storeRuntimeSessionId(session.session_id);
        setActivationMessage("Self-hosted architecture selected. Local Qdrant and the selected on-demand precision stage are ready.");
        router.push(`/processing?profile_id=${encodeURIComponent(session.profile.id)}&runtime_session_id=${encodeURIComponent(session.session_id)}`);
      } catch (cause) {
        setError(errorText(cause));
      } finally {
        setActivating(false);
      }
      return;
    }

    const missingCredentials = new Set<SecretName>();
    STAGE_KEYS.forEach((stage) => {
      const option = selectedOptions[stage];
      const credential = providerCredential(option?.provider ?? "");
      if (option?.credential_required && credential && !secrets[credential].trim()) missingCredentials.add(credential);
    });
    if (!qdrantUrl.trim() || !qdrantApiKey.trim()) {
      setError("Enter the Qdrant Cloud URL and API key in the storage block before activating API-based mode.");
      return;
    }
    if (missingCredentials.size) {
      setError(`Enter ${[...missingCredentials].map(credentialLabel).join(" and ")} in the selected provider block${missingCredentials.size === 1 ? "" : "s"}.`);
      return;
    }
    if (!cloudConsent) {
      setError("Confirm cloud-video consent before activating an API-based architecture.");
      return;
    }

    setActivating(true);
    let createdSessionId: string | undefined;
    try {
      const runtime: RuntimeSessionRequest = {
        profile_id: activeProfile.id,
        qdrant_url: qdrantUrl.trim(),
        qdrant_api_key: qdrantApiKey.trim(),
        gemini_api_key: secrets.gemini_api_key.trim() || undefined,
        openai_api_key: secrets.openai_api_key.trim() || undefined,
        nvidia_api_key: secrets.nvidia_api_key.trim() || undefined,
        providers,
        models,
        consent_cloud_video: true,
      };
      const session = await jsonFetch<RuntimeSession>("/api/runtime/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(runtime),
      });
      createdSessionId = session.session_id;
      const preflight = await jsonFetch<RuntimePreflight>(
        `/api/runtime/session/${encodeURIComponent(session.session_id)}/preflight`,
        { method: "POST" },
      );
      setRuntimePreflight(preflight);
      setRuntimePreflightCheckedAt(new Date().toISOString());
      const summary = summarizeCloudPreflight(preflight);
      if (!preflight.reachable || preflight.schema_valid === false) {
        throw new Error(`${summary.headline}: ${summary.message}${summary.nextAction ? ` ${summary.nextAction}` : ""}`);
      }
      storeRuntimeSessionId(session.session_id);
      // Ownership has transferred to the active browser session. Do not tear
      // it down in the catch path below.
      createdSessionId = undefined;
      // Clear every credential after the request has been accepted.  Only the
      // opaque runtime-session id survives in browser sessionStorage.
      setSecrets({ gemini_api_key: "", openai_api_key: "", nvidia_api_key: "" });
      setQdrantApiKey("");
      setActivationMessage(preflight.collection_exists
        ? "Architecture activated. The compatible Qdrant Cloud collection is ready."
        : "Architecture activated. Qdrant Cloud is reachable; the compatible collection will be created on the first index run.");
      router.push(`/processing?profile_id=${encodeURIComponent(session.profile.id)}&runtime_session_id=${encodeURIComponent(session.session_id)}`);
    } catch (cause) {
      if (createdSessionId) {
        try {
          await deleteRuntimeSession(createdSessionId);
        } catch {
          // Preserve the useful setup failure; backend expiry is the fallback
          // if a local teardown request itself cannot be delivered.
        }
      }
      setError(errorText(cause));
    } finally {
      setActivating(false);
    }
  }

  return <main className="architecture-page">
    <div className="page-heading">
      <div><p className="eyebrow">Step 0 of 3</p><h1>Choose the search architecture</h1></div>
      <Link href="/processing" className="secondary button">Skip to indexing</Link>
    </div>
    <p className="lede">Select the runtime contract before uploading footage. The diagram is the actual order of work, not a single fused embedding shortcut.</p>

    <form className="architecture-form" onSubmit={activate}>
      <section className="form-section">
        <div className="section-heading"><h2>Run profile</h2><p>Profiles isolate vector dimensions and collection schemas, so incompatible vectors can never mix.</p></div>
        <div className="profile-choice" role="radiogroup" aria-label="Run profile">
          {visibleProfiles.map((profile) => <label className={`profile-option ${profile.id === activeProfile?.id ? "selected" : ""}`} key={profile.id}>
            <input type="radio" name="architecture_profile" checked={profile.id === activeProfile?.id} onChange={() => chooseProfile(profile)} />
            <span><strong>{profile.label}</strong><small>{profile.description}</small><code>{profile.collection_name}</code></span>
          </label>)}
        </div>
      </section>

      {apiBased && <section className="architecture-storage" aria-labelledby="storage-heading">
        <div className="architecture-storage-copy"><p className="architecture-kicker">Storage</p><h2 id="storage-heading">Qdrant Cloud, named vectors</h2><p>One hosted collection keeps visual, audio, transcript, and caption vectors together as separate fields. No Docker or database VM is needed for this profile.</p></div>
        <div className="architecture-storage-fields">
          <label className="field">Qdrant Cloud URL<input required type="url" value={qdrantUrl} onChange={(event) => setQdrantUrl(event.target.value)} autoComplete="off" placeholder="https://your-cluster.cloud.qdrant.io:6333" /></label>
          <label className="field">Qdrant Cloud API key<input required type="password" value={qdrantApiKey} onChange={(event) => setQdrantApiKey(event.target.value)} autoComplete="off" spellCheck={false} placeholder="Held only until activation" /></label>
        </div>
      </section>}

      <section className="architecture-section" aria-labelledby="index-flow-heading">
        <div className="section-heading"><div><p className="eyebrow">Processing</p><h2 id="index-flow-heading">Indexing flow</h2></div><p>20-second windows with a 10-second stride in API-based mode. Every window retains distinct modality records.</p></div>
        <div className="architecture-source">
          <span className="architecture-number">01</span><div><strong>Upload and normalise</strong><p>Validate the video, convert WebM or unsupported input into compatible video and audio clips, then create timestamped windows.</p></div><span className="architecture-output">video + audio windows</span>
        </div>
        <div className="architecture-arrow" aria-hidden="true">↓</div>
        <div className="architecture-split" aria-label="Independent indexing channels">
          <ArchitectureStageCard stage="media_embedding" profile={activeProfile} selections={selections} selectedOptions={selectedOptions} credentialOwners={credentialOwners} secrets={secrets} onSelectStage={selectStage} onSetSecret={setSecret} />
          <ArchitectureStageCard stage="transcription" profile={activeProfile} selections={selections} selectedOptions={selectedOptions} credentialOwners={credentialOwners} secrets={secrets} onSelectStage={selectStage} onSetSecret={setSecret} />
          <ArchitectureStageCard stage="text_embedding" profile={activeProfile} selections={selections} selectedOptions={selectedOptions} credentialOwners={credentialOwners} secrets={secrets} onSelectStage={selectStage} onSetSecret={setSecret} />
          <ArchitectureStageCard stage="caption" profile={activeProfile} selections={selections} selectedOptions={selectedOptions} credentialOwners={credentialOwners} secrets={secrets} onSelectStage={selectStage} onSetSecret={setSecret} />
        </div>
        <div className="architecture-arrow" aria-hidden="true">↓</div>
        <div className="architecture-vector-store"><span className="architecture-number">02</span><div><strong>Named-vector store</strong><p>Upsert window timestamps, source metadata, transcript, caption, diagnostics, and four independent vector fields. Raw vectors are not averaged or concatenated.</p></div><div className="architecture-vector-list"><span>visual</span><span>audio</span><span>transcript</span><span>caption</span></div></div>
      </section>

      <section className="architecture-section" aria-labelledby="query-flow-heading">
        <div className="section-heading"><div><p className="eyebrow">Querying</p><h2 id="query-flow-heading">Recall, then precision</h2></div><p>RRF only chooses the bounded candidate set. It is not an input feature for the cross-encoder.</p></div>
        <div className="architecture-query-flow">
          <ArchitectureStageCard stage="query_decomposition" profile={activeProfile} selections={selections} selectedOptions={selectedOptions} credentialOwners={credentialOwners} secrets={secrets} onSelectStage={selectStage} onSetSecret={setSecret} />
          <div className="architecture-arrow architecture-arrow-horizontal" aria-hidden="true">→</div>
          <div className="architecture-stage architecture-static-stage"><p className="architecture-kicker">Query</p><h3>Four compatible encoders</h3><p>The visual, audio, transcript, and caption prompts each become a vector in their own indexed space.</p><div className="architecture-vector-list"><span>visual</span><span>audio</span><span>transcript</span><span>caption</span></div><span className="architecture-output">four query vectors</span></div>
          <div className="architecture-arrow architecture-arrow-horizontal" aria-hidden="true">→</div>
          <div className="architecture-stage architecture-static-stage"><p className="architecture-kicker">Recall</p><h3>Top K per channel + RRF</h3><p>Search the four named fields independently, fuse only their ranked lists, and merge adjacent matching windows.</p><strong className="architecture-guardrail">RRF scores stop here.</strong><span className="architecture-output">bounded candidate list</span></div>
        </div>
        <div className="architecture-arrow" aria-hidden="true">↓</div>
        <div className="architecture-precision-flow">
          <ArchitectureStageCard stage="reranker" profile={activeProfile} selections={selections} selectedOptions={selectedOptions} credentialOwners={credentialOwners} secrets={secrets} onSelectStage={selectStage} onSetSecret={setSecret} />
          <div className="architecture-arrow architecture-arrow-horizontal" aria-hidden="true">→</div>
          <ArchitectureStageCard stage="verification" profile={activeProfile} selections={selections} selectedOptions={selectedOptions} credentialOwners={credentialOwners} secrets={secrets} onSelectStage={selectStage} onSetSecret={setSecret} />
        </div>
      </section>

      {apiBased && <label className="consent"><input required type="checkbox" checked={cloudConsent} onChange={(event) => setCloudConsent(event.target.checked)} /><span>I have permission to send this footage to the selected cloud providers and understand that the free tier may have provider data-use and quota limits.</span></label>}
      {error && <p className="error panel" role="alert">{error}</p>}
      {apiBased && <CloudPreflightDiagnostics preflight={runtimePreflight} checkedAt={runtimePreflightCheckedAt} />}
      {activationMessage && <p className="architecture-message" role="status">{activationMessage}</p>}
      <div className="architecture-actions"><button className="button" disabled={activating}>{activating ? "Checking architecture…" : apiBased ? "Activate API-based architecture" : "Use self-hosted architecture"}</button><Link href="/processing" className="secondary button">Index a video</Link></div>
    </form>
  </main>;
}
