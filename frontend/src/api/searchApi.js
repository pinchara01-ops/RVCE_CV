// ---------------------------------------------------------------------
// INTEGRATION POINT: this is the one place that talks to the backend
// Query & Retrieval module (see /query_retrieval, POST /search).
//
// The backend contract (query_retrieval/models.py):
//   request:  { query: string, top_k?: number }
//   response: { results: SearchResultItem[] }
//   SearchResultItem: { video_id, window_id, start, end, transcript,
//                        caption, score, matched_modalities }
//
// The backend is already built, tested (74/74), and stable, so this
// calls it directly rather than staying mock-only. If the backend isn't
// running (e.g. working on the frontend alone), this falls back to
// MOCK_RESULTS so the UI still renders real-looking content - remove
// the fallback once the backend is reliably available in your dev setup.
//
// Override the backend URL with VITE_API_BASE_URL in a .env file if it's
// not running on the default localhost:8000.
// ---------------------------------------------------------------------
import { MOCK_RESULTS } from '../data/mockResults.js'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export async function searchApi(query, topK = 10) {
  try {
    const response = await fetch(`${API_BASE_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: topK }),
    })

    if (!response.ok) {
      throw new Error(`Search request failed with status ${response.status}`)
    }

    const data = await response.json()
    return { results: data.results, source: 'live' }
  } catch (err) {
    // Backend unreachable (not running, wrong port, CORS, etc.) - fall
    // back to mock data so the demo doesn't show a blank/broken page.
    console.warn('[searchApi] backend unreachable, falling back to mock results:', err.message)
    return { results: MOCK_RESULTS, source: 'mock' }
  }
}
