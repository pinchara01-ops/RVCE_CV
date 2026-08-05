export const API = process.env.NEXT_PUBLIC_PROCESSING_API_URL ?? "http://localhost:8000";

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
};

export type SearchModality = "visual" | "audio" | "speech" | "caption";

export type VerificationProvider = "none" | "openai" | "cosmos";

export type SearchVerificationRequest = {
  provider: VerificationProvider;
  /** Sent only with the current request. The UI never persists this value. */
  api_key?: string;
};

export type SearchRequest = {
  query: string;
  top_k?: number;
  enable_decomposition?: boolean;
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
};

export type SearchResponse = {
  results: SearchResult[];
  /** `query_decomposition` is accepted during the backend transition. */
  decomposition?: SearchDecomposition | null;
  query_decomposition?: SearchDecomposition | null;
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
