"use client";

import { useState } from "react";
import { API } from "@/lib/api";

type Moment = {
  start: number;
  end: number;
  description: string;
  confidence: number;
  clip_url: string | null;
};

type QuickResponse = {
  query: string;
  summary: string;
  model: string;
  moments: Moment[];
};

const MODELS = [
  { id: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite" },
  { id: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite" },
];

function formatRange(start: number, end: number): string {
  const stamp = (value: number) => {
    const minutes = Math.floor(value / 60);
    const seconds = Math.floor(value % 60);
    return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  };
  return `${stamp(start)}, ${stamp(end)}`;
}

export function QuickDemoSection() {
  const [model, setModel] = useState(MODELS[0].id);
  const [query, setQuery] = useState("");
  const [video, setVideo] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [response, setResponse] = useState<QuickResponse>();

  async function run() {
    if (!video) {
      setError("Choose a video first.");
      return;
    }
    if (!query.trim()) {
      setError("Describe the moment you want to find.");
      return;
    }

    setBusy(true);
    setError("");
    setResponse(undefined);

    const body = new FormData();
    body.append("video", video, video.name || "video.mp4");
    body.append("query", query.trim());
    body.append("model", model);

    try {
      const result = await fetch(`${API}/api/quick/search`, { method: "POST", body });
      if (!result.ok) {
        const raw = await result.text();
        let message = raw;
        try {
          const parsed = JSON.parse(raw) as { detail?: unknown };
          if (typeof parsed.detail === "string") message = parsed.detail;
        } catch {
          // Not JSON; show the raw body.
        }
        throw new Error(message);
      }
      setResponse((await result.json()) as QuickResponse);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The search could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="form-section">
      <div className="section-heading">
        <h2>Single-call video search</h2>
        <p>
          Send one video and one question straight to the selected model, which returns matching
          time ranges. No indexing, Qdrant, or runtime session is involved.
        </p>
      </div>

      <div className="field-grid">
        <label className="field">
          Model
          <select value={model} onChange={(event) => setModel(event.target.value)} disabled={busy}>
            {MODELS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
          <span>Both accept video directly. Switch to compare their time ranges.</span>
        </label>

        <label className="field">
          Video
          <input
            type="file"
            accept="video/*"
            disabled={busy}
            onChange={(event) => setVideo(event.target.files?.[0])}
          />
          <span>
            {video ? `${video.name} · ${(video.size / 1_048_576).toFixed(1)} MB` : "MP4, WebM, or MOV."}
          </span>
        </label>
      </div>

      <div className="search-form">
        <input
          aria-label="Describe the moment to find"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          disabled={busy}
          placeholder="e.g. a car runs a red light"
        />
        <button type="button" className="button" onClick={run} disabled={busy || !video}>
          {busy ? "Searching…" : "Find the moment"}
        </button>
      </div>

      {busy && <p className="runtime-message">Analysing the video with {model}. Keep this page open.</p>}
      {error && <p className="error panel">{error}</p>}

      {response && (
        <>
          <p className="muted">
            {response.moments.length} moment{response.moments.length === 1 ? "" : "s"} from{" "}
            <code>{response.model}</code>
            {response.summary ? ` · ${response.summary}` : ""}
          </p>

          {!response.moments.length && (
            <div className="empty-state">
              <h2>No matching moments</h2>
              <p>Nothing in this footage matched that description.</p>
            </div>
          )}

          <section className="results-list">
            {response.moments.map((moment, index) => (
              <article className="search-result" key={`${moment.start}-${index}`}>
                <div className="result-meta">
                  <span>#{index + 1}</span>
                  <span>{formatRange(moment.start, moment.end)}</span>
                  <span>{Math.round(moment.confidence * 100)}% match</span>
                </div>
                <div className="result-body">
                  <div>
                    <h2>{moment.description || "Matching moment"}</h2>
                    {!moment.clip_url && (
                      <p className="muted">
                        This clip could not be prepared, but the moment is at{" "}
                        {formatRange(moment.start, moment.end)}.
                      </p>
                    )}
                  </div>
                  {moment.clip_url && (
                    <video controls preload="metadata" src={`${API}${moment.clip_url}`} />
                  )}
                </div>
              </article>
            ))}
          </section>
        </>
      )}
    </section>
  );
}
