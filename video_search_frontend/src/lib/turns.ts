import type { SearchResponse } from './api'

export interface Turn {
  id: string
  query: string
  status: 'loading' | 'done' | 'error'
  response: SearchResponse | null
  error: string | null
  startedAt: number
  finishedAt: number | null
}
