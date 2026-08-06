"use client";

import Link from "next/link";
import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { LibraryDiagnostics } from "@/components/LibraryDiagnostics";
import {
  API,
  IndexedWindow,
  LibraryDiagnostic,
  RuntimeSession,
  apiErrorMessage,
  jsonFetch,
  loadRuntimeSessionId,
} from "@/lib/api";

type WindowPayload = IndexedWindow["payload"];

function hasUsefulText(value: unknown): boolean {
  const text = String(value || "").trim();
  return Boolean(text) && !/^no (speech )?transcript$/i.test(text);
}

function excerpt(value: unknown, fallback: string, length = 110): string {
  const text = String(value || "").trim();
  if (!text) return fallback;
  return text.length > length ? `${text.slice(0, length).trimEnd()}…` : text;
}

function rangeLabel(payload: WindowPayload): string {
  return `${Number(payload.start || 0).toFixed(1)}s–${Number(payload.end || 0).toFixed(1)}s`;
}

function profileLabel(payload: WindowPayload): string {
  return payload.api_based ? "Gemini Embedding 2" : "local embedding profile";
}

function vlmState(payload: WindowPayload): { label: string; detail: string; tone: "ready" | "quiet" | "warning" } {
  const model = String(payload.caption_model || "selected VLM");
  if (payload.caption_direct) {
    return { label: "Direct VLM output", detail: `${model} · ${excerpt(payload.caption, "Caption recorded", 84)}`, tone: "ready" };
  }
  if (payload.caption_inherited) {
    return { label: "Context inherited", detail: `${model} · ${excerpt(payload.caption, "Caption inherited from a nearby clip", 84)}`, tone: "quiet" };
  }
  if (String(payload.vlm_call_state || "") === "failed") {
    return { label: "VLM unavailable", detail: "The VLM call failed for this clip", tone: "warning" };
  }
  return { label: "No VLM output", detail: "This clip was not selected for captioning", tone: "quiet" };
}

function vectorDetail(
  vectors: IndexedWindow["vectors"] | undefined,
  names: string[],
  fallback: string,
): string {
  const vector = names.map((name) => vectors?.[name]).find(Boolean);
  return vector ? `${vector.dimensions}-D vector stored` : fallback;
}

function ModalityCell({
  label,
  state,
  detail,
  tone = "ready",
}: {
  label: string;
  state: string;
  detail: string;
  tone?: "ready" | "quiet" | "warning";
}) {
  return (
    <span className={`clip-modality ${tone}`}>
      <span className="clip-modality-label">{label}</span>
      <strong>{state}</strong>
      <span className="clip-modality-detail">{detail}</span>
    </span>
  );
}

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
    const request = window.setTimeout(() => {
      setError("");
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
          if (!cancelled) {
            setError(apiErrorMessage(cause));
            void loadDiagnostics();
          }
        });
    }, 0);
    return () => { cancelled = true; window.clearTimeout(request); };
  }, [videoId, profileQuery, requestedProfileId, runtimeSession, runtimeSessionState, loadDiagnostics]);

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
        if (!cancelled) {
          setError(apiErrorMessage(cause));
          void loadDiagnostics();
        }
      });
    return () => { cancelled = true; };
  }, [selected, profileQuery, runtimeSessionState, loadDiagnostics]);

  const listedActive = useMemo(
    () => windows.find((window) => window.payload.window_id === selected) ?? windows[0],
    [selected, windows],
  );
  const active = selectedDetail?.payload.window_id === selected ? selectedDetail : listedActive;
  const start = Number(active?.payload.start ?? 0);
  const end = Number(active?.payload.end ?? 0);
  const canPlay = Boolean(active?.payload.media_available && active?.payload.window_id);
  const activeVlm = active ? vlmState(active.payload) : undefined;

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
      <LibraryDiagnostics diagnostics={diagnostics} />
      <section className="clip-section" aria-label="Indexed clip sections">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Clip sections</p>
            <h2>Each searchable window</h2>
          </div>
          <p>Choose a clip to preview it and inspect its four independent retrieval channels.</p>
        </div>
        {windows.length ? (
          <div className="clip-grid">
            {windows.map((window, index) => {
              const payload = window.payload;
              const isActive = payload.window_id === active?.payload.window_id;
              const vlm = vlmState(payload);
              const audioDetected = Boolean(payload.has_audio);
              const transcriptPresent = hasUsefulText(payload.transcript);
              return (
                <button
                  aria-pressed={isActive}
                  className={`clip-card ${isActive ? "active" : ""}`}
                  key={window.point_id}
                  onClick={() => setSelected(String(payload.window_id))}
                >
                  <span className="clip-card-heading">
                    <span>
                      <span className="clip-number">Clip {index + 1}</span>
                      <strong>{rangeLabel(payload)}</strong>
                    </span>
                    <span className={`clip-status ${payload.media_available ? "ready" : "quiet"}`}>
                      {payload.media_available ? "Playable" : "Indexed"}
                    </span>
                  </span>
                  <span className="clip-summary">{excerpt(payload.caption || payload.transcript, "No text evidence recorded")}</span>
                  <span className="clip-modalities">
                    <ModalityCell
                      label="Video"
                      state="Visual window"
                      detail={`20-second video embedding · ${profileLabel(payload)}`}
                    />
                    <ModalityCell
                      label="Audio"
                      state={audioDetected ? "Audio detected" : "No audio"}
                      detail={audioDetected ? "Separate audio channel indexed" : "No audio embedding expected"}
                      tone={audioDetected ? "ready" : "quiet"}
                    />
                    <ModalityCell
                      label="Text"
                      state={transcriptPresent ? "Transcript available" : "No transcript"}
                      detail={excerpt(payload.transcript, "No speech content recorded", 72)}
                      tone={transcriptPresent ? "ready" : "quiet"}
                    />
                    <ModalityCell label="VLM output" state={vlm.label} detail={vlm.detail} tone={vlm.tone} />
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="empty-state"><h2>No indexed clips yet</h2><p>Return to Processing, index a video, then refresh this page.</p></div>
        )}
      </section>
      {active && activeVlm && (
        <section className="selected-clip">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Selected clip</p>
              <h2>{start.toFixed(1)}s–{end.toFixed(1)}s</h2>
            </div>
            <p className="code">{active.payload.window_id}</p>
          </div>
          <div className="video-inspector">
            <div className="video-stage">
              {canPlay ? (
                <video controls src={`${API}/api/index/media/${encodeURIComponent(String(active.payload.window_id))}${profileQueryPrefix}#t=${start},${end}`} />
              ) : (
                <div className="media-unavailable">The original uploaded file is not available to the server.</div>
              )}
            </div>
            <div className="clip-evidence-grid">
              <ModalityCell
                label="Video"
                state={canPlay ? "Playable source" : "Visual record"}
                detail={vectorDetail(active.vectors, ["visual"], `Visual embedding · ${profileLabel(active.payload)}`)}
              />
              <ModalityCell
                label="Audio"
                state={active.payload.has_audio ? "Audio detected" : "No audio"}
                detail={active.payload.has_audio
                  ? vectorDetail(active.vectors, ["audio"], "Separate audio embedding channel")
                  : "No audio was present in this source window"}
                tone={active.payload.has_audio ? "ready" : "quiet"}
              />
              <ModalityCell
                label="Text"
                state={hasUsefulText(active.payload.transcript) ? "Transcript available" : "No transcript"}
                detail={excerpt(active.payload.transcript, "No speech content recorded", 180)}
                tone={hasUsefulText(active.payload.transcript) ? "ready" : "quiet"}
              />
              <ModalityCell
                label="VLM output"
                state={activeVlm.label}
                detail={`${activeVlm.detail} · ${vectorDetail(active.vectors, ["caption"], "Caption embedding")}`}
                tone={activeVlm.tone}
              />
            </div>
          </div>
          <details className="stored-record">
            <summary>Inspect stored record and vector summaries</summary>
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
            <pre>{JSON.stringify(active.vectors ?? {}, null, 2)}</pre>
          </details>
        </section>
      )}
    </main>
  );
}
