// Client for the unified backend (processing_indexing/debug_api.py), which
// mounts query_retrieval's /search as /api/query/search. Types mirror
// query_retrieval/models.py (SearchRequest/SearchResponse) so the shape stays
// in sync with the backend contract without importing Python.

import {
  getModel,
  getIndexModel,
  keyForModel,
  getConnectorField,
  QUERY_MODELS,
  INDEX_MODELS,
} from './settings'

export const API_BASE_URL =
  (import.meta.env.VITE_SEARCH_API_URL as string | undefined) ?? 'http://localhost:8000'

export interface ModalityEvidence {
  modality: string
  rank: number
  contribution: number
}

export interface SearchResultItem {
  video_id: string
  window_id: string
  start: number
  end: number
  transcript: string
  caption: string
  score: number
  matched_modalities: string[]
  modality_evidence: ModalityEvidence[]
  source_path: string
  media_available: boolean
  source_window_ids: string[]
  state?: string
  final_score?: number | null
}

export interface DecompositionResult {
  visual_query: string
  audio_query: string
  speech_query: string
  caption_query: string
  required_conditions: string[]
  weights: Record<string, number>
  tier: string
}

export interface SearchResponse {
  results: SearchResultItem[]
  decomposition: DecompositionResult | null
  diagnostics: Record<string, unknown>
}

export class SearchApiError extends Error {}

// `language` is not a field on query_retrieval's SearchRequest, the backend
// has no per-language query handling yet, so it is intentionally not sent.
export async function runSearch(query: string, signal?: AbortSignal): Promise<SearchResponse> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/query/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        query,
        top_k: 6,
      }),
    })
  } catch (err) {
    if (signal?.aborted) throw err
    throw new SearchApiError('Could not reach the search API. Is the backend running on ' + API_BASE_URL + '?')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body?.detail ? JSON.stringify(body.detail) : detail
    } catch {
      // response body was not JSON; fall back to statusText
    }
    throw new SearchApiError(`Search request failed (${res.status}): ${detail}`)
  }
  return res.json() as Promise<SearchResponse>
}

// Single-call search over one uploaded video (processing_indexing/quick_demo.py).
// This path needs no indexed library: the video and the query are sent together
// and the backend returns matching time ranges already cut into playable clips.

export interface QuickMoment {
  start: number
  end: number
  description: string
  confidence: number
  clip_url: string | null
}

export interface QuickSearchResponse {
  request_id: string
  query: string
  spoken: boolean
  summary: string
  model: string
  moments: QuickMoment[]
}

export interface QuickSearchInput {
  query?: string
  /** Spoken request, sent to the model as audio rather than transcribed text. */
  audio?: Blob | null
  /** Reference images: "find this person/object". */
  images?: File[]
  /** Reference clip: "find moments like this". */
  reference?: File | null
  language?: string
}

export function clipUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

export async function runQuickSearch(
  input: QuickSearchInput,
  video: File,
  signal?: AbortSignal,
): Promise<QuickSearchResponse> {
  const body = new FormData()
  body.append('video', video, video.name || 'video.mp4')
  body.append('query', input.query ?? '')
  body.append('model', getModel())
  const key = keyForModel(getModel(), QUERY_MODELS)
  if (key) body.append('api_key', key)
  if (input.language) body.append('language', input.language)
  if (input.audio) {
    const extension = input.audio.type.includes('ogg')
      ? 'ogg'
      : input.audio.type.includes('mp4')
        ? 'mp4'
        : 'webm'
    body.append('audio', input.audio, `request.${extension}`)
  }
  for (const image of input.images ?? []) {
    body.append('images', image, image.name || 'reference.jpg')
  }
  if (input.reference) {
    body.append('reference', input.reference, input.reference.name || 'reference.mp4')
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/quick/search`, { method: 'POST', body, signal })
  } catch (err) {
    if (signal?.aborted) throw err
    throw new SearchApiError(
      'Could not reach the search API. Is the backend running on ' + API_BASE_URL + '?',
    )
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const parsed = await res.json()
      if (typeof parsed?.detail === 'string') detail = parsed.detail
      else if (parsed?.detail) detail = JSON.stringify(parsed.detail)
    } catch {
      // response body was not JSON; fall back to statusText
    }
    throw new SearchApiError(detail)
  }
  return res.json() as Promise<QuickSearchResponse>
}

export interface VoiceQueryResponse {
  query: string
  language: string
  model: string
}

// The model takes the recording directly, it is multimodal, so no separate
// speech-to-text service sits in front of it.
export async function runVoiceQuery(
  audio: Blob,
  signal?: AbortSignal,
): Promise<VoiceQueryResponse> {
  const body = new FormData()
  const extension = audio.type.includes('ogg') ? 'ogg' : audio.type.includes('mp4') ? 'mp4' : 'webm'
  body.append('audio', audio, `speech.${extension}`)
  body.append('model', getModel())

  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/quick/voice-query`, { method: 'POST', body, signal })
  } catch (err) {
    if (signal?.aborted) throw err
    throw new SearchApiError('Could not reach the search API.')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const parsed = await res.json()
      if (typeof parsed?.detail === 'string') detail = parsed.detail
    } catch {
      // response body was not JSON; fall back to statusText
    }
    throw new SearchApiError(detail)
  }
  return res.json() as Promise<VoiceQueryResponse>
}

export async function pingApi(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/query/health`, { signal })
    return res.ok
  } catch {
    return false
  }
}

export interface PlaceholderVector {
  dimensions: number
  preview: number[]
  checksum: string
  placeholder: boolean
}

export interface IndexWindow {
  window_id: string
  start: number
  end: number
  caption: string
  transcript: string
  audio_events: string[]
  objects: string[]
  actions: string[]
  vectors: Record<string, PlaceholderVector>
}

export interface IndexResponse {
  request_id: string
  model: string
  provider: string
  frames_sampled: number
  duration_seconds: number | null
  summary: string
  window_count: number
  windows: IndexWindow[]
  vectors_are_placeholder: boolean
}

export async function runIndex(video: File, signal?: AbortSignal): Promise<IndexResponse> {
  const body = new FormData()
  body.append('video', video, video.name || 'video.mp4')
  const model = getIndexModel()
  body.append('model', model)
  const key = keyForModel(model, INDEX_MODELS)
  if (key) body.append('api_key', key)

  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/quick/index`, { method: 'POST', body, signal })
  } catch (err) {
    if (signal?.aborted) throw err
    throw new SearchApiError('Could not reach the indexing API on ' + API_BASE_URL + '.')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const parsed = await res.json()
      if (typeof parsed?.detail === 'string') detail = parsed.detail
      else if (parsed?.detail) detail = JSON.stringify(parsed.detail)
    } catch {
      // response body was not JSON; fall back to statusText
    }
    throw new SearchApiError(detail)
  }
  return res.json() as Promise<IndexResponse>
}

export function testAssetUrl(relativePath: string): string {
  return `${API_BASE_URL}/api/test-assets/${relativePath.split('/').map(encodeURIComponent).join('/')}`
}

export interface DriveFile {
  id: string
  name: string
  mime_type: string
  size_bytes: number | null
  duration_seconds: number | null
}

export interface DriveListing {
  folder_id: string
  count: number
  files: DriveFile[]
}

// Drive is reached with an API key against a link-shared folder, so there is no
// OAuth round trip to sit through during a demo.
export async function listDriveVideos(folder: string): Promise<DriveListing> {
  const body = new FormData()
  body.append('folder', folder)
  const key = getConnectorField('drive')
  if (key) body.append('api_key', key)

  const res = await fetch(`${API_BASE_URL}/api/quick/drive/list`, { method: 'POST', body })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const parsed = await res.json()
      if (typeof parsed?.detail === 'string') detail = parsed.detail
    } catch {
      // response body was not JSON; fall back to statusText
    }
    throw new SearchApiError(detail)
  }
  return res.json() as Promise<DriveListing>
}
