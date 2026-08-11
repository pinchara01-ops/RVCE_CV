import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, Check, Eye, Film, Image, Mic, Play, Search, Upload, Volume2 } from 'lucide-react'
import { Nav } from '../components/Nav'
import { BackgroundVideo } from '../components/BackgroundVideo'
import { ParticleField } from '../components/ParticleField'
import { MomentResults } from '../components/MomentResults'
import { StageSequence } from '../components/StageSequence'
import {
  getPublicSamples,
  getPublicUsage,
  publicSampleMediaUrl,
  runQuickSearch,
  SearchApiError,
  type PublicSample,
  type PublicUsage,
  type QuickSearchResponse,
} from '../lib/api'
import { LANGUAGE_OPTIONS } from '../lib/languages'
import { stringsFor, RTL_LANGUAGES } from '../lib/i18n'
import { QUERY_STAGES } from '../lib/stages'
import { useLanguage } from '../lib/settings'
import { navigate } from '../lib/router'
import { track } from '../lib/analytics'

const CAPABILITIES = [
  { icon: Film, title: 'Describe it', copy: 'Search using natural-language text.' },
  { icon: Mic, title: 'Say it', copy: 'Ask by voice in your own language.' },
  { icon: Image, title: 'Show it', copy: 'Upload a reference image to find a person or object.' },
  { icon: Play, title: 'Match it', copy: 'Provide a reference clip to find similar moments.' },
]

const SIGNALS = [
  ['Visual content', Eye], ['Audio events', Volume2], ['Spoken words', Mic], ['Captions, objects and actions', Film],
] as const

function route(path: string, event?: string) {
  if (event) track(event)
  navigate(path)
}

export function Landing() {
  const [language] = useLanguage()
  const t = stringsFor(language)
  const rtl = RTL_LANGUAGES.has(language)
  const [query, setQuery] = useState('')
  const [samples, setSamples] = useState<PublicSample[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sourceMode, setSourceMode] = useState<'sample' | 'upload'>('sample')
  const [video, setVideo] = useState<File | null>(null)
  const [usage, setUsage] = useState<PublicUsage | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [response, setResponse] = useState<QuickSearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const startedAt = useRef(0)

  const selected = useMemo(() => samples.find((sample) => sample.id === selectedId) ?? null, [samples, selectedId])
  const exhausted = usage?.remaining === 0
  const sourceReady = sourceMode === 'sample' ? Boolean(selected?.available) : Boolean(video)

  useEffect(() => {
    track('landing_viewed', { language })
    getPublicSamples()
      .then((catalog) => {
        setSamples(catalog)
        track('sample_library_viewed', { language })
      })
      .catch(() => setError('The sample library is temporarily unavailable. Recorded examples are still available.'))
    getPublicUsage()
      .then(setUsage)
      .catch(() => setError('Live searches are temporarily unavailable. The sample library and recorded examples remain accessible.'))
  }, [language])

  useEffect(() => {
    if (!busy) return
    startedAt.current = performance.now()
    const timer = window.setInterval(() => setElapsed((performance.now() - startedAt.current) / 1000), 200)
    return () => window.clearInterval(timer)
  }, [busy])

  const submit = async () => {
    if (!sourceReady || exhausted || busy) return
    if (!query.trim()) return
    setBusy(true)
    setError(null)
    setResponse(null)
    setElapsed(0)
    const modality = 'text'
    const sampleId = sourceMode === 'sample' ? selected?.id : undefined
    track('live_search_started', { sample_id: sampleId, modality, language })
    try {
      const result = await runQuickSearch({
        query,
        sampleId,
        audio: null,
        images: [],
        reference: null,
        language: LANGUAGE_OPTIONS.find((item) => item.code === language)?.label ?? 'English',
      }, sourceMode === 'upload' ? video : null, undefined, crypto.randomUUID())
      setResponse(result)
      if (result.usage) setUsage(result.usage)
      track('live_search_completed', { sample_id: sampleId, modality, language, outcome: 'success' })
      window.setTimeout(() => document.getElementById('results-section')?.scrollIntoView({ behavior: 'smooth' }), 80)
    } catch (cause) {
      const message = cause instanceof SearchApiError ? cause.message : 'Search failed safely. Please try again.'
      setError(message)
      if (cause instanceof SearchApiError && cause.usage) setUsage(cause.usage)
      if (message.toLowerCase().includes('two live searches')) track('live_limit_reached', { sample_id: sampleId, modality, language })
      else track('live_search_failed', { sample_id: sampleId, modality, language, outcome: 'safe_error' })
      void getPublicUsage().then(setUsage).catch(() => undefined)
    } finally {
      setBusy(false)
    }
  }

  const stageLabels: Record<string, string> = {
    uploading: 'Preparing sample', decoding: 'Reading footage', understanding: 'Understanding your request',
    scanning: 'Scanning every signal', matching: 'Ranking matching moments', localising: 'Finding exact timestamps', clipping: 'Preparing playable moments',
  }

  const changeMode = (mode: 'sample' | 'upload') => {
    setSourceMode(mode)
    setQuery('')
    setResponse(null)
    setError(null)
  }

  const chooseSample = (sample: PublicSample) => {
    if (!sample.available) return
    setSelectedId(sample.id)
    setQuery('')
    setResponse(null)
    setError(null)
    track('sample_selected', { sample_id: sample.id, language })
  }

  const promptForm = (placeholder: string) => (
    <form
      className="mt-4 flex items-center gap-2 rounded-2xl border border-white/15 bg-black/55 p-2 focus-within:border-glow/60"
      onSubmit={(event) => { event.preventDefault(); void submit() }}
    >
      <Search size={18} className="ml-2 shrink-0 text-white/45" aria-hidden="true" />
      <input
        aria-label="Describe the moment"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={placeholder}
        disabled={busy || exhausted}
        className="min-w-0 flex-1 bg-transparent px-2 py-3 text-sm text-white outline-none placeholder:text-white/35"
      />
      <button
        type="submit"
        aria-label="Run search"
        disabled={!query.trim() || busy || exhausted}
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-glow text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ArrowRight size={19} />
      </button>
    </form>
  )

  return (
    <div className="min-h-screen overflow-x-hidden bg-black text-paper-100" dir={rtl ? 'rtl' : 'ltr'}>
      <section className="relative min-h-screen overflow-hidden">
        <BackgroundVideo />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/70 via-black/35 to-black" />
        <div className="relative z-10"><Nav /></div>
        <div className="relative z-10 mx-auto flex max-w-6xl flex-col items-center px-5 pb-16 pt-12 text-center md:pt-20">
          <p className="font-mono text-[11px] uppercase tracking-[0.32em] text-glow">Aperture</p>
          <h1 className="mt-5 max-w-4xl text-5xl leading-[0.98] tracking-tight text-white md:text-7xl" style={{ fontFamily: "'Instrument Serif', serif" }}>
            Search any video archive <span className="italic text-glow">the way you remember it.</span>
          </h1>
          <p className="mt-6 max-w-2xl text-balance text-base leading-relaxed text-white/70 md:text-lg">
            Ask with text, voice, an image or another clip, in 13 Indian languages, and retrieve the exact playable moment.
          </p>
          <p className="mt-4 text-xs text-paper-300/55">No account needed · 2 free live searches · 13 Indian languages</p>

          <div id="live-demo" className="mt-8 w-full max-w-5xl overflow-hidden rounded-3xl border border-white/15 bg-black/70 text-left shadow-2xl backdrop-blur-xl">
            <div className="border-b border-white/10 px-5 py-4 md:px-6">
              <p className="text-sm font-medium text-white">Search a video</p>
              <p className="mt-1 text-xs text-white/50">Keep your footage selected while you describe the moment to find.</p>
            </div>
            <div className="grid lg:grid-cols-[0.9fr_1.1fr]">
              <section className="border-b border-white/10 p-5 lg:border-b-0 lg:border-r lg:p-6" aria-labelledby="footage-heading">
                <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div><p className="font-mono text-[10px] uppercase tracking-[0.2em] text-glow">Footage</p><h2 id="footage-heading" className="mt-1 text-lg text-white">Choose one video</h2></div>
                  <div className="grid w-full grid-cols-2 rounded-full border border-white/10 bg-black/35 p-1 text-[11px] sm:flex sm:w-auto">
                    <button type="button" onClick={() => changeMode('sample')} aria-pressed={sourceMode === 'sample'} className={`rounded-full px-3 py-1.5 ${sourceMode === 'sample' ? 'bg-glow font-medium text-black' : 'text-white/60'}`}>Samples</button>
                    <button type="button" onClick={() => changeMode('upload')} aria-pressed={sourceMode === 'upload'} className={`rounded-full px-3 py-1.5 ${sourceMode === 'upload' ? 'bg-glow font-medium text-black' : 'text-white/60'}`}>Upload yours</button>
                  </div>
                </div>

                {sourceMode === 'sample' && <div className="mt-4 space-y-2">
                  {samples.map((sample, index) => <button key={sample.id} type="button" disabled={!sample.available} aria-pressed={selectedId === sample.id} onClick={() => chooseSample(sample)} className={`group flex w-full min-w-0 items-center gap-3 rounded-2xl border p-2 text-left transition ${selectedId === sample.id ? 'border-glow bg-glow/10' : 'border-white/10 bg-white/[0.03] hover:border-white/25'} disabled:cursor-not-allowed disabled:opacity-45`}>
                    <div className="relative h-16 w-24 shrink-0 overflow-hidden rounded-xl bg-ink-800"><video src={sample.available ? publicSampleMediaUrl(sample.id) : undefined} muted playsInline preload="metadata" className="h-full w-full object-cover opacity-80"/><span className="absolute left-1.5 top-1.5 rounded bg-black/65 px-1.5 py-0.5 font-mono text-[8px] text-white/70">0{index + 1}</span></div>
                    <div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-2"><h3 className="text-sm font-medium text-white">{sample.name}</h3>{selectedId === sample.id && <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-glow text-black"><Check size={13}/></span>}</div><p className="mt-1 truncate text-[11px] text-white/45">{sample.description}</p><p className="mt-1 text-[10px] text-glow/75">{sample.duration}</p></div>
                  </button>)}
                </div>}

                {sourceMode === 'upload' && <label htmlFor="hero-video-upload" className={`mt-4 flex cursor-pointer items-center gap-3 rounded-2xl border px-4 py-5 transition ${video ? 'border-glow bg-glow/[0.07]' : 'border-dashed border-white/20 bg-white/[0.03] hover:border-glow/50'}`}>
                  <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-glow/10 text-glow">{video ? <Check size={18}/> : <Upload size={18}/>}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-white">{video?.name ?? 'Choose one video file'}</span><span className="mt-1 block text-[11px] text-white/45">MP4, WebM, MOV or MKV · up to 25 MB</span></span>
                  <span className="rounded-full border border-white/15 px-3 py-1.5 text-xs text-white/70">{video ? 'Replace' : 'Browse'}</span>
                  <input id="hero-video-upload" type="file" accept="video/mp4,video/webm,video/quicktime,video/x-matroska" onChange={(event) => { const next = event.target.files?.[0] ?? null; setVideo(next); setQuery(''); setResponse(null); setError(null); if (next) track('upload_started', { language }) }} className="sr-only"/>
                </label>}

                <p className="mt-4 text-[11px] leading-5 text-white/40">{sourceMode === 'sample' ? 'Sample selection is free. A search is counted only when you submit a query.' : 'Your upload is processed temporarily and removed after the search.'}</p>
              </section>

              <section className="p-5 lg:p-6" aria-labelledby="query-heading">
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-glow">Query</p>
                <h2 id="query-heading" className="mt-1 text-lg text-white">Ask for the moment you remember</h2>
                {sourceReady ? <div className="mt-4 flex items-center gap-2 rounded-xl border border-glow/25 bg-glow/[0.06] px-3 py-2 text-xs text-white/70"><Check size={14} className="shrink-0 text-glow"/><span className="truncate"><span className="text-white/45">Selected:</span> {sourceMode === 'sample' ? selected?.name : video?.name}</span></div> : <p className="mt-4 rounded-xl border border-dashed border-white/15 px-4 py-3 text-xs text-white/45">Choose a video on the left to continue.</p>}

                {sourceMode === 'sample' && selected && <div className="mt-4"><p className="text-xs text-white/45">Try a suggested query</p><div className="mt-2 flex flex-wrap gap-2">{selected.queries.map((suggestion) => <button key={suggestion} type="button" onClick={() => { setQuery(suggestion); track('suggested_query_selected', { sample_id: selected.id, language }) }} className={`rounded-full border px-3 py-2 text-xs transition ${query === suggestion ? 'border-glow bg-glow/10 text-glow' : 'border-white/15 text-white/70 hover:border-glow/50 hover:text-white'}`}>{suggestion}</button>)}</div></div>}

                {sourceReady && promptForm(sourceMode === 'sample' ? 'Describe another moment in this sample…' : 'For example: Find the person waving at the camera…')}
                <div className="mt-3 min-h-6 text-xs" aria-live="polite">{usage && !exhausted && <span className="text-paper-300/60">{usage.remaining} free live {usage.remaining === 1 ? 'search' : 'searches'} remaining today</span>}{usage && exhausted && <span className="text-amber-200">You’ve used today’s two live searches. Reset {new Date(usage.resetAt).toLocaleString()}.</span>}</div>
                {busy && <div className="mt-4" aria-live="polite"><StageSequence stages={QUERY_STAGES} labels={stageLabels} elapsedSeconds={elapsed} expectedSeconds={35} active/></div>}
                {error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}
              </section>
            </div>
          </div>
          <div className="mt-5 flex flex-wrap justify-center gap-3"><button onClick={() => route('/how-it-works', 'how_it_works_opened')} className="rounded-full border border-white/20 px-6 py-3 text-sm text-white/80">See how it works</button></div>
        </div>
      </section>

      <main className="relative bg-black"><ParticleField />
        {response && <section id="results-section" className="relative z-10 mx-auto max-w-4xl px-5 py-12" aria-live="polite"><div className="liquid-glass overflow-hidden rounded-2xl"><div className="border-b border-white/10 px-5 py-3 text-sm">Exact matching moments</div><MomentResults strings={t} response={response} error={null}/></div></section>}

        <section className="relative z-10 mx-auto max-w-6xl px-5 py-24"><p className="eyebrow">Search the way you remember</p><div className="mt-8 grid gap-4 md:grid-cols-4">{CAPABILITIES.map(({ icon: Icon, title, copy }) => <article key={title} className="rounded-2xl border border-white/10 bg-ink-900/60 p-5"><Icon className="text-glow" size={20}/><h3 className="mt-5 text-lg text-white">{title}</h3><p className="mt-2 text-sm text-paper-300/55">{copy}</p></article>)}</div></section>

        <section className="relative z-10 mx-auto max-w-6xl border-y border-white/10 px-5 py-24"><p className="eyebrow">From hours of footage to the exact moment</p><div className="mt-9 grid gap-8 md:grid-cols-3">{['Choose footage', 'Ask naturally', 'Play the matching moment'].map((label, i) => <div key={label}><span className="font-mono text-xs text-glow">0{i + 1}</span><h3 className="mt-3 text-2xl text-white">{label}</h3></div>)}</div><button onClick={() => route('/how-it-works', 'how_it_works_opened')} className="mt-10 inline-flex items-center gap-2 text-sm text-glow">How it works <ArrowRight size={15}/></button></section>

        <section className="relative z-10 mx-auto grid max-w-6xl gap-16 px-5 py-24 lg:grid-cols-2"><div><p className="eyebrow">Built for difficult footage</p><h2 className="mt-4 text-4xl text-white" style={{ fontFamily: "'Instrument Serif', serif" }}>Real archives are rarely clean.</h2><p className="mt-5 max-w-xl text-sm leading-7 text-paper-300/60">Silent video, audio-only inputs, low-light scenes, contradictory signals, long recordings and honest no-result queries are part of the design—not afterthoughts.</p></div><div><p className="eyebrow">How Aperture understands video</p><div className="mt-5 grid grid-cols-2 gap-3">{SIGNALS.map(([label, Icon]) => <div key={label} className="rounded-xl border border-white/10 p-4"><Icon size={16} className="text-glow"/><p className="mt-3 text-sm text-white/80">{label}</p></div>)}</div><p className="mt-5 text-sm leading-7 text-paper-300/60">Each signal stays independent and ranking combines the evidence, so a missing or misleading modality does not automatically ruin the result.</p><button onClick={() => route('/design')} className="mt-5 text-sm text-glow">View technical design →</button></div></section>

        <section className="relative z-10 mx-auto max-w-6xl px-5 py-24"><div className="rounded-3xl border border-glow/20 bg-gradient-to-br from-glow/10 to-transparent p-8 md:p-12"><p className="eyebrow">For builders</p><h2 className="mt-4 text-4xl text-white" style={{ fontFamily: "'Instrument Serif', serif" }}>Hosted or self-hosted. One retrieval language.</h2><p className="mt-5 max-w-3xl text-sm leading-7 text-paper-300/65">Qdrant support, OpenAI-compatible custom models, long-video indexing, multimodal retrieval and multilingual querying remain available under protected Developer settings.</p><button onClick={() => route('/developer', 'developer_page_opened')} className="mt-7 rounded-full border border-white/20 px-5 py-2.5 text-sm">Developer settings</button></div></section>

        <section className="relative z-10 mx-auto max-w-5xl px-5 py-28 text-center"><h2 className="text-5xl text-white md:text-6xl" style={{ fontFamily: "'Instrument Serif', serif" }}>Your footage already contains the answer.</h2><p className="mx-auto mt-5 max-w-xl text-white/60">Aperture helps you find the exact moment without scrubbing through the entire recording.</p><button onClick={() => { track('product_hunt_cta_clicked'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} className="mt-8 rounded-full bg-glow px-7 py-3 font-semibold text-black">Try two live searches</button></section>
      </main>
    </div>
  )
}
