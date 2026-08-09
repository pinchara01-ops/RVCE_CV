import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, Eye, Film, Image, Mic, Play, Volume2 } from 'lucide-react'
import { Nav } from '../components/Nav'
import { BackgroundVideo } from '../components/BackgroundVideo'
import { ParticleField } from '../components/ParticleField'
import { MomentResults } from '../components/MomentResults'
import { StageSequence } from '../components/StageSequence'
import { QueryComposer, EMPTY_ATTACHMENTS, type Attachments } from '../components/QueryComposer'
import {
  getPublicSamples,
  getPublicUsage,
  runQuickSearch,
  SearchApiError,
  type PublicSample,
  type PublicUsage,
  type QuickSearchResponse,
} from '../lib/api'
import type { Recording } from '../components/VoiceRecorder'
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
  const [recording, setRecording] = useState<Recording | null>(null)
  const [attachments, setAttachments] = useState<Attachments>(EMPTY_ATTACHMENTS)
  const [samples, setSamples] = useState<PublicSample[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [usage, setUsage] = useState<PublicUsage | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [response, setResponse] = useState<QuickSearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const startedAt = useRef(0)

  const selected = useMemo(() => samples.find((sample) => sample.id === selectedId) ?? null, [samples, selectedId])
  const exhausted = usage?.remaining === 0

  useEffect(() => {
    track('landing_viewed', { language })
    getPublicSamples()
      .then((catalog) => {
        setSamples(catalog)
        setSelectedId(catalog.find((sample) => sample.available)?.id ?? catalog[0]?.id ?? null)
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
    if (!selected?.available || exhausted || busy) return
    const hasRequest = query.trim() || recording || attachments.images.length || attachments.reference
    if (!hasRequest) return
    setBusy(true)
    setError(null)
    setResponse(null)
    setElapsed(0)
    const modality = attachments.reference ? 'reference_clip' : attachments.images.length ? 'reference_image' : recording ? 'voice' : 'text'
    track('live_search_started', { sample_id: selected.id, modality, language })
    try {
      const result = await runQuickSearch({
        query,
        sampleId: selected.id,
        audio: recording?.blob ?? null,
        images: attachments.images,
        reference: attachments.reference,
        language: LANGUAGE_OPTIONS.find((item) => item.code === language)?.label ?? 'English',
      }, null, undefined, crypto.randomUUID())
      setResponse(result)
      if (result.usage) setUsage(result.usage)
      track('live_search_completed', { sample_id: selected.id, modality, language, outcome: 'success' })
      window.setTimeout(() => document.getElementById('results-section')?.scrollIntoView({ behavior: 'smooth' }), 80)
    } catch (cause) {
      const message = cause instanceof SearchApiError ? cause.message : 'Search failed safely. Please try again.'
      setError(message)
      if (cause instanceof SearchApiError && cause.usage) setUsage(cause.usage)
      if (message.toLowerCase().includes('two live searches')) track('live_limit_reached', { sample_id: selected.id, modality, language })
      else track('live_search_failed', { sample_id: selected.id, modality, language, outcome: 'safe_error' })
      void getPublicUsage().then(setUsage).catch(() => undefined)
    } finally {
      setBusy(false)
    }
  }

  const stageLabels: Record<string, string> = {
    uploading: 'Preparing sample', decoding: 'Reading footage', understanding: 'Understanding your request',
    scanning: 'Scanning every signal', matching: 'Ranking matching moments', localising: 'Finding exact timestamps', clipping: 'Preparing playable moments',
  }

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

          <div className="mt-9 w-full max-w-2xl">
            {selected && <p className="mb-3 text-left text-xs text-paper-300/60">Searching in <span className="text-glow">{selected.name}</span></p>}
            <QueryComposer strings={t} value={query} onChange={setQuery} recording={recording} onRecorded={(value) => { setRecording(value); if (value) track('voice_query_used', { language }) }} attachments={attachments} onAttachments={(value) => { setAttachments(value); if (value.images.length) track('reference_image_used', { language }); if (value.reference) track('reference_clip_used', { language }) }} disabled={busy || exhausted || !selected?.available} onSubmit={submit} onError={setError} rtl={rtl} />
            <div className="mt-3 min-h-6 text-left text-xs" aria-live="polite">
              {usage && !exhausted && <span className="text-paper-300/60">{usage.remaining} free live {usage.remaining === 1 ? 'search' : 'searches'} remaining today</span>}
              {usage && exhausted && <span className="text-amber-200">You’ve used today’s two live searches. Recorded examples remain available. Reset {new Date(usage.resetAt).toLocaleString()}.</span>}
            </div>
            {busy && <div className="mt-5" aria-live="polite"><StageSequence stages={QUERY_STAGES} labels={stageLabels} elapsedSeconds={elapsed} expectedSeconds={35} active /></div>}
            {error && <p role="alert" className="mt-3 text-left text-sm text-red-300">{error}</p>}
          </div>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <button onClick={() => document.getElementById('sample-library')?.scrollIntoView({ behavior: 'smooth' })} className="rounded-full bg-glow px-6 py-3 text-sm font-semibold text-black">Try the live demo</button>
            <button onClick={() => route('/how-it-works', 'how_it_works_opened')} className="rounded-full border border-white/20 px-6 py-3 text-sm text-white/80">See how it works</button>
          </div>
        </div>
      </section>

      <main className="relative bg-black"><ParticleField />
        <section id="sample-library" className="relative z-10 mx-auto max-w-6xl px-5 py-20">
          <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end"><div><p className="eyebrow">Public demo library</p><h2 className="mt-3 text-4xl text-white md:text-5xl" style={{ fontFamily: "'Instrument Serif', serif" }}>Choose footage, then ask naturally.</h2></div><div className="rounded-full border border-white/10 p-1 text-xs"><span className="inline-block rounded-full bg-glow px-4 py-2 text-black">Try sample footage</span><span className="inline-block px-4 py-2 text-white/35" title="Disabled for public launch">Upload your own video · Developer/local</span></div></div>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {samples.map((sample, index) => <button key={sample.id} type="button" disabled={!sample.available} aria-pressed={selectedId === sample.id} onClick={() => { setSelectedId(sample.id); track('sample_selected', { sample_id: sample.id, language }) }} className={`group overflow-hidden rounded-2xl border text-left transition ${selectedId === sample.id ? 'border-glow bg-glow/10' : 'border-white/10 bg-ink-900/80 hover:border-white/25'} disabled:cursor-not-allowed disabled:opacity-55`}>
              <div className="relative aspect-video overflow-hidden bg-gradient-to-br from-ink-700 via-black to-amber-950/50"><div className="absolute inset-0 opacity-50" style={{ backgroundImage: `linear-gradient(90deg, transparent 49%, rgba(255,255,255,.06) 50%), linear-gradient(transparent 49%, rgba(255,255,255,.05) 50%)`, backgroundSize: '32px 32px' }} /><span className="absolute left-3 top-3 rounded-full bg-black/70 px-2 py-1 font-mono text-[10px] text-white/70">CAM {String(index + 1).padStart(2, '0')}</span><span className="absolute bottom-3 right-3 text-xs text-white/60">{sample.duration}</span></div>
              <div className="p-4"><h3 className="text-sm text-white">{sample.name}</h3><p className="mt-2 text-xs leading-relaxed text-paper-300/50">{sample.description}</p><p className="mt-3 text-[10px] uppercase tracking-wider text-glow/80">{sample.modalities.join(' · ')}</p>{!sample.available && <p className="mt-2 text-[11px] text-amber-200/70">Media must be configured on the backend</p>}</div>
            </button>)}
          </div>
          {selected && <div className="mt-5 rounded-2xl border border-white/10 bg-ink-900/70 p-5"><p className="text-xs uppercase tracking-widest text-paper-300/40">Suggested searches · selecting one does not use a live search</p><div className="mt-3 flex flex-wrap gap-2">{selected.queries.map((suggestion) => <button key={suggestion} onClick={() => { setQuery(suggestion); track('suggested_query_selected', { sample_id: selected.id, language }); window.scrollTo({ top: 0, behavior: 'smooth' }) }} className="rounded-full border border-white/15 px-4 py-2 text-left text-xs text-white/75 hover:border-glow/60 hover:text-white">{suggestion}</button>)}</div></div>}
        </section>

        <section id="results-section" className="relative z-10 mx-auto max-w-4xl px-5 py-12" aria-live="polite"><div className="liquid-glass overflow-hidden rounded-2xl"><div className="border-b border-white/10 px-5 py-3 text-sm">Exact matching moments</div><MomentResults strings={t} response={response} error={null} /></div></section>

        <section className="relative z-10 mx-auto max-w-6xl px-5 py-24"><p className="eyebrow">Search the way you remember</p><div className="mt-8 grid gap-4 md:grid-cols-4">{CAPABILITIES.map(({ icon: Icon, title, copy }) => <article key={title} className="rounded-2xl border border-white/10 bg-ink-900/60 p-5"><Icon className="text-glow" size={20}/><h3 className="mt-5 text-lg text-white">{title}</h3><p className="mt-2 text-sm text-paper-300/55">{copy}</p></article>)}</div></section>

        <section className="relative z-10 mx-auto max-w-6xl border-y border-white/10 px-5 py-24"><p className="eyebrow">From hours of footage to the exact moment</p><div className="mt-9 grid gap-8 md:grid-cols-3">{['Choose footage', 'Ask naturally', 'Play the matching moment'].map((label, i) => <div key={label}><span className="font-mono text-xs text-glow">0{i + 1}</span><h3 className="mt-3 text-2xl text-white">{label}</h3></div>)}</div><button onClick={() => route('/how-it-works', 'how_it_works_opened')} className="mt-10 inline-flex items-center gap-2 text-sm text-glow">How it works <ArrowRight size={15}/></button></section>

        <section className="relative z-10 mx-auto grid max-w-6xl gap-16 px-5 py-24 lg:grid-cols-2"><div><p className="eyebrow">Built for difficult footage</p><h2 className="mt-4 text-4xl text-white" style={{ fontFamily: "'Instrument Serif', serif" }}>Real archives are rarely clean.</h2><p className="mt-5 max-w-xl text-sm leading-7 text-paper-300/60">Silent video, audio-only inputs, low-light scenes, contradictory signals, long recordings and honest no-result queries are part of the design—not afterthoughts.</p><button onClick={() => route('/tests')} className="mt-7 text-sm text-glow">Explore recorded tests →</button></div><div><p className="eyebrow">How Aperture understands video</p><div className="mt-5 grid grid-cols-2 gap-3">{SIGNALS.map(([label, Icon]) => <div key={label} className="rounded-xl border border-white/10 p-4"><Icon size={16} className="text-glow"/><p className="mt-3 text-sm text-white/80">{label}</p></div>)}</div><p className="mt-5 text-sm leading-7 text-paper-300/60">Each signal stays independent and ranking combines the evidence, so a missing or misleading modality does not automatically ruin the result.</p><button onClick={() => route('/design')} className="mt-5 text-sm text-glow">View technical design →</button></div></section>

        <section className="relative z-10 mx-auto max-w-6xl px-5 py-24"><div className="rounded-3xl border border-glow/20 bg-gradient-to-br from-glow/10 to-transparent p-8 md:p-12"><p className="eyebrow">For builders</p><h2 className="mt-4 text-4xl text-white" style={{ fontFamily: "'Instrument Serif', serif" }}>Hosted or self-hosted. One retrieval language.</h2><p className="mt-5 max-w-3xl text-sm leading-7 text-paper-300/65">Qdrant support, OpenAI-compatible custom models, long-video indexing, multimodal retrieval and multilingual querying remain available under protected Developer settings.</p><button onClick={() => route('/developer', 'developer_page_opened')} className="mt-7 rounded-full border border-white/20 px-5 py-2.5 text-sm">Developer settings</button></div></section>

        <section className="relative z-10 mx-auto max-w-5xl px-5 py-28 text-center"><h2 className="text-5xl text-white md:text-6xl" style={{ fontFamily: "'Instrument Serif', serif" }}>Your footage already contains the answer.</h2><p className="mx-auto mt-5 max-w-xl text-white/60">Aperture helps you find the exact moment without scrubbing through the entire recording.</p><button onClick={() => { track('product_hunt_cta_clicked'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} className="mt-8 rounded-full bg-glow px-7 py-3 font-semibold text-black">Try two live searches</button></section>
      </main>
    </div>
  )
}
