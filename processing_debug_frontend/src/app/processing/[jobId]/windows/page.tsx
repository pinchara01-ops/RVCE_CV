"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { WindowRow, jsonFetch } from "@/lib/api";
import { filterWindows } from "@/lib/filters";
import { JobNav } from "@/components/JobNav";

export default function WindowsPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [rows, setRows] = useState<WindowRow[]>([]);
  const [filter, setFilter] = useState("all");
  const [reason, setReason] = useState("");
  useEffect(() => {
    const load = () => jsonFetch<{ windows: WindowRow[] }>(`/api/processing/jobs/${jobId}/windows`).then((data) => setRows(data.windows)).catch(() => undefined);
    load();
    const timer = setInterval(load, 1500);
    return () => clearInterval(timer);
  }, [jobId]);
  const shown = useMemo(() => filterWindows(rows, filter, reason), [rows, filter, reason]);
  return <main>
    <div className="page-heading"><div><p className="eyebrow">Job evidence</p><h1>Window diagnostics</h1></div><p className="muted">Completed window records appear after processing. Open a row to compare the pipeline record with its Qdrant read-back.</p></div>
    <JobNav id={jobId} />
    <div className="actions"><select aria-label="Window filter" value={filter} onChange={(event) => setFilter(event.target.value)}>{["all", "selected", "skipped", "direct", "inherited", "unavailable", "failures", "indexed", "not_indexed"].map((value) => <option key={value}>{value}</option>)}</select><input placeholder="Filter by selection reason" value={reason} onChange={(event) => setReason(event.target.value)} /></div>
    {!rows.length && <p className="muted">No completed window records yet.</p>}
    <div className="scroll"><table><thead><tr><th>Window</th><th>Time</th><th>Text evidence</th><th>Selection</th><th>Stored</th><th>Vector checks</th></tr></thead><tbody>{shown.map((row) => <tr key={row.index}><td><Link className="text-link" href={`/processing/${jobId}/windows/${row.index}`}>#{row.index}</Link><span className="code">{row.window_id}</span></td><td>{row.start.toFixed(1)}–{row.end.toFixed(1)}s</td><td><strong>{row.caption || "No direct caption"}</strong><span>{row.transcript || "No transcript"}</span></td><td><span>{row.selected ? "selected" : "skipped"}</span><div className="badge-row">{row.selection_reasons.map((item) => <span className="badge" key={item}>{item}</span>)}</div></td><td><span className={row.indexed ? "ok" : "muted"}>{row.indexed ? "indexed" : "not indexed"}</span><span className="code">{row.point_id ?? "—"}</span></td><td>{Object.entries(row.vectors).map(([name, vector]) => <span key={name}>{name}: {vector.shape.join("×")}, {vector.finite ? "finite" : "invalid"}<br /></span>)}</td></tr>)}</tbody></table></div>
  </main>;
}
