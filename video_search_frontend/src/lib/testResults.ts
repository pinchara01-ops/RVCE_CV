export type TestStatus = 'pass' | 'warning' | 'fail'

export interface TestResult {
  id: string
  name: string
  category: string
  status: TestStatus
  description: string
  /** The input used to exercise this case, when the case has one (e.g. not a schema/manifest check). */
  query?: string
  /** What the test asserts should happen. */
  expected: string
  /** What actually happened on the run this row represents. */
  actual: string
  /**
   * "<filename> · <mm:ss>-<mm:ss>" for retrieval-style cases with a sample
   * clip to preview. Omitted for data-integrity/input-validation cases that
   * have no associated footage.
   */
  sampleClip?: string
}

export interface TestSummary {
  pass: number
  warning: number
  fail: number
  total: number
}

export function summarizeTestResults(results: TestResult[]): TestSummary {
  const summary = { pass: 0, warning: 0, fail: 0, total: results.length }
  for (const r of results) summary[r.status] += 1
  return summary
}

// PLACEHOLDER DATA, these 13 rows are dummy QA output, not a real test run.
// Swap this array for whatever a real pipeline test-run artifact/endpoint
// returns once live integration exists; `pages/Tests.tsx` and `TestsTable`
// only depend on the `TestResult[]` shape above, so the categories, names,
// counts, and detail fields here are expected to change without touching
// the page or table itself.
export const TEST_RESULTS: TestResult[] = [
  {
    id: 'hindi-script-preserved',
    name: 'Hindi query, script preserved',
    category: 'Multilingual',
    status: 'pass',
    description: "Devanagari script isn't transliterated or mangled before reaching the query encoder.",
    query: 'रात में लाल दरवाज़ा खोलता हुआ व्यक्ति',
    expected: 'Query string reaches the encoder byte-identical, with no transliteration or normalization loss.',
    actual: 'Script passed through unchanged; embeddings generated from the original Devanagari text.',
    sampleClip: 'porch_cam_01.mp4 · 00:58-01:06',
  },
  {
    id: 'kannada-script-preserved',
    name: 'Kannada query, script preserved',
    category: 'Multilingual',
    status: 'pass',
    description: 'Kannada script is preserved through decomposition and encoding.',
    query: 'ಒಬ್ಬ ವ್ಯಕ್ತಿ ರಾತ್ರಿ ಕೆಂಪು ಬಾಗಿಲು ತೆರೆಯುತ್ತಿದ್ದಾನೆ',
    expected: 'Query decomposition preserves Kannada script across all per-modality sub-queries.',
    actual: 'Script preserved in visual, caption, and speech sub-queries alike.',
    sampleClip: 'hallway_interior.mp4 · 05:02-05:11',
  },
  {
    id: 'mixed-language-query',
    name: 'Mixed-language query (English + Hindi)',
    category: 'Multilingual',
    status: 'pass',
    description: 'A single query mixing English and Hindi tokens still produces valid per-modality embeddings.',
    query: 'a person outside देर रात door खोलता हुआ',
    expected: 'Decomposition splits per-modality text without dropping either language span.',
    actual: 'Both language spans were embedded correctly; no truncation observed.',
    sampleClip: 'backyard_camera_04.mp4 · 02:14-02:29',
  },
  {
    id: 'empty-query-handling',
    name: 'Empty query string handling',
    category: 'Input handling',
    status: 'pass',
    description: 'An empty or whitespace-only query is rejected before it reaches the encoders.',
    query: '"" (empty string)',
    expected: 'Request is rejected before any encoder call, no wasted inference.',
    actual: 'Rejected with "query must not be empty"; encoders were never invoked.',
  },
  {
    id: 'zero-result-query',
    name: 'Query with no matching footage (0 results)',
    category: 'Retrieval robustness',
    status: 'pass',
    description: 'A query with no plausible match returns an empty result set instead of low-confidence noise.',
    query: 'a dog flying a kite',
    expected: 'Empty results array, no fabricated low-confidence matches padded in.',
    actual: 'Returned 0 results, as expected for this library.',
  },
  {
    id: 'split-leakage',
    name: 'Split leakage, same source_video_id in two splits',
    category: 'Data integrity',
    status: 'warning',
    description: 'One clip appears in both the train and eval splits; flagged, not yet excluded.',
    expected: 'Every source_video_id appears in exactly one of train/eval/test.',
    actual: 'cam03_0417 found in both train.jsonl and eval.jsonl, flagged for exclusion, not yet fixed.',
  },
  {
    id: 'negative-example-missing-reason',
    name: 'Negative example missing "reason" field',
    category: 'Data integrity',
    status: 'pass',
    description: 'Negative examples without a reason field are caught by schema validation before training.',
    expected: 'Every negative example includes a non-empty reason field.',
    actual: '3 of 1,240 negative examples were missing reason; all 3 caught by schema validation.',
  },
  {
    id: 'event-window-out-of-bounds',
    name: 'Event window outside labeled window bounds',
    category: 'Data integrity',
    status: 'pass',
    description: "A refined event timestamp is clamped within the labeled window's start/end.",
    expected: 'refined_start/refined_end always stay within [start, end] of the labeled window.',
    actual: 'Clamped correctly across all sampled windows.',
  },
  {
    id: 'malformed-manifest-sha256',
    name: 'Malformed sha256 in model manifest',
    category: 'Data integrity',
    status: 'pass',
    description: 'A manifest entry with an invalid sha256 hash fails validation instead of silently loading.',
    expected: 'Manifest load fails fast on an invalid sha256 hex string.',
    actual: 'Raised a validation error as expected; model was not loaded.',
  },
  {
    id: 'reranker-timeout-fallback',
    name: 'Reranker timeout, falls back to fused ranking',
    category: 'Retrieval robustness',
    status: 'warning',
    description: 'Fallback engages correctly, but the fallback path runs 1.8s slower than its budget.',
    query: 'a person opening a red door at night',
    expected: 'On timeout, the response falls back to fused (RRF) order within its latency budget.',
    actual: 'Fallback triggered correctly, but took 2.1s against a 300ms budget.',
    sampleClip: 'backyard_camera_04.mp4 · 02:14-02:29',
  },
  {
    id: 'reranker-exception-fallback',
    name: 'Reranker exception, falls back to fused ranking',
    category: 'Retrieval robustness',
    status: 'pass',
    description: 'An unhandled reranker exception fails open to the RRF-fused order instead of dropping results.',
    query: 'a person opening a red door at night',
    expected: 'An unhandled exception in the reranker must not remove recall.',
    actual: 'Fused order returned unchanged; no results were dropped.',
    sampleClip: 'backyard_camera_04.mp4 · 02:14-02:29',
  },
  {
    id: 'upload-unsupported-format',
    name: 'Upload, unsupported file format rejected',
    category: 'Upload validation',
    status: 'pass',
    description: 'A non-MP4/MOV/AVI file is rejected client-side with a clear reason before any upload starts.',
    expected: '.gif, .txt, and other non-video files are rejected before upload starts.',
    actual: 'Rejected "sample.gif" immediately with "Unsupported format".',
  },
  {
    id: 'upload-exceeds-size-limit',
    name: 'Upload, file exceeds size limit rejected',
    category: 'Upload validation',
    status: 'pass',
    description: 'A file over the 2GB placeholder limit is rejected immediately instead of starting a doomed upload.',
    expected: 'Files over the 2GB placeholder limit are rejected before upload starts.',
    actual: 'Rejected a 2.4GB fixture file immediately with "Exceeds 2GB limit".',
  },
]
