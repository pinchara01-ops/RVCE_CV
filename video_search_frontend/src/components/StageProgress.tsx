interface StageProgressProps {
  active: boolean
  label: string
  progress: number // 0..1
}

/**
 * Continuous progress bar shown while a query is in flight, sized by its
 * parent (used directly under the hero search bar). The fill tracks
 * estimated stage progress (see lib/pipeline.ts) and is paired with the
 * current stage's label so the wait reads as work happening, not a frozen
 * spinner. Renders nothing once the turn resolves.
 */
export function StageProgress({ active, label, progress }: StageProgressProps) {
  if (!active) return null

  return (
    <div className="liquid-glass flex items-center gap-4 rounded-full px-5 py-2.5">
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-glow transition-[width] duration-300 ease-out"
          style={{ width: `${Math.max(6, progress * 100)}%` }}
        />
        <div
          className="absolute inset-0 rounded-full bg-gradient-to-r from-transparent via-white/30 to-transparent animate-shimmer"
          style={{ backgroundSize: '200% 100%' }}
        />
      </div>
      <span className="shrink-0 whitespace-nowrap font-mono text-xs text-paper-300/70">{label}</span>
    </div>
  )
}
