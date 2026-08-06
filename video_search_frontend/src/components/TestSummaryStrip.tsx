import type { TestSummary } from '../lib/testResults'

export function TestSummaryStrip({ summary }: { summary: TestSummary }) {
  return (
    <div className="liquid-glass inline-flex flex-wrap items-center gap-3 rounded-full px-5 py-2.5 text-sm">
      <span className="text-emerald-300">{summary.pass} passed</span>
      <span className="text-paper-300/25">·</span>
      <span className="text-amber-300">
        {summary.warning} warning{summary.warning === 1 ? '' : 's'}
      </span>
      <span className="text-paper-300/25">·</span>
      <span className="text-red-300">{summary.fail} failed</span>
    </div>
  )
}
