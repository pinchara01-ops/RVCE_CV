// Stage sequences shown while a request is in flight.
//
// These mirror the architecture's real phases so the wait is legible. The
// per-stage durations are display weights, not measured timings, a single
// upstream call gives no per-stage telemetry to report, so nothing here claims
// to be a measurement.

export interface StageSpec {
  key: string
  /** Relative weight; converted to a share of the elapsed animation. */
  weight: number
}

export const QUERY_STAGES: StageSpec[] = [
  { key: 'uploading', weight: 2 },
  { key: 'decoding', weight: 1.5 },
  { key: 'understanding', weight: 2 },
  { key: 'scanning', weight: 4 },
  { key: 'matching', weight: 3 },
  { key: 'localising', weight: 2 },
  { key: 'clipping', weight: 1.5 },
]

export const INDEX_STAGES: StageSpec[] = [
  { key: 'uploading', weight: 2 },
  { key: 'segmenting', weight: 2 },
  { key: 'visual', weight: 3 },
  { key: 'audio', weight: 2 },
  { key: 'transcript', weight: 3 },
  { key: 'captioning', weight: 3 },
  { key: 'embedding', weight: 2 },
  { key: 'persisting', weight: 1.5 },
]

/**
 * Progress through a stage list from elapsed seconds.
 *
 * The sequence eases toward the final stage and holds there rather than
 * completing, because the real finish is whenever the upstream call returns.
 */
export function stageAt(
  stages: StageSpec[],
  elapsedSeconds: number,
  expectedSeconds: number,
): { index: number; fraction: number } {
  const total = stages.reduce((sum, stage) => sum + stage.weight, 0)

  // Even pacing for the bulk of the wait, so each stage gets a comparable share
  // of the time rather than the early ones flashing past. Past the expected
  // duration it creeps through a long tail that approaches but never reaches
  // the end, because the real finish is whenever the upstream call returns.
  const t = elapsedSeconds / Math.max(1, expectedSeconds)
  const progress =
    t <= 1 ? t * 0.88 : 0.88 + (1 - Math.exp(-(t - 1) * 0.6)) * 0.11
  const target = progress * total

  let consumed = 0
  for (let index = 0; index < stages.length; index++) {
    const stage = stages[index]
    if (target < consumed + stage.weight || index === stages.length - 1) {
      return {
        index,
        fraction: Math.min(1, Math.max(0, (target - consumed) / stage.weight)),
      }
    }
    consumed += stage.weight
  }
  return { index: stages.length - 1, fraction: 1 }
}
