import { useState } from 'react'
import { ArrowRight, Check, Cloud, KeyRound, Languages, Server, Sparkles } from 'lucide-react'
import { LANGUAGE_OPTIONS } from '../lib/languages'
import { stringsFor, RTL_LANGUAGES } from '../lib/i18n'
import {
  INDEX_MODELS,
  QUERY_MODELS,
  completeOnboarding,
  providerOf,
  setApiKey,
  setDeployment,
  setIndexModel,
  setLanguage,
  setModel,
  useLanguage,
} from '../lib/settings'

type Step = 'welcome' | 'language' | 'profile' | 'models' | 'key'

const ORDER: Step[] = ['welcome', 'language', 'profile', 'models', 'key']

interface OnboardingProps {
  onDone: () => void
}

/**
 * First-run setup. There is no account system, so this exists to get a new
 * visitor to a working configuration in a few clicks rather than leaving them
 * to find the Developer page. Every choice writes to the same settings store
 * the rest of the app reads, so nothing here is a separate code path.
 */
export function Onboarding({ onDone }: OnboardingProps) {
  const [language, setLocalLanguage] = useLanguage()
  const t = stringsFor(language)
  const rtl = RTL_LANGUAGES.has(language)

  const [step, setStep] = useState<Step>('welcome')
  const [profile, setProfile] = useState('api-based')
  const [queryModel, setQueryModel] = useState(QUERY_MODELS[0].id)
  const [indexModel, setIndexModelLocal] = useState(INDEX_MODELS[0].id)
  const [key, setKey] = useState('')

  const position = ORDER.indexOf(step)

  const finish = () => {
    setDeployment(profile)
    setModel(queryModel)
    setIndexModel(indexModel)
    if (key.trim()) {
      setApiKey(providerOf(queryModel, QUERY_MODELS), key.trim())
      setApiKey(providerOf(indexModel, INDEX_MODELS), key.trim())
    }
    completeOnboarding()
    onDone()
  }

  const skip = () => {
    completeOnboarding()
    onDone()
  }

  const next = () => {
    const following = ORDER[position + 1]
    if (following) setStep(following)
    else finish()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-6 backdrop-blur-sm"
      dir={rtl ? 'rtl' : 'ltr'}
    >
      <div className="liquid-glass w-full max-w-lg rounded-2xl border border-white/10 bg-ink-900/90 p-6">
        <div className="mb-5 flex items-center gap-1.5">
          {ORDER.map((item, index) => (
            <span
              key={item}
              className={`h-0.5 flex-1 rounded-full transition-colors ${
                index <= position ? 'bg-glow' : 'bg-white/10'
              }`}
            />
          ))}
        </div>

        {step === 'welcome' && (
          <div>
            <Sparkles size={22} className="text-glow" />
            <h2
              className="mt-3 text-3xl leading-tight text-white"
              style={{ fontFamily: "'Instrument Serif', serif" }}
            >
              {t.onboardWelcomeTitle}
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-paper-300/70">
              {t.onboardWelcomeBody}
            </p>
          </div>
        )}

        {step === 'language' && (
          <div>
            <Languages size={20} className="text-glow" />
            <h2 className="mt-3 text-lg text-paper-100">{t.onboardLanguageTitle}</h2>
            <p className="mt-1 text-xs text-paper-300/50">{t.onboardLanguageBody}</p>
            <div className="mt-4 grid max-h-56 grid-cols-2 gap-1.5 overflow-y-auto sm:grid-cols-3">
              {LANGUAGE_OPTIONS.map((option) => (
                <button
                  key={option.code}
                  type="button"
                  onClick={() => {
                    setLanguage(option.code)
                    setLocalLanguage(option.code)
                  }}
                  className={`rounded-lg border px-2.5 py-2 text-xs transition-colors ${
                    option.code === language
                      ? 'border-glow bg-glow/10 text-paper-100'
                      : 'border-white/10 bg-ink-800/60 text-paper-300/70 hover:border-white/25'
                  }`}
                >
                  {stringsFor(option.code).nativeName}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 'profile' && (
          <div>
            <Cloud size={20} className="text-glow" />
            <h2 className="mt-3 text-lg text-paper-100">{t.onboardProfileTitle}</h2>
            <p className="mt-1 text-xs text-paper-300/50">{t.onboardProfileBody}</p>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {[
                { id: 'api-based', label: 'API-based', hint: t.onboardApiHint, icon: Cloud },
                { id: 'self-hosted', label: 'Self-hosted', hint: t.onboardLocalHint, icon: Server },
              ].map((option) => {
                const Icon = option.icon
                const selected = option.id === profile
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setProfile(option.id)}
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      selected
                        ? 'border-glow bg-glow/10'
                        : 'border-white/10 bg-ink-800/60 hover:border-white/25'
                    }`}
                  >
                    <Icon size={15} className={selected ? 'text-glow' : 'text-paper-300/60'} />
                    <p className="mt-1.5 text-sm text-paper-100">{option.label}</p>
                    <p className="mt-0.5 text-[11px] leading-tight text-paper-300/50">
                      {option.hint}
                    </p>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {step === 'models' && (
          <div>
            <Check size={20} className="text-glow" />
            <h2 className="mt-3 text-lg text-paper-100">{t.onboardModelTitle}</h2>
            <p className="mt-1 text-xs text-paper-300/50">{t.onboardModelBody}</p>

            <p className="mt-4 text-[11px] uppercase tracking-wider text-paper-300/40">
              {t.queryModelLabel}
            </p>
            <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
              {QUERY_MODELS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setQueryModel(option.id)}
                  className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    option.id === queryModel
                      ? 'border-glow bg-glow/10 text-paper-100'
                      : 'border-white/10 bg-ink-800/60 text-paper-300/70 hover:border-white/25'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>

            <p className="mt-3 text-[11px] uppercase tracking-wider text-paper-300/40">
              {t.indexModelLabel}
            </p>
            <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
              {INDEX_MODELS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setIndexModelLocal(option.id)}
                  className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    option.id === indexModel
                      ? 'border-glow bg-glow/10 text-paper-100'
                      : 'border-white/10 bg-ink-800/60 text-paper-300/70 hover:border-white/25'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 'key' && (
          <div>
            <KeyRound size={20} className="text-glow" />
            <h2 className="mt-3 text-lg text-paper-100">{t.onboardKeyTitle}</h2>
            <p className="mt-1 text-xs text-paper-300/50">{t.onboardKeyBody}</p>
            <input
              type="password"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder={t.onboardKeyPlaceholder}
              className="mt-4 w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2.5 text-sm text-paper-100 outline-none placeholder:text-paper-300/30"
            />
            <p className="mt-2 text-[10px] leading-relaxed text-paper-300/40">
              {t.onboardKeyNote}
            </p>
          </div>
        )}

        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={skip}
            className="text-xs text-paper-300/45 underline-offset-4 transition-colors hover:text-paper-100 hover:underline"
          >
            {t.onboardSkip}
          </button>
          <button
            type="button"
            onClick={next}
            className="flex items-center gap-2 rounded-xl bg-glow px-5 py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
          >
            {position === ORDER.length - 1 ? t.onboardFinish : t.onboardNext}
            <ArrowRight size={15} className={rtl ? 'rotate-180' : undefined} />
          </button>
        </div>
      </div>
    </div>
  )
}
