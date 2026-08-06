import type { ModalityStatus, Stage } from '../lib/pipeline'
import { Check, Circle, Loader2 } from 'lucide-react'

function StatusIcon({ status }: { status: Stage['status'] }) {
  if (status === 'done') return <Check size={16} className="text-glow" />
  if (status === 'active') return <Loader2 size={16} className="animate-spin text-glow" />
  if (status === 'skipped') return <Circle size={14} className="text-paper-300/25" />
  return <Circle size={14} className="text-paper-300/25" />
}

function StageRow({ stage, isLast }: { stage: Stage; isLast: boolean }) {
  return (
    <li className="relative flex gap-4 pb-8 last:pb-0">
      {!isLast && (
        <span
          className={`absolute left-[9px] top-6 h-full w-px ${
            stage.status === 'done' ? 'bg-glow/40' : 'bg-ink-600'
          }`}
        />
      )}
      <span className="relative z-10 mt-0.5 flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full bg-ink-900">
        {stage.status === 'active' ? (
          <span className="absolute inline-flex h-full w-full animate-pulse-soft rounded-full bg-glow/20" />
        ) : null}
        <StatusIcon status={stage.status} />
      </span>
      <div className="flex min-w-0 flex-1 items-baseline justify-between gap-3">
        <span
          className={`text-sm ${
            stage.status === 'pending' ? 'text-paper-300/40' : 'text-paper-100'
          }`}
        >
          {stage.label}
        </span>
        <span className="shrink-0 font-mono text-xs text-paper-300/40">
          {stage.status === 'pending'
            ? ''
            : stage.status === 'skipped'
              ? 'skipped'
              : stage.durationMs != null
                ? `${stage.durationMs.toFixed(0)}ms${stage.isReal ? '' : '*'}`
                : ''}
        </span>
      </div>
    </li>
  )
}

interface PipelineTabProps {
  stages: Stage[] | null
  modalities: ModalityStatus[]
  hasMockedTiming: boolean
}

export function PipelineTab({ stages, modalities, hasMockedTiming }: PipelineTabProps) {
  if (!stages) {
    return (
      <div className="flex h-full items-center justify-center px-6 py-16 text-center text-sm text-paper-300/40">
        Run a query to see the retrieval pipeline stage by stage.
      </div>
    )
  }

  return (
    <div className="px-6 py-6">
      <ol>
        {stages.map((stage, i) => (
          <StageRow key={stage.key} stage={stage} isLast={i === stages.length - 1} />
        ))}
      </ol>

      <div className="mt-2 border-t border-ink-700 pt-5">
        <p className="mb-3 text-xs uppercase tracking-wide text-paper-300/40">
          Modalities that returned candidates
        </p>
        <div className="flex flex-wrap gap-2">
          {modalities.length === 0 && (
            <span className="text-sm text-paper-300/40">none reported</span>
          )}
          {modalities.map((m) => (
            <span
              key={m.name}
              className="liquid-glass rounded-full px-3 py-1 text-xs capitalize text-paper-100"
            >
              {m.name}
            </span>
          ))}
        </div>
      </div>

      {hasMockedTiming && (
        <p className="mt-5 text-xs text-paper-300/35">
          * This backend response has no per-stage timing, so stage durations above are
          estimated client-side from total response time, not measured.
        </p>
      )}
    </div>
  )
}
