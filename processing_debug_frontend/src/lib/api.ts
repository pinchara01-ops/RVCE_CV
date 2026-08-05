export const API = process.env.NEXT_PUBLIC_PROCESSING_API_URL ?? "http://127.0.0.1:8000";

export type ModelStatus = {
  component: string;
  checkpoint: string;
  device: string;
  expected_dimension: number | null;
  cache_available: boolean;
  loading_attempted: boolean;
  load_success: boolean;
  provider_kind: string;
  message: string;
};

export type IndexHealth = {
  reachable: boolean;
  collection_exists: boolean;
  collection_name: string;
  points_count: number;
  vectors: Record<string, { dimensions: number; distance: string }>;
  schema_valid?: boolean;
  schema_errors?: string[];
  error?: string;
  embedding_profile?: string;
};

/** A non-secret, versioned embedding contract available to the UI. */
export type RuntimeProfile = {
  id: string;
  label: string;
  mode: "api-based" | "self-hosted" | "api_based" | "self_hosted";
  description: string;
  collection_name: string;
  vector_dimensions?: Record<string, number>;
  vector_schema?: Record<string, { dimensions?: number; dim?: number; distance?: string }>;
  defaults?: Record<string, unknown>;
  provider_options?: Record<string, Array<{ provider: string; model: string; label: string; credential_required?: boolean; cost_label?: string }>>;
  free_default?: boolean;
  requires_cloud_consent?: boolean;
};

export type ProviderChoice = "gemini" | "openai" | "cosmos" | "self-hosted" | "local" | "local_qwen" | "none";

export type RuntimeStage = "transcription" | "media_embedding" | "text_embedding" | "caption" | "verification" | "query_decomposition" | "reranker";

export type RuntimePreflight = {
  qdrant?: { ok: boolean; message: string };
  gemini?: { ok: boolean; message: string };
  warnings?: string[];
  reachable?: boolean;
  collection_exists?: boolean;
  schema_valid?: boolean;
  schema_errors?: string[];
  expected_schema?: Record<string, unknown>;
  error?: string;
};

export type RuntimeSession = {
  session_id: string;
  profile: RuntimeProfile;
  configuration?: Record<string, unknown>;
  credentials?: Record<string, boolean>;
};

export type RuntimeSessionRequest = {
  profile_id: string;
  qdrant_url?: string;
  qdrant_api_key?: string;
  gemini_api_key?: string;
  openai_api_key?: string;
  nvidia_api_key?: string;
  providers?: Partial<Record<RuntimeStage, ProviderChoice>>;
  models?: Record<string, string>;
  consent_cloud_video?: boolean;
};

export type Job = {
  job_id: string;
  status: string;
  stage: string;
  progress: number;
  current_window: number;
  total_windows: number;
  elapsed_seconds: number;
  configuration: Record<string, unknown>;
  metadata: Record<string, unknown>;
  summary: Record<string, unknown> & {
    stage_durations?: Record<string, number>;
    stage_timing_semantics?: string;
  };
  errors: { message: string; window_id?: string }[];
  model_status: ModelStatus[];
  /** Chronological, structured updates emitted by the indexing worker. */
  activity?: JobActivity[];
};

export type JobActivity = {
  /** Monotonic per-job sequence, used to keep rendered entries stable. */
  sequence: number;
  /** ISO timestamp or Unix seconds, depending on the API process version. */
  timestamp: string | number;
  level: "info" | "warning" | "error";
  area: string;
  message: string;
  details?: Record<string, unknown>;
};

export type WindowRow = {
  index: number;
  video_id: string;
  window_id: string;
  start: number;
  end: number;
  transcript: string;
  change_scores: Record<string, number>;
  selected: boolean;
  selection_reasons: string[];
  vlm_call_state: string;
  caption: string;
  has_audio: boolean;
  provenance: string;
  confidence: number;
  indexed: boolean;
  point_id: string | null;
  stored_payload: Record<string, unknown>;
  vectors: Record<string, { shape: number[]; norm: number; min: number; max: number; finite: boolean }>;
  openai?: { request: unknown; response: unknown; usage: unknown } | null;
  errors: string[];
};

export type IndexedWindow = {
  point_id: string;
  payload: Record<string, unknown> & {
    video_id?: string;
    window_id?: string;
    start?: number;
    end?: number;
    transcript?: string;
    caption?: string;
    media_available?: boolean;
  };
  vectors?: Record<string, { dimensions: number; norm: number; minimum: number; maximum: number; finite: boolean }>;
};

export type IndexedVideo = {
  video_id: string;
  windows: number;
  start: number;
  end: number;
  source_filename: string;
  media_available: boolean;
  direct_captions: number;
  caption_available: number;
  embedding_profile?: string;
};

export type SearchModality = "visual" | "audio" | "speech" | "transcript" | "caption";

export type VerificationProvider = "none" | "gemini" | "openai" | "cosmos";

export type SearchVerificationRequest = {
  provider: VerificationProvider;
  /** Sent only with the current request. The UI never persists this value. */
  api_key?: string;
  /** Number of fused regions to run through the first VLM verification pass. */
  top_n?: number;
  /** Run a bounded second VLM pass to return a 2–5 second event span. */
  enable_temporal_localization?: boolean;
};

export type SearchRequest = {
  query: string;
  top_k?: number;
  enable_decomposition?: boolean;
  enable_reranking?: boolean;
  rerank_top_n?: number;
  /** Explicit local precision-stage opt-in for self-hosted search. */
  reranker_provider?: "none" | "local_qwen";
  reranker_model?: string;
  relevant_window_ids?: string[];
  profile_id?: string;
  runtime_session_id?: string;
  verification?: SearchVerificationRequest;
};

export type SearchDecomposition = {
  tier?: string;
  weights?: Partial<Record<SearchModality, number>>;
  required_conditions?: string[];
  visual_query?: string;
  audio_query?: string;
  speech_query?: string;
  caption_query?: string;
};

export type SearchVerification = {
  state?: string;
  confidence?: number | null;
  evidence?: string;
  reason?: string;
  satisfied_conditions?: string[];
  missing_conditions?: string[];
  contradictions?: string[];
  matched_conditions?: string[];
  final_score?: number | null;
  refined_start?: number | null;
  refined_end?: number | null;
  refined_start_seconds?: number | null;
  refined_end_seconds?: number | null;
  localization_state?: "not_attempted" | "not_needed" | "localized" | "localization_unavailable";
  localization_reason?: string;
  localization_evidence?: string;
  localization_frame_timestamps?: number[];
};

export type SearchResult = {
  video_id: string;
  window_id: string;
  start: number;
  end: number;
  transcript: string;
  caption: string;
  score: number;
  matched_modalities?: string[];
  modality_evidence?: { modality: string; rank: number; contribution: number }[];
  state?: string;
  media_available: boolean;
  retrieval_score?: number | null;
  final_score?: number | null;
  confidence?: number | null;
  evidence?: string;
  verification_state?: string;
  verification_confidence?: number | null;
  verification_evidence?: string;
  verification_reason?: string;
  verification?: SearchVerification | null;
  verification_result?: SearchVerification | null;
  refined_start?: number | null;
  refined_end?: number | null;
  refined_start_seconds?: number | null;
  refined_end_seconds?: number | null;
  satisfied_conditions?: string[];
  missing_conditions?: string[];
  contradictions?: string[];
  matched_conditions?: string[];
  localization_state?: "not_attempted" | "not_needed" | "localized" | "localization_unavailable";
  localization_reason?: string;
  localization_evidence?: string;
};

export type SearchResponse = {
  results: SearchResult[];
  /** `query_decomposition` is accepted during the backend transition. */
  decomposition?: SearchDecomposition | null;
  query_decomposition?: SearchDecomposition | null;
  diagnostics?: Record<string, unknown>;
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
  ) {
    super(body || `Request failed (${status}).`);
    this.name = "ApiError";
  }
}

export async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API + path, { ...init, cache: "no-store" });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

/**
 * Best-effort teardown for a session that this page created but could not
 * activate.  Runtime sessions are bearer-like references to credentials, so a
 * failed preflight should not leave an unreachable configuration resident until
 * its server-side TTL expires.
 */
export async function deleteRuntimeSession(sessionId: string): Promise<void> {
  const response = await fetch(`${API}/api/runtime/session/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!response.ok && response.status !== 404) {
    throw new ApiError(response.status, await response.text());
  }
}

const RUNTIME_SESSION_STORAGE_KEY = "video-index-runtime-session";

/** The opaque session id is safe to keep per browser tab; API keys never leave the API process. */
export function loadRuntimeSessionId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return window.sessionStorage.getItem(RUNTIME_SESSION_STORAGE_KEY) || undefined;
}

export function storeRuntimeSessionId(sessionId: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(RUNTIME_SESSION_STORAGE_KEY, sessionId);
}

export function clearRuntimeSessionId(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(RUNTIME_SESSION_STORAGE_KEY);
}
