// Client for the unified backend (processing_indexing/debug_api.py), which
// mounts query_retrieval's /search as /api/query/search. Types mirror
// query_retrieval/models.py (SearchRequest/SearchResponse) so the shape stays
// in sync with the backend contract without importing Python.

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

// `language` is not a field on query_retrieval's SearchRequest — the backend
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

export async function pingApi(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/query/health`, { signal })
    return res.ok
  } catch {
    return false
  }
}
