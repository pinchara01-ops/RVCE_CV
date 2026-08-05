import type { TestStatus } from '../lib/testResults'

const STATUS_STYLES: Record<TestStatus, string> = {
  pass: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
  warning: 'border-amber-400/25 bg-amber-400/10 text-amber-300',
  fail: 'border-red-400/25 bg-red-400/10 text-red-300',
}

const STATUS_LABEL: Record<TestStatus, string> = {
  pass: 'Pass',
  warning: 'Warning',
  fail: 'Fail',
}

export function TestStatusBadge({ status }: { status: TestStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
      {STATUS_LABEL[status]}
    </span>
  )
}
