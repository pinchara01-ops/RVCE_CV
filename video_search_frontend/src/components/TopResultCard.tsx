import { Film, Play } from 'lucide-react'
import type { SearchResultItem } from '../lib/api'
import { formatTimestamp } from '../lib/format'

function matchReason(result: SearchResultItem) {
  const top = result.matched_modalities?.[0]
  if (result.caption) return result.caption
  if (top) return `Matched via ${top}`
  return 'Retrieved candidate window'
}

// Demo-only normalization: an RRF/rerank score isn't a calibrated
// probability, so this just maps it onto a 0-100 bar for a rough visual
// signal rather than an exact confidence figure.
function confidencePercent(result: SearchResultItem): number {
  const raw = result.final_score ?? result.score
  const squashed = raw / (Math.abs(raw) + 1) // -1..1
  return Math.round(Math.min(Math.max((squashed + 1) / 2, 0), 1) * 100)
}

interface TopResultCardProps {
  result: SearchResultItem
  resultCount: number
  onViewAll: () => void
}

export function TopResultCard({ result, resultCount, onViewAll }: TopResultCardProps) {
  const confidence = confidencePercent(result)

  return (
    <div>
      <div className="liquid-glass flex gap-4 rounded-2xl border border-white/10 bg-ink-900/70 p-3">
        <div className="relative h-20 w-32 shrink-0 overflow-hidden rounded-xl bg-ink-800">
          <div className="flex h-full w-full items-center justify-center text-paper-300/25">
            <Film size={26} />
          </div>
          <button
            type="button"
            aria-label="Play matched clip"
            className="absolute inset-0 flex items-center justify-center bg-black/20 transition-colors hover:bg-black/35"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/90 text-black">
              <Play size={16} fill="currentColor" />
            </span>
          </button>
        </div>

        <div className="min-w-0 flex-1 text-left">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-medium text-paper-100">{result.video_id}</span>
            <span className="shrink-0 font-mono text-xs text-paper-300/50">
              {formatTimestamp(result.start)} – {formatTimestamp(result.end)}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-paper-300/60">{matchReason(result)}</p>
          <div className="mt-2 flex items-center gap-2">
            <div className="h-1 w-20 overflow-hidden rounded-full bg-ink-700">
              <div className="h-full rounded-full bg-glow" style={{ width: `${confidence}%` }} />
            </div>
            <span className="font-mono text-[10px] text-paper-300/40">{confidence}% match</span>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={onViewAll}
        className="mt-3 block w-full text-center text-xs text-paper-300/50 underline-offset-4 transition-colors hover:text-paper-100 hover:underline"
      >
        View all {resultCount} results and pipeline →
      </button>
    </div>
  )
}
