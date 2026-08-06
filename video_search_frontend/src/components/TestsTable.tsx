import { Fragment, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import type { TestResult } from '../lib/testResults'
import { CategoryBadge } from './CategoryBadge'
import { TestStatusBadge } from './TestStatusBadge'
import { TestDetailPanel } from './TestDetailPanel'

export function TestsTable({ results }: { results: TestResult[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <div
      className="liquid-glass overflow-hidden rounded-2xl"
      style={{ backgroundColor: 'rgba(20,19,15,0.97)' }}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-ink-700 text-xs uppercase tracking-wide text-paper-300/40">
              <th className="w-8 px-5 py-3" />
              <th className="px-5 py-3 font-medium">Test</th>
              <th className="px-5 py-3 font-medium">Category</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Checks</th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => {
              const isOpen = expandedId === result.id
              return (
                <Fragment key={result.id}>
                  <tr
                    onClick={() => setExpandedId(isOpen ? null : result.id)}
                    className="cursor-pointer border-b border-ink-700/60 last:border-0 hover:bg-white/[0.02]"
                  >
                    <td className="px-5 py-3 align-top">
                      <ChevronDown
                        size={15}
                        className={`text-paper-300/40 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                      />
                    </td>
                    <td className="px-5 py-3 align-top text-paper-100">{result.name}</td>
                    <td className="px-5 py-3 align-top">
                      <CategoryBadge label={result.category} />
                    </td>
                    <td className="px-5 py-3 align-top">
                      <TestStatusBadge status={result.status} />
                    </td>
                    <td className="px-5 py-3 align-top text-paper-300/60">{result.description}</td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-ink-700/60 bg-black/20 last:border-0">
                      <td colSpan={5}>
                        <TestDetailPanel result={result} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
