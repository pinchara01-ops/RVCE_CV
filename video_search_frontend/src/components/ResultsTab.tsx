import { Film, AlertTriangle } from 'lucide-react'
import type { Turn } from '../lib/turns'
import type { SearchResultItem } from '../lib/api'

function formatTime(seconds: number) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function matchReason(result: SearchResultItem) {
  const top = result.matched_modalities?.[0]
  if (result.caption) return result.caption
  if (top) return `Matched via ${top}`
  return 'Retrieved candidate window'
}

function ResultCard({ result }: { result: SearchResultItem }) {
  return (
    <div className="liquid-glass flex gap-3 rounded-xl p-3">
      <div className="flex h-16 w-24 shrink-0 items-center justify-center rounded-lg bg-ink-800 text-paper-300/30">
        <Film size={22} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-paper-100">{result.video_id}</span>
          <span className="shrink-0 font-mono text-xs text-paper-300/50">
            {formatTime(result.start)}-{formatTime(result.end)}
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs text-paper-300/60">{matchReason(result)}</p>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {result.matched_modalities.map((m) => (
            <span
              key={m}
              className="rounded-full bg-ink-800 px-2 py-0.5 text-[10px] capitalize text-paper-300/50"
            >
              {m}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function TurnBlock({ turn }: { turn: Turn }) {
  return (
    <div className="animate-fade-up space-y-3">
      <div className="flex justify-end">
        <div className="liquid-glass max-w-[80%] rounded-2xl rounded-tr-sm px-4 py-2 text-sm text-paper-100">
          {turn.query}
        </div>
      </div>

      {turn.status === 'loading' && (
        <p className="pl-1 text-sm text-paper-300/50">Searching your footage…</p>
      )}

      {turn.status === 'error' && (
        <div className="flex items-center gap-2 pl-1 text-sm text-red-300/80">
          <AlertTriangle size={14} />
          {turn.error}
        </div>
      )}

      {turn.status === 'done' && turn.response && (
        <div className="space-y-2 pl-1">
          {turn.response.results.length === 0 ? (
            <p className="text-sm text-paper-300/50">No matching windows found.</p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {turn.response.results.map((r) => (
                <ResultCard key={r.window_id} result={r} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ResultsTab({ turns }: { turns: Turn[] }) {
  if (turns.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-6 py-16 text-center text-sm text-paper-300/40">
        Ask something about your footage to get started.
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto px-6 py-6">
      {turns.map((turn) => (
        <TurnBlock key={turn.id} turn={turn} />
      ))}
    </div>
  )
}
