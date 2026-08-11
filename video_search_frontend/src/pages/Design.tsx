import { useState } from 'react'
import { PageShell } from '../components/PageShell'
import { DEPENDENCIES, DESIGN_SECTIONS } from '../lib/acceptance'

type Tab = 'design' | 'deps'

const TABS: { id: Tab; label: string }[] = [
  { id: 'design', label: 'System design' },
  { id: 'deps', label: 'Technology' },
]

export function Design() {
  const [tab, setTab] = useState<Tab>('design')

  return (
    <PageShell heroHeight="45vh">
      <div className="mx-auto w-full max-w-4xl px-6 pb-24 pt-8">
        <h1
          className="text-5xl leading-tight tracking-tight text-white md:text-6xl"
          style={{ fontFamily: "'Instrument Serif', serif" }}
        >
          Designed for <span className="italic text-glow">real footage</span>
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/70">
          How Aperture turns multimodal video into searchable, timestamped moments.
        </p>

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

        {tab === 'deps' && (
          <div className="mt-6 liquid-glass overflow-hidden rounded-2xl border border-white/10 bg-ink-900/70">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[42rem] text-left text-xs">
                <thead>
                  <tr className="border-b border-white/10">
                    {['Technology', 'Role', 'Licence', 'Cost', 'Operational note'].map((head) => (
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
                      <td className="px-4 py-3 text-paper-300/65">{dep.cost}</td>
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
