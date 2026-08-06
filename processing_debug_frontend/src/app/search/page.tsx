"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  API,
  SearchDecomposition,
  SearchRequest,
  SearchResponse,
  SearchResult,
  SearchVerification,
  VerificationProvider,
  RuntimeProfile,
  RuntimeSession,
  apiErrorMessage,
  jsonFetch,
  loadRuntimeSessionId,
} from "@/lib/api";

type ResultView = {
  state: string;
  confidence?: number;
  evidence?: string;
  reason?: string;
  localizationState?: string;
  localizationReason?: string;
  localizationEvidence?: string;
  finalScore?: number;
  start: number;
  end: number;
  hasRefinedRange: boolean;
  satisfiedConditions: string[];
  missingConditions: string[];
  contradictions: string[];
};

function finiteNumber(...values: Array<number | null | undefined>): number | undefined {
  return values.find((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function resultView(result: SearchResult): ResultView {
  const verification: SearchVerification | undefined = result.verification ?? result.verification_result ?? undefined;
  const refinedStart = finiteNumber(
    result.refined_start,
    result.refined_start_seconds,
    verification?.refined_start,
    verification?.refined_start_seconds,
  );
  const refinedEnd = finiteNumber(
    result.refined_end,
    result.refined_end_seconds,
    verification?.refined_end,
    verification?.refined_end_seconds,
  );

  return {
    state: verification?.state ?? result.verification_state ?? result.state ?? "retrieved",
    confidence: finiteNumber(verification?.confidence, result.verification_confidence, result.confidence),
    evidence: verification?.evidence ?? result.verification_evidence ?? result.evidence,
    reason: verification?.reason ?? result.verification_reason,
    localizationState: verification?.localization_state ?? result.localization_state,
    localizationReason: verification?.localization_reason ?? result.localization_reason,
    localizationEvidence: verification?.localization_evidence ?? result.localization_evidence,
    finalScore: finiteNumber(verification?.final_score, result.final_score),
    start: refinedStart ?? result.start,
    end: refinedEnd ?? result.end,
    hasRefinedRange: refinedStart !== undefined || refinedEnd !== undefined,
    satisfiedConditions: verification?.satisfied_conditions ?? verification?.matched_conditions ?? result.satisfied_conditions ?? result.matched_conditions ?? [],
    missingConditions: verification?.missing_conditions ?? result.missing_conditions ?? [],
    contradictions: verification?.contradictions ?? result.contradictions ?? [],
  };
}

function stateLabel(state: string): string {
  switch (state) {
    case "verified":
      return "Verified";
    case "rejected":
      return "Rejected";
    case "verification_unavailable":
      return "Verification unavailable";
    default:
      return "Retrieved";
  }
}

function stateClass(state: string): string {
  if (state === "verified") return "ok";
  if (state === "rejected") return "error";
  return "muted";
}

function formatRange(start: number, end: number): string {
  return `${start.toFixed(1)}s–${end.toFixed(1)}s`;
}

function configuredProvider(
  session: RuntimeSession | undefined,
  stage: "verification" | "reranker",
): string | undefined {
  const providers = session?.configuration?.providers;
  if (!providers || typeof providers !== "object") return undefined;
  const value = (providers as Record<string, unknown>)[stage];
  return typeof value === "string" ? value : undefined;
}

function configuredModel(
  session: RuntimeSession | undefined,
  stage: "reranker",
): string | undefined {
  const models = session?.configuration?.models;
  if (!models || typeof models !== "object") return undefined;
  const value = (models as Record<string, unknown>)[stage];
  return typeof value === "string" ? value : undefined;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [decomposition, setDecomposition] = useState<SearchDecomposition>();
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown>>();
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [enableDecomposition, setEnableDecomposition] = useState(false);
  const [verificationProvider, setVerificationProvider] = useState<VerificationProvider>("none");
  const [verificationApiKey, setVerificationApiKey] = useState("");
  const [enableTemporalLocalization, setEnableTemporalLocalization] = useState(true);
  const [enableReranking, setEnableReranking] = useState(true);
  const [rerankerProvider, setRerankerProvider] = useState<"none" | "local_qwen">("none");
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([]);
  const [profileId, setProfileId] = useState("self-hosted-v1");
  const [runtimeSession, setRuntimeSession] = useState<RuntimeSession>();
  const activeProfile = profiles.find((profile) => profile.id === profileId);
  const isApiBased = activeProfile?.mode === "api-based" || activeProfile?.mode === "api_based" || profileId === "api-gemini-free-v1";
  const runtimeSessionId = loadRuntimeSessionId();
  const sessionMatchesProfile = Boolean(runtimeSessionId && runtimeSession?.profile.id === profileId);
  const sessionReranker = configuredProvider(runtimeSession, "reranker");
  const effectiveReranker = sessionMatchesProfile && (sessionReranker === "none" || sessionReranker === "local_qwen")
    ? sessionReranker
    : rerankerProvider;
  const effectiveRerankerModel = sessionMatchesProfile ? configuredModel(runtimeSession, "reranker") : undefined;
  const sessionVerification = configuredProvider(runtimeSession, "verification");
  const effectiveVerificationProvider: VerificationProvider = isApiBased && sessionMatchesProfile
    ? verificationProvider === "none"
      ? "none"
      : (sessionVerification === "gemini" || sessionVerification === "openai" || sessionVerification === "cosmos")
        ? sessionVerification
        : "gemini"
    : verificationProvider;
  const shouldRunReranker = enableReranking && effectiveReranker === "local_qwen";
  const profileQuery = isApiBased && sessionMatchesProfile && runtimeSessionId
    ? `?${new URLSearchParams({ profile_id: profileId, runtime_session_id: runtimeSessionId }).toString()}`
    : "";

  useEffect(() => {
    jsonFetch<{ profiles: RuntimeProfile[] }>("/api/runtime/profiles")
      .then((data) => setProfiles(data.profiles))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!runtimeSessionId) return;
    jsonFetch<RuntimeSession>(`/api/runtime/session/${encodeURIComponent(runtimeSessionId)}`)
      .then((session) => {
        setRuntimeSession(session);
        setProfileId(session.profile.id);
        if (session.profile.mode === "api-based" || session.profile.mode === "api_based") {
          setEnableDecomposition(true);
          const provider = configuredProvider(session, "verification");
          if (provider === "gemini" || provider === "openai" || provider === "cosmos") {
            setVerificationProvider(provider);
          }
        }
      })
      .catch(() => setRuntimeSession(undefined));
  }, [runtimeSessionId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    if (!isApiBased && effectiveVerificationProvider !== "none" && !verificationApiKey.trim()) {
      setError("Enter an API key for the selected verification provider, or choose no verification.");
      return;
    }
    if (isApiBased && !sessionMatchesProfile) {
      setError("Set up API-based mode in Architecture first. Its opaque session is required to access the selected Qdrant target and Gemini.");
      return;
    }

    setSearching(true);
    setError("");
    setHasSearched(true);
    setDecomposition(undefined);
    setDiagnostics(undefined);
    const payload: SearchRequest = {
      query: query.trim(),
      top_k: 8,
      // The API profile always creates its four modality-specific prompts.
      enable_decomposition: isApiBased || enableDecomposition,
      enable_reranking: shouldRunReranker,
      rerank_top_n: 20,
      profile_id: profileId,
      ...(sessionMatchesProfile && runtimeSessionId ? { runtime_session_id: runtimeSessionId } : {}),
      reranker_provider: effectiveReranker,
      ...(effectiveRerankerModel ? { reranker_model: effectiveRerankerModel } : {}),
      verification: {
        provider: effectiveVerificationProvider,
        ...(!isApiBased && effectiveVerificationProvider !== "none" ? {
          api_key: verificationApiKey.trim(),
          top_n: 7,
          enable_temporal_localization: enableTemporalLocalization,
        } : effectiveVerificationProvider !== "none" ? { top_n: 7, enable_temporal_localization: enableTemporalLocalization } : {}),
      },
    };

    try {
      const data = await jsonFetch<SearchResponse>("/api/query/search", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      setResults(data.results);
      setDecomposition(data.decomposition ?? data.query_decomposition ?? undefined);
      setDiagnostics(data.diagnostics);
    } catch (cause) {
      setError(apiErrorMessage(cause));
      setResults([]);
      setDiagnostics(undefined);
    } finally {
      // The value is never persisted and is cleared when this request completes.
      setVerificationApiKey("");
      setSearching(false);
    }
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">Step 3 of 3</p><h1>Search indexed videos</h1></div>
        <Link className="secondary button" href={`/library${profileQuery}`}>Browse library</Link>
      </div>
      <p className="muted search-intro">Search across visual, audio, speech, and caption vectors. The first search loads query models, so it can take several minutes on a fresh machine.</p>

      <section className="form-section">
        <div className="section-heading"><h2>Search profile</h2><p>{isApiBased ? "Uses the active API session, its selected Qdrant target, and the compatible four-vector embedding profile." : "Uses local query models and the local Qdrant collection."}</p></div>
        <label className="field">
          Indexed embedding profile
          <select value={profileId} onChange={(event) => {
            const next = event.target.value;
            setProfileId(next);
            const api = next === "api-gemini-free-v1";
            setEnableDecomposition(api || enableDecomposition);
            setVerificationProvider(api ? "gemini" : "none");
            setVerificationApiKey("");
            if (!api) setRerankerProvider("none");
          }}>
            {(profiles.length ? profiles : [
              { id: "self-hosted-v1", label: "Self-hosted", mode: "self-hosted" },
              { id: "api-gemini-free-v1", label: "API-based (Gemini)", mode: "api-based" },
            ]).map((profile) => <option value={profile.id} key={profile.id}>{profile.label}</option>)}
          </select>
          {isApiBased && <span>{sessionMatchesProfile ? "Active API session found; keys stay in the backend." : "No active API session. Return to Architecture to configure Qdrant and Gemini."}</span>}
        </label>
      </section>

      <form className="processing-form" onSubmit={submit}>
        <div className="search-form">
          <input aria-label="Search indexed video" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. a person moves a red box" />
          <button className="button" disabled={searching}>{searching ? "Searching and verifying…" : "Search library"}</button>
        </div>
        <section className="form-section">
          <div className="section-heading"><h2>Search options</h2><p>{isApiBased ? "Vector recall, cross-encoder reranking, and final verification are bounded to the retrieved candidates." : "Verification runs only for this request. Keys are never saved in the browser."}</p></div>
          <div className="field-grid">
            <label className="field">Verification provider
              <select value={isApiBased ? (effectiveVerificationProvider === "none" ? "none" : effectiveVerificationProvider) : verificationProvider} onChange={(event) => {
                const provider = event.target.value as VerificationProvider;
                setVerificationProvider(provider);
                // Never carry a credential from one provider to another.
                setVerificationApiKey("");
              }}>
                <option value="none">None, retrieval only</option>
                {isApiBased ? <option value={sessionVerification === "openai" || sessionVerification === "cosmos" ? sessionVerification : "gemini"}>{sessionVerification === "openai" ? "OpenAI from active Architecture setup" : sessionVerification === "cosmos" ? "NVIDIA Cosmos from active Architecture setup" : "Gemini from active Architecture setup"}</option> : <><option value="openai">OpenAI</option><option value="cosmos">NVIDIA Cosmos</option></>}
              </select>
            </label>
            {!isApiBased && effectiveVerificationProvider !== "none" && <label className="field field-wide">{effectiveVerificationProvider === "cosmos" ? "NVIDIA API key" : "OpenAI API key"}
              <input type="password" value={verificationApiKey} onChange={(event) => setVerificationApiKey(event.target.value)} autoComplete="off" spellCheck={false} placeholder="Sent once, then cleared" />
              <span>It is held only in this page while the request is running.</span>
            </label>}
            <label className="field">Precision reranker
              <select value={effectiveReranker} onChange={(event) => {
                setRerankerProvider(event.target.value as "none" | "local_qwen");
                setEnableReranking(event.target.value === "local_qwen");
              }} disabled={sessionMatchesProfile}>
                <option value="none">Disabled, RRF recall only</option>
                <option value="local_qwen">Qwen3-VL-Reranker-2B, local on-demand</option>
              </select>
              <span>{sessionMatchesProfile ? "Configured in Architecture. It receives the RRF shortlist only." : "Runs locally only after RRF selects candidates. No API key is required."}</span>
            </label>
          </div>
          <div className="index-choice">
            <label><input type="checkbox" checked={isApiBased || enableDecomposition} disabled={isApiBased} onChange={(event) => setEnableDecomposition(event.target.checked)} /> Use query decomposition</label>
            <span className="muted">{isApiBased ? "Required for the API profile: Gemini creates visual, audio, transcript, and caption prompts." : "Split the query into visual, audio, transcript, and caption cues before independent retrieval."}</span>
          </div>
          <div className="index-choice">
            <label><input type="checkbox" checked={shouldRunReranker} disabled={effectiveReranker === "none"} onChange={(event) => setEnableReranking(event.target.checked)} /> Run selected reranker</label>
            <span className="muted">A multimodal cross-encoder sees only the fused top candidates and assigns fresh relevance scores. RRF rankings never enter its input.</span>
          </div>
          {effectiveVerificationProvider !== "none" && <div className="index-choice">
            <label><input type="checkbox" checked={enableTemporalLocalization} onChange={(event) => setEnableTemporalLocalization(event.target.checked)} /> Localise verified moments</label>
            <span className="muted">Checks up to seven candidate regions, then densely inspects broad matches to return a short 2â€“5 second span.</span>
          </div>}
        </section>
      </form>

      {error && <p className="error panel">{error}</p>}
      {decomposition && <section className="form-section">
        <div className="section-heading"><h2>Query interpretation</h2><p>Decomposition tier: <code>{decomposition.tier ?? "not reported"}</code></p></div>
        {!!Object.keys(decomposition.weights ?? {}).length && <div className="badge-row">{Object.entries(decomposition.weights ?? {}).map(([modality, weight]) => typeof weight === "number" && Number.isFinite(weight) && <span className="badge" key={modality}>{modality}: {(weight * 100).toFixed(0)}%</span>)}</div>}
        {!!decomposition.required_conditions?.length && <p className="muted">Required conditions: {decomposition.required_conditions.join(" · ")}</p>}
      </section>}
      {diagnostics && <section className="form-section">
        <div className="section-heading"><h2>Retrieval diagnostics</h2><p>Latency and bounded-stage evidence for this search. Quality metrics appear only when evaluation labels are supplied.</p></div>
        <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
      </section>}
      {hasSearched && !searching && !error && !results.length && <section className="empty-state"><h2>No matching indexed windows</h2><p>Try a broader description, or return to the library to make sure a video was indexed into <code>video_windows</code>.</p></section>}

      <section className="results-list">
        {results.map((result, index) => {
          const view = resultView(result);
          return <article className="search-result" key={`${result.window_id}-${index}`}>
            <div className="result-meta">
              <span>#{index + 1}</span>
              <span>{formatRange(view.start, view.end)}{view.hasRefinedRange ? " refined" : ""}</span>
              {view.finalScore !== undefined && <span>{view.finalScore.toFixed(4)} precision</span>}
              <span>{(result.retrieval_score ?? result.score).toFixed(4)} RRF recall</span>
            </div>
            <div className="result-body">
              <div>
                <h2>{result.caption || "Matched indexed video window"}</h2>
                <p>{result.transcript || "No speech transcript for this window."}</p>
                <div className="badge-row">
                  {(result.matched_modalities ?? []).map((modality) => <span className="badge" key={modality}>{modality}</span>)}
                  <span className={`badge ${stateClass(view.state)}`}>{stateLabel(view.state)}</span>
                  {view.confidence !== undefined && <span className="badge">{Math.round(view.confidence * 100)}% confidence</span>}
                  {view.localizationState === "localized" && <span className="badge ok">time-localized</span>}
                </div>
                <details>
                  <summary>Why this result matched</summary>
                  <dl>
                    {(result.modality_evidence ?? []).map((entry) => <div key={entry.modality}><dt>{entry.modality}</dt><dd>rank {entry.rank}, contribution {entry.contribution.toFixed(5)}</dd></div>)}
                    {view.finalScore !== undefined && <div><dt>precision score</dt><dd>{view.finalScore.toFixed(5)} {shouldRunReranker ? "(fresh Qwen cross-encoder score)" : "(reported by the selected precision flow)"}</dd></div>}
                    {view.hasRefinedRange && <div><dt>refined moment</dt><dd>{formatRange(view.start, view.end)}</dd></div>}
                    {view.evidence && <div><dt>verification evidence</dt><dd>{view.evidence}</dd></div>}
                    {view.localizationEvidence && <div><dt>temporal evidence</dt><dd>{view.localizationEvidence}</dd></div>}
                    {view.localizationReason && <div><dt>temporal localisation</dt><dd>{view.localizationReason}</dd></div>}
                    {view.reason && <div><dt>verification note</dt><dd>{view.reason}</dd></div>}
                    {!!view.satisfiedConditions.length && <div><dt>satisfied conditions</dt><dd>{view.satisfiedConditions.join(" · ")}</dd></div>}
                    {!!view.missingConditions.length && <div><dt>missing conditions</dt><dd>{view.missingConditions.join(" · ")}</dd></div>}
                    {!!view.contradictions.length && <div><dt>contradictions</dt><dd>{view.contradictions.join(" · ")}</dd></div>}
                  </dl>
                </details>
                <Link className="text-link" href={`/library/${encodeURIComponent(result.video_id)}${profileQuery}`}>Inspect the indexed record →</Link>
              </div>
              {result.media_available && <video controls preload="metadata" src={`${API}/api/index/media/${encodeURIComponent(result.window_id)}${profileQuery}#t=${view.start},${view.end}`} />}
            </div>
          </article>;
        })}
      </section>
    </main>
  );
}
