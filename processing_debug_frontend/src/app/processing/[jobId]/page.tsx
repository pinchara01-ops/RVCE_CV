"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API, Job, jsonFetch } from "@/lib/api";
import { JobNav } from "@/components/JobNav";

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job>();
  const [error, setError] = useState("");
  const load = useCallback(
    () => jsonFetch<Job>(`/api/processing/jobs/${jobId}`).then(setJob).catch((e) => setError(String(e))),
    [jobId],
  );
  useEffect(() => {
    load();
    const timer = setInterval(load, 1000);
    return () => clearInterval(timer);
  }, [load]);
  async function action(name: string) {
    await fetch(`${API}/api/processing/jobs/${jobId}/${name}`, { method: "POST" });
    load();
  }
  if (!job) return <main>{error || "Loading…"}</main>;
  const s = job.summary;
  return <main><h1>Job {jobId.slice(0, 8)}</h1><JobNav id={jobId}/><div className="actions"><button onClick={() => action("start")}>Start processing</button><button className="secondary" onClick={() => action("cancel")}>Cancel safely</button></div><div className="panel"><progress value={job.progress} max="1" style={{width:"100%"}}/><p>{job.status} · {job.stage} · window {job.current_window}/{job.total_windows} · {job.elapsed_seconds.toFixed(1)}s</p></div><div className="grid">{[["Selected",s.selected_vlm_windows],["OpenAI calls",s.actual_openai_calls],["Calls saved",s.estimated_calls_saved],["Direct",s.direct_caption_windows],["Inherited",s.inherited_caption_windows],["Unavailable",s.unavailable_caption_windows],["Qdrant inserted",s.qdrant_inserted]].map(([k,v])=><div className="panel" key={String(k)}><div className="muted">{String(k)}</div><div className="metric">{String(v??0)}</div></div>)}</div><h2>Models</h2><div className="grid">{job.model_status.map(m=><div className="panel" key={m.component}><b>{m.component}: {m.checkpoint}</b><div>{m.provider_kind} · {m.device}</div><div>{m.message}</div></div>)}</div>{job.errors?.map((e,i)=><p className="error" key={i}>{e.message}</p>)}<h2>Exports</h2><div className="actions">{["report","windows","selector","transcript","vlm","errors","config","evaluation"].map(x=><a key={x} href={`${API}/api/processing/jobs/${jobId}/exports/${x}`}>{x}</a>)}</div></main>;
}
