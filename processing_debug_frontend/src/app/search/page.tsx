"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import {
  API,
  SearchDecomposition,
  SearchRequest,
  SearchResponse,
  SearchResult,
  SearchVerification,
  VerificationProvider,
  jsonFetch,
} from "@/lib/api";

type ResultView = {
  state: string;
  confidence?: number;
  evidence?: string;
  reason?: string;
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

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [decomposition, setDecomposition] = useState<SearchDecomposition>();
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [enableDecomposition, setEnableDecomposition] = useState(false);
  const [verificationProvider, setVerificationProvider] = useState<VerificationProvider>("none");
  const [verificationApiKey, setVerificationApiKey] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    if (verificationProvider !== "none" && !verificationApiKey.trim()) {
      setError("Enter an API key for the selected verification provider, or choose no verification.");
      return;
    }

    setSearching(true);
    setError("");
    setHasSearched(true);
    setDecomposition(undefined);
    const payload: SearchRequest = {
      query: query.trim(),
      top_k: 8,
      enable_decomposition: enableDecomposition,
      verification: {
        provider: verificationProvider,
        ...(verificationProvider !== "none" ? { api_key: verificationApiKey.trim() } : {}),
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
    } catch (cause) {
      setError(String(cause));
      setResults([]);
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
        <Link className="secondary button" href="/library">Browse library</Link>
      </div>
      <p className="muted search-intro">Search across visual, audio, speech, and caption vectors. The first search loads query models, so it can take several minutes on a fresh machine.</p>

      <form className="processing-form" onSubmit={submit}>
        <div className="search-form">
          <input aria-label="Search indexed video" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. a person moves a red box" />
          <button className="button" disabled={searching}>{searching ? "Searching and verifying…" : "Search library"}</button>
        </div>
        <section className="form-section">
          <div className="section-heading"><h2>Search options</h2><p>Verification runs only for this request. Keys are never saved in the browser.</p></div>
          <div className="field-grid">
            <label className="field">Verification provider
              <select value={verificationProvider} onChange={(event) => {
                const provider = event.target.value as VerificationProvider;
                setVerificationProvider(provider);
                // Never carry a credential from one provider to another.
                setVerificationApiKey("");
              }}>
                <option value="none">None, retrieval only</option>
                <option value="openai">OpenAI</option>
                <option value="cosmos">NVIDIA Cosmos</option>
              </select>
            </label>
            {verificationProvider !== "none" && <label className="field field-wide">{verificationProvider === "cosmos" ? "NVIDIA API key" : "OpenAI API key"}
              <input type="password" value={verificationApiKey} onChange={(event) => setVerificationApiKey(event.target.value)} autoComplete="off" spellCheck={false} placeholder="Sent once, then cleared" />
              <span>It is held only in this page while the request is running.</span>
            </label>}
          </div>
          <div className="index-choice">
            <label><input type="checkbox" checked={enableDecomposition} onChange={(event) => setEnableDecomposition(event.target.checked)} /> Use query decomposition</label>
            <span className="muted">Split the query into visual, audio, speech, and caption cues before retrieval.</span>
          </div>
        </section>
      </form>

      {error && <p className="error panel">{error}</p>}
      {decomposition && <section className="form-section">
        <div className="section-heading"><h2>Query interpretation</h2><p>Decomposition tier: <code>{decomposition.tier ?? "not reported"}</code></p></div>
        {!!Object.keys(decomposition.weights ?? {}).length && <div className="badge-row">{Object.entries(decomposition.weights ?? {}).map(([modality, weight]) => typeof weight === "number" && Number.isFinite(weight) && <span className="badge" key={modality}>{modality}: {(weight * 100).toFixed(0)}%</span>)}</div>}
        {!!decomposition.required_conditions?.length && <p className="muted">Required conditions: {decomposition.required_conditions.join(" · ")}</p>}
      </section>}
      {hasSearched && !searching && !error && !results.length && <section className="empty-state"><h2>No matching indexed windows</h2><p>Try a broader description, or return to the library to make sure a video was indexed into <code>video_windows</code>.</p></section>}

      <section className="results-list">
        {results.map((result, index) => {
          const view = resultView(result);
          return <article className="search-result" key={`${result.window_id}-${index}`}>
            <div className="result-meta">
              <span>#{index + 1}</span>
              <span>{formatRange(view.start, view.end)}{view.hasRefinedRange ? " refined" : ""}</span>
              {view.finalScore !== undefined && <span>{view.finalScore.toFixed(4)} final</span>}
              <span>{(result.retrieval_score ?? result.score).toFixed(4)} RRF</span>
            </div>
            <div className="result-body">
              <div>
                <h2>{result.caption || "Matched indexed video window"}</h2>
                <p>{result.transcript || "No speech transcript for this window."}</p>
                <div className="badge-row">
                  {(result.matched_modalities ?? []).map((modality) => <span className="badge" key={modality}>{modality}</span>)}
                  <span className={`badge ${stateClass(view.state)}`}>{stateLabel(view.state)}</span>
                  {view.confidence !== undefined && <span className="badge">{Math.round(view.confidence * 100)}% confidence</span>}
                </div>
                <details>
                  <summary>Why this result matched</summary>
                  <dl>
                    {(result.modality_evidence ?? []).map((entry) => <div key={entry.modality}><dt>{entry.modality}</dt><dd>rank {entry.rank}, contribution {entry.contribution.toFixed(5)}</dd></div>)}
                    {view.finalScore !== undefined && <div><dt>final score</dt><dd>{view.finalScore.toFixed(5)}</dd></div>}
                    {view.hasRefinedRange && <div><dt>refined moment</dt><dd>{formatRange(view.start, view.end)}</dd></div>}
                    {view.evidence && <div><dt>verification evidence</dt><dd>{view.evidence}</dd></div>}
                    {view.reason && <div><dt>verification note</dt><dd>{view.reason}</dd></div>}
                    {!!view.satisfiedConditions.length && <div><dt>satisfied conditions</dt><dd>{view.satisfiedConditions.join(" · ")}</dd></div>}
                    {!!view.missingConditions.length && <div><dt>missing conditions</dt><dd>{view.missingConditions.join(" · ")}</dd></div>}
                    {!!view.contradictions.length && <div><dt>contradictions</dt><dd>{view.contradictions.join(" · ")}</dd></div>}
                  </dl>
                </details>
                <Link className="text-link" href={`/library/${encodeURIComponent(result.video_id)}`}>Inspect the indexed record →</Link>
              </div>
              {result.media_available && <video controls preload="metadata" src={`${API}/api/index/media/${encodeURIComponent(result.window_id)}#t=${view.start},${view.end}`} />}
            </div>
          </article>;
        })}
      </section>
    </main>
  );
}
