import { useRef, useState } from 'react'
import { Film, Library, Search, UploadCloud, X } from 'lucide-react'
import { formatBytes } from '../lib/format'
import type { Strings } from '../lib/i18n'

export type Source = 'upload' | 'library'

interface SourceChoiceProps {
  strings: Strings
  query: string
  source: Source | null
  file: File | null
  busy: boolean
  onChangeQuery: () => void
  onPickSource: (source: Source) => void
  onPickFile: (file: File | null) => void
  onSubmit: () => void
}

export function SourceChoice({
  strings: t,
  query,
  source,
  file,
  busy,
  onChangeQuery,
  onPickSource,
  onPickFile,
  onSubmit,
}: SourceChoiceProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragActive, setDragActive] = useState(false)

  return (
    <div className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-4 text-left">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-widest text-paper-300/40">{t.lookingFor}</p>
          <p className="mt-1 truncate text-sm text-paper-100">“{query}”</p>
        </div>
        <button
          type="button"
          onClick={onChangeQuery}
          disabled={busy}
          className="shrink-0 text-xs text-paper-300/50 underline-offset-4 transition-colors hover:text-paper-100 hover:underline disabled:opacity-40"
        >
          {t.change}
        </button>
      </div>

      <p className="mt-4 text-sm text-paper-300/70">{t.whereToLook}</p>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onPickSource('upload')}
          disabled={busy}
          className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm transition-colors disabled:opacity-40 ${
            source === 'upload'
              ? 'border-glow bg-glow/10 text-paper-100'
              : 'border-white/10 bg-ink-800/60 text-paper-300/70 hover:border-white/25 hover:text-paper-100'
          }`}
        >
          <UploadCloud size={16} />
          {t.uploadFootage}
        </button>
        <button
          type="button"
          onClick={() => onPickSource('library')}
          disabled={busy}
          className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm transition-colors disabled:opacity-40 ${
            source === 'library'
              ? 'border-glow bg-glow/10 text-paper-100'
              : 'border-white/10 bg-ink-800/60 text-paper-300/70 hover:border-white/25 hover:text-paper-100'
          }`}
        >
          <Library size={16} />
          {t.searchLibrary}
        </button>
      </div>

      {source === 'upload' && (
        <div className="mt-3">
          {file ? (
            <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2.5">
              <Film size={16} className="shrink-0 text-glow" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-paper-100">{file.name}</p>
                <p className="font-mono text-[10px] text-paper-300/40">
                  {formatBytes(file.size)}
                </p>
              </div>
              <button
                type="button"
                aria-label="Remove selected video"
                onClick={() => onPickFile(null)}
                disabled={busy}
                className="shrink-0 text-paper-300/40 transition-colors hover:text-paper-100 disabled:opacity-40"
              >
                <X size={16} />
              </button>
            </div>
          ) : (
            <div
              role="button"
              tabIndex={0}
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
              }}
              onDragOver={(e) => {
                e.preventDefault()
                setDragActive(true)
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragActive(false)
                const dropped = e.dataTransfer.files?.[0]
                if (dropped) onPickFile(dropped)
              }}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
                dragActive ? 'border-glow bg-glow/5' : 'border-white/15 bg-ink-800/40'
              }`}
            >
              <UploadCloud size={22} className={dragActive ? 'text-glow' : 'text-paper-300/50'} />
              <p className="text-sm text-paper-100">{t.dropHint}</p>
              <p className="text-xs text-paper-300/40">{t.fileHint}</p>
            </div>
          )}

          <input
            ref={inputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => {
              const picked = e.target.files?.[0] ?? null
              if (picked) onPickFile(picked)
              e.target.value = ''
            }}
          />

          <button
            type="button"
            onClick={onSubmit}
            disabled={busy || !file}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-glow px-4 py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <Search size={15} />
            {busy ? t.searching : t.findTheMoment}
          </button>
        </div>
      )}

      {source === 'library' && (
        <div className="mt-3 rounded-xl border border-white/10 bg-ink-800/40 px-4 py-5 text-center">
          <p className="text-sm text-paper-100">{t.nothingIndexed}</p>
          <p className="mt-1 text-xs text-paper-300/50">
{t.nothingIndexedBody}
          </p>
        </div>
      )}
    </div>
  )
}
