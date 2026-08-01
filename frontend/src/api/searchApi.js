// ---------------------------------------------------------------------
// INTEGRATION POINT: this is the one place that talks to the backend
// Query & Retrieval module (see /query_retrieval, POST /search).
//
// The backend contract (query_retrieval/models.py):
//   request:  { query: string, top_k?: number }
//   response: { results: SearchResultItem[] }
//   SearchResultItem: { video_id, window_id, start, end, transcript,
//                        caption, score, matched_modalities,
//                        modality_evidence, state }
//
// Mock data is OFF by default and only ever used when explicitly opted
// into via VITE_USE_MOCK_DATA=true in frontend/.env.local - it is never
// a silent fallback for a real backend failure. When the backend really
// is unreachable or errors, this surfaces that as source: 'error' so the
// UI shows a clear error state, not fake-looking results that could be
// mistaken for real ones. See Section "Production safety" in the README.
//
// Override the backend URL with VITE_API_BASE_URL in a .env file if it's
// not running on the default localhost:8000.
// ---------------------------------------------------------------------
import { MOCK_RESULTS } from '../data/mockResults.js'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const USE_MOCK_DATA = import.meta.env.VITE_USE_MOCK_DATA === 'true'

export async function searchApi(query, topK = 10) {
  if (USE_MOCK_DATA) {
    console.warn('[searchApi] VITE_USE_MOCK_DATA=true - returning mock results, not calling the backend.')
    return { results: MOCK_RESULTS, source: 'mock' }
  }

  try {
    const response = await fetch(`${API_BASE_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: topK }),
    })

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      const detail = body.detail || `status ${response.status}`
      throw new Error(detail)
    }

    const data = await response.json()
    return { results: data.results, source: 'live' }
  } catch (err) {
    // Backend unreachable or returned an error (e.g. 503 when Qdrant/
    // encoders are down) - surface this as an error state. Never
    // silently substitute mock/fake results for a real failure.
    console.error('[searchApi] search failed:', err.message)
    return { results: [], source: 'error', error: err.message }
  }
}
