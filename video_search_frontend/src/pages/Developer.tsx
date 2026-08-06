import { Check, Cloud, KeyRound, Server } from 'lucide-react'
import { PageShell } from '../components/PageShell'
import {
  INDEX_MODELS,
  QUERY_MODELS,
  providerOf,
  useApiKey,
  useDeployment,
  useIndexModel,
  useModel,
  useQdrantTarget,
  useLanguage,
  resetOnboarding,
  sessionId,
  type ModelChoice,
} from '../lib/settings'
import { stringsFor } from '../lib/i18n'

// Mirrors the runtime profiles the Qdrant-backed backend exposes, so the two
// surfaces describe the same system. Vector dimensions and stage models are
// taken from processing_indexing/runtime_profiles.py.
const PROFILES = [
  {
    id: 'api-based',
    label: 'API-based',
    blurb: 'Hosted models, nothing downloaded. Fastest to run, needs keys.',
    icon: Cloud,
    vectors: [
      { name: 'visual', dims: 1536 },
      { name: 'audio', dims: 1536 },
      { name: 'transcript', dims: 1536 },
      { name: 'caption', dims: 1536 },
    ],
    stages: [
      ['Transcription', 'Gemini Flash-Lite'],
      ['Media embedding', 'Gemini Embedding 2'],
      ['Text embedding', 'Gemini Embedding 2'],
      ['Caption', 'Gemini Flash-Lite / GPT / Cosmos'],
      ['Verification', 'Gemini Flash-Lite / GPT / Cosmos'],
      ['Reranker', 'Qwen3-VL-Reranker-2B (local, optional)'],
    ],
  },
  {
    id: 'self-hosted',
    label: 'Self-hosted',
    blurb: 'Everything on this machine. No keys, needs model downloads and a GPU.',
    icon: Server,
    vectors: [
      { name: 'visual', dims: 512 },
      { name: 'audio', dims: 512 },
      { name: 'speech', dims: 1024 },
      { name: 'caption', dims: 1024 },
    ],
    stages: [
      ['Transcription', 'faster-whisper-small'],
      ['Media embedding', 'X-CLIP + CLAP'],
      ['Text embedding', 'BAAI/bge-m3'],
      ['Caption', 'Qwen2.5-VL-3B (optional)'],
      ['Verification', 'Disabled'],
      ['Reranker', 'Qwen3-VL-Reranker-2B (optional)'],
    ],
  },
] as const

function Panel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5">
      <p className="text-sm font-medium text-paper-100">{title}</p>
      {hint && <p className="mt-1 text-xs text-paper-300/50">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function ModelList({
  options,
  value,
  onChange,
}: {
  options: readonly ModelChoice[]
  value: string
  onChange: (id: string) => void
}) {
  return (
    <div className="space-y-2">
      {options.map((option) => {
        const selected = option.id === value
        return (
          <button
            key={option.id}
            type="button"
            onClick={() => onChange(option.id)}
            className={`flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors ${
              selected
                ? 'border-glow bg-glow/10 text-paper-100'
                : 'border-white/10 bg-ink-800/60 text-paper-300/70 hover:border-white/25 hover:text-paper-100'
            }`}
          >
            <span className="min-w-0">
              <span className="block text-sm">{option.label}</span>
              <span className="block font-mono text-[10px] text-paper-300/40">{option.id}</span>
            </span>
            {selected && <Check size={16} className="shrink-0 text-glow" />}
          </button>
        )
      })}
    </div>
  )
}

function KeyField({ provider, label }: { provider: string; label: string }) {
  const [key, setKey] = useApiKey(provider)
  return (
    <label className="block">
      <span className="text-xs text-paper-300/60">{label}</span>
      <div className="mt-1.5 flex items-center gap-2 rounded-xl border border-white/10 bg-ink-800/60 px-3">
        <KeyRound size={14} className="shrink-0 text-paper-300/40" />
        <input
          type="password"
          value={key}
          onChange={(event) => setKey(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          placeholder="Leave blank to use the server's key"
          className="min-w-0 flex-1 bg-transparent py-2.5 text-sm text-paper-100 outline-none placeholder:text-paper-300/30"
        />
        {key && (
          <button
            type="button"
            onClick={() => setKey('')}
            className="shrink-0 text-[11px] text-paper-300/50 transition-colors hover:text-paper-100"
          >
            clear
          </button>
        )}
      </div>
    </label>
  )
}

export function Developer() {
  const [language] = useLanguage()
  const t = stringsFor(language)
  const [queryModel, setQueryModel] = useModel()
  const [indexModel, setIndexModel] = useIndexModel()
  const [deployment, setDeployment] = useDeployment()
  const [qdrantTarget, setQdrantTarget] = useQdrantTarget()

  const providers = Array.from(
    new Set([providerOf(queryModel, QUERY_MODELS), providerOf(indexModel, INDEX_MODELS)]),
  )
  const profile = PROFILES.find((item) => item.id === deployment) ?? PROFILES[0]

  return (
    <PageShell heroHeight="40vh">
      <div className="mx-auto w-full max-w-3xl px-6 pb-24 pt-8">
        <h1
          className="text-5xl leading-tight tracking-tight text-white md:text-6xl"
          style={{ fontFamily: "'Instrument Serif', serif" }}
        >
          {t.developerTitle}
        </h1>
        <p className="mt-4 text-base text-white/70">{t.developerSubtitle}</p>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => {
              resetOnboarding()
              window.location.reload()
            }}
            className="rounded-xl border border-white/15 px-4 py-2 text-sm text-paper-300/80 transition-colors hover:border-white/30 hover:text-paper-100"
          >
            {t.rerunSetup}
          </button>
          {/* No accounts: this id only groups a visitor's own runs. */}
          <span className="font-mono text-[10px] text-paper-300/35">session {sessionId()}</span>
        </div>

        <div className="mt-10 space-y-4">
          <Panel
            title={t.deploymentProfile}
            hint={t.deploymentProfileHint}
          >
            <div className="grid gap-2 sm:grid-cols-2">
              {PROFILES.map((item) => {
                const Icon = item.icon
                const selected = item.id === deployment
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setDeployment(item.id)}
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      selected
                        ? 'border-glow bg-glow/10'
                        : 'border-white/10 bg-ink-800/60 hover:border-white/25'
                    }`}
                  >
                    <Icon size={16} className={selected ? 'text-glow' : 'text-paper-300/60'} />
                    <p className="mt-1.5 text-sm text-paper-100">{item.label}</p>
                    <p className="mt-0.5 text-[11px] leading-tight text-paper-300/50">
                      {item.blurb}
                    </p>
                  </button>
                )
              })}
            </div>

            <div className="mt-4 rounded-xl border border-white/10 bg-ink-800/40 p-3">
              <p className="font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                {t.stageModels}
              </p>
              <dl className="mt-2 space-y-1">
                {profile.stages.map(([stage, model]) => (
                  <div key={stage} className="flex justify-between gap-3 text-[11px]">
                    <dt className="text-paper-300/50">{stage}</dt>
                    <dd className="text-right font-mono text-paper-300/75">{model}</dd>
                  </div>
                ))}
              </dl>

              <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-paper-300/40">
                {t.namedVectors}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {profile.vectors.map((vector) => (
                  <span
                    key={vector.name}
                    className="rounded-full border border-white/10 bg-ink-900/60 px-2 py-0.5 font-mono text-[10px] text-paper-300/70"
                  >
                    {vector.name} · {vector.dims}d
                  </span>
                ))}
              </div>
            </div>
          </Panel>

          <Panel
            title={t.vectorStore}
            hint={t.vectorStoreHint}
          >
            <div className="grid gap-2 sm:grid-cols-2">
              {[
                { id: 'local', label: 'Local Qdrant', detail: 'localhost:6333 via Docker' },
                { id: 'cloud', label: 'Qdrant Cloud', detail: 'Hosted cluster, needs URL + key' },
              ].map((option) => {
                const selected = option.id === qdrantTarget
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setQdrantTarget(option.id)}
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      selected
                        ? 'border-glow bg-glow/10'
                        : 'border-white/10 bg-ink-800/60 hover:border-white/25'
                    }`}
                  >
                    <p className="text-sm text-paper-100">{option.label}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-paper-300/45">
                      {option.detail}
                    </p>
                  </button>
                )
              })}
            </div>
            {qdrantTarget === 'cloud' && (
              <div className="mt-3 space-y-3">
                <KeyField provider="qdrant_url" label="Qdrant cluster URL" />
                <KeyField provider="qdrant" label="Qdrant API key" />
              </div>
            )}
          </Panel>

          <Panel title={t.queryModelLabel} hint={t.queryModelHint}>
            <ModelList options={QUERY_MODELS} value={queryModel} onChange={setQueryModel} />
            <p className="mt-3 font-mono text-[11px] text-paper-300/40">{t.activeLabel}: {queryModel}</p>
          </Panel>

          <Panel
            title={t.indexModelLabel}
            hint={t.indexModelHint}
          >
            <ModelList options={INDEX_MODELS} value={indexModel} onChange={setIndexModel} />
            <p className="mt-3 font-mono text-[11px] text-paper-300/40">{t.activeLabel}: {indexModel}</p>
          </Panel>

          <Panel
            title={t.apiKeysLabel}
            hint={t.apiKeysHint}
          >
            <div className="space-y-3">
              {providers.map((provider) => (
                <KeyField
                  key={provider}
                  provider={provider}
                  label={provider === 'openai' ? 'OpenAI API key' : 'Gemini API key'}
                />
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </PageShell>
  )
}
