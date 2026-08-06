import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Loader2, Play } from 'lucide-react'
import { PageShell } from '../components/PageShell'
import { TEST_CASES, type TestCase } from '../lib/testCases'
import { testAssetUrl } from '../lib/api'
import { QUERY_STAGES, stageAt } from '../lib/stages'
import { useLanguage } from '../lib/settings'
import { stringsFor, type Strings } from '../lib/i18n'

const STAGE_LABELS: Record<string, string> = {
  uploading: 'Uploading footage',
  decoding: 'Decoding and probing duration',
  understanding: 'Understanding the request',
  scanning: 'Scanning visual, audio, and speech',
  matching: 'Matching against the request',
  localising: 'Localising exact moments',
  clipping: 'Cutting playable clips',
}

// Paced so each stage is legible rather than flickering past.
const RUN_SECONDS = 14

function TestCard({ test, strings: t }: { test: TestCase; strings: Strings }) {
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const startedAt = useRef(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const url = testAssetUrl(test.localFile)
  const isAudio = test.localFile.endsWith('.mp3')

  useEffect(() => {
    if (!running) return
    startedAt.current = performance.now()
    const id = window.setInterval(() => {
      const seconds = (performance.now() - startedAt.current) / 1000
      setElapsed(seconds)
      if (seconds >= RUN_SECONDS) {
        window.clearInterval(id)
        setRunning(false)
        setDone(true)
        // Jump the player to the section this case is about and play it.
        const player = videoRef.current
        if (player) {
          player.currentTime = test.sectionStart
          void player.play().catch(() => undefined)
        }
      }
    }, 100)
    return () => window.clearInterval(id)
  }, [running])

  const { index } = stageAt(QUERY_STAGES, elapsed, RUN_SECONDS)

  return (
    <article className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5">
      {isAudio ? (
        <audio
          ref={videoRef as unknown as React.RefObject<HTMLAudioElement>}
          controls
          preload="metadata"
          src={url}
          className="mb-4 w-full"
        />
      ) : (
        <video
          ref={videoRef}
          controls
          preload="metadata"
          src={url}
          className="mb-4 aspect-video w-full rounded-xl bg-black"
        />
      )}

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-base text-paper-100">{test.title}</h2>
          <p className="mt-1 text-xs leading-relaxed text-paper-300/50">{test.stresses}</p>
        </div>
        <span className="shrink-0 rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 font-mono text-[10px] text-amber-200/80">
          {t.notBuilt}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3">
        {[
          { label: 'accuracy', value: `${test.accuracy}%` },
          { label: 'recall', value: `${test.recall}%` },
          { label: 'latency', value: `${test.latencySeconds.toFixed(1)}s` },
        ].map((metric) => (
          <div key={metric.label} className="rounded-xl border border-white/10 bg-ink-800/50 p-2.5">
            <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
              {metric.label}
            </p>
            <p className="mt-0.5 text-lg text-paper-100">{metric.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 space-y-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
            {t.challengeLabel}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-paper-300/70">{test.challenge}</p>
        </div>
        <div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
            {t.handledLabel}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-paper-300/70">{test.mitigation}</p>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-white/10 bg-ink-800/40 p-3">
        <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">{t.queryLabel}</p>
        <p className="mt-1 text-xs text-paper-100">“{test.query}”</p>
        <p className="mt-2 font-mono text-[10px] text-paper-300/35">
          {test.localFile}
        </p>
        <p className="mt-1 font-mono text-[10px] text-paper-300/35">
          {test.durationSeconds.toFixed(1)}s · {test.streams}
        </p>
      </div>

      {running && (
        <div className="mt-4 rounded-xl border border-white/10 bg-ink-800/40 p-3">
          <div className="flex items-center gap-2 text-xs text-paper-100">
            <Loader2 size={12} className="animate-spin text-glow" />
            {STAGE_LABELS[QUERY_STAGES[index].key]}
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-ink-700">
            <div
              className="h-full rounded-full bg-glow transition-[width] duration-200"
              style={{ width: `${Math.min(100, (elapsed / RUN_SECONDS) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {done && (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-glow/30 bg-glow/10 p-3 text-xs text-paper-100">
          <Check size={13} className="shrink-0 text-glow" />
          <span>
            {test.sectionStart.toFixed(1)}s - {test.sectionEnd.toFixed(1)}s · {t.walkthroughDone}
          </span>
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          setDone(false)
          setElapsed(0)
          setRunning(true)
        }}
        disabled={running}
        className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-sm text-paper-300/80 transition-colors hover:border-white/30 hover:text-paper-100 disabled:opacity-40"
      >
        <Play size={14} />
        {running ? t.runningLabel : t.tryItOut}
      </button>
    </article>
  )
}

export function Tests() {
  const [language] = useLanguage()
  const t = stringsFor(language)

  return (
    <PageShell heroHeight="70vh">
      <div className="mx-auto w-full max-w-5xl px-6 pb-24 pt-8">
        <h1
          className="text-5xl leading-tight tracking-tight text-white md:text-6xl"
          style={{ fontFamily: "'Instrument Serif', serif" }}
        >
          {t.testsTitle}
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/70">
{t.testsSubtitle}
        </p>

        <div className="mt-6 flex items-start gap-3 rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-300" />
          <div className="text-sm text-amber-100/90">
            <p className="font-medium">{t.placeholderBanner}</p>
            <p className="mt-1 text-xs text-amber-100/70">
              Every card is marked <span className="font-mono">placeholder</span> and “Try it out”
              replays a scripted walkthrough on a timer. Replace the numbers in{' '}
              <span className="font-mono">src/lib/testCases.ts</span> with real figures, and clear
              the badge, once the corpus has actually been run.
            </p>
          </div>
        </div>

        <div className="mt-8 grid gap-4 lg:grid-cols-2">
          {TEST_CASES.map((test) => (
            <TestCard key={test.id} test={test} strings={t} />
          ))}
        </div>
      </div>
    </PageShell>
  )
}
