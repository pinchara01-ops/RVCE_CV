"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { API, IndexedWindow, jsonFetch } from "@/lib/api";

export default function VideoLibraryPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const [windows, setWindows] = useState<IndexedWindow[]>([]);
  const [selected, setSelected] = useState<string>();
  const [selectedDetail, setSelectedDetail] = useState<IndexedWindow>();
  const [error, setError] = useState("");

  useEffect(() => {
    // Loading every high-dimensional vector in a video makes the inspector
    // slow on a laptop. List the lightweight records first, then fetch the
    // selected record with its vector summaries below.
    jsonFetch<{ windows: IndexedWindow[] }>(
      `/api/index/windows?video_id=${encodeURIComponent(videoId)}&limit=500&vectors=false`,
    )
      .then((data) => {
        setWindows(data.windows);
        setSelected(data.windows[0]?.payload.window_id);
        setSelectedDetail(undefined);
      })
      .catch((cause) => setError(String(cause)));
  }, [videoId]);

  useEffect(() => {
    if (!selected) return;
    jsonFetch<IndexedWindow>(
      `/api/index/windows/${encodeURIComponent(selected)}?vectors=true`,
    )
      .then(setSelectedDetail)
      .catch((cause) => setError(String(cause)));
  }, [selected]);

  const listedActive = useMemo(
    () => windows.find((window) => window.payload.window_id === selected) ?? windows[0],
    [selected, windows],
  );
  const active = selectedDetail?.payload.window_id === selected ? selectedDetail : listedActive;
  const start = Number(active?.payload.start ?? 0);
  const end = Number(active?.payload.end ?? 0);
  const canPlay = Boolean(active?.payload.media_available && active?.payload.window_id);

  return (
    <main>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Stored Qdrant records</p>
          <h1>Indexed video</h1>
          <p className="code">{videoId}</p>
        </div>
        <Link className="secondary button" href="/library">Back to library</Link>
      </div>
      {error && <p className="error panel">{error}</p>}
      {active && (
        <section className="video-inspector">
          <div className="video-stage">
            {canPlay ? (
              <video controls src={`${API}/api/index/media/${encodeURIComponent(String(active.payload.window_id))}#t=${start},${end}`} />
            ) : (
              <div className="media-unavailable">The original uploaded file is not available to the server.</div>
            )}
          </div>
          <div className="window-summary">
            <p className="eyebrow">Window {active.payload.window_id}</p>
            <h2>{start.toFixed(1)}s–{end.toFixed(1)}s</h2>
            <p><strong>Transcript</strong><br />{String(active.payload.transcript || "No speech transcript")}</p>
            <p><strong>Caption</strong><br />{String(active.payload.caption || "No direct caption available")}</p>
            <div className="badge-row">
              {["has_audio", "caption_direct", "caption_inherited", "caption_available", "vlm_processed"]
                .filter((key) => Boolean(active.payload[key]))
                .map((key) => <span className="badge" key={key}>{key.replaceAll("_", " ")}</span>)}
            </div>
          </div>
        </section>
      )}
      <section className="split-view">
        <div className="window-list">
          <h2>Windows</h2>
          {windows.map((window) => (
            <button
              className={`window-item ${window.payload.window_id === active?.payload.window_id ? "active" : ""}`}
              key={window.point_id}
              onClick={() => setSelected(String(window.payload.window_id))}
            >
              <span>{Number(window.payload.start).toFixed(1)}s–{Number(window.payload.end).toFixed(1)}s</span>
              <strong>{String(window.payload.caption || window.payload.transcript || "No text evidence").slice(0, 90)}</strong>
              <small>{window.point_id}</small>
            </button>
          ))}
        </div>
        <div className="stored-record">
          <h2>Stored record</h2>
          {active && (
            <>
              <dl>
                {Object.entries(active.payload)
                  .filter(([key]) => !["transcript", "caption"].includes(key))
                  .map(([key, value]) => (
                    <Fragment key={key}>
                      <dt>{key}</dt>
                      <dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
                    </Fragment>
                  ))}
              </dl>
              <h3>Vector summaries</h3>
              <pre>{JSON.stringify(active.vectors ?? {}, null, 2)}</pre>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
