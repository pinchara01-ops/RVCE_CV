import { useEffect, useRef, useState } from 'react'
import { Nav } from '../components/Nav'
import { BackgroundVideo } from '../components/BackgroundVideo'
import { SearchBar } from '../components/SearchBar'
import { LanguageSelect } from '../components/LanguageSelect'
import { StageProgress } from '../components/StageProgress'
import { ResultsTab } from '../components/ResultsTab'
import { PipelineTab } from '../components/PipelineTab'
import { TopResultCard } from '../components/TopResultCard'
import { ParticleField } from '../components/ParticleField'
import { runSearch, SearchApiError, type SearchResultItem } from '../lib/api'
import {
  buildCompletedStages,
  buildInFlightStages,
  currentProgress,
  type ModalityStatus,
  type Stage,
} from '../lib/pipeline'
import type { Turn } from '../lib/turns'

type Tab = 'results' | 'pipeline'

export function Landing() {
  const [query, setQuery] = useState('')
  const [language, setLanguage] = useState('english')
  const [turns, setTurns] = useState<Turn[]>([])
  const [tab, setTab] = useState<Tab>('results')
  const [inFlightId, setInFlightId] = useState<string | null>(null)
  const [progress, setProgress] = useState({ label: '', progress: 0 })
  const startedAtRef = useRef<number | null>(null)

  const [latestStages, setLatestStages] = useState<Stage[] | null>(null)
  const [latestModalities, setLatestModalities] = useState<ModalityStatus[]>([])
  const [latestMocked, setLatestMocked] = useState(false)

  const [displayedResult, setDisplayedResult] = useState<SearchResultItem | null>(null)
  const [displayedCount, setDisplayedCount] = useState(0)

  const isLoading = inFlightId !== null
  const lastTurn = turns[turns.length - 1] ?? null
  const cardVisible =
    !isLoading &&
    lastTurn?.status === 'done' &&
    (lastTurn.response?.results.length ?? 0) > 0

  // Keep the previous top result rendered while the card collapses, so the
  // grid-row transition animates a shrink instead of the content vanishing.
  useEffect(() => {
    if (cardVisible && lastTurn?.response) {
      setDisplayedResult(lastTurn.response.results[0])
      setDisplayedCount(lastTurn.response.results.length)
    }
  }, [cardVisible, lastTurn])

  const scrollToPipeline = () => {
    document.getElementById('pipeline-section')?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    if (!isLoading) return
    let raf: number
    const tick = () => {
      if (startedAtRef.current != null) {
        const elapsed = performance.now() - startedAtRef.current
        setLatestStages(buildInFlightStages(elapsed))
        setProgress(currentProgress(elapsed))
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [isLoading])

  const submitQuery = async () => {
    const q = query.trim()
    if (!q) return
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const startedAt = performance.now()
    startedAtRef.current = startedAt
    setProgress({ label: '', progress: 0 })
    setInFlightId(id)
    setQuery('')
    setTab('pipeline')
    setLatestModalities([])
    setLatestMocked(false)

    const turn: Turn = {
      id,
      query: q,
      status: 'loading',
      response: null,
      error: null,
      startedAt,
      finishedAt: null,
    }
    setTurns((prev) => [...prev, turn])

    try {
      const response = await runSearch(q)
      const total = performance.now() - startedAt
      const { stages, modalities } = buildCompletedStages(response, total)
      const hasMocked = stages.some((s) => !s.isReal)
      setLatestStages(stages)
      setLatestModalities(modalities)
      setLatestMocked(hasMocked)
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id
            ? { ...t, status: 'done', response, finishedAt: performance.now() }
            : t,
        ),
      )
      setTab('results')
    } catch (err) {
      const message = err instanceof SearchApiError ? err.message : 'Could not reach the search API.'
      // Clear the in-flight (mocked) stage snapshot rather than leaving it frozen
      // mid-progression — the request failed, so those stages never really ran.
      setLatestStages(null)
      setLatestModalities([])
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, status: 'error', error: message, finishedAt: performance.now() } : t,
        ),
      )
    } finally {
      setInFlightId(null)
      startedAtRef.current = null
    }
  }

  return (
    <div className="min-h-screen bg-black text-paper-100">
      <section className="relative h-screen w-full overflow-hidden bg-black">
        <BackgroundVideo />
        {/* Minimal legibility gradient — the video itself carries the art direction. */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/55 via-black/10 to-transparent" />
        {/* Dedicated fade into the section below, so the video doesn't end on a hard edge. */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-64 bg-gradient-to-b from-transparent to-black" />

        <div className="relative z-10 flex h-full flex-col">
          <Nav />

          <div className="relative flex flex-1 flex-col items-center justify-center px-6 py-12 text-center md:-translate-y-[10%]">
            {/* Background glow rings */}
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="h-[34rem] w-[34rem] rounded-full border border-glow/10 blur-[1px]" />
              <div className="absolute h-[24rem] w-[24rem] rounded-full border border-glow/15" />
              <div className="absolute h-[15rem] w-[15rem] rounded-full bg-glow/5 blur-3xl" />
            </div>

            <div className="relative">
              <h1
                className="text-5xl leading-tight tracking-tight text-white md:text-6xl lg:text-7xl"
                style={{ fontFamily: "'Instrument Serif', serif" }}
              >
                Ask your footage <span className="italic text-glow">anything</span>
              </h1>
              <p className="mx-auto mt-6 max-w-xl text-balance px-4 text-sm leading-relaxed text-white/70 md:text-base">
                Multilingual, natural-language search across video archives — ask in English,
                Hindi, Kannada, or any mix, and retrieve the exact moment.
              </p>

              <div className="mx-auto mt-10 w-full max-w-xl">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <LanguageSelect value={language} onChange={setLanguage} disabled={isLoading} />
                  <div className="flex-1">
                    <SearchBar
                      value={query}
                      onChange={setQuery}
                      onSubmit={submitQuery}
                      disabled={isLoading}
                    />
                  </div>
                </div>

                <div className="mt-4">
                  <StageProgress active={isLoading} label={progress.label} progress={progress.progress} />

                  <div
                    className="grid transition-[grid-template-rows,opacity] duration-500 ease-out"
                    style={{
                      gridTemplateRows: cardVisible ? '1fr' : '0fr',
                      opacity: cardVisible ? 1 : 0,
                    }}
                  >
                    <div className="overflow-hidden">
                      {displayedResult && (
                        <TopResultCard
                          result={displayedResult}
                          resultCount={displayedCount}
                          onViewAll={scrollToPipeline}
                        />
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="relative bg-black">
        <ParticleField />

        <section
          id="pipeline-section"
          className="relative z-10 mx-auto w-full max-w-3xl scroll-mt-10 px-6 py-16"
        >
          <div
            className="liquid-glass overflow-hidden rounded-2xl"
            style={{ backgroundColor: 'rgba(20,19,15,0.97)' }}
          >
            <div className="flex border-b border-ink-700">
              {(['results', 'pipeline'] as Tab[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`flex-1 py-3 text-sm font-medium capitalize transition-colors ${
                    tab === t
                      ? 'border-b-2 border-glow text-paper-100'
                      : 'text-paper-300/40 hover:text-paper-300/70'
                  }`}
                >
                  {t === 'results' ? 'Results' : 'Pipeline'}
                </button>
              ))}
            </div>

            <div className="h-[26rem]">
              {tab === 'results' ? (
                <ResultsTab turns={turns} />
              ) : (
                <PipelineTab
                  stages={latestStages}
                  modalities={latestModalities}
                  hasMockedTiming={latestMocked}
                />
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
