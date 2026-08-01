import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import SearchBar from '../components/SearchBar.jsx'
import ResultRow from '../components/ResultRow.jsx'
import { searchApi } from '../api/searchApi.js'
import './ResultsPage.css'

export default function ResultsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''

  const [results, setResults] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [latencyMs, setLatencyMs] = useState(null)
  const [source, setSource] = useState('live')
  const [errorMessage, setErrorMessage] = useState(null)

  useEffect(() => {
    if (!query) {
      setResults([])
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)

    const t0 = performance.now()
    searchApi(query).then(({ results, source, error }) => {
      if (cancelled) return
      setResults(results)
      setSource(source)
      setErrorMessage(error ?? null)
      setLatencyMs(Math.round(performance.now() - t0))
      setIsLoading(false)
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
            <ResultRow key={result.window_id} result={result} />
          ))}
        </div>
      </main>

      <footer className="app-footer">
        index: {results.length} windows returned · fused via reciprocal rank fusion
      </footer>
    </div>
  )
}
