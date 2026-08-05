// Client for query_retrieval/api.py. Types mirror query_retrieval/models.py
// (SearchRequest/SearchResponse) so the shape stays in sync with the backend
// contract without importing Python.

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

export async function runSearch(
  query: string,
  language?: string,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        query,
        top_k: 6,
        enable_reranking: false,
        // `language` isn't part of query_retrieval's SearchRequest schema
        // yet, so the backend currently ignores it (pydantic's default
        // extra='ignore'). Sent anyway so the UI is ready once the API
        // gains real per-language query handling.
        language,
      }),
    })
  } catch (err) {
    if (signal?.aborted) throw err
    // TEMPORARY: the backend (query_retrieval/api.py + Qdrant) isn't running
    // in this environment. Rather than dead-end on a network error, fall
    // back to fixture data so the reveal card / results / pipeline UI can
    // still be exercised end-to-end. Remove this fallback once /search is
    // reachable for real use — see lib/mock.ts.
    const { buildMockResponse } = await import('./mock')
    await new Promise((resolve) => setTimeout(resolve, 1400))
    return buildMockResponse(query)
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
    const res = await fetch(`${API_BASE_URL}/health`, { signal })
    return res.ok
  } catch {
    return false
  }
}
