import { useState } from 'react'
import { CheckCircle2, CircleDashed, CircleSlash, XCircle } from 'lucide-react'
import { PageShell } from '../components/PageShell'
import {
  ACCEPTANCE_CASES,
  ATP_META,
  DEPENDENCIES,
  DESIGN_SECTIONS,
  statusLabel,
  type TestStatus,
} from '../lib/acceptance'

type Tab = 'design' | 'atp' | 'atc' | 'deps'

const TABS: { id: Tab; label: string; weight: string }[] = [
  { id: 'design', label: 'Detailed design', weight: '30%' },
  { id: 'atp', label: 'Acceptance test plan', weight: '20%' },
  { id: 'atc', label: 'Acceptance test cases', weight: '20%' },
  { id: 'deps', label: 'Third-party libraries', weight: '10%' },
]

function StatusPill({ status }: { status: TestStatus }) {
  const styles: Record<TestStatus, string> = {
    pass: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
    fail: 'border-red-400/30 bg-red-400/10 text-red-200',
    blocked: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
    'not-executed': 'border-white/15 bg-white/5 text-paper-300/60',
  }
  const Icon =
    status === 'pass'
      ? CheckCircle2
      : status === 'fail'
        ? XCircle
        : status === 'blocked'
          ? CircleSlash
          : CircleDashed
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] ${styles[status]}`}
    >
      <Icon size={10} />
      {statusLabel(status)}
    </span>
  )
}

export function Design() {
  const [tab, setTab] = useState<Tab>('design')

  const counts = ACCEPTANCE_CASES.reduce<Record<string, number>>((acc, item) => {
    acc[item.status] = (acc[item.status] ?? 0) + 1
    return acc
  }, {})

  return (
    <PageShell heroHeight="45vh">
      <div className="mx-auto w-full max-w-4xl px-6 pb-24 pt-8">
        <h1
          className="text-5xl leading-tight tracking-tight text-white md:text-6xl"
          style={{ fontFamily: "'Instrument Serif', serif" }}
        >
          Design and <span className="italic text-glow">verification</span>
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/70">
          {ATP_META.system}. Design record, acceptance test plan, and executed test cases.
        </p>

        <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ['Cases', String(ACCEPTANCE_CASES.length)],
            ['Passed', String(counts.pass ?? 0)],
            ['Not executed', String(counts['not-executed'] ?? 0)],
            ['Blocked', String(counts.blocked ?? 0)],
          ].map(([label, value]) => (
            <div
              key={label}
              className="liquid-glass rounded-xl border border-white/10 bg-ink-900/70 p-3"
            >
              <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                {label}
              </p>
              <p className="mt-0.5 text-xl text-paper-100">{value}</p>
            </div>
          ))}
        </div>

        <div className="mt-8 flex flex-wrap gap-2">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`rounded-xl border px-3.5 py-2 text-sm transition-colors ${
                tab === item.id
                  ? 'border-glow bg-glow/10 text-paper-100'
                  : 'border-white/10 bg-ink-800/60 text-paper-300/70 hover:border-white/25'
              }`}
            >
              {item.label}
              <span className="ml-2 font-mono text-[10px] text-paper-300/40">{item.weight}</span>
            </button>
          ))}
        </div>

        {tab === 'design' && (
          <div className="mt-6 space-y-4">
            {DESIGN_SECTIONS.map((section, index) => (
              <section
                key={section.id}
                className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5"
              >
                <div className="flex items-baseline gap-3">
                  <span className="font-mono text-xs text-glow">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <h2 className="text-lg text-paper-100">{section.title}</h2>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-paper-300/75">{section.body}</p>
                {section.points && (
                  <ul className="mt-3 space-y-1.5">
                    {section.points.map((point) => (
                      <li
                        key={point}
                        className="flex gap-2 font-mono text-[11px] leading-relaxed text-paper-300/50"
                      >
                        <span className="text-glow">·</span>
                        {point}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        )}

        {tab === 'atp' && (
          <div className="mt-6 space-y-4">
            <section className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg text-paper-100">{ATP_META.document}</h2>
                <span className="font-mono text-[10px] text-paper-300/40">
                  v{ATP_META.version}
                </span>
              </div>
              <dl className="mt-4 space-y-3">
                {[
                  ['Scope', ATP_META.scope],
                  ['Strategy', ATP_META.strategy],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                      {label}
                    </dt>
                    <dd className="mt-1 text-sm leading-relaxed text-paper-300/75">{value}</dd>
                  </div>
                ))}
              </dl>
            </section>

            <div className="grid gap-4 sm:grid-cols-2">
              {[
                ['Entry criteria', ATP_META.entryCriteria],
                ['Exit criteria', ATP_META.exitCriteria],
              ].map(([label, items]) => (
                <section
                  key={label as string}
                  className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5"
                >
                  <p className="text-sm font-medium text-paper-100">{label as string}</p>
                  <ul className="mt-3 space-y-1.5">
                    {(items as string[]).map((item) => (
                      <li key={item} className="flex gap-2 text-xs leading-relaxed text-paper-300/65">
                        <span className="text-glow">·</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>

            <section className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5">
              <p className="text-sm font-medium text-paper-100">Test environment</p>
              <dl className="mt-3 space-y-1.5">
                {ATP_META.environment.map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3 text-[11px]">
                    <dt className="text-paper-300/50">{label}</dt>
                    <dd className="text-right font-mono text-paper-300/75">{value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          </div>
        )}

        {tab === 'atc' && (
          <div className="mt-6 space-y-3">
            <p className="text-xs leading-relaxed text-paper-300/50">
              Status is recorded as observed. A case reads Pass only where it was executed and its
              evidence seen; anything unrun says so.
            </p>
            {ACCEPTANCE_CASES.map((test) => (
              <article
                key={test.id}
                className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="font-mono text-xs text-glow">{test.id}</span>
                      <h2 className="text-sm text-paper-100">{test.title}</h2>
                    </div>
                    <p className="mt-1 font-mono text-[10px] text-paper-300/40">
                      {test.requirement}
                    </p>
                  </div>
                  <StatusPill status={test.status} />
                </div>

                <dl className="mt-4 space-y-2.5">
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                      Precondition
                    </dt>
                    <dd className="mt-0.5 text-xs text-paper-300/70">{test.precondition}</dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                      Steps
                    </dt>
                    <dd className="mt-0.5">
                      <ol className="space-y-0.5">
                        {test.steps.map((step, index) => (
                          <li key={step} className="flex gap-2 text-xs text-paper-300/70">
                            <span className="font-mono text-paper-300/35">{index + 1}.</span>
                            {step}
                          </li>
                        ))}
                      </ol>
                    </dd>
                  </div>
                  <div className="grid gap-2.5 sm:grid-cols-2">
                    <div>
                      <dt className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                        Expected
                      </dt>
                      <dd className="mt-0.5 text-xs leading-relaxed text-paper-300/70">
                        {test.expected}
                      </dd>
                    </div>
                    <div>
                      <dt className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                        Actual
                      </dt>
                      <dd
                        className={`mt-0.5 text-xs leading-relaxed ${
                          test.status === 'pass' ? 'text-paper-300/70' : 'text-amber-200/60'
                        }`}
                      >
                        {test.actual}
                      </dd>
                    </div>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        )}

        {tab === 'deps' && (
          <div className="mt-6 liquid-glass overflow-hidden rounded-2xl border border-white/10 bg-ink-900/70">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[42rem] text-left text-xs">
                <thead>
                  <tr className="border-b border-white/10">
                    {['Library', 'Role', 'Licence', 'Cost', 'Dependency risk'].map((head) => (
                      <th
                        key={head}
                        className="px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-paper-300/40"
                      >
                        {head}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {DEPENDENCIES.map((dep) => (
                    <tr key={dep.name} className="border-b border-white/5 last:border-0">
                      <td className="px-4 py-3 text-paper-100">{dep.name}</td>
                      <td className="px-4 py-3 text-paper-300/65">{dep.role}</td>
                      <td className="px-4 py-3 font-mono text-[10px] text-paper-300/55">
                        {dep.licence}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
                            dep.cost.startsWith('Free')
                              ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-200/80'
                              : 'border-amber-400/25 bg-amber-400/10 text-amber-200/80'
                          }`}
                        >
                          {dep.cost}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-paper-300/55">{dep.risk}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </PageShell>
  )
}
