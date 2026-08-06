interface LinearProgressProps {
  percent: number // 0..100
  tone?: 'default' | 'error'
}

/** Same visual language as the search flow's progress bar, but determinate. */
export function LinearProgress({ percent, tone = 'default' }: LinearProgressProps) {
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
      <div
        className={`absolute inset-y-0 left-0 rounded-full transition-[width] duration-300 ease-out ${
          tone === 'error' ? 'bg-red-400/70' : 'bg-glow'
        }`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  )
}
