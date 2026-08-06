import { useEffect, useState } from 'react'

// Developer-facing runtime settings, kept in localStorage so a choice made on
// /developer still applies after a reload, and broadcast so any mounted page
// picks up the change immediately.
//
// API keys entered here are held in sessionStorage rather than localStorage, so
// they are dropped when the tab closes instead of persisting on disk.

export interface ModelChoice {
  id: string
  label: string
  provider: 'gemini' | 'openai'
}

export const QUERY_MODELS: readonly ModelChoice[] = [
  { id: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash-Lite', provider: 'gemini' },
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite', provider: 'gemini' },
]

export const INDEX_MODELS: readonly ModelChoice[] = [
  { id: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash-Lite', provider: 'gemini' },
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite', provider: 'gemini' },
  { id: 'gpt-4.1-mini', label: 'OpenAI GPT-4.1 mini', provider: 'openai' },
  { id: 'gpt-5-mini', label: 'OpenAI GPT-5 mini', provider: 'openai' },
]

export type ModelId = string

export const DEFAULT_MODEL = 'gemini-3.1-flash-lite'
export const DEFAULT_INDEX_MODEL = 'gemini-3.1-flash-lite'

export function providerOf(id: string, options: readonly ModelChoice[]): string {
  return options.find((option) => option.id === id)?.provider ?? 'gemini'
}

const CHANGE_EVENT = 'footageask:settings-change'

function broadcast() {
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT))
}

function readLocal(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) || fallback
  } catch {
    return fallback
  }
}

function writeLocal(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Best effort; the broadcast below still updates mounted pages.
  }
  broadcast()
}

/** Shared subscription so every hook below reacts to the same change event. */
function useStoredValue(read: () => string, write: (value: string) => void) {
  const [value, setValue] = useState('')

  useEffect(() => {
    setValue(read())
    const sync = () => setValue(read())
    window.addEventListener(CHANGE_EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync)
      window.removeEventListener('storage', sync)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return [value, write] as const
}

const MODEL_KEY = 'footageask.model'
const INDEX_MODEL_KEY = 'footageask.indexModel'
const LANGUAGE_KEY = 'footageask.language'

export function getModel(): string {
  return readLocal(MODEL_KEY, DEFAULT_MODEL)
}

export function setModel(model: string): void {
  writeLocal(MODEL_KEY, model)
}

export function useModel() {
  return useStoredValue(getModel, setModel)
}

export function getIndexModel(): string {
  return readLocal(INDEX_MODEL_KEY, DEFAULT_INDEX_MODEL)
}

export function setIndexModel(model: string): void {
  writeLocal(INDEX_MODEL_KEY, model)
}

export function useIndexModel() {
  return useStoredValue(getIndexModel, setIndexModel)
}

export function getLanguage(): string {
  return readLocal(LANGUAGE_KEY, 'english')
}

export function setLanguage(language: string): void {
  writeLocal(LANGUAGE_KEY, language)
}

export function useLanguage() {
  return useStoredValue(getLanguage, setLanguage)
}

// Keys live in sessionStorage: cleared when the tab closes, never on disk.
export function getApiKey(provider: string): string {
  try {
    return window.sessionStorage.getItem(`footageask.key.${provider}`) || ''
  } catch {
    return ''
  }
}

export function setApiKey(provider: string, key: string): void {
  try {
    if (key) window.sessionStorage.setItem(`footageask.key.${provider}`, key)
    else window.sessionStorage.removeItem(`footageask.key.${provider}`)
  } catch {
    // Best effort.
  }
  broadcast()
}

export function useApiKey(provider: string) {
  const [value, setValue] = useState('')

  useEffect(() => {
    setValue(getApiKey(provider))
    const sync = () => setValue(getApiKey(provider))
    window.addEventListener(CHANGE_EVENT, sync)
    return () => window.removeEventListener(CHANGE_EVENT, sync)
  }, [provider])

  return [value, (key: string) => setApiKey(provider, key)] as const
}

/** The key to send for whichever model is selected, if the user supplied one. */
export function keyForModel(id: string, options: readonly ModelChoice[]): string {
  return getApiKey(providerOf(id, options))
}

const DEPLOYMENT_KEY = 'footageask.deployment'
const QDRANT_KEY = 'footageask.qdrantTarget'

export function getDeployment(): string {
  return readLocal(DEPLOYMENT_KEY, 'api-based')
}

export function setDeployment(value: string): void {
  writeLocal(DEPLOYMENT_KEY, value)
}

export function useDeployment() {
  return useStoredValue(getDeployment, setDeployment)
}

export function getQdrantTarget(): string {
  return readLocal(QDRANT_KEY, 'local')
}

export function setQdrantTarget(value: string): void {
  writeLocal(QDRANT_KEY, value)
}

export function useQdrantTarget() {
  return useStoredValue(getQdrantTarget, setQdrantTarget)
}

// Connector credentials. sessionStorage, same as model keys: present for the
// tab, gone when it closes, never on disk.
export function getConnectorField(key: string): string {
  try {
    return window.sessionStorage.getItem(`footageask.conn.${key}`) || ''
  } catch {
    return ''
  }
}

export function setConnectorField(key: string, value: string): void {
  try {
    if (value) window.sessionStorage.setItem(`footageask.conn.${key}`, value)
    else window.sessionStorage.removeItem(`footageask.conn.${key}`)
  } catch {
    // Best effort.
  }
  broadcast()
}

export function useConnectorField(key: string) {
  const [value, setValue] = useState('')

  useEffect(() => {
    setValue(getConnectorField(key))
    const sync = () => setValue(getConnectorField(key))
    window.addEventListener(CHANGE_EVENT, sync)
    return () => window.removeEventListener(CHANGE_EVENT, sync)
  }, [key])

  return [value, (next: string) => setConnectorField(key, next)] as const
}
