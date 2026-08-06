"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  API,
  IndexHealth,
  ModelStatus,
  RuntimeProfile,
  RuntimePreflight,
  RuntimeSession,
  RuntimeSessionRequest,
  ProviderChoice,
  deleteRuntimeSession,
  jsonFetch,
  loadRuntimeSessionId,
  storeRuntimeSessionId,
} from "@/lib/api";
import { CloudPreflightDiagnostics } from "@/components/CloudPreflightDiagnostics";
import { summarizeCloudPreflight } from "@/lib/preflight";

async function errorMessage(response: Response): Promise<string> {
  const body = await response.text();
  let detail = body;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
  } catch {
    // A plain-text response is still useful to the person running the app.
  }
  if (detail.includes("There was an error parsing the body")) {
    return "The upload could not be read. Re-select the video file and try again. If it repeats, refresh this page before retrying.";
  }
  return detail || `Request failed (${response.status}).`;
}

function displayError(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export default function ProcessingPage() {
  return <Suspense fallback={<main className="page-loading">Loading processing setup…</main>}><ProcessingContent /></Suspense>;
}

function ProcessingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [models, setModels] = useState<ModelStatus[]>([]);
  const [health, setHealth] = useState<IndexHealth>();
  const [healthRefreshKey, setHealthRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [vlmMode, setVlmMode] = useState("selection_only");
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([]);
  const [profileId, setProfileId] = useState(() => searchParams.get("profile_id") || "self-hosted-v1");
  const [runtimeMessage, setRuntimeMessage] = useState("");
  const [runtimePreflight, setRuntimePreflight] = useState<RuntimePreflight>();
  const [runtimePreflightCheckedAt, setRuntimePreflightCheckedAt] = useState<string>();
  const [configuredRuntimeSession, setConfiguredRuntimeSession] = useState<RuntimeSession>();
  const [apiVectorStoreTarget, setApiVectorStoreTarget] = useState<"cloud" | "local">("cloud");
  const requestedRuntimeSessionId = searchParams.get("runtime_session_id");
  const activeProfile = profiles.find((profile) => profile.id === profileId);
  const isApiBased = activeProfile?.mode === "api-based" || activeProfile?.mode === "api_based" || profileId === "api-gemini-free-v1";
  const hasConfiguredApiSession = Boolean(isApiBased
    && configuredRuntimeSession?.profile.id === profileId);
  const hasConfiguredSelfHostedSession = Boolean(!isApiBased
    && configuredRuntimeSession?.profile.id === "self-hosted-v1"
    && profileId === "self-hosted-v1");
  const sessionProviders = configuredRuntimeSession?.configuration?.providers as Record<string, unknown> | undefined;
  const sessionModels = configuredRuntimeSession?.configuration?.models as Record<string, unknown> | undefined;
  const sessionVectorStoreTarget = configuredRuntimeSession?.configuration?.vector_store_target === "local"
    ? "local"
    : "cloud";
  const sessionCaptionProvider = typeof sessionProviders?.caption === "string"
    ? sessionProviders.caption
    : "none";
  const sessionCaptionModel = typeof sessionModels?.caption === "string"
    ? sessionModels.caption
    : "";
  const architectureVlmMode = sessionCaptionProvider === "local_qwen" ? "local_qwen" : "selection_only";
  const effectiveSelfHostedVlmMode = hasConfiguredSelfHostedSession
    ? architectureVlmMode
    : vlmMode;
  const cloudPreflightSummary = runtimePreflight ? summarizeCloudPreflight(runtimePreflight) : undefined;

  useEffect(() => {
    fetch(`${API}/api/processing/preflight`).then((response) => response.json())
      .then((data) => setModels(data.models)).catch((cause) => setError(displayError(cause)));
    let cancelled = false;
    let retryTimer: number | undefined;
    const loadHealth = async (attempt = 0) => {
      try {
        const data = await jsonFetch<IndexHealth>("/api/index/health");
        if (cancelled) return;
        setHealth(data);
        if (!data.reachable && attempt < 2) {
          retryTimer = window.setTimeout(() => { void loadHealth(attempt + 1); }, 1000 * (attempt + 1));
        }
      } catch (cause) {
        if (!cancelled) setError(displayError(cause));
      }
    };
    void loadHealth();
    jsonFetch<{ profiles: RuntimeProfile[] }>("/api/runtime/profiles")
      .then((data) => {
        setProfiles(data.profiles);
        if (!data.profiles.some((profile) => profile.id === "self-hosted-v1")) {
          setProfileId(data.profiles[0]?.id ?? "self-hosted-v1");
        }
      })
      .catch((cause) => setRuntimeMessage(`Runtime setup is unavailable: ${displayError(cause)}`));
    return () => {
      cancelled = true;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [healthRefreshKey]);

  useEffect(() => {
    const sessionId = requestedRuntimeSessionId || loadRuntimeSessionId();
    if (!sessionId) return;
    jsonFetch<RuntimeSession>(`/api/runtime/session/${encodeURIComponent(sessionId)}`)
      .then((session) => {
        setConfiguredRuntimeSession(session);
        setProfileId(session.profile.id);
        if (session.profile.id === "self-hosted-v1") {
          const providers = session.configuration?.providers as Record<string, unknown> | undefined;
          setVlmMode(providers?.caption === "local_qwen" ? "local_qwen" : "selection_only");
        }
        storeRuntimeSessionId(session.session_id);
        setRuntimeMessage("Using the active architecture session. Its API keys remain only in the backend process.");
      })
      .catch(() => {
        if (requestedRuntimeSessionId) {
          setRuntimeMessage("The architecture session is no longer active. Return to Architecture to enter keys again.");
        }
      });
  }, [requestedRuntimeSessionId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    const video = data.get("video");
    if (!(video instanceof File) || video.size === 0) {
      setError("Choose a non-empty video file before creating an indexing job.");
      setSubmitting(false);
      return;
    }
    const config: Record<string, unknown> = {
      profile_id: profileId,
      window_seconds: Number(data.get("window_seconds")),
      stride_seconds: Number(data.get("stride_seconds")),
      device: isApiBased ? "hosted" : data.get("device"),
      vlm_mode: isApiBased ? String(data.get("caption_provider") ?? "gemini") : effectiveSelfHostedVlmMode,
      max_windows: Number(data.get("max_windows")),
      index_qdrant: data.get("index_qdrant") === "on",
      visual_threshold: Number(data.get("visual_threshold")),
      audio_threshold: Number(data.get("audio_threshold")),
      speech_threshold: Number(data.get("speech_threshold")),
      combined_threshold: Number(data.get("combined_threshold")),
      visual_weight: Number(data.get("visual_weight")),
      audio_weight: Number(data.get("audio_weight")),
      speech_weight: Number(data.get("speech_weight")),
    };
    if (isApiBased) {
      if (!hasConfiguredApiSession && data.get("consent_cloud_video") !== "on") {
        setError("Confirm that this video may be sent to the selected cloud providers before starting an API-based run.");
        setSubmitting(false);
        return;
      }
      const providers: RuntimeSessionRequest["providers"] = {
        media_embedding: "gemini",
        transcription: data.get("transcription_provider") as ProviderChoice,
        text_embedding: data.get("text_embedding_provider") as ProviderChoice,
        caption: data.get("caption_provider") as ProviderChoice,
        verification: data.get("verification_provider") as ProviderChoice,
        query_decomposition: data.get("query_decomposition_provider") as ProviderChoice,
      };
      if (!hasConfiguredApiSession) {
        const unsupported = Object.entries(providers)
          .filter(([, provider]) => provider && provider !== "gemini")
          .map(([stage]) => stage.replaceAll("_", " "));
        if (unsupported.length) {
          setError(`The quick API setup supports the free Gemini contract only. Configure ${unsupported.join(", ")} in Architecture before uploading.`);
          setSubmitting(false);
          return;
        }
      }
      let createdSessionId: string | undefined;
      try {
        let session = configuredRuntimeSession;
        if (!session || session.profile.id !== profileId) {
          const runtime: RuntimeSessionRequest = {
            profile_id: profileId,
            vector_store_target: apiVectorStoreTarget,
            qdrant_url: String(data.get("qdrant_url") ?? "").trim(),
            qdrant_api_key: apiVectorStoreTarget === "cloud"
              ? String(data.get("qdrant_api_key") ?? "").trim()
              : undefined,
            gemini_api_key: String(data.get("gemini_api_key") ?? "").trim(),
            openai_api_key: String(data.get("api_openai_api_key") ?? "").trim() || undefined,
            nvidia_api_key: String(data.get("api_nvidia_api_key") ?? "").trim() || undefined,
            providers,
            models: {
              transcription: String(data.get("transcription_model") ?? "gemini-3.5-flash-lite"),
              media_embedding: String(data.get("media_embedding_model") ?? "gemini-embedding-2"),
              text_embedding: String(data.get("text_embedding_model") ?? "gemini-embedding-2"),
              caption: String(data.get("caption_model") ?? "gemini-3.5-flash-lite"),
              verification: String(data.get("verification_model") ?? "gemini-3.5-flash-lite"),
              query_decomposition: String(data.get("query_decomposition_model") ?? "gemini-3.5-flash-lite"),
            },
            consent_cloud_video: true,
          };
          session = await jsonFetch<RuntimeSession>("/api/runtime/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(runtime),
          });
          createdSessionId = session.session_id;
        }
        if (!session) throw new Error("The API runtime session could not be created.");
        const preflight = await jsonFetch<RuntimePreflight>(
          `/api/runtime/session/${encodeURIComponent(session.session_id)}/preflight`,
          { method: "POST" },
        );
        setRuntimePreflight(preflight);
        setRuntimePreflightCheckedAt(new Date().toISOString());
        const summary = summarizeCloudPreflight(preflight);
        setRuntimeMessage(`${summary.headline}: ${summary.message}`);
        if (!preflight.reachable || preflight.schema_valid === false) {
          throw new Error(`${summary.headline}: ${summary.message}${summary.nextAction ? ` ${summary.nextAction}` : ""}`);
        }
        setConfiguredRuntimeSession(session);
        storeRuntimeSessionId(session.session_id);
        // The session is now the active browser architecture. Do not delete it
        // from the failure handler below.
        createdSessionId = undefined;
        // The upload job owns only per-video tuning.  Cloud endpoint, model
        // selection, collection contract, and credentials stay in the opaque
        // backend runtime session and are deliberately never copied into this
        // serialised job configuration.
        const apiJobConfig: Record<string, unknown> = {
          profile_id: session.profile.id,
          runtime_session_id: session.session_id,
          window_seconds: config.window_seconds,
          stride_seconds: config.stride_seconds,
          max_windows: config.max_windows,
          index_qdrant: config.index_qdrant,
        };
        Object.keys(config).forEach((key) => delete config[key]);
        Object.assign(config, apiJobConfig);
      } catch (cause) {
        if (createdSessionId) {
          try {
            await deleteRuntimeSession(createdSessionId);
          } catch {
            // Keep the original preflight error actionable. Server-side TTL is
            // the fallback if a best-effort local teardown cannot complete.
          }
          setConfiguredRuntimeSession((current) => current?.session_id === createdSessionId ? undefined : current);
        }
        setError(displayError(cause));
        setSubmitting(false);
        return;
      }
    }
    if (!isApiBased && effectiveSelfHostedVlmMode === "openai") {
      config.openai_api_key = String(data.get("openai_api_key") ?? "");
      config.openai_model = String(data.get("openai_model") ?? "gpt-4.1-mini");
      config.openai_max_frames = Number(data.get("openai_max_frames"));
    }
    if (!isApiBased && effectiveSelfHostedVlmMode === "cosmos") {
      config.nvidia_api_key = String(data.get("nvidia_api_key") ?? "");
      config.cosmos_model = String(data.get("cosmos_model") ?? "nvidia/cosmos3-nano-reasoner");
      config.cosmos_max_frames = Number(data.get("cosmos_max_frames"));
    }
    if (!isApiBased && effectiveSelfHostedVlmMode === "local_qwen") {
      const selectedQwenModel = hasConfiguredSelfHostedSession
        ? sessionCaptionModel
        : String(data.get("local_qwen_model") ?? "").trim();
      if (!selectedQwenModel) {
        setError("The selected Qwen-VL caption model is unavailable. Return to Architecture and select it again.");
        setSubmitting(false);
        return;
      }
      config.local_qwen_model = selectedQwenModel;
    }
    const body = new FormData();
    // Include the filename explicitly. It makes the multipart part unambiguous
    // across browsers and lets the server validate the upload consistently.
    body.append("video", video, video.name || "upload.mp4");
    body.append("configuration", JSON.stringify(config));
    // The request has its own serialized copy now. Clear secrets from the
    // browser form immediately; they are neither local-storage nor job-history data.
    form.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach((input) => { input.value = ""; });
    try {
      const response = await fetch(`${API}/api/processing/jobs`, { method: "POST", body });
      if (!response.ok) throw new Error(await errorMessage(response));
      const job = await response.json();
      router.push(`/processing/${job.job_id}`);
    } catch (cause) {
      setError(displayError(cause));
      setSubmitting(false);
    }
  }

    return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">Step 1 of 3</p><h1>Index a video</h1></div>
        <p className="muted">This uploads one local video, creates searchable windows, and can save them into your shared Qdrant collection.</p>
      </div>

      {error && <p className="error panel">{error}</p>}
      <section className={`status-strip ${isApiBased ? (cloudPreflightSummary?.tone ?? (runtimeMessage ? "ready" : "warning")) : health ? (health.reachable && health.schema_valid !== false ? "ready" : "warning") : ""}`}>
        <div><strong>{isApiBased ? (cloudPreflightSummary?.headline ?? "Qdrant Cloud setup") : `Qdrant ${health ? (health.reachable ? "connected" : "not ready") : "checking"}`}</strong><span>{isApiBased ? (cloudPreflightSummary?.message || runtimeMessage || "Enter Qdrant Cloud details below; a read-only preflight runs before upload.") : health ? (health.collection_exists ? `${health.points_count} indexed windows in ${health.collection_name}` : health.error ?? "The shared collection will be created when you index your first video.") : "Checking the shared collection…"}</span>{!isApiBased && health?.schema_errors?.map((message) => <span className="error" key={message}>{message}</span>)}</div>
        {!isApiBased && <button type="button" className="link-button" onClick={() => { setHealth(undefined); setHealthRefreshKey((value) => value + 1); }}>Retry Qdrant</button>}
        <Link href="/library">Inspect library</Link>
      </section>
      {isApiBased && <CloudPreflightDiagnostics preflight={runtimePreflight} checkedAt={runtimePreflightCheckedAt} />}

      <form onSubmit={submit} className="processing-form">
        <section className="form-section">
          <div className="section-heading"><h2>Run profile</h2><p>Choose where models and the vector store run. Collections are isolated by embedding contract.</p></div>
          <div className="profile-choice" role="radiogroup" aria-label="Run profile">
            {(profiles.length ? profiles : [
              { id: "self-hosted-v1", label: "Self-hosted", mode: "self-hosted", description: "Local CPU models and local Qdrant.", collection_name: "video_windows" },
              { id: "api-gemini-free-v1", label: "API-based", mode: "api-based", description: "Gemini APIs and Qdrant Cloud. No local model downloads or Docker.", collection_name: "video_windows_api_gemini_free" },
            ]).map((profile) => (
              <label className={`profile-option ${profile.id === profileId ? "selected" : ""}`} key={profile.id}>
                <input type="radio" name="run_profile" value={profile.id} checked={profile.id === profileId} onChange={() => { setProfileId(profile.id); setRuntimeMessage(""); setRuntimePreflight(undefined); setRuntimePreflightCheckedAt(undefined); if (configuredRuntimeSession?.profile.id !== profile.id) setConfiguredRuntimeSession(undefined); }} />
                <span><strong>{profile.label}</strong><small>{profile.description}</small><code>{profile.collection_name}</code></span>
              </label>
            ))}
          </div>
        </section>
        {isApiBased ? (
          <>
            <section className="form-section">
              <div className="section-heading"><h2>Video and indexing</h2><p>Creates 20-second searchable windows with a 10-second stride. Unsupported uploads such as WebM are normalized before cloud processing.</p></div>
              <div className="field-grid">
                <label className="field field-wide">Video file<input required name="video" type="file" accept="video/*" /></label>
                <label className="field">Maximum windows<input name="max_windows" type="number" min="0" defaultValue="0" /><span>0 processes the full video.</span></label>
                <label className="field">Window length (seconds)<input key={`${profileId}-window`} name="window_seconds" type="number" step="0.1" min="1" defaultValue="20" /></label>
                <label className="field">Stride (seconds)<input key={`${profileId}-stride`} name="stride_seconds" type="number" step="0.1" min="1" defaultValue="10" /></label>
              </div>
              <input type="hidden" name="index_qdrant" value="on" />
              <p className="hint">This profile always saves separate visual, audio, transcript, and caption vectors. The Architecture session decides whether those vectors use Qdrant Cloud or local Qdrant.</p>
            </section>

            {hasConfiguredApiSession && configuredRuntimeSession ? <section className="form-section api-setup">
              <div className="section-heading"><h2>Architecture session is ready</h2><p>Your model choices and vector-database connection were checked in the Architecture step. Keys are not sent again with this upload.</p></div>
              <div className="runtime-summary"><strong>{configuredRuntimeSession.profile.label}</strong><span>Collection: <code>{configuredRuntimeSession.profile.collection_name}</code></span><span>Vector DB: {sessionVectorStoreTarget === "local" ? "local Qdrant" : "Qdrant Cloud"}. Session-only credentials are active in this backend process.</span></div>
              <p className="hint">Upload the video above to start the configured API-based index. To change providers or keys, return to <Link href="/architecture">Architecture</Link>.</p>
              {runtimeMessage && <p className="runtime-message">{runtimeMessage}</p>}
            </section> : <section className="form-section api-setup">
              <div className="section-heading"><h2>API-based setup</h2><p>Credentials remain only in this backend process for the active browser session. Restarting the backend clears them.</p></div>
              <div className="runtime-summary"><strong>Free default</strong><span>Gemini Embedding 2 + Gemini 3.5 Flash-Lite + Qdrant Cloud Free.</span><span>You can instead choose local Qdrant below; OpenAI and NVIDIA Cosmos are optional and require your own paid API credit.</span></div>
              <div className="field-grid">
                <label className="field">Vector database<select name="vector_store_target" value={apiVectorStoreTarget} onChange={(event) => setApiVectorStoreTarget(event.target.value as "cloud" | "local")}><option value="cloud">Qdrant Cloud</option><option value="local">Local Qdrant on this laptop</option></select><span>{apiVectorStoreTarget === "local" ? "Start local Qdrant first. No Qdrant API key is used." : "Managed endpoint; no local database container is needed."}</span></label>
                <label className="field field-wide">{apiVectorStoreTarget === "local" ? "Local Qdrant URL" : "Qdrant Cloud URL"}<input key={apiVectorStoreTarget} required name="qdrant_url" type="url" autoComplete="off" defaultValue={apiVectorStoreTarget === "local" ? "http://127.0.0.1:6333" : ""} placeholder={apiVectorStoreTarget === "local" ? "http://127.0.0.1:6333" : "https://your-cluster.cloud.qdrant.io:6333"} /><span>{apiVectorStoreTarget === "local" ? "Run `docker compose up -d qdrant` before submitting." : "Your managed Qdrant Cloud endpoint. No database container is needed on this laptop."}</span></label>
                {apiVectorStoreTarget === "cloud" && <label className="field">Qdrant Cloud API key<input required name="qdrant_api_key" type="password" autoComplete="off" /><span>Session-only; never shown in diagnostics or exports.</span></label>}
                <label className="field field-wide">Gemini API key<input required name="gemini_api_key" type="password" autoComplete="off" placeholder="AIza..." /><span>Required for the free Gemini default. Free-tier inputs can be used by Google to improve products.</span></label>
              </div>
              <div className="provider-grid">
                <label className="field">Video + audio embeddings<select name="media_embedding_provider" defaultValue="gemini"><option value="gemini">Gemini Embedding 2, free default</option></select><input name="media_embedding_model" defaultValue="gemini-embedding-2" /><span>Separate visual and audio vectors; they are never raw-vector merged.</span></label>
                <label className="field">Timestamped transcription<select name="transcription_provider" defaultValue="gemini"><option value="gemini">Gemini, free default</option><option value="openai">OpenAI, paid credit required</option></select><select name="transcription_model" defaultValue="gemini-3.5-flash-lite"><option value="gemini-3.5-flash-lite">Gemini 3.5 Flash-Lite</option><option value="gemini-3.1-flash-lite">Gemini 3.1 Flash-Lite</option><option value="gpt-4o-transcribe">GPT-4o Transcribe</option></select></label>
                <label className="field">Transcript + caption embeddings<select name="text_embedding_provider" defaultValue="gemini"><option value="gemini">Gemini, free default</option><option value="openai">OpenAI, paid credit required</option></select><select name="text_embedding_model" defaultValue="gemini-embedding-2"><option value="gemini-embedding-2">Gemini Embedding 2</option><option value="text-embedding-3-small">OpenAI text-embedding-3-small</option></select></label>
                <label className="field">Window captions<select name="caption_provider" defaultValue="gemini"><option value="gemini">Gemini, free default</option><option value="openai">OpenAI, paid credit required</option><option value="cosmos">NVIDIA Cosmos, paid credit required</option></select><select name="caption_model" defaultValue="gemini-3.5-flash-lite"><option value="gemini-3.5-flash-lite">Gemini 3.5 Flash-Lite</option><option value="gpt-4.1-mini">OpenAI GPT-4.1 mini</option><option value="nvidia/cosmos3-nano-reasoner">NVIDIA Cosmos Reasoner</option></select></label>
                <label className="field">Query decomposition<select name="query_decomposition_provider" defaultValue="gemini"><option value="gemini">Gemini, free default</option><option value="openai">OpenAI, paid credit required</option></select><select name="query_decomposition_model" defaultValue="gemini-3.5-flash-lite"><option value="gemini-3.5-flash-lite">Gemini 3.5 Flash-Lite</option><option value="gpt-4.1-mini">OpenAI GPT-4.1 mini</option></select></label>
                <label className="field">Result verification + localisation<select name="verification_provider" defaultValue="gemini"><option value="gemini">Gemini, free default</option><option value="openai">OpenAI, paid credit required</option><option value="cosmos">NVIDIA Cosmos, paid credit required</option></select><select name="verification_model" defaultValue="gemini-3.5-flash-lite"><option value="gemini-3.5-flash-lite">Gemini 3.5 Flash-Lite</option><option value="gpt-4.1-mini">OpenAI GPT-4.1 mini</option><option value="nvidia/cosmos3-nano-reasoner">NVIDIA Cosmos Reasoner</option></select></label>
              </div>
              <p className="provider-note">This quick setup is for the free Gemini contract. Use <Link href="/architecture">Architecture</Link> to make and validate an advanced provider selection before uploading.</p>
              <div className="field-grid">
                <label className="field">OpenAI API key (optional)<input name="api_openai_api_key" type="password" autoComplete="off" placeholder="sk-..." /><span>Needed only when an OpenAI provider is selected.</span></label>
                <label className="field">NVIDIA API key (optional)<input name="api_nvidia_api_key" type="password" autoComplete="off" placeholder="nvapi-..." /><span>Needed only when NVIDIA Cosmos is selected.</span></label>
              </div>
              <label className="consent"><input required type="checkbox" name="consent_cloud_video" /> <span>I understand that this video, including any identifiable surveillance footage, will be uploaded to the selected cloud provider. I have permission to process it and consent to the provider&apos;s free-tier data policy.</span></label>
              {runtimeMessage && <p className="runtime-message">{runtimeMessage}</p>}
            </section>}
          </>
        ) : (
        <section className="form-section">
          <div className="section-heading"><h2>Video and indexing</h2><p>Start with a short test video. The pipeline downloads real ML models on first use.</p></div>
          <div className="field-grid">
            <label className="field field-wide">Video file<input required name="video" type="file" accept="video/*" /></label>
            {hasConfiguredSelfHostedSession ? <label className="field">Caption pipeline<input readOnly value={effectiveSelfHostedVlmMode === "local_qwen" ? `Local Qwen-VL \u00b7 ${sessionCaptionModel || "selected model"}` : "Selection only (no caption VLM)"} /><span>Locked by the active Architecture session. Return to Architecture to change the caption model or provider.</span></label> : <label className="field">Processing mode<select name="vlm_mode" value={vlmMode} onChange={(event) => setVlmMode(event.target.value)}><option value="selection_only">Selection only, no caption VLM</option><option value="local_qwen">Local Qwen2.5-VL captions, on-demand</option><option value="openai">OpenAI VLM captions</option><option value="cosmos">NVIDIA Cosmos Reasoner captions</option><option value="mock">Deterministic mock captions, debug only</option></select></label>}
            <label className="field">Compute device<select name="device" defaultValue="cpu"><option value="cpu">CPU</option><option value="cuda">CUDA GPU</option></select></label>
            <label className="field">Maximum windows<input name="max_windows" type="number" min="0" defaultValue="0" /><span>0 processes the full video.</span></label>
            <label className="field">Window length (seconds)<input name="window_seconds" type="number" step="0.1" min="1" defaultValue="10" /></label>
            <label className="field">Stride (seconds)<input name="stride_seconds" type="number" step="0.1" min="1" defaultValue="5" /></label>
            {!hasConfiguredSelfHostedSession && vlmMode === "openai" && <><label className="field">OpenAI API key<input required name="openai_api_key" type="password" autoComplete="off" placeholder="sk-..." /><span>Used only for this indexing job, never saved.</span></label><label className="field">OpenAI model<input name="openai_model" defaultValue="gpt-4.1-mini" /></label><label className="field">OpenAI frames<input name="openai_max_frames" type="number" min="1" max="12" defaultValue="4" /></label></>}
            {!hasConfiguredSelfHostedSession && vlmMode === "cosmos" && <><label className="field">NVIDIA API key<input required name="nvidia_api_key" type="password" autoComplete="off" placeholder="nvapi-..." /><span>Used only for this indexing job, never saved.</span></label><label className="field">Cosmos model<input name="cosmos_model" defaultValue="nvidia/cosmos3-nano-reasoner" /></label><label className="field">Cosmos frames<input name="cosmos_max_frames" type="number" min="2" max="16" defaultValue="8" /></label></>}
            {!hasConfiguredSelfHostedSession && vlmMode === "local_qwen" && <label className="field field-wide">Local Qwen-VL model<input name="local_qwen_model" defaultValue="Qwen/Qwen2.5-VL-3B-Instruct" /><span>No API key is used. The first selected caption window downloads the model; CUDA is strongly recommended for a practical run.</span></label>}
          </div>
          <div className="index-choice">
            <label><input type="checkbox" name="index_qdrant" defaultChecked /> Save real vectors into Qdrant</label>
            <span className="muted">Shared collection: <code>{health?.collection_name ?? "video_windows"}</code></span>
          </div>
          <p className="hint">The collection is configured once on the server, so indexing, Library, and Search always use the same data. Selection-only indexing is the safe first run.</p>
        </section>
        )}

        <details className="form-section advanced"><summary>Advanced selection settings</summary><div className="field-grid compact">{[["visual_threshold", 0.12], ["audio_threshold", 0.15], ["speech_threshold", 0.18], ["combined_threshold", 0.13], ["visual_weight", 0.55], ["audio_weight", 0.25], ["speech_weight", 0.2]].map(([name, value]) => <label className="field" key={String(name)}>{String(name).replaceAll("_", " ")}<input name={String(name)} type="number" step="0.01" defaultValue={Number(value)} /></label>)}</div></details>
        <button className="button" disabled={submitting || (!isApiBased && health?.collection_exists === true && health.schema_valid === false)}>{submitting ? "Uploading…" : "Create indexing job"}</button>
      </form>

      {isApiBased ? <section className="models-section"><div className="section-heading"><h2>API readiness</h2><p>Cloud connectivity is checked immediately before an API-based job begins. Model downloads and local Docker are not used in this profile.</p></div><p className="hint">Qdrant Cloud may suspend after inactivity; this page will tell you if it needs to be woken before a demo.</p></section> : <section className="models-section"><div className="section-heading"><h2>Local model readiness</h2><p>This check does not download or load models.</p></div><div className="model-list">{models.map((model) => <div key={model.component} className="model-row"><div><strong>{model.component}</strong><span>{model.checkpoint}</span></div><span>{model.device}</span><span className={model.cache_available ? "ok" : "muted"}>{model.cache_available ? "cached" : "downloads on first run"}</span></div>)}</div></section>}
    </main>
  );
}
