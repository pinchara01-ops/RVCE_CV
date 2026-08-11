type SafeEventProperties = Record<string, string | number | boolean | undefined>
export type AnalyticsConsent = 'accepted' | 'rejected' | null

declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
    __apertureGaLoaded?: boolean
  }
}

const CONSENT_KEY = 'aperture.analytics.consent'
const MEASUREMENT_ID = (import.meta.env.VITE_GA_MEASUREMENT_ID as string | undefined)?.trim()

const ALLOWED_PROPERTIES = new Set([
  'utm_source', 'utm_medium', 'utm_campaign', 'referrer_category', 'sample_id',
  'modality', 'language', 'outcome', 'duration_bucket',
])

function attribution(): SafeEventProperties {
  const params = new URLSearchParams(window.location.search)
  const current = {
    utm_source: params.get('utm_source') ?? undefined,
    utm_medium: params.get('utm_medium') ?? undefined,
    utm_campaign: params.get('utm_campaign') ?? undefined,
    referrer_category: document.referrer ? new URL(document.referrer).hostname : 'direct',
  }
  const key = 'aperture.launch.attribution'
  try {
    const saved = window.sessionStorage.getItem(key)
    if (saved) return JSON.parse(saved) as SafeEventProperties
    window.sessionStorage.setItem(key, JSON.stringify(current))
  } catch {
    // Attribution is best-effort and never required for product behavior.
  }
  return current
}

function gtag(...args: unknown[]): void {
  window.dataLayer = window.dataLayer ?? []
  window.dataLayer.push(args)
}

export function analyticsConsent(): AnalyticsConsent {
  try {
    const value = window.localStorage.getItem(CONSENT_KEY)
    return value === 'accepted' || value === 'rejected' ? value : null
  } catch {
    return null
  }
}

export function initializeGoogleAnalytics(): void {
  if (!MEASUREMENT_ID || analyticsConsent() !== 'accepted') return

  window.gtag = gtag
  gtag('consent', 'default', {
    analytics_storage: 'denied',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
  })
  gtag('consent', 'update', { analytics_storage: 'granted' })

  if (!window.__apertureGaLoaded) {
    const script = document.createElement('script')
    script.async = true
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(MEASUREMENT_ID)}`
    document.head.appendChild(script)
    window.__apertureGaLoaded = true
    gtag('js', new Date())
    gtag('config', MEASUREMENT_ID, {
      send_page_view: false,
      anonymize_ip: true,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
    })
  }
}

export function setAnalyticsConsent(consent: Exclude<AnalyticsConsent, null>): void {
  try {
    window.localStorage.setItem(CONSENT_KEY, consent)
  } catch {
    // Consent remains session-only if storage is unavailable.
  }

  if (consent === 'accepted') {
    initializeGoogleAnalytics()
  } else if (window.gtag) {
    window.gtag('consent', 'update', { analytics_storage: 'denied' })
  }
}

export function trackPageView(pathname: string): void {
  if (!MEASUREMENT_ID || analyticsConsent() !== 'accepted') return
  initializeGoogleAnalytics()
  window.gtag?.('event', 'page_view', {
    page_path: pathname,
    page_location: window.location.href,
    page_title: document.title,
  })
}

export function track(name: string, properties: SafeEventProperties = {}): void {
  const safe = Object.fromEntries(
    Object.entries({ ...attribution(), ...properties }).filter(
      ([key, value]) => ALLOWED_PROPERTIES.has(key) && value !== undefined,
    ),
  )
  window.dispatchEvent(new CustomEvent('aperture:analytics', { detail: { name, properties: safe } }))
  if (MEASUREMENT_ID && analyticsConsent() === 'accepted') {
    initializeGoogleAnalytics()
    window.gtag?.('event', name, safe)
  }
  const endpoint = import.meta.env.VITE_ANALYTICS_ENDPOINT as string | undefined
  if (endpoint && navigator.sendBeacon) {
    navigator.sendBeacon(endpoint, JSON.stringify({ name, properties: safe }))
  }
}
