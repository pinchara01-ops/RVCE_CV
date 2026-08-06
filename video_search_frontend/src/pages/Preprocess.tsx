import { useEffect, useRef, useState } from 'react'
import { Film, Layers, UploadCloud } from 'lucide-react'
import { PageShell } from '../components/PageShell'
import { ConnectorGrid } from '../components/ConnectorGrid'
import { StageSequence } from '../components/StageSequence'
import { INDEX_STAGES } from '../lib/stages'
import { runIndex, SearchApiError, type IndexResponse, type IndexWindow } from '../lib/api'
import { formatTimestamp, formatBytes } from '../lib/format'
import { useLanguage } from '../lib/settings'
import { stringsFor, type Strings } from '../lib/i18n'

const STAGE_LABELS: Record<string, string> = {
  uploading: 'Uploading footage',
  segmenting: 'Segmenting into windows',
  visual: 'Extracting visual features',
  audio: 'Extracting audio events',
  transcript: 'Transcribing speech',
  captioning: 'Captioning each window',
  embedding: 'Building vectors',
  persisting: 'Writing to the index',
}

function WindowRow({
  window: entry,
  videoUrl,
  strings: t,
}: {
  window: IndexWindow
  videoUrl: string | null
  strings: Strings
}) {
  const [open, setOpen] = useState(false)

  return (
    <article className="rounded-xl border border-white/10 bg-ink-800/50">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-3 p-3 text-left"
      >
        <span className="mt-0.5 shrink-0 font-mono text-[11px] text-glow">
          {formatTimestamp(entry.start)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm text-paper-100">{entry.caption || 'Window'}</span>
          <span className="mt-0.5 block font-mono text-[10px] text-paper-300/40">
            {entry.window_id} · {(entry.end - entry.start).toFixed(1)}s
          </span>
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-white/10 p-3">
          {videoUrl && (
            <video
              controls
              preload="metadata"
              className="w-full rounded-lg bg-black"
              src={`${videoUrl}#t=${entry.start},${entry.end}`}
            />
          )}

          {entry.transcript && (
            <div>
              <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                {t.transcriptLabel}
              </p>
              <p className="mt-1 text-xs text-paper-300/75">{entry.transcript}</p>
            </div>
          )}

          {[
            { label: 'objects', values: entry.objects },
            { label: 'actions', values: entry.actions },
            { label: 'audio events', values: entry.audio_events },
          ].map(
            (group) =>
              group.values.length > 0 && (
                <div key={group.label}>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                    {group.label}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {group.values.map((value) => (
                      <span
                        key={value}
                        className="rounded-full border border-white/10 bg-ink-900/60 px-2 py-0.5 text-[11px] text-paper-300/70"
                      >
                        {value}
                      </span>
                    ))}
                  </div>
                </div>
              ),
          )}

          <div>
            <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
              vectors
            </p>
            <div className="mt-1 grid gap-1.5 sm:grid-cols-2">
              {Object.entries(entry.vectors).map(([name, vector]) => (
                <div
                  key={name}
                  className="rounded-lg border border-white/10 bg-ink-900/60 px-2.5 py-1.5"
                >
                  <p className="font-mono text-[10px] text-paper-100">
                    {name}
                    <span className="text-paper-300/40"> · {vector.dimensions}d</span>
                  </p>
                  <p className="mt-0.5 truncate font-mono text-[9px] text-paper-300/35">
                    [{vector.preview.map((v) => v.toFixed(2)).join(', ')} …]
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] text-amber-200/60">
              {t.placeholderVectors}
            </p>
          </div>
        </div>
      )}
    </article>
  )
}

export function Preprocess() {
  const [language] = useLanguage()
  const t = stringsFor(language)
  const [file, setFile] = useState<File | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<IndexResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)

  const inputRef = useRef<HTMLInputElement>(null)
  const startedAt = useRef<number | null>(null)

  useEffect(() => {
    if (!busy) return
    startedAt.current = performance.now()
    const id = window.setInterval(() => {
      if (startedAt.current != null) setElapsed((performance.now() - startedAt.current) / 1000)
    }, 200)
    return () => window.clearInterval(id)
  }, [busy])

  // Object URL backs the per-window previews; revoked when the file changes.
  useEffect(() => {
    if (!file) {
      setVideoUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setVideoUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const start = async () => {
    if (!file) return
    setBusy(true)
    setElapsed(0)
    setError(null)
    setResult(null)
    try {
      setResult(await runIndex(file))
    } catch (cause) {
      setError(cause instanceof SearchApiError ? cause.message : 'Indexing could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  const expectedSeconds = file ? Math.max(30, Math.min(240, file.size / 1_048_576 / 0.7)) : 40

  return (
    <PageShell heroHeight="75vh">
      <div className="mx-auto w-full max-w-3xl px-6 pb-24 pt-8">
        <h1
          className="text-5xl leading-tight tracking-tight text-white md:text-6xl"
          style={{ fontFamily: "'Instrument Serif', serif" }}
        >
          {t.buildIndexTitle} <span className="italic text-glow">{t.buildIndexEmphasis}</span>
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/70">
{t.buildIndexSubtitle}
        </p>

        <div className="mt-10">
          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click()
            }}
            onDragOver={(event) => {
              event.preventDefault()
              setDragActive(true)
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragActive(false)
              const dropped = event.dataTransfer.files?.[0]
              if (dropped) setFile(dropped)
            }}
            className={`liquid-glass flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-5 py-8 text-center transition-colors ${
              dragActive ? 'border-glow bg-glow/5' : 'border-white/15 bg-ink-900/50'
            }`}
          >
            <UploadCloud size={24} className={dragActive ? 'text-glow' : 'text-paper-300/50'} />
            <p className="text-sm text-paper-100">
              {file ? file.name : t.uploadLongForm}
            </p>
            <p className="font-mono text-[10px] text-paper-300/40">
              {file ? formatBytes(file.size) : 'MP4, WebM, MOV, AVI, MKV'}
            </p>
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(event) => {
            const picked = event.target.files?.[0]
            if (picked) setFile(picked)
            event.target.value = ''
          }}
        />


        <div className="mt-3">
          <ConnectorGrid strings={t} onError={setError} />
        </div>

        <button
          type="button"
          onClick={start}
          disabled={!file || busy}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-glow px-4 py-3 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
        >
          <Layers size={15} />
          {busy ? t.indexingNow : t.startIndexing}
        </button>

        {busy && (
          <div className="mt-4">
            <StageSequence
              stages={INDEX_STAGES}
              labels={STAGE_LABELS}
              elapsedSeconds={elapsed}
              expectedSeconds={expectedSeconds}
              active
            />
          </div>
        )}

        {error && <p className="mt-4 text-sm text-red-300/90">{error}</p>}

        {result && (
          <div className="mt-8">
            <div className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5">
              <div className="flex items-center gap-2">
                <Film size={16} className="text-glow" />
                <p className="text-sm text-paper-100">
                  {result.window_count} {t.windowsIndexed}
                </p>
              </div>
              {result.summary && (
                <p className="mt-2 text-sm leading-relaxed text-paper-300/70">{result.summary}</p>
              )}
              <p className="mt-3 font-mono text-[10px] text-paper-300/40">
                {result.model} · {result.provider}
                {result.frames_sampled > 0 ? ` · ${result.frames_sampled} frames sampled` : ''}
                {result.duration_seconds ? ` · ${result.duration_seconds}s source` : ''}
              </p>
            </div>

            <div className="mt-4 space-y-2">
              {result.windows.map((entry) => (
                <WindowRow key={entry.window_id} window={entry} videoUrl={videoUrl} strings={t} />
              ))}
            </div>
          </div>
        )}
      </div>
    </PageShell>
  )
}
