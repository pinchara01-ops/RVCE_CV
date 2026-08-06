import { useEffect, useRef, useState } from 'react'
import { Nav } from '../components/Nav'
import { BackgroundVideo } from '../components/BackgroundVideo'
import { ParticleField } from '../components/ParticleField'
import { SourceChoice, type Source } from '../components/SourceChoice'
import { MomentResults } from '../components/MomentResults'
import { StageSequence } from '../components/StageSequence'
import { QueryComposer, EMPTY_ATTACHMENTS, type Attachments } from '../components/QueryComposer'
import { runQuickSearch, SearchApiError, type QuickSearchResponse } from '../lib/api'
import type { Recording } from '../components/VoiceRecorder'
import { LANGUAGE_OPTIONS } from '../lib/languages'
import { stringsFor, RTL_LANGUAGES } from '../lib/i18n'
import { QUERY_STAGES } from '../lib/stages'
import { useLanguage } from '../lib/settings'

type Step = 'ask' | 'source' | 'results'

export function Landing() {
  const [language] = useLanguage()
  const t = stringsFor(language)
  const rtl = RTL_LANGUAGES.has(language)

  const [step, setStep] = useState<Step>('ask')
  const [query, setQuery] = useState('')
  const [askedQuery, setAskedQuery] = useState('')

  const [recording, setRecording] = useState<Recording | null>(null)
  const [askedRecording, setAskedRecording] = useState<Recording | null>(null)
  const [attachments, setAttachments] = useState<Attachments>(EMPTY_ATTACHMENTS)
  const [askedAttachments, setAskedAttachments] = useState<Attachments>(EMPTY_ATTACHMENTS)

  const [source, setSource] = useState<Source | null>(null)
  const [file, setFile] = useState<File | null>(null)

  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [response, setResponse] = useState<QuickSearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const startedAtRef = useRef<number | null>(null)

  useEffect(() => {
    if (!busy) return
    startedAtRef.current = performance.now()
    const id = window.setInterval(() => {
      if (startedAtRef.current != null) {
        setElapsed((performance.now() - startedAtRef.current) / 1000)
      }
    }, 200)
    return () => {
      window.clearInterval(id)
      startedAtRef.current = null
    }
  }, [busy])

  const stageLabels: Record<string, string> = {
    uploading: t.stageUploading,
    decoding: t.stageDecoding,
    understanding: t.stageUnderstanding,
    scanning: t.stageScanning,
    matching: t.stageMatching,
    localising: t.stageLocalising,
    clipping: t.stageClipping,
  }

  const scrollToResults = () => {
    document.getElementById('results-section')?.scrollIntoView({ behavior: 'smooth' })
  }

  const askQuery = () => {
    const q = query.trim()
    const hasAny =
      q || recording || attachments.images.length > 0 || attachments.reference !== null
    if (!hasAny) return
    setAskedQuery(q)
    setAskedRecording(recording)
    setAskedAttachments(attachments)
    setError(null)
    setStep('source')
  }

  const backToQuery = () => {
    setStep('ask')
    setQuery(askedQuery)
    setRecording(askedRecording)
    setAttachments(askedAttachments)
    setSource(null)
    setError(null)
  }

  const findMoments = async () => {
    if (!file) return
    setBusy(true)
    setElapsed(0)
    setError(null)
    setResponse(null)

    try {
      const result = await runQuickSearch(
        {
          query: askedQuery,
          audio: askedRecording?.blob ?? null,
          images: askedAttachments.images,
          reference: askedAttachments.reference,
          language: LANGUAGE_OPTIONS.find((item) => item.code === language)?.label ?? 'English',
        },
        file,
      )
      setResponse(result)
      setStep('results')
      window.setTimeout(scrollToResults, 60)
    } catch (cause) {
      setError(cause instanceof SearchApiError ? cause.message : t.searchFailed)
    } finally {
      setBusy(false)
    }
  }

  const startOver = () => {
    setStep('ask')
    setQuery('')
    setAskedQuery('')
    setRecording(null)
    setAskedRecording(null)
    setAttachments(EMPTY_ATTACHMENTS)
    setAskedAttachments(EMPTY_ATTACHMENTS)
    setSource(null)
    setFile(null)
    setResponse(null)
    setError(null)
  }

  const requestLabel =
    askedQuery ||
    (askedRecording ? `${t.spokenRequest} · ${askedRecording.seconds.toFixed(1)}s` : '') ||
    (askedAttachments.images.length ? askedAttachments.images[0].name : '') ||
    (askedAttachments.reference?.name ?? '')

  // Long uploads dominate the wait, so the stage animation is paced off file
  // size. Deliberately generous: finishing early and holding on the last stage
  // reads better than racing to the end and sitting there.
  const expectedSeconds = file ? Math.max(25, Math.min(180, file.size / 1_048_576 / 0.9)) : 30

  return (
    <div className="min-h-screen bg-black text-paper-100" dir={rtl ? 'rtl' : 'ltr'}>
      <section className="relative min-h-screen w-full overflow-hidden bg-black">
        <BackgroundVideo />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/55 via-black/10 to-transparent" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-64 bg-gradient-to-b from-transparent to-black" />

        <div className="relative z-10 flex min-h-screen flex-col">
          <Nav />

          <div className="relative flex flex-1 flex-col items-center justify-center px-6 py-12 text-center md:-translate-y-[6%]">
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="h-[34rem] w-[34rem] rounded-full border border-glow/10 blur-[1px]" />
              <div className="absolute h-[24rem] w-[24rem] rounded-full border border-glow/15" />
              <div className="absolute h-[15rem] w-[15rem] rounded-full bg-glow/5 blur-3xl" />
            </div>

            <div className="relative w-full">
              <h1
                className="text-5xl leading-tight tracking-tight text-white md:text-6xl lg:text-7xl"
                style={{ fontFamily: "'Instrument Serif', serif" }}
              >
                {t.heroTitle} <span className="italic text-glow">{t.heroEmphasis}</span>
              </h1>
              <p className="mx-auto mt-6 max-w-xl text-balance px-4 text-sm leading-relaxed text-white/70 md:text-base">
                {t.heroSubtitle}
              </p>

              <div className="mx-auto mt-10 w-full max-w-xl">
                {step === 'ask' && (
                  <div>
                    <div>
                      <QueryComposer
                        strings={t}
                        value={query}
                        onChange={setQuery}
                        recording={recording}
                        onRecorded={setRecording}
                        attachments={attachments}
                        onAttachments={setAttachments}
                        disabled={busy}
                        onSubmit={askQuery}
                        onError={setError}
                        rtl={rtl}
                      />
                    </div>
                  </div>
                )}

                {step === 'source' && !busy && (
                  <SourceChoice
                    strings={t}
                    query={requestLabel}
                    source={source}
                    file={file}
                    busy={busy}
                    onChangeQuery={backToQuery}
                    onPickSource={setSource}
                    onPickFile={setFile}
                    onSubmit={findMoments}
                  />
                )}

                {busy && (
                  <StageSequence
                    stages={QUERY_STAGES}
                    labels={stageLabels}
                    elapsedSeconds={elapsed}
                    expectedSeconds={expectedSeconds}
                    active
                  />
                )}

                {step === 'results' && !busy && (
                  <div className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-4 text-left">
                    <p className="text-[11px] uppercase tracking-widest text-paper-300/40">
                      {t.searchedFor}
                    </p>
                    <p className="mt-1 text-sm text-paper-100">“{requestLabel}”</p>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={scrollToResults}
                        className="flex-1 rounded-xl bg-glow px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90"
                      >
                        {t.viewMoments}
                      </button>
                      <button
                        type="button"
                        onClick={startOver}
                        className="rounded-xl border border-white/15 px-4 py-2 text-sm text-paper-300/70 transition-colors hover:border-white/30 hover:text-paper-100"
                      >
                        {t.newSearch}
                      </button>
                    </div>
                  </div>
                )}

                {error && !busy && (
                  <p className="mt-3 text-left text-sm text-red-300/90">{error}</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="relative bg-black">
        <ParticleField />
        <section
          id="results-section"
          className="relative z-10 mx-auto w-full max-w-3xl scroll-mt-10 px-6 py-16"
        >
          <div
            className="liquid-glass overflow-hidden rounded-2xl"
            style={{ backgroundColor: 'rgba(20,19,15,0.97)' }}
          >
            <div className="border-b border-ink-700 px-5 py-3">
              <span className="text-sm font-medium text-paper-100">{t.moments}</span>
            </div>
            <MomentResults
              strings={t}
              response={response}
              error={step === 'results' ? null : error}
            />
          </div>
        </section>
      </div>
    </div>
  )
}
