type SafeEventProperties = Record<string, string | number | boolean | undefined>

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

export function track(name: string, properties: SafeEventProperties = {}): void {
  const safe = Object.fromEntries(
    Object.entries({ ...attribution(), ...properties }).filter(
      ([key, value]) => ALLOWED_PROPERTIES.has(key) && value !== undefined,
    ),
  )
  window.dispatchEvent(new CustomEvent('aperture:analytics', { detail: { name, properties: safe } }))
  const endpoint = import.meta.env.VITE_ANALYTICS_ENDPOINT as string | undefined
  if (endpoint && navigator.sendBeacon) {
    navigator.sendBeacon(endpoint, JSON.stringify({ name, properties: safe }))
  }
}
