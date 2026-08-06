import { Check, Loader2 } from 'lucide-react'
import { stageAt, type StageSpec } from '../lib/stages'

interface StageSequenceProps {
  stages: StageSpec[]
  labels: Record<string, string>
  elapsedSeconds: number
  expectedSeconds: number
  active: boolean
}

/**
 * Architecture-shaped progress. Stages already passed are ticked, the current
 * one spins, and the rest are dimmed. The footnote states plainly that the
 * timings are indicative, so nobody reads them as measured per-stage latency.
 */
export function StageSequence({
  stages,
  labels,
  elapsedSeconds,
  expectedSeconds,
  active,
}: StageSequenceProps) {
  if (!active) return null
  const { index, fraction } = stageAt(stages, elapsedSeconds, expectedSeconds)

  return (
    <div className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-4 text-left">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm text-paper-100">{labels[stages[index].key] ?? stages[index].key}</span>
        <span className="font-mono text-xs text-paper-300/50">{elapsedSeconds.toFixed(0)}s</span>
      </div>

      <div className="mb-3 h-1 overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full rounded-full bg-glow transition-[width] duration-300 ease-out"
          style={{
            width: `${((index + fraction) / stages.length) * 100}%`,
          }}
        />
      </div>

      <ul className="space-y-1.5">
        {stages.map((stage, position) => {
          const done = position < index
          const current = position === index
          return (
            <li
              key={stage.key}
              className={`flex items-center gap-2 text-xs transition-colors ${
                done ? 'text-paper-300/50' : current ? 'text-paper-100' : 'text-paper-300/25'
              }`}
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                {done ? (
                  <Check size={12} className="text-glow" />
                ) : current ? (
                  <Loader2 size={12} className="animate-spin text-glow" />
                ) : (
                  <span className="h-1 w-1 rounded-full bg-current" />
                )}
              </span>
              {labels[stage.key] ?? stage.key}
            </li>
          )
        })}
      </ul>

      <p className="mt-3 text-[10px] text-paper-300/30">
        Stage timings are indicative, not measured.
      </p>
    </div>
  )
}
