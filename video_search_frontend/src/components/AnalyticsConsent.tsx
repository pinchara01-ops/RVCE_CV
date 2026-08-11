import { useEffect, useState } from 'react'
import {
  analyticsConsent,
  setAnalyticsConsent,
  trackPageView,
  type AnalyticsConsent as Consent,
} from '../lib/analytics'

export function AnalyticsConsent({ pathname }: { pathname: string }) {
  const [consent, setConsent] = useState<Consent>(() => analyticsConsent())
  const [editing, setEditing] = useState(consent === null)

  useEffect(() => {
    if (consent === 'accepted') trackPageView(pathname)
  }, [consent, pathname])

  const choose = (value: Exclude<Consent, null>) => {
    setAnalyticsConsent(value)
    setConsent(value)
    setEditing(false)
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="fixed bottom-3 left-3 z-50 rounded-full border border-white/10 bg-black/80 px-3 py-1.5 text-[10px] text-white/45 backdrop-blur transition hover:text-white/75"
      >
        Analytics settings
      </button>
    )
  }

  return (
    <aside
      className="fixed inset-x-3 bottom-3 z-50 mx-auto max-w-2xl rounded-2xl border border-white/15 bg-[#0b0b0b]/95 p-4 text-white backdrop-blur-xl sm:p-5"
      aria-label="Analytics preference"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium">Help improve Aperture</p>
          <p className="mt-1 max-w-lg text-xs leading-5 text-white/55">
            Allow anonymous Google Analytics measurements such as page visits, referrals, and
            feature usage. Advertising signals are disabled. You can change this choice anytime.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => choose('rejected')}
            className="rounded-full border border-white/15 px-4 py-2 text-xs text-white/70 transition hover:border-white/30 hover:text-white"
          >
            No thanks
          </button>
          <button
            type="button"
            onClick={() => choose('accepted')}
            className="rounded-full bg-glow px-4 py-2 text-xs font-semibold text-black transition hover:brightness-110"
          >
            Allow analytics
          </button>
        </div>
      </div>
    </aside>
  )
}
