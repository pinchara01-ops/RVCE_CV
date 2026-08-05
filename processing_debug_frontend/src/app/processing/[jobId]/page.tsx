"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API, ApiError, Job, JobActivity, jsonFetch } from "@/lib/api";
import { JobNav } from "@/components/JobNav";

function label(value: string) {
  return value.replaceAll("_", " ");
}

function parseTimestamp(timestamp: string | number) {
  return new Date(typeof timestamp === "number" ? timestamp * 1000 : timestamp);
}

function displayTime(timestamp: string | number) {
  const parsed = parseTimestamp(timestamp);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function dateTime(timestamp: string | number) {
  const parsed = parseTimestamp(timestamp);
  return Number.isNaN(parsed.getTime()) ? String(timestamp) : parsed.toISOString();
}

function hasDetails(activity: JobActivity) {
  return !!activity.details && Object.keys(activity.details).length > 0;
}

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [storedJob, setStoredJob] = useState<Job>();
  const [error, setError] = useState<{ jobId: string; message: string }>();
  const [missingJobId, setMissingJobId] = useState<string>();
  const jobMissing = missingJobId === jobId;
  const currentError = error?.jobId === jobId ? error.message : "";
  const job = storedJob?.job_id === jobId ? storedJob : undefined;

  const load = useCallback(async () => {
    try {
      const nextJob = await jsonFetch<Job>(`/api/processing/jobs/${jobId}`);
      setStoredJob(nextJob);
      setError(undefined);
      setMissingJobId(undefined);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        setStoredJob(undefined);
        setError(undefined);
        setMissingJobId(jobId);
        return;
      }
      setError({ jobId, message: cause instanceof Error ? cause.message : String(cause) });
    }
  }, [jobId]);

  useEffect(() => {
    if (jobMissing) return;
    const poll = () => { void load(); };
    const initial = window.setTimeout(poll, 0);
    const timer = window.setInterval(poll, 1000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [jobMissing, load]);

  async function action(name: "start" | "cancel") {
    setError(undefined);
    try {
      const response = await fetch(`${API}/api/processing/jobs/${jobId}/${name}`, { method: "POST" });
      if (!response.ok) {
        const body = await response.text();
        if (response.status === 404) {
          setStoredJob(undefined);
          setMissingJobId(jobId);
          return;
        }
        throw new ApiError(response.status, body);
      }
      void load();
    } catch (cause) {
      setError({ jobId, message: cause instanceof Error ? cause.message : String(cause) });
    }
  }

  if (jobMissing) return <main><section className="empty-state panel restart-state"><p className="eyebrow">Live status unavailable</p><h1>This job is no longer active</h1><p>The backend no longer has this job in memory. This commonly happens after the local API restarts, so its live progress cannot be resumed from this page.</p><div className="actions"><Link className="button" href="/processing">Create another indexing job</Link><Link className="button secondary" href="/library">Inspect library</Link></div></section></main>;
  if (!job) return <main><section className="empty-state panel"><p className="eyebrow">Loading indexing job</p><h1>{currentError ? "Could not load this job" : "Loading job..."}</h1>{currentError && <><p className="error">{currentError}</p><button onClick={() => { void load(); }}>Retry</button></>}</section></main>;

  const summary = job.summary;
  const canStart = job.status === "created";
  const canCancel = ["queued", "running"].includes(job.status);
  const indexedCount = Number(summary.qdrant_inserted ?? 0);
  const statusClass = job.status === "failed" ? "error" : ["cancelled", "partial", "completed_with_errors"].includes(job.status) ? "warning" : "ready";
  const activity = [...(job.activity ?? [])].sort((first, second) => second.sequence - first.sequence);
  const latestActivity = activity[0];
  const activityContext = job.total_windows > 0 ? `${label(job.stage)} / window ${job.current_window}/${job.total_windows}` : label(job.stage);
  const waitingMessage = job.status === "created" ? "Waiting for you to start this job." : job.status === "running" ? "Waiting for the worker to report its first update." : "No worker activity was reported for this job.";

  return <main>
    <div className="page-heading"><div><p className="eyebrow">Indexing job</p><h1>{String(job.metadata.filename ?? "Uploaded video")}</h1><p className="code">{jobId}</p></div>{indexedCount > 0 && <Link className="button secondary" href="/library">Inspect stored windows</Link>}</div>
    <JobNav id={jobId} />
    {currentError && <p className="error panel">{currentError}</p>}
    <section className={`status-strip ${statusClass}`}><div><strong>{label(job.status)}</strong><span>{label(job.stage)} / window {job.current_window}/{job.total_windows} / {job.elapsed_seconds.toFixed(1)} seconds</span></div>{canStart && <button onClick={() => action("start")}>Start processing</button>}{canCancel && <button className="secondary" onClick={() => action("cancel")}>Cancel safely</button>}</section>
    <section className="panel"><progress value={job.progress} max="1" style={{ width: "100%" }} /><p className="muted">{Math.round(job.progress * 100)}% complete. Models may take time to download on the first run.</p></section>
    <div className="grid">{[["Total windows", summary.total_windows ?? job.total_windows], ["Selected for VLM", summary.selected_vlm_windows], ["Direct captions", summary.direct_caption_windows], ["Qdrant confirmed", indexedCount], ["VLM calls", summary.actual_openai_calls], ["Calls saved", summary.estimated_calls_saved]].map(([name, value]) => <div className="panel" key={String(name)}><div className="muted">{String(name)}</div><div className="metric">{String(value ?? 0)}</div></div>)}</div>

    <section className="diagnostic-section" aria-labelledby="live-diagnostics-heading">
      <div className="section-heading"><div><h2 id="live-diagnostics-heading">Live diagnostics</h2><p>Updates every second while this page is open. Each item is a structured update from the indexing worker.</p></div><span className="diagnostic-count">{activity.length} update{activity.length === 1 ? "" : "s"}</span></div>
      <div className={`diagnostic-latest ${latestActivity?.level ?? "info"}`} aria-live="polite">
        <span className="diagnostic-label">Now</span>
        <div><strong>{latestActivity?.message ?? waitingMessage}</strong><span>{latestActivity ? `${label(latestActivity.area)} / ${activityContext}` : activityContext}</span></div>
        {latestActivity && <time dateTime={dateTime(latestActivity.timestamp)}>{displayTime(latestActivity.timestamp)}</time>}
      </div>
      {activity.length > 0 ? <ol className="diagnostic-list">{activity.slice(0, 100).map((entry) => <li className="diagnostic-row" key={entry.sequence}>
        <time className="diagnostic-time" dateTime={dateTime(entry.timestamp)}>{displayTime(entry.timestamp)}</time>
        <span className={`diagnostic-level ${entry.level}`}>{entry.level}</span>
        <div className="diagnostic-message"><strong>{entry.message}</strong><span>{label(entry.area)}{entry.area !== job.stage ? ` / current stage: ${label(job.stage)}` : ""}</span>{hasDetails(entry) && <details className="diagnostic-detail"><summary>Details</summary><pre>{JSON.stringify(entry.details, null, 2)}</pre></details>}</div>
      </li>)}</ol> : <p className="diagnostic-empty">{waitingMessage}</p>}
      {activity.length > 100 && <p className="hint">Showing the latest 100 updates. Download the activity export for the full job record.</p>}
    </section>

    {summary.stage_durations && <section className="form-section"><div className="section-heading"><h2>Runtime</h2><p>{summary.stage_timing_semantics ?? "Accumulated time by processing stage."}</p></div>{Object.entries(summary.stage_durations).map(([name, seconds]) => <p key={name}>{label(name)}: <strong>{Number(seconds).toFixed(2)}s</strong></p>)}</section>}
    <section className="models-section"><div className="section-heading"><h2>Model readiness</h2><p>These are reported for this job.</p></div><div className="model-list">{job.model_status.map((model) => <div className="model-row" key={model.component}><div><strong>{model.component}</strong><span>{model.checkpoint}</span></div><span>{model.device}</span><span>{model.message}</span></div>)}</div></section>
    {!!job.errors?.length && <section className="form-section"><h2>Errors</h2>{job.errors.map((entry, index) => <p className="error" key={index}>{entry.window_id ? `${entry.window_id}: ` : ""}{entry.message}</p>)}</section>}
    <section className="form-section"><h2>Diagnostic exports</h2><div className="actions">{["report", "windows", "selector", "transcript", "vlm", "errors", "config", "evaluation", "activity"].map((name) => <a className="button secondary" key={name} href={`${API}/api/processing/jobs/${jobId}/exports/${name}`}>{name}</a>)}</div></section>
  </main>;
}
