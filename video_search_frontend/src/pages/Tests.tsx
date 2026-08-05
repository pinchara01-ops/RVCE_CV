import { Nav } from '../components/Nav'
import { ParticleField } from '../components/ParticleField'
import { TestSummaryStrip } from '../components/TestSummaryStrip'
import { TestsTable } from '../components/TestsTable'
import { TEST_RESULTS, summarizeTestResults } from '../lib/testResults'

export function Tests() {
  const summary = summarizeTestResults(TEST_RESULTS)

  return (
    <div className="min-h-screen bg-black text-paper-100">
      <Nav />

      <div className="relative">
        <ParticleField />

        <div className="relative z-10 mx-auto max-w-5xl px-6 py-16 md:px-10">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-glow/80">
            Quality assurance
          </p>
          <h1
            className="mt-3 text-4xl leading-tight tracking-tight text-white md:text-5xl"
            style={{ fontFamily: "'Instrument Serif', serif" }}
          >
            Edge cases, <span className="italic text-glow">verified</span>
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-white/70 md:text-base">
            13 edge cases covering multilingual queries, split leakage, malformed input, and
            retrieval failure modes — run against dummy data until live integration.
          </p>

          <div className="mt-8">
            <TestSummaryStrip summary={summary} />
          </div>

          <div className="mt-6">
            <TestsTable results={TEST_RESULTS} />
          </div>
        </div>
      </div>
    </div>
  )
}
