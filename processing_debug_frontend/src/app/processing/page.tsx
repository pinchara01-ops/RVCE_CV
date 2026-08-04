"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { API, IndexHealth, ModelStatus } from "@/lib/api";

async function errorMessage(response: Response): Promise<string> {
  const body = await response.text();
  let detail = body;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
  } catch {
    // A plain-text response is still useful to the person running the app.
  }
  if (detail.includes("There was an error parsing the body")) {
    return "The upload could not be read. Re-select the video file and try again. If it repeats, refresh this page before retrying.";
  }
  return detail || `Request failed (${response.status}).`;
}

function displayError(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export default function ProcessingPage() {
  const router = useRouter();
  const [models, setModels] = useState<ModelStatus[]>([]);
  const [health, setHealth] = useState<IndexHealth>();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [vlmMode, setVlmMode] = useState("selection_only");

  useEffect(() => {
    fetch(`${API}/api/processing/preflight`).then((response) => response.json())
      .then((data) => setModels(data.models)).catch((cause) => setError(displayError(cause)));
    fetch(`${API}/api/index/health`).then((response) => response.json())
      .then(setHealth).catch((cause) => setError(displayError(cause)));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    const video = data.get("video");
    if (!(video instanceof File) || video.size === 0) {
      setError("Choose a non-empty video file before creating an indexing job.");
      setSubmitting(false);
      return;
    }
    const config: Record<string, unknown> = {
      window_seconds: Number(data.get("window_seconds")),
      stride_seconds: Number(data.get("stride_seconds")),
      device: data.get("device"),
      vlm_mode: vlmMode,
      max_windows: Number(data.get("max_windows")),
      index_qdrant: data.get("index_qdrant") === "on",
      visual_threshold: Number(data.get("visual_threshold")),
      audio_threshold: Number(data.get("audio_threshold")),
      speech_threshold: Number(data.get("speech_threshold")),
      combined_threshold: Number(data.get("combined_threshold")),
      visual_weight: Number(data.get("visual_weight")),
      audio_weight: Number(data.get("audio_weight")),
      speech_weight: Number(data.get("speech_weight")),
    };
    if (vlmMode === "openai") {
      config.openai_api_key = String(data.get("openai_api_key") ?? "");
      config.openai_model = String(data.get("openai_model") ?? "gpt-4.1-mini");
      config.openai_max_frames = Number(data.get("openai_max_frames"));
    }
    if (vlmMode === "cosmos") {
      config.nvidia_api_key = String(data.get("nvidia_api_key") ?? "");
      config.cosmos_model = String(data.get("cosmos_model") ?? "nvidia/cosmos3-nano-reasoner");
      config.cosmos_max_frames = Number(data.get("cosmos_max_frames"));
    }
    const body = new FormData();
    // Include the filename explicitly. It makes the multipart part unambiguous
    // across browsers and lets the server validate the upload consistently.
    body.append("video", video, video.name || "upload.mp4");
    body.append("configuration", JSON.stringify(config));
    // The request has its own serialized copy now. Clear secrets from the
    // browser form immediately; they are neither local-storage nor job-history data.
    form.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach((input) => { input.value = ""; });
    try {
      const response = await fetch(`${API}/api/processing/jobs`, { method: "POST", body });
      if (!response.ok) throw new Error(await errorMessage(response));
      const job = await response.json();
      router.push(`/processing/${job.job_id}`);
    } catch (cause) {
      setError(displayError(cause));
      setSubmitting(false);
    }
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">Step 1 of 3</p><h1>Index a video</h1></div>
        <p className="muted">This uploads one local video, creates searchable windows, and can save them into your shared Qdrant collection.</p>
      </div>

      {error && <p className="error panel">{error}</p>}
      <section className={`status-strip ${health ? (health.reachable && health.schema_valid !== false ? "ready" : "warning") : ""}`}>
        <div><strong>Qdrant {health ? (health.reachable ? "connected" : "not ready") : "checking"}</strong><span>{health ? (health.collection_exists ? `${health.points_count} indexed windows in ${health.collection_name}` : health.error ?? "The shared collection will be created when you index your first video.") : "Checking the shared collection…"}</span>{health?.schema_errors?.map((message) => <span className="error" key={message}>{message}</span>)}</div>
        <Link href="/library">Inspect library</Link>
      </section>

      <form onSubmit={submit} className="processing-form">
        <section className="form-section">
          <div className="section-heading"><h2>Video and indexing</h2><p>Start with a short test video. The pipeline downloads real ML models on first use.</p></div>
          <div className="field-grid">
            <label className="field field-wide">Video file<input required name="video" type="file" accept="video/*" /></label>
            <label className="field">Processing mode<select name="vlm_mode" value={vlmMode} onChange={(event) => setVlmMode(event.target.value)}><option value="selection_only">Selection only, no hosted VLM</option><option value="openai">OpenAI VLM captions</option><option value="cosmos">NVIDIA Cosmos Reasoner captions</option><option value="mock">Deterministic mock captions, debug only</option></select></label>
            <label className="field">Compute device<select name="device" defaultValue="cpu"><option value="cpu">CPU</option><option value="cuda">CUDA GPU</option></select></label>
            <label className="field">Maximum windows<input name="max_windows" type="number" min="0" defaultValue="0" /><span>0 processes the full video.</span></label>
            <label className="field">Window length (seconds)<input name="window_seconds" type="number" step="0.1" min="1" defaultValue="10" /></label>
            <label className="field">Stride (seconds)<input name="stride_seconds" type="number" step="0.1" min="1" defaultValue="5" /></label>
            {vlmMode === "openai" && <><label className="field">OpenAI API key<input required name="openai_api_key" type="password" autoComplete="off" placeholder="sk-..." /><span>Used only for this indexing job, never saved.</span></label><label className="field">OpenAI model<input name="openai_model" defaultValue="gpt-4.1-mini" /></label><label className="field">OpenAI frames<input name="openai_max_frames" type="number" min="1" max="12" defaultValue="4" /></label></>}
            {vlmMode === "cosmos" && <><label className="field">NVIDIA API key<input required name="nvidia_api_key" type="password" autoComplete="off" placeholder="nvapi-..." /><span>Used only for this indexing job, never saved.</span></label><label className="field">Cosmos model<input name="cosmos_model" defaultValue="nvidia/cosmos3-nano-reasoner" /></label><label className="field">Cosmos frames<input name="cosmos_max_frames" type="number" min="2" max="16" defaultValue="8" /></label></>}
          </div>
          <div className="index-choice">
            <label><input type="checkbox" name="index_qdrant" defaultChecked /> Save real vectors into Qdrant</label>
            <span className="muted">Shared collection: <code>{health?.collection_name ?? "video_windows"}</code></span>
          </div>
          <p className="hint">The collection is configured once on the server, so indexing, Library, and Search always use the same data. Selection-only indexing is the safe first run.</p>
        </section>

        <details className="form-section advanced"><summary>Advanced selection settings</summary><div className="field-grid compact">{[["visual_threshold", 0.12], ["audio_threshold", 0.15], ["speech_threshold", 0.18], ["combined_threshold", 0.13], ["visual_weight", 0.55], ["audio_weight", 0.25], ["speech_weight", 0.2]].map(([name, value]) => <label className="field" key={String(name)}>{String(name).replaceAll("_", " ")}<input name={String(name)} type="number" step="0.01" defaultValue={Number(value)} /></label>)}</div></details>
        <button className="button" disabled={submitting || (health?.collection_exists === true && health.schema_valid === false)}>{submitting ? "Uploading…" : "Create indexing job"}</button>
      </form>

      <section className="models-section"><div className="section-heading"><h2>Local model readiness</h2><p>This check does not download or load models.</p></div><div className="model-list">{models.map((model) => <div key={model.component} className="model-row"><div><strong>{model.component}</strong><span>{model.checkpoint}</span></div><span>{model.device}</span><span className={model.cache_available ? "ok" : "muted"}>{model.cache_available ? "cached" : "downloads on first run"}</span></div>)}</div></section>
    </main>
  );
}
