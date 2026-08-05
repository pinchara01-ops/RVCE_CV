// ---------------------------------------------------------------------
// INTEGRATION POINT: this is the one place that talks to the backend
// Query & Retrieval module (see /query_retrieval, POST /search).
//
// The backend contract (query_retrieval/models.py):
//   POST /search   request:  { query: string, top_k?: number }
//                  response: { results: SearchResultItem[] }
//                  SearchResultItem: { video_id, window_id, start, end,
//                    transcript, caption, score, matched_modalities,
//                    modality_evidence, state }
//   POST /verify   request:  { candidate_ids: string[], query: string,
//                    required_conditions?: string[] }
//                  response: { results: VerificationResult[] }
//                  VerificationResult: { candidate_id, state, match,
//                    confidence, satisfied_conditions, missing_conditions,
//                    contradictions, evidence, reason }
//                  404 if the backend has ENABLE_VERIFICATION=false.
//   GET  /health   response includes { verification_enabled: bool } -
//                  checked before ever calling /verify, so the UI never
//                  shows even a brief "verifying..." flash when the
//                  feature is off server-side.
//
// /verify is deliberately called AFTER /search's results have already
// rendered (see ResultsPage.jsx), never awaited as part of the initial
// search - a slow or failed verification call must never delay or block
// the primary result render. See README "Production safety" / the
// non-blocking verification design note.
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

// Checked once per new search, before ever calling /verify - if the
// backend can't be reached or verification is off, this returns false
// and ResultsPage never fires /verify or shows any verifying state.
export async function checkVerificationEnabled() {
  if (USE_MOCK_DATA) return false
  try {
    const response = await fetch(`${API_BASE_URL}/health`)
    if (!response.ok) return false
    const data = await response.json()
    return data.verification_enabled === true
  } catch (err) {
    console.warn('[checkVerificationEnabled] /health unreachable:', err.message)
    return false
  }
}

// candidateIds should be in fused_score-descending order (the order
// /search already returns results in) - the backend truncates to its own
// VERIFICATION_TOP_N, this doesn't need to know that number itself.
export async function verifyApi(candidateIds, query, requiredConditions = []) {
  try {
    const response = await fetch(`${API_BASE_URL}/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_ids: candidateIds, query, required_conditions: requiredConditions }),
    })
    if (!response.ok) {
      // 404 = disabled server-side (shouldn't happen if checkVerificationEnabled
      // was checked first, but the flag could change between calls) - either
      // way, no verification results, caller just shows nothing extra.
      return []
    }
    const data = await response.json()
    return data.results
  } catch (err) {
    console.warn('[verifyApi] verification request failed:', err.message)
    return []
  }
}
