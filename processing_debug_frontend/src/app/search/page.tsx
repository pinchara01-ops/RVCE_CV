"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { API, SearchResult, jsonFetch } from "@/lib/api";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError("");
    setHasSearched(true);
    try {
      const data = await jsonFetch<{ results: SearchResult[] }>("/api/query/search", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query, top_k: 8 }),
      });
      setResults(data.results);
    } catch (cause) {
      setError(String(cause));
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  return <main>
    <div className="page-heading"><div><p className="eyebrow">Step 3 of 3</p><h1>Search indexed videos</h1></div><Link className="secondary button" href="/library">Browse library</Link></div>
    <p className="muted search-intro">Search across visual, audio, speech, and caption vectors. The first search loads query models, so it can take several minutes on a fresh machine.</p>
    <form className="search-form" onSubmit={submit}><input aria-label="Search indexed video" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. a person moves a red box" /><button className="button" disabled={searching}>{searching ? "Loading models and searching…" : "Search library"}</button></form>
    {error && <p className="error panel">{error}</p>}
    {hasSearched && !searching && !error && !results.length && <section className="empty-state"><h2>No matching indexed windows</h2><p>Try a broader description, or return to the library to make sure a video was indexed into <code>video_windows</code>.</p></section>}
    <section className="results-list">{results.map((result, index) => <article className="search-result" key={`${result.window_id}-${index}`}><div className="result-meta"><span>#{index + 1}</span><span>{result.start.toFixed(1)}s–{result.end.toFixed(1)}s</span><span>{result.score.toFixed(4)} RRF</span></div><div className="result-body"><div><h2>{result.caption || "Matched indexed video window"}</h2><p>{result.transcript || "No speech transcript for this window."}</p><div className="badge-row">{result.matched_modalities.map((modality) => <span className="badge" key={modality}>{modality}</span>)}</div><details><summary>Why this result matched</summary><dl>{result.modality_evidence.map((entry) => <div key={entry.modality}><dt>{entry.modality}</dt><dd>rank {entry.rank}, contribution {entry.contribution.toFixed(5)}</dd></div>)}</dl></details><Link className="text-link" href={`/library/${encodeURIComponent(result.video_id)}`}>Inspect the indexed record →</Link></div>{result.media_available && <video controls preload="metadata" src={`${API}/api/index/media/${encodeURIComponent(result.window_id)}#t=${result.start},${result.end}`} />}</div></article>)}</section>
  </main>;
}
