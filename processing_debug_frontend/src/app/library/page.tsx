"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { LibraryDiagnostics } from "@/components/LibraryDiagnostics";
import {
  IndexHealth,
  IndexedVideo,
  LibraryDiagnostic,
  RuntimeSession,
  ApiError,
  apiErrorMessage,
  jsonFetch,
  loadRuntimeSessionId,
} from "@/lib/api";

export default function LibraryPage() {
  return <Suspense fallback={<main className="page-loading">Loading library…</main>}><LibraryContent /></Suspense>;
}

function LibraryContent() {
  const searchParams = useSearchParams();
  const runtimeSessionId = searchParams.get("runtime_session_id") || loadRuntimeSessionId();
  const requestedProfileId = searchParams.get("profile_id");
  const [runtimeSession, setRuntimeSession] = useState<RuntimeSession>();
  const [runtimeSessionState, setRuntimeSessionState] = useState<"not_required" | "pending" | "ready" | "missing">(
    () => runtimeSessionId ? "pending" : "not_required",
  );
  const profileId = runtimeSession?.profile.id || (runtimeSessionId ? undefined : requestedProfileId || "self-hosted-v1");
  const profileQuery = profileId === "api-gemini-free-v1" && runtimeSessionId && runtimeSession?.profile.id === profileId
    ? `?${new URLSearchParams({ profile_id: profileId, runtime_session_id: runtimeSessionId }).toString()}`
    : "";
  const [health, setHealth] = useState<IndexHealth>();
  const [videos, setVideos] = useState<IndexedVideo[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [diagnostics, setDiagnostics] = useState<LibraryDiagnostic[]>([]);
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
  const loadDiagnostics = useCallback(async () => {
    try {
      const result = await jsonFetch<{ diagnostics: LibraryDiagnostic[] }>("/api/diagnostics/library?limit=50");
      setDiagnostics(result.diagnostics);
    } catch {
      // The original error remains more useful if the diagnostic endpoint is unavailable.
    }
  }, []);
  const load = useCallback(async () => {
    if (runtimeSessionState === "pending") return;
    setLoading(true);
    setError("");
    if (runtimeSessionState === "missing" || (requestedProfileId === "api-gemini-free-v1" && !runtimeSession)) {
      setVideos([]);
      setHealth(undefined);
      setError("The API-based architecture session has expired or is unavailable. Return to Architecture to enter the cloud credentials again.");
      setLoading(false);
      return;
    }
    try {
      let nextHealth: IndexHealth | undefined;
      let data: { videos: IndexedVideo[] } | undefined;
      let lastError: unknown;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          [nextHealth, data] = await Promise.all([
            jsonFetch<IndexHealth>(`/api/index/health${profileQuery}`),
            jsonFetch<{ videos: IndexedVideo[] }>(`/api/index/videos${profileQuery}`),
          ]);
          if (nextHealth.reachable) break;
          lastError = new Error(nextHealth.error || "Qdrant is temporarily unavailable.");
        } catch (cause) {
          lastError = cause;
          // The backend already made bounded Qdrant retry attempts and wrote
          // a diagnostic. Surface that result promptly instead of making the
          // user wait through another three identical browser retries.
          if (cause instanceof ApiError) break;
        }
        if (attempt < 2) {
          await new Promise<void>((resolve) => window.setTimeout(resolve, 1000 * (attempt + 1)));
        }
      }
      if (!nextHealth?.reachable || !data) throw lastError || new Error("Qdrant is temporarily unavailable.");
      setHealth(nextHealth);
      setVideos(data.videos);
    } catch (cause) {
      setError(apiErrorMessage(cause));
      void loadDiagnostics();
    } finally {
      setLoading(false);
    }
  }, [loadDiagnostics, profileQuery, requestedProfileId, runtimeSession, runtimeSessionState]);
  useEffect(() => {
    if (runtimeSessionState === "pending") return;
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load, runtimeSessionState]);

  return <main>
    <div className="page-heading">
      <div><p className="eyebrow">Step 2 of 3</p><h1>Indexed library</h1></div>
      <button className="secondary" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
    </div>
    {error && <p className="error panel">{error}</p>}
    <LibraryDiagnostics diagnostics={diagnostics} />
    <section className={`status-strip ${health?.reachable ? "ready" : "warning"}`}>
      <div><strong>{health?.collection_name ?? "video_windows"}</strong><span>{health?.reachable ? `${health.points_count} stored windows` : health?.error ?? "Qdrant is not reachable"}</span></div>
      <Link href={`/processing${profileQuery}`}>Index another video</Link>
    </section>
    {!loading && !videos.length && <section className="empty-state"><h2>Your library is empty</h2><p>Index a video with “Save real vectors into Qdrant” enabled. It will appear here after the job completes.</p><Link className="button" href={`/processing${profileQuery}`}>Create indexing job</Link></section>}
    {!!videos.length && <section className="library-table scroll"><table><thead><tr><th>Video</th><th>Profile</th><th>Windows</th><th>Duration</th><th>Captions</th><th>Media</th><th /></tr></thead><tbody>{videos.map((video) => <tr key={video.video_id}><td><strong>{video.source_filename || video.video_id.slice(0, 12)}</strong><span className="code">{video.video_id}</span></td><td><code>{video.embedding_profile ?? profileId}</code></td><td>{video.windows}</td><td>{video.start.toFixed(1)}s–{video.end.toFixed(1)}s</td><td>{video.direct_captions} direct, {video.caption_available} available</td><td><span className={video.media_available ? "ok" : "muted"}>{video.media_available ? "playable" : "not available"}</span></td><td><Link className="text-link" href={`/library/${encodeURIComponent(video.video_id)}${profileQuery}`}>Inspect windows →</Link></td></tr>)}</tbody></table></section>}
  </main>;
}
