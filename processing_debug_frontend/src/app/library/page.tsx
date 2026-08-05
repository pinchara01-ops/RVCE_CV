"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { IndexHealth, IndexedVideo, jsonFetch } from "@/lib/api";

export default function LibraryPage() {
  const [health, setHealth] = useState<IndexHealth>();
  const [videos, setVideos] = useState<IndexedVideo[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextHealth, data] = await Promise.all([
        jsonFetch<IndexHealth>("/api/index/health"),
        jsonFetch<{ videos: IndexedVideo[] }>("/api/index/videos"),
      ]);
      setHealth(nextHealth);
      setVideos(data.videos);
    } catch (cause) {
      setError(String(cause));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return <main>
    <div className="page-heading">
      <div><p className="eyebrow">Step 2 of 3</p><h1>Indexed library</h1></div>
      <button className="secondary" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
    </div>
    {error && <p className="error panel">{error}</p>}
    <section className={`status-strip ${health?.reachable ? "ready" : "warning"}`}>
      <div><strong>{health?.collection_name ?? "video_windows"}</strong><span>{health?.reachable ? `${health.points_count} stored windows` : health?.error ?? "Qdrant is not reachable"}</span></div>
      <Link href="/processing">Index another video</Link>
    </section>
    {!loading && !videos.length && <section className="empty-state"><h2>Your library is empty</h2><p>Index a video with “Save real vectors into Qdrant” enabled. It will appear here after the job completes.</p><Link className="button" href="/processing">Create indexing job</Link></section>}
    {!!videos.length && <section className="library-table scroll"><table><thead><tr><th>Video</th><th>Windows</th><th>Duration</th><th>Captions</th><th>Media</th><th /></tr></thead><tbody>{videos.map((video) => <tr key={video.video_id}><td><strong>{video.source_filename || video.video_id.slice(0, 12)}</strong><span className="code">{video.video_id}</span></td><td>{video.windows}</td><td>{video.start.toFixed(1)}s–{video.end.toFixed(1)}s</td><td>{video.direct_captions} direct, {video.caption_available} available</td><td><span className={video.media_available ? "ok" : "muted"}>{video.media_available ? "playable" : "not available"}</span></td><td><Link className="text-link" href={`/library/${encodeURIComponent(video.video_id)}`}>Inspect windows →</Link></td></tr>)}</tbody></table></section>}
  </main>;
}
