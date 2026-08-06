import { Film, Play } from 'lucide-react'
import type { TestResult } from '../lib/testResults'

export function TestDetailPanel({ result }: { result: TestResult }) {
  const [clipName, timeRange] = result.sampleClip?.split(' · ') ?? []

  return (
    <div className="grid grid-cols-1 gap-6 p-5 md:grid-cols-[14rem_1fr]">
      <div>
        {result.sampleClip ? (
          <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-ink-800">
            <div className="flex h-full w-full items-center justify-center text-paper-300/25">
              <Film size={28} />
            </div>
            <button
              type="button"
              aria-label="Play sample clip"
              className="absolute inset-0 flex items-center justify-center bg-black/20 transition-colors hover:bg-black/35"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-black">
                <Play size={17} fill="currentColor" />
              </span>
            </button>
            <div className="absolute inset-x-0 bottom-0 bg-black/60 px-2 py-1">
              <p className="truncate text-xs text-paper-100">{clipName}</p>
              <p className="font-mono text-[10px] text-paper-300/60">{timeRange}</p>
            </div>
          </div>
        ) : (
          <div className="flex aspect-video w-full items-center justify-center rounded-xl border border-dashed border-white/10 bg-ink-800/50 px-3 text-center text-xs text-paper-300/40">
            No sample clip, not a retrieval case
          </div>
        )}
      </div>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-[6rem_1fr]">
        {result.query && (
          <>
            <dt className="text-paper-300/40">Query</dt>
            <dd className="text-paper-100">{result.query}</dd>
          </>
        )}
        <dt className="text-paper-300/40">Expected</dt>
        <dd className="text-paper-300/80">{result.expected}</dd>
        <dt className="text-paper-300/40">Actual</dt>
        <dd className="text-paper-300/80">{result.actual}</dd>
        <dt className="text-paper-300/40">Test ID</dt>
        <dd className="font-mono text-xs text-paper-300/50">{result.id}</dd>
      </dl>
    </div>
  )
}
