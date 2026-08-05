import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import SearchBar from '../components/SearchBar.jsx'
import ResultRow from '../components/ResultRow.jsx'
import { searchApi, checkVerificationEnabled, verifyApi } from '../api/searchApi.js'
import './ResultsPage.css'

export default function ResultsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''

  const [results, setResults] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [latencyMs, setLatencyMs] = useState(null)
  const [source, setSource] = useState('live')
  const [errorMessage, setErrorMessage] = useState(null)
  // window_id -> 'pending' | VerificationResult. Absent entirely (no key
  // for a given window_id) means "not being verified" - either
  // verification is off, or this candidate wasn't in the top N sent to
  // /verify. Never populated at all for mock/error results.
  const [verifications, setVerifications] = useState({})

  useEffect(() => {
    if (!query) {
      setResults([])
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)
    setVerifications({})

    const t0 = performance.now()
    searchApi(query).then(({ results, source, error }) => {
      if (cancelled) return
      setResults(results)
      setSource(source)
      setErrorMessage(error ?? null)
      setLatencyMs(Math.round(performance.now() - t0))
      setIsLoading(false)

      // Fired only after the primary results have already rendered -
      // verification never delays or blocks the search response itself.
      if (source === 'live' && results.length > 0) {
        checkVerificationEnabled().then((enabled) => {
          if (cancelled || !enabled) return

          const candidateIds = results.map((r) => r.window_id)
          setVerifications(Object.fromEntries(candidateIds.map((id) => [id, 'pending'])))

          verifyApi(candidateIds, query).then((verifyResults) => {
            if (cancelled) return
            setVerifications((prev) => {
              const next = { ...prev }
              for (const v of verifyResults) next[v.candidate_id] = v
              return next
            })
          })
        })
      }
    })

    return () => {
      cancelled = true
    }
  }, [query])

  const matchedModalities = [...new Set(results.flatMap((r) => r.matched_modalities))]

  function handleSearch(newQuery) {
    setSearchParams({ q: newQuery })
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="wordmark">archival</span>
        <span className="subtitle">multimodal video search</span>
      </header>

      <main className="results-main">
        <SearchBar defaultValue={query} onSearch={handleSearch} />

        {source === 'mock' && (
          <div className="mock-mode-banner font-mono" role="status">
            ⚠ MOCK MODE — showing fake data, not a real backend response (VITE_USE_MOCK_DATA=true)
          </div>
        )}

        {!isLoading && source === 'error' && (
          <div className="error-banner font-mono" role="alert">
            search failed: {errorMessage || 'backend unreachable'}
          </div>
        )}

        <div className="results-status font-mono">
          {isLoading ? (
            <span>searching…</span>
          ) : (
            <>
              <span>
                {matchedModalities.length > 0
                  ? `● ${matchedModalities.join(' + ')} matched`
                  : '● no modalities matched'}
              </span>
              <span>{results.length} results</span>
              <span>{latencyMs}ms{source === 'mock' ? ' (mock)' : ''}</span>
            </>
          )}
        </div>

        <div className="results-section-label">
          <span className="eyebrow">Results</span>
          <span className="eyebrow">ranked by relevance</span>
        </div>

        <div className="results-list">
          {!isLoading && source !== 'error' && results.length === 0 && (
            <p className="results-empty font-mono">no matching windows found</p>
          )}
          {results.map((result) => (
            <ResultRow key={result.window_id} result={result} verification={verifications[result.window_id]} />
          ))}
        </div>
      </main>

      <footer className="app-footer">
        index: {results.length} windows returned · fused via reciprocal rank fusion
      </footer>
    </div>
  )
}
