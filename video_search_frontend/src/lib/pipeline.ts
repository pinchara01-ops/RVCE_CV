import type { SearchResponse } from './api'

export type StageStatus = 'pending' | 'active' | 'done' | 'skipped'

export interface Stage {
  key: string
  label: string
  status: StageStatus
  durationMs: number | null
  /** false when the duration was derived client-side, not read from the API response. */
  isReal: boolean
}

export interface ModalityStatus {
  name: string
  matched: boolean
}

const ALL_MODALITIES = ['visual', 'audio', 'speech', 'caption', 'transcript']

const STAGE_LABELS: Record<string, string> = {
  query_embedding: 'Query embedding',
  retrieval: 'Visual / Audio / Text retrieval',
  rrf_fusion: 'RRF fusion',
  window_merging: 'Window merging',
  reranking: 'Reranking',
  done: 'Done',
}

// Action-phrased labels for the in-flight progress bar (StageProgress.tsx),
// distinct from the noun-phrased pipeline tracker labels above.
const PROGRESS_LABELS: Record<string, string> = {
  query_embedding: 'Embedding query…',
  retrieval: 'Retrieving candidates…',
  rrf_fusion: 'Fusing rankings…',
  window_merging: 'Merging windows…',
  reranking: 'Reranking…',
  done: 'Done',
}

// The default self-hosted request path returns an empty `diagnostics` object
// (see query_retrieval/api.py: `SearchResponse(results=results, decomposition=decomposition)`
// has no per-stage timing). When that happens we approximate each stage's
// share of the observed round-trip time with these fixed weights, purely so
// the tracker has something proportionate to animate through. This is a
// MOCKED breakdown, not measured timing — flagged via `isReal: false` on
// every stage below so the UI can label it honestly.
const MOCK_STAGE_WEIGHTS: Record<string, number> = {
  query_embedding: 0.18,
  retrieval: 0.32,
  rrf_fusion: 0.14,
  window_merging: 0.14,
  reranking: 0.16,
  done: 0.06,
}

function modalitiesFromResponse(response: SearchResponse): ModalityStatus[] {
  const matched = new Set<string>()
  for (const result of response.results) {
    for (const modality of result.matched_modalities ?? []) {
      matched.add(modality)
    }
  }
  const channelCounts = response.diagnostics?.channel_hit_counts as
    | Record<string, number>
    | undefined
  if (channelCounts) {
    for (const [modality, count] of Object.entries(channelCounts)) {
      if (count > 0) matched.add(modality)
    }
  }
  const known = ALL_MODALITIES.filter((m) => matched.has(m))
  const extra = [...matched].filter((m) => !ALL_MODALITIES.includes(m))
  return [...known, ...extra].map((name) => ({ name, matched: true }))
}

/** Builds the finished (post-response) stage list for a completed turn. */
export function buildCompletedStages(
  response: SearchResponse,
  totalElapsedMs: number,
): { stages: Stage[]; modalities: ModalityStatus[] } {
  const d = response.diagnostics ?? {}
  const hasRealTiming =
    typeof d.query_expansion_and_embedding_seconds === 'number' ||
    typeof d.vector_retrieval_seconds === 'number'

  let stages: Stage[]
  if (hasRealTiming) {
    const embedS = (d.query_expansion_and_embedding_seconds as number) ?? 0
    const retrievalS = (d.vector_retrieval_seconds as number) ?? 0
    const fusionS = (d.rrf_fusion_and_merge_seconds as number) ?? 0
    const reranking = d.reranking as { state?: string; latency_ms?: number } | undefined
    const verification = d.verification as { latency_ms?: number } | undefined
    stages = [
      { key: 'query_embedding', label: STAGE_LABELS.query_embedding, status: 'done', durationMs: embedS * 1000, isReal: true },
      { key: 'retrieval', label: STAGE_LABELS.retrieval, status: 'done', durationMs: retrievalS * 1000, isReal: true },
      { key: 'rrf_fusion', label: STAGE_LABELS.rrf_fusion, status: 'done', durationMs: fusionS * 500, isReal: true },
      { key: 'window_merging', label: STAGE_LABELS.window_merging, status: 'done', durationMs: fusionS * 500, isReal: true },
      {
        key: 'reranking',
        label: STAGE_LABELS.reranking,
        status: reranking?.state === 'disabled' ? 'skipped' : 'done',
        durationMs: reranking?.latency_ms ?? null,
        isReal: true,
      },
      {
        key: 'done',
        label: STAGE_LABELS.done,
        status: 'done',
        durationMs: verification?.latency_ms ?? 0,
        isReal: true,
      },
    ]
  } else {
    // MOCKED: split observed total elapsed time by fixed weights (see comment above).
    stages = Object.entries(MOCK_STAGE_WEIGHTS).map(([key, weight]) => ({
      key,
      label: STAGE_LABELS[key],
      status: key === 'reranking' && !response.diagnostics ? 'skipped' : 'done',
      durationMs: totalElapsedMs * weight,
      isReal: false,
    }))
  }

  return { stages, modalities: modalitiesFromResponse(response) }
}

/** Builds an in-flight (pre-response) stage list, advancing by elapsed time. */
export function buildInFlightStages(elapsedMs: number): Stage[] {
  // MOCKED progression while a request is in flight: we do not yet know
  // which backend path will answer, so stage boundaries are heuristic
  // checkpoints over elapsed time rather than server-reported transitions.
  const order = Object.keys(MOCK_STAGE_WEIGHTS)
  const cumulative: number[] = []
  let acc = 0
  for (const key of order) {
    acc += MOCK_STAGE_WEIGHTS[key]
    cumulative.push(acc)
  }
  // Assume a typical turn completes in ~3.5s; stages beyond that keep
  // "active" on the last one rather than jumping straight to done.
  const assumedTotalMs = 3500
  const progress = Math.min(elapsedMs / assumedTotalMs, 0.98)

  return order.map((key, i) => {
    const start = i === 0 ? 0 : cumulative[i - 1]
    const end = cumulative[i]
    let status: StageStatus = 'pending'
    if (progress >= end) status = 'done'
    else if (progress >= start) status = 'active'
    return {
      key,
      label: STAGE_LABELS[key],
      status,
      durationMs: null,
      isReal: false,
    }
  })
}

/** Current stage label + 0..1 fill fraction for the in-flight progress bar. */
export function currentProgress(elapsedMs: number): { label: string; progress: number } {
  const order = Object.keys(MOCK_STAGE_WEIGHTS)
  const cumulative: number[] = []
  let acc = 0
  for (const key of order) {
    acc += MOCK_STAGE_WEIGHTS[key]
    cumulative.push(acc)
  }
  const assumedTotalMs = 3500
  const progress = Math.min(elapsedMs / assumedTotalMs, 0.98)
  const activeIndex = cumulative.findIndex((end) => progress < end)
  const key = order[activeIndex === -1 ? order.length - 1 : activeIndex]
  return { label: PROGRESS_LABELS[key], progress }
}
