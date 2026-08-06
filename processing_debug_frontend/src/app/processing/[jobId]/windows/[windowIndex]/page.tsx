"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API, IndexedWindow, WindowRow, jsonFetch } from "@/lib/api";
import { JobNav } from "@/components/JobNav";

export default function WindowDetail() {
  const { jobId, windowIndex } = useParams<{ jobId: string; windowIndex: string }>();
  const [row, setRow] = useState<WindowRow>();
  const [stored, setStored] = useState<IndexedWindow>();
  const [storedError, setStoredError] = useState("");
  useEffect(() => {
    jsonFetch<WindowRow>(`/api/processing/jobs/${jobId}/windows/${windowIndex}`).then((data) => {
      setRow(data);
      if (data.indexed) jsonFetch<IndexedWindow>(`/api/index/windows/${encodeURIComponent(data.window_id)}?vectors=true`).then(setStored).catch((cause) => setStoredError(String(cause)));
    });
  }, [jobId, windowIndex]);
  if (!row) return <main>Loading window…</main>;
  return <main>
    <div className="page-heading"><div><p className="eyebrow">Window {row.index}</p><h1>{row.start.toFixed(1)}s-{row.end.toFixed(1)}s</h1></div></div>
    <JobNav id={jobId} />
    <section className="video-inspector"><div className="video-stage"><video controls src={`${API}/api/processing/jobs/${jobId}/video#t=${row.start},${row.end}`} /></div><div className="window-summary"><p><strong>Transcript</strong><br />{row.transcript || "No speech transcript"}</p><p><strong>Caption</strong><br />{row.caption || "No direct caption available"}</p><div className="badge-row">{[row.provenance, row.vlm_call_state, row.has_audio ? "has audio" : "silent"].map((label) => <span className="badge" key={label}>{label}</span>)}</div></div></section>
    <section className="split-view"><div><h2>Selection evidence</h2><pre>{JSON.stringify({ selected: row.selected, reasons: row.selection_reasons, changes: row.change_scores }, null, 2)}</pre><h2 className="section-gap">Pipeline vector summaries</h2><pre>{JSON.stringify(row.vectors, null, 2)}</pre></div><div className="stored-record"><h2>Qdrant read-back</h2>{row.indexed && !stored && !storedError && <p className="muted">Reading the stored point…</p>}{storedError && <p className="error">This window was marked for indexing, but Qdrant could not read it back: {storedError}</p>}{stored && <><p className="ok">Stored point {stored.point_id}</p><h3>Actual stored payload</h3><pre>{JSON.stringify(stored.payload, null, 2)}</pre><h3>Actual stored vector summaries</h3><pre>{JSON.stringify(stored.vectors, null, 2)}</pre></>}{!row.indexed && <p className="muted">This job was run without Qdrant indexing, so there is no persisted point to read back.</p>}</div></section>
    <section className="form-section"><h2>Sanitized VLM diagnostics</h2><pre>{JSON.stringify(row.openai ?? { status: "No OpenAI VLM call for this window" }, null, 2)}</pre></section>
    <Evaluation jobId={jobId} index={row.index} />
  </main>;
}

function Evaluation({ jobId, index }: { jobId: string; index: number }) {
  const [label, setLabel] = useState("unsure");
  const [text, setText] = useState("");
  const [saved, setSaved] = useState(false);
  async function save() {
    await fetch(`${API}/api/processing/jobs/${jobId}/windows/${index}/evaluation`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ label, expected_event_text: text }),
    });
    setSaved(true);
  }
  return <section className="form-section"><h2>Manual evaluation</h2><p className="muted">This stays alongside the job as a local label for later retrieval evaluation.</p><div className="field-grid"><label className="field">Label<select value={label} onChange={(event) => setLabel(event.target.value)}><option>important event</option><option>not important</option><option>unsure</option></select></label><label className="field field-wide">Expected event text<textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="What should a query find here?" /></label></div><div className="actions"><button onClick={save}>Save label</button>{saved && <span className="ok">Saved locally</span>}</div></section>;
}
