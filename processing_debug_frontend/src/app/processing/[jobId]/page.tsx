"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API, Job, jsonFetch } from "@/lib/api";
import { JobNav } from "@/components/JobNav";

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job>();
  const [error, setError] = useState("");
  const load = useCallback(() => jsonFetch<Job>(`/api/processing/jobs/${jobId}`).then(setJob).catch((cause) => setError(String(cause))), [jobId]);
  useEffect(() => { load(); const timer = setInterval(load, 1000); return () => clearInterval(timer); }, [load]);
  async function action(name: "start" | "cancel") {
    setError("");
    try {
      const response = await fetch(`${API}/api/processing/jobs/${jobId}/${name}`, { method: "POST" });
      if (!response.ok) throw new Error(await response.text());
      load();
    } catch (cause) { setError(String(cause)); }
  }
  if (!job) return <main>{error || "Loading job…"}</main>;
  const summary = job.summary;
  const canStart = job.status === "created";
  const canCancel = ["queued", "running"].includes(job.status);
  const indexedCount = Number(summary.qdrant_inserted ?? 0);
  const statusClass = job.status === "failed" ? "error" : ["cancelled", "partial", "completed_with_errors"].includes(job.status) ? "warning" : "ready";
  return <main>
    <div className="page-heading"><div><p className="eyebrow">Indexing job</p><h1>{String(job.metadata.filename ?? "Uploaded video")}</h1><p className="code">{jobId}</p></div>{indexedCount > 0 && <Link className="button secondary" href="/library">Inspect stored windows</Link>}</div>
    <JobNav id={jobId} />
    {error && <p className="error panel">{error}</p>}
    <section className={`status-strip ${statusClass}`}><div><strong>{job.status.replaceAll("_", " ")}</strong><span>{job.stage.replaceAll("_", " ")} · window {job.current_window}/{job.total_windows} · {job.elapsed_seconds.toFixed(1)} seconds</span></div>{canStart && <button onClick={() => action("start")}>Start processing</button>}{canCancel && <button className="secondary" onClick={() => action("cancel")}>Cancel safely</button>}</section>
    <section className="panel"><progress value={job.progress} max="1" style={{ width: "100%" }} /><p className="muted">{Math.round(job.progress * 100)}% complete. Models may take time to download on the first run.</p></section>
    <div className="grid">{[["Total windows", summary.total_windows ?? job.total_windows], ["Selected for VLM", summary.selected_vlm_windows], ["Direct captions", summary.direct_caption_windows], ["Qdrant confirmed", indexedCount], ["VLM calls", summary.actual_openai_calls], ["Calls saved", summary.estimated_calls_saved]].map(([label, value]) => <div className="panel" key={String(label)}><div className="muted">{String(label)}</div><div className="metric">{String(value ?? 0)}</div></div>)}</div>
    {summary.stage_durations && <section className="form-section"><div className="section-heading"><h2>Runtime</h2><p>{summary.stage_timing_semantics ?? "Accumulated time by processing stage."}</p></div>{Object.entries(summary.stage_durations).map(([name, seconds]) => <p key={name}>{name.replaceAll("_", " ")}: <strong>{Number(seconds).toFixed(2)}s</strong></p>)}</section>}
    <section className="models-section"><div className="section-heading"><h2>Model readiness</h2><p>These are reported for this job.</p></div><div className="model-list">{job.model_status.map((model) => <div className="model-row" key={model.component}><div><strong>{model.component}</strong><span>{model.checkpoint}</span></div><span>{model.device}</span><span>{model.message}</span></div>)}</div></section>
    {!!job.errors?.length && <section className="form-section"><h2>Errors</h2>{job.errors.map((entry, index) => <p className="error" key={index}>{entry.window_id ? `${entry.window_id}: ` : ""}{entry.message}</p>)}</section>}
    <section className="form-section"><h2>Diagnostic exports</h2><div className="actions">{["report", "windows", "selector", "transcript", "vlm", "errors", "config", "evaluation"].map((name) => <a className="button secondary" key={name} href={`${API}/api/processing/jobs/${jobId}/exports/${name}`}>{name}</a>)}</div></section>
  </main>;
}
