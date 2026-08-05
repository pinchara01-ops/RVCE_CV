"use client";

import Link from "next/link";
import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { API, IndexedWindow, RuntimeSession, jsonFetch, loadRuntimeSessionId } from "@/lib/api";

export default function VideoLibraryPage() {
  return <Suspense fallback={<main className="page-loading">Loading indexed video…</main>}><VideoLibraryContent /></Suspense>;
}

function VideoLibraryContent() {
  const { videoId } = useParams<{ videoId: string }>();
  const searchParams = useSearchParams();
  const runtimeSessionId = searchParams.get("runtime_session_id") || loadRuntimeSessionId();
  const requestedProfileId = searchParams.get("profile_id");
  const [runtimeSession, setRuntimeSession] = useState<RuntimeSession>();
  const [runtimeSessionState, setRuntimeSessionState] = useState<"not_required" | "pending" | "ready" | "missing">(
    () => runtimeSessionId ? "pending" : "not_required",
  );
  const profileId = runtimeSession?.profile.id || (runtimeSessionId ? undefined : requestedProfileId || "self-hosted-v1");
  const profileQuery = profileId === "api-gemini-free-v1" && runtimeSessionId && runtimeSession?.profile.id === profileId
    ? `&${new URLSearchParams({ profile_id: profileId, runtime_session_id: runtimeSessionId }).toString()}`
    : "";
  const profileQueryPrefix = profileQuery ? `?${profileQuery.slice(1)}` : "";
  const [windows, setWindows] = useState<IndexedWindow[]>([]);
  const [selected, setSelected] = useState<string>();
  const [selectedDetail, setSelectedDetail] = useState<IndexedWindow>();
  const [error, setError] = useState("");

  useEffect(() => {
    if (!runtimeSessionId) return;
    let cancelled = false;
    const start = window.setTimeout(() => {
      setRuntimeSessionState("pending");
      setRuntimeSession(undefined);
      jsonFetch<RuntimeSession>(`/api/runtime/session/${encodeURIComponent(runtimeSessionId)}`)
        .then((session) => {
          if (cancelled) return;
          setRuntimeSession(session);
          setRuntimeSessionState("ready");
        })
        .catch(() => {
          if (cancelled) return;
          setRuntimeSessionState("missing");
        });
    }, 0);
    return () => { cancelled = true; window.clearTimeout(start); };
  }, [runtimeSessionId]);

  useEffect(() => {
    if (runtimeSessionState === "pending") return;
    if (runtimeSessionState === "missing" || (requestedProfileId === "api-gemini-free-v1" && !runtimeSession)) {
      const reset = window.setTimeout(() => {
        setWindows([]);
        setSelected(undefined);
        setSelectedDetail(undefined);
        setError("The API-based architecture session has expired or is unavailable. Return to Architecture to enter the cloud credentials again.");
      }, 0);
      return () => window.clearTimeout(reset);
    }
    let cancelled = false;
    // Loading every high-dimensional vector in a video makes the inspector
    // slow on a laptop. List the lightweight records first, then fetch the
    // selected record with its vector summaries below.
    jsonFetch<{ windows: IndexedWindow[] }>(
      `/api/index/windows?video_id=${encodeURIComponent(videoId)}&limit=500&vectors=false${profileQuery}`,
    )
      .then((data) => {
        if (cancelled) return;
        setWindows(data.windows);
        setSelected(data.windows[0]?.payload.window_id);
        setSelectedDetail(undefined);
      })
      .catch((cause) => {
        if (!cancelled) setError(String(cause));
      });
    return () => { cancelled = true; };
  }, [videoId, profileQuery, requestedProfileId, runtimeSession, runtimeSessionState]);

  useEffect(() => {
    if (!selected || runtimeSessionState === "pending" || runtimeSessionState === "missing") return;
    let cancelled = false;
    jsonFetch<IndexedWindow>(
      `/api/index/windows/${encodeURIComponent(selected)}?vectors=true${profileQuery}`,
    )
      .then((window) => {
        if (!cancelled) setSelectedDetail(window);
      })
      .catch((cause) => {
        if (!cancelled) setError(String(cause));
      });
    return () => { cancelled = true; };
  }, [selected, profileQuery, runtimeSessionState]);

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
        <Link className="secondary button" href={`/library${profileQueryPrefix}`}>Back to library</Link>
      </div>
      {error && <p className="error panel">{error}</p>}
      {active && (
        <section className="video-inspector">
          <div className="video-stage">
            {canPlay ? (
              <video controls src={`${API}/api/index/media/${encodeURIComponent(String(active.payload.window_id))}${profileQueryPrefix}#t=${start},${end}`} />
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
