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

  useEffect(() => {
    if (!query) {
      setResults([])
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)

    const t0 = performance.now()
    searchApi(query).then(({ results, source }) => {
      if (cancelled) return
      setResults(results)
      setSource(source)
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
          {!isLoading && results.length === 0 && (
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
