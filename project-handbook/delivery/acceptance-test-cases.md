# Acceptance Test Cases

This catalogue turns the [acceptance test plan](acceptance-test-plan.md) into
repeatable checks. Each case says whether existing automation exercises the
underlying contract. That mapping is not a claim that a case has passed on a
particular machine or cloud account; record the actual result in the run
evidence template at the end of this page.

## Conventions

| Label | Meaning |
|---|---|
| P0 | Security, data-integrity, or false-success failure. Blocks release. |
| P1 | Required workflow or retrieval-boundary failure. Blocks the affected profile. |
| P2 | Recoverable behaviour, diagnostic, optional capability, or usability defect. |
| Automated | A named existing test exercises the stated contract with fakes, a local test collection, or both. |
| Manual | Requires a person to use the browser, a real asset, a device, or a provider account. |

For API-based cases, use a disposable Qdrant Cloud collection/account and a
video approved for the selected provider. Do not put a real key, source path,
raw frame, or unredacted provider response in the evidence record.

## Environment and browser shell

### ENV-001 - Start the selected runtime and navigate the primary routes

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Self-hosted or API-based | Manual |

**Steps**

1. From the repository root, run `./start-local.ps1` for self-hosted mode or
   `./start-local.ps1 -ApiOnly` for API-based mode.
2. Open `http://127.0.0.1:3000` after the API and browser UI are healthy.
3. Navigate through Architecture, Index video, Library, and Search.

**Expected outcome**

- The UI communicates which profile is active and no route renders an
  uncaught error.
- The self-hosted launcher starts/uses local Qdrant; API-only mode explicitly
  avoids starting Docker/Qdrant and directs the operator to cloud setup.
- The browser talks only to the local FastAPI endpoint configured for the
  application.

### ENV-002 - Browser code quality gate

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated commands; manual review of results |

**Steps**

1. In `processing_debug_frontend`, run `npm test`, `npm run lint`,
   `npm run typecheck`, and `npm run build`.
2. Preserve the command output in the release evidence.

**Expected outcome**

- The filter unit tests pass.
- Lint, TypeScript, and the production Next build complete without an error.
- A failure is recorded as a defect; do not substitute a running development
  server for a successful build check.

Automated mapping:
[`processing_debug_frontend/src/lib/filters.test.ts`](../../processing_debug_frontend/src/lib/filters.test.ts)
and the npm scripts in
[`processing_debug_frontend/package.json`](../../processing_debug_frontend/package.json).

### ENV-003 - Accessibility and responsive operator review

| Priority | Profile | Coverage |
|---|---|---|
| P2 | Both | Manual |

**Steps**

1. At a desktop and a narrow viewport, use only keyboard Tab, Shift+Tab,
   Enter, Space, Escape, and arrow keys to select a profile, configure a
   stage, upload a file, inspect a job, and submit a search.
2. Check visible focus, labels for inputs/selects, error text, progress,
   expandable diagnostics, and result controls.
3. Repeat one flow with browser zoom at 200%.

**Expected outcome**

- The key actions remain discoverable, focus is visible, and controls expose
  their purpose in the browser accessibility tree.
- Important progress/error information is textual, not colour-only.
- Any inaccessible control is logged as a P2 issue or elevated if it blocks a
  required user journey.

This is a manual acceptance check; the repository does not yet claim a full
automated accessibility audit or certification.

## Profile, consent, and credential handling

### CFG-001 - Enforce profile-specific vector contracts

| Priority | Profile | Coverage |
|---|---|---|
| P0 | Both | Automated + manual |

**Steps**

1. Select Self-hosted and note its collection and named-vector schema.
2. Select API-based and complete no credentials yet; compare the displayed
   collection/schema contract.
3. Attempt to submit a configuration that uses an unsupported provider/model
   pairing or vectors from the other profile.

**Expected outcome**

- Self-hosted and API-based profiles use different collection contracts.
- The UI/API rejects incompatible profile, provider, model, or vector-schema
  combinations before an indexing or query job begins.
- A rejected configuration never creates or overwrites a collection under a
  misleading compatible name.

Automated mapping:
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py),
[`test_profile_qdrant_store.py`](../../processing_indexing/tests/test_profile_qdrant_store.py),
and [`test_qdrant_store.py`](../../processing_indexing/tests/test_qdrant_store.py).

### CFG-002 - Gate API-based work on consent and required credentials

| Priority | Profile | Coverage |
|---|---|---|
| P0 | API-based | Automated + manual |

**Steps**

1. Select API-based mode and enter a valid HTTPS Qdrant Cloud URL without
   cloud-video consent and/or without one required key.
2. Attempt preflight/indexing.
3. Add a Gemini key, Qdrant key, and explicit consent; retry with a
   disposable cloud collection.

**Expected outcome**

- The first attempt is blocked before video processing or provider work.
- The accepted setup requires the required Gemini and Qdrant credentials,
  a valid cloud URL, and affirmative consent.
- The public setup response reports configuration state, never the submitted
  credential values.

Automated mapping:
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py).

### CFG-003 - Advanced providers require only their selected key

| Priority | Profile | Coverage |
|---|---|---|
| P1 | API-based | Automated + manual when selected |

**Steps**

1. Keep the default Gemini selections and confirm the form does not demand an
   OpenAI or NVIDIA key.
2. Select an implemented OpenAI or NVIDIA caption/verification option.
3. Attempt configuration without the corresponding key, then provide only
   the required selected key and retry.

**Expected outcome**

- Default API-based configuration does not make unselected advanced-provider
  keys mandatory.
- Selecting an advanced provider requires its corresponding key and rejects a
  missing one with a safe configuration error.
- Advanced selections are not presented as interchangeable embedding profiles.

Automated mapping:
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py).

### CFG-004 - Keep API keys private for the active backend session

| Priority | Profile | Coverage |
|---|---|---|
| P0 | API-based | Automated + manual |

**Steps**

1. Configure a distinct, non-production test value for each API key.
2. Inspect browser `sessionStorage`, Architecture response payloads, job
   status/diagnostic responses, Search responses, and exported job output.
3. Restart the backend and reload the browser.

**Expected outcome**

- The browser stores only an opaque runtime-session identifier, never an API
  key.
- Public payloads do not reflect key values, including invalid long values or
  nested configuration values.
- Restarting the backend invalidates the in-memory credential session; a new
  API-based run must be configured again.

Automated mapping:
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py),
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py), and
[`test_api_reranking_boundary.py`](../../query_retrieval/tests/test_api_reranking_boundary.py).

### CFG-005 - Reject credentials embedded in a cloud URL

| Priority | Profile | Coverage |
|---|---|---|
| P0 | API-based | Automated + manual |

**Steps**

1. Enter an HTTPS Qdrant URL containing `user:password@`.
2. Run setup validation/preflight.

**Expected outcome**

- Setup rejects the URL before a session is made public.
- Neither the embedded user name nor password appears in the returned
  validation error or browser state.

Automated mapping:
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py).

## Indexing, media, and persistence

### IDX-001 - Index a supported MP4 in self-hosted mode

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Self-hosted | Manual; component contracts automated |

**Steps**

1. Start local Qdrant and the default launcher route.
2. Select Self-hosted, leave optional captioning/reranking unselected, and
   upload a lawful MP4 with audio.
3. Watch the job until it reaches a terminal state, then open Library.

**Expected outcome**

- Media is probed, overlapping windows are created, and the job reports
  stage/timing/model-readiness diagnostics.
- The video is represented by the self-hosted profile's visual, audio,
  `speech`, and caption fields as available under the configured local path.
- A terminal failure is reported as failure, not as completed indexing.

Automated mapping:
[`test_probe.py`](../../processing_indexing/tests/test_probe.py),
[`test_windowing.py`](../../processing_indexing/tests/test_windowing.py),
[`test_pipeline.py`](../../processing_indexing/tests/test_pipeline.py), and
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py).

### IDX-002 - Normalise a WebM and preserve independent API vectors

| Priority | Profile | Coverage |
|---|---|---|
| P1 | API-based | Automated + manual cloud smoke |

**Steps**

1. Complete API-based preflight with a disposable Cloud collection.
2. Upload a WebM containing video and audio.
3. Inspect job diagnostics, then inspect the resulting record/Library vector
   summary without exposing any raw vectors in the browser.

**Expected outcome**

- The API path prepares bounded provider-compatible video and audio media and
  cleans up temporary prepared media after the run.
- A 20-second-window/10-second-stride API record holds separate `visual`,
  `audio`, `transcript`, and `caption` vectors when those signals are
  available; they are not averaged or concatenated.
- Profile metadata identifies the Gemini API contract so the record cannot be
  mixed with the local collection.

Automated mapping:
[`test_api_pipeline.py`](../../processing_indexing/tests/test_api_pipeline.py),
[`test_gemini_embeddings.py`](../../processing_indexing/tests/test_gemini_embeddings.py), and
[`test_profile_qdrant_store.py`](../../processing_indexing/tests/test_profile_qdrant_store.py).

### IDX-003 - Handle a silent video safely

| Priority | Profile | Coverage |
|---|---|---|
| P1 | API-based; repeat locally when practical | Automated + manual |

**Steps**

1. Index a known silent MP4 in API-based mode.
2. Inspect window diagnostics and records.
3. Search for an audible event that cannot be present.

**Expected outcome**

- The job completes without an audio-transcription call or fake transcript.
- API records omit unavailable `audio` and `transcript` vectors rather than
  falsely treating silence as positive evidence.
- Audio retrieval cannot manufacture a match from an absent audio channel.

Automated mapping:
[`test_api_pipeline.py`](../../processing_indexing/tests/test_api_pipeline.py) and
[`test_comprehensive.py`](../../query_retrieval/tests/test_comprehensive.py).

### IDX-004 - Reject malformed or unsupported media with recovery guidance

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + manual |

**Steps**

1. Upload a corrupt media file and a non-video/unsupported extension.
2. Observe the HTTP/UI response and job state.

**Expected outcome**

- The upload is rejected with an actionable, safe message.
- Path traversal names and unsupported file types are not accepted.
- No incomplete record is reported as indexed and no raw parser traceback is
  rendered to the browser.

Automated mapping:
[`test_probe.py`](../../processing_indexing/tests/test_probe.py) and
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py).

### IDX-005 - Maintain deterministic windows and idempotent point identity

| Priority | Profile | Coverage |
|---|---|---|
| P0 | Both | Automated + manual local collection inspection |

**Steps**

1. Index the same source video twice with the same profile/settings.
2. Compare stable video/window IDs and point count before/after the second
   run.
3. Confirm final windows do not exceed the video duration.

**Expected outcome**

- The window grid and point identity are deterministic for the same source.
- Reprocessing overwrites the logical point instead of accumulating duplicate
  points.
- Final windows are clipped to video duration and timestamp mapping preserves
  overlap semantics.

Automated mapping:
[`test_windowing.py`](../../processing_indexing/tests/test_windowing.py),
[`test_validation.py`](../../processing_indexing/tests/test_validation.py),
[`test_pipeline.py`](../../processing_indexing/tests/test_pipeline.py), and
[`test_qdrant_store.py`](../../processing_indexing/tests/test_qdrant_store.py).

### IDX-006 - Bound selective captions and preserve provenance

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both when captioning is selected | Automated + manual |

**Steps**

1. Index a video with visibly different segments and optional captioning
   selected.
2. Inspect selection counts, direct/inherited caption states, source-window
   reference, and any failed caption attempt.
3. Confirm neighbouring windows are not presented as direct VLM evidence when
   they inherited context.

**Expected outcome**

- Caption calls are bounded by change-driven selection instead of running over
  every window.
- First/last/change/recovery selection reasons are visible in diagnostics.
- Direct, inherited, and unavailable captions remain distinguishable, and an
  inherited caption never crosses a video boundary.

Automated mapping:
[`test_selection.py`](../../processing_indexing/tests/test_selection.py) and
[`test_selective_pipeline.py`](../../processing_indexing/tests/test_selective_pipeline.py).

### IDX-007 - Refuse an incompatible existing collection/schema

| Priority | Profile | Coverage |
|---|---|---|
| P0 | Both | Automated + manual controlled test |

**Steps**

1. Create or point the configured collection at a deliberately incompatible
   named-vector schema in a disposable environment.
2. Start preflight/indexing.

**Expected outcome**

- The job stops before an upsert with a schema/profile error.
- The system does not silently recreate or mutate an incompatible collection.
- The error is sanitised and identifies recovery action without exposing a
  connection credential.

Automated mapping:
[`test_qdrant_store.py`](../../processing_indexing/tests/test_qdrant_store.py),
[`test_profile_qdrant_store.py`](../../processing_indexing/tests/test_profile_qdrant_store.py), and
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py).

### IDX-008 - Cancel an in-progress job safely

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + manual |

**Steps**

1. Start indexing a sufficiently long test video.
2. Use **Cancel safely** during a visible stage.
3. Wait for a terminal event and reopen the job/Library.

**Expected outcome**

- The terminal job status and terminal activity event agree on cancellation.
- The UI never calls a cancelled or failed job complete.
- Any partial data is clearly represented by the job outcome; it is not
  silently presented as a complete library entry.

Automated mapping:
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py).

### IDX-009 - Surface provider quota retry/failure without leaking a secret

| Priority | Profile | Coverage |
|---|---|---|
| P1 | API-based | Automated + controlled manual only if safe |

**Steps**

1. Use an injected/fake provider test or a deliberately exhausted disposable
   quota; do not intentionally exhaust a shared account.
2. Trigger an API indexing operation and inspect timeline details.

**Expected outcome**

- Retry attempts are bounded and represented as retries/failure, not silent
  success.
- The failure preserves stage/provider context and safe error type.
- Credential text from a provider exception does not appear in diagnostics,
  exports, or response bodies.

Automated mapping:
[`test_api_pipeline.py`](../../processing_indexing/tests/test_api_pipeline.py) and
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py).

### IDX-010 - Report unavailable Qdrant cleanly

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + manual local disruption test |

**Steps**

1. Stop local Qdrant, or use an unreachable disposable Cloud URL.
2. Run preflight or start indexing.

**Expected outcome**

- The UI/API identifies Qdrant as unavailable or timed out with a recoverable
  status.
- No success toast, fake indexed count, or secret-bearing connection string
  is returned.

Automated mapping:
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py),
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py), and
[`test_qdrant_timeout.py`](../../query_retrieval/tests/test_qdrant_timeout.py).

## Library and public-output safety

### LIB-001 - Inspect the indexed library and playable media

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Manual; API/response safety automated |

**Steps**

1. Complete IDX-001 or IDX-002.
2. Open Library, choose the indexed video, and inspect its window list.
3. Open a window/playback control through the UI.

**Expected outcome**

- The library identifies the video, active embedding profile, timestamps,
  transcript/caption availability and provenance, vector summary, and current
  indexing state.
- Playback is resolved by an application media endpoint/window identifier;
  the browser does not receive a raw local filesystem path.
- A missing source file produces a safe unavailable state rather than a
  server path disclosure.

Automated mapping:
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py) and
[`query_retrieval/models.py`](../../query_retrieval/models.py) response models.

### LIB-002 - Verify public-path and cloud-payload boundaries honestly

| Priority | Profile | Coverage |
|---|---|---|
| P0 | Both, with special review for API-based | Automated + manual inspection |

**Steps**

1. Inspect browser/API search, activity, Library, and export responses for a
   controlled indexed video.
2. In API-based mode, inspect the disposable Qdrant payload only through an
   authorised administrative tool; do not copy its content into the test log.

**Expected outcome**

- Public browser/API outputs exclude local `source_path` values and API keys.
- The test record explicitly acknowledges the current implementation detail:
  the API-based indexing payload includes a source-path string when it is
  written to Qdrant Cloud. This is a data-minimisation limitation, not a
  reason to claim that source paths never leave the laptop.
- Any release requiring a strict "no source metadata in hosted storage"
  guarantee remains blocked until that payload contract changes and is
  retested.

Automated mapping:
[`test_api_pipeline.py`](../../processing_indexing/tests/test_api_pipeline.py),
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py), and
[`query_retrieval/models.py`](../../query_retrieval/models.py).

## Retrieval, precision, and evidence

### QRY-001 - Retrieve each modality in its compatible space

| Priority | Profile | Coverage |
|---|---|---|
| P0 | Both | Automated + labelled manual query |

**Steps**

1. Index a labelled video under one profile.
2. Submit a query that contains visual, audible, spoken/text, and caption-like
   concepts.
3. Inspect query decomposition, per-modality result diagnostics, and result
   modality evidence.

**Expected outcome**

- A compatible query representation is produced for every available named
  channel: `visual`, `audio`, `speech`/`transcript`, and `caption`.
- Searches remain profile-compatible. API profile filters include the exact
  embedding profile/provider/model/dimension contract.
- Missing channels degrade safely; the system does not compare incompatible
  raw vectors or fabricate a modality hit.

Automated mapping:
[`test_encoders.py`](../../query_retrieval/tests/test_encoders.py),
[`test_gemini_embeddings.py`](../../processing_indexing/tests/test_gemini_embeddings.py),
[`test_decomposition_integration.py`](../../query_retrieval/tests/test_decomposition_integration.py), and
[`test_api_reranking_boundary.py`](../../query_retrieval/tests/test_api_reranking_boundary.py).

### QRY-002 - Fuse only ranked modality lists with RRF

| Priority | Profile | Coverage |
|---|---|---|
| P0 | Both | Automated + diagnostic review |

**Steps**

1. Run a query with hits from more than one modality.
2. Inspect each result's modality rank/contribution evidence and the fused
   candidate order before optional reranking.
3. Repeat with a zero-weight or unavailable modality.

**Expected outcome**

- RRF sums rank-based contributions for the same window; it neither averages
  nor concatenates raw modality vectors.
- Modality evidence identifies the contributing modality, rank, and
  contribution. Inherited caption evidence remains visible and discounted as
  configured.
- A missing/empty modality list does not crash the search.

Automated mapping:
[`test_fusion.py`](../../query_retrieval/tests/test_fusion.py) and
[`test_decomposition_integration.py`](../../query_retrieval/tests/test_decomposition_integration.py).

### QRY-003 - Merge only adjacent regions from the same video

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + labelled manual query |

**Steps**

1. Use a query with adjacent/overlapping matching windows in one video and
   similarly timed windows in a second video.
2. Inspect merged result timestamps and source window IDs.

**Expected outcome**

- Adjacent matching windows may collapse into a bounded region.
- A merge never crosses `video_id`; its maximum duration and constituent
  window count remain bounded.
- Request `top_k` is applied after merging, so a chain is not truncated into
  a misleading partial event before it can be merged.

Automated mapping:
[`test_merge_windows.py`](../../query_retrieval/tests/test_merge_windows.py),
[`test_phase5_regression.py`](../../query_retrieval/tests/test_phase5_regression.py), and
[`test_comprehensive.py`](../../query_retrieval/tests/test_comprehensive.py).

### QRY-004 - Decompose queries safely and fall back deterministically

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + manual |

**Steps**

1. Submit a representative natural-language query with decomposition enabled.
2. Disable decomposition, remove its optional key if applicable, or inject a
   timeout/malformed response.
3. Compare the response diagnostics and ensure a search still completes where
   a fallback is defined.

**Expected outcome**

- The system exposes the per-modality plan/weights without revealing private
  provider data.
- Cache/live/fallback decisions are observable.
- A timeout, malformed response, disabled switch, or absent optional key does
  not crash search or silently claim that a live decomposition succeeded.

Automated mapping:
[`test_decomposition.py`](../../query_retrieval/tests/test_decomposition.py),
[`test_decomposition_integration.py`](../../query_retrieval/tests/test_decomposition_integration.py), and
[`test_kill_switches.py`](../../query_retrieval/tests/test_kill_switches.py).

### QRY-005 - Skip hosted work for a zero-result request

| Priority | Profile | Coverage |
|---|---|---|
| P2 | API-based | Automated |

**Steps**

1. Issue an API-profile search with `top_k=0` through the test/API route.
2. Inspect the returned result list and diagnostics.

**Expected outcome**

- The response contains an empty result list and a clear skipped state.
- The request does not initiate Gemini embedding/decomposition or Qdrant
  search work beyond validation required to interpret the selected profile.

Automated mapping:
[`test_api_reranking_boundary.py`](../../query_retrieval/tests/test_api_reranking_boundary.py).

### QRY-006 - Rerank only the bounded RRF candidate list with fresh evidence

| Priority | Profile | Coverage |
|---|---|---|
| P0 | Both when local Qwen is explicitly selected | Automated + manual diagnostic review |

**Steps**

1. Run a query that produces more candidates than the selected rerank bound.
2. Explicitly choose the local Qwen reranker and inspect stage diagnostics.
3. Compare candidate ordering and fields before and after reranking.

**Expected outcome**

- RRF supplies only the candidate list. The cross-encoder receives a raw
  query, bounded sampled frames, transcript, and caption for each selected
  candidate; it does not receive RRF score, vector similarity, modality rank,
  or modality contribution.
- The reranker produces a fresh relevance score and may change order using
  only that score. It never scans the full vector collection.
- At most the configured candidate/frame bounds are sampled; candidates after
  the bound are explicitly discarded from this precision stage.

Automated mapping:
[`test_reranking.py`](../../query_retrieval/tests/test_reranking.py),
[`test_qwen3_vl_backend.py`](../../query_retrieval/tests/test_qwen3_vl_backend.py), and
[`test_api_reranking_boundary.py`](../../query_retrieval/tests/test_api_reranking_boundary.py).

### QRY-007 - Fail open safely when the local reranker cannot run

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both when local Qwen is selected | Automated + manual first-run check |

**Steps**

1. Select local Qwen on a machine without its usable backend/model, or use an
   injected unavailable adapter.
2. Run a query and inspect results and diagnostics.

**Expected outcome**

- The query retains the fused candidate order rather than blending partial
  fresh scores with RRF scores.
- Diagnostics say reranking is unavailable/partial and expose only safe error
  classification, not backend exception text, paths, or credentials.
- No Qwen model is downloaded or allocated merely by opening Search without
  explicit selection.

Automated mapping:
[`test_reranking.py`](../../query_retrieval/tests/test_reranking.py),
[`test_api_reranking_boundary.py`](../../query_retrieval/tests/test_api_reranking_boundary.py), and
[`test_runtime_profiles.py`](../../processing_indexing/tests/test_runtime_profiles.py).

### QRY-008 - Verify only final candidates and preserve API precision order

| Priority | Profile | Coverage |
|---|---|---|
| P0 | API-based; inspect local legacy path separately | Automated + manual |

**Steps**

1. Configure a bounded VLM verification option and produce several reranked
   candidates.
2. Inspect the number of verification calls, verification states, evidence,
   and final ordering.

**Expected outcome**

- Verification receives only the selected final candidates, not the full
  library.
- In the API path, verification attaches evidence/rejection/localisation state
  without blending VLM confidence with RRF/cross-encoder scores or changing
  fresh cross-encoder order.
- An unavailable or failed verifier is reported as `verification_unavailable`,
  never as a verified match.

Automated mapping:
[`test_api_reranking_boundary.py`](../../query_retrieval/tests/test_api_reranking_boundary.py),
[`test_verification.py`](../../query_retrieval/tests/test_verification.py), and
[`test_vision_verification.py`](../../query_retrieval/tests/test_vision_verification.py).

**Compatibility note.** The legacy self-hosted verification route retains
historical verification-aware ordering semantics. It must be assessed
separately and must not be described as satisfying the API path's strict
"fresh-reranker-order only" rule until that legacy path is aligned.

### QRY-009 - Refine a verified event into a short playback interval

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Any profile with verification configured | Automated + manual |

**Steps**

1. Use a labelled event inside a broad merged candidate region.
2. Enable temporal localisation and run the query.
3. Play the returned interval and compare it with the label.

**Expected outcome**

- A verified broad region may receive a second bounded temporal pass.
- A successful refinement returns an absolute, playable interval targeted at
  2-5 seconds; a failed refinement preserves the safe first-pass evidence
  instead of inventing timestamps.
- Localisation uses candidate-bounded frames and records its state/evidence.

Automated mapping:
[`test_vision_verification.py`](../../query_retrieval/tests/test_vision_verification.py).

### QRY-010 - Measure labelled ranking quality without fabricating metrics

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + manual labelled evaluation |

**Steps**

1. Prepare a query with known relevant source window IDs.
2. Run it with those IDs in the controlled evaluation input, record K and the
   candidate list, then run an equivalent ordinary live query without labels.
3. Record Recall@K, MRR, nDCG@K, hits, stage latencies, profile, and model
   configuration.

**Expected outcome**

- The labelled run produces binary ranking metrics with merged candidates
  counting as relevant when a source window is labelled.
- The ordinary live run reports the metrics as unevaluated rather than using
  retrieval scores, VLM confidence, or a model assertion as ground truth.
- Scores from RRF, reranking, and verification remain visibly separate.

Automated mapping:
[`test_reranking.py`](../../query_retrieval/tests/test_reranking.py).

## Diagnostics, resilience, and scale

### OBS-001 - Make job progress and model readiness inspectable

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + manual |

**Steps**

1. Start an indexing run before local models are warm or while API calls are
   pending.
2. Keep the job screen open through completion/failure.
3. Inspect the activity timeline, stage counts, model readiness, retries,
   and timing data.

**Expected outcome**

- Progress distinguishes preprocessing, transcription, embedding, caption,
  Qdrant persistence, complete, cancelled, and failed states as applicable.
- The activity endpoint is bounded and uses safe ISO timestamps/structured
  values.
- Cached-but-not-loaded model state is not falsely displayed as successfully
  loaded, and a model failure is visible by component/stage.

Automated mapping:
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py).

### OBS-002 - Exercise error and recovery states in the UI

| Priority | Profile | Coverage |
|---|---|---|
| P1 | Both | Automated + manual |

**Steps**

1. Trigger one malformed upload, one unavailable model/provider, and one
   unavailable Qdrant scenario in a controlled environment.
2. For each, inspect the current status banner, diagnostic detail, retry or
   recovery guidance, and library state.

**Expected outcome**

- The UI identifies the failed subsystem and current stage.
- Raw exception bodies, credentials, local paths, and internal frames are not
  rendered.
- A failed inner stage never changes the job to complete; a retry/cancel
  control is only offered when it is meaningful.

Automated mapping:
[`test_debug_support.py`](../../processing_indexing/tests/test_debug_support.py),
[`test_integration.py`](../../query_retrieval/tests/test_integration.py), and
[`test_qdrant_timeout.py`](../../query_retrieval/tests/test_qdrant_timeout.py).

### PERF-001 - Run the bounded synthetic retrieval regression

| Priority | Profile | Coverage |
|---|---|---|
| P2 | Self-hosted local test collection | Automated + recorded run |

**Steps**

1. Start local Qdrant and run the retrieval suite containing the phase-5
   regression tests.
2. Capture the elapsed time reported by the synthetic 200-window/40-region
   fixture.

**Expected outcome**

- The fixture merges the expected contiguous chains, applies result limits
  after merge, and finishes under the test's local 10-second guardrail.
- The recorded time is treated only as a regression signal for that synthetic
  local fixture. It is not a promise for a new machine, a cold model cache,
  a long uploaded video, or a hosted provider.

Automated mapping:
[`test_phase5_regression.py`](../../query_retrieval/tests/test_phase5_regression.py).

### PERF-002 - Record a real end-to-end baseline, do not infer one

| Priority | Profile | Coverage |
|---|---|---|
| P2 | Both as claimed | Manual |

**Steps**

1. Use the same labelled asset in a cold and warm run for the profile being
   evaluated.
2. Record upload/probe, transcription, each embedding channel, caption,
   Qdrant upsert, query encode/search/fusion, rerank, and verification timing.
3. Record model cache state, GPU/CPU, memory pressure, network, provider
   requests/retries, and collection size.

**Expected outcome**

- The evidence separates one-time model download/initialisation time from
  steady-state processing.
- The team can compare like-for-like profile runs without turning an isolated
  anecdote into a throughput promise.
- Any provider rate limit or quota delay is labelled as external dependency
  behaviour, not hidden inside a single aggregate duration.

## Manual evidence record

Copy this block into the release/PR record for every manual or cloud run.

```text
Date and operator:
Commit / branch:
Profile ID / collection:
Runtime mode and launcher command:
Device, OS, Python, Node, Docker/Qdrant version:
Models/providers selected; cache state:
Test asset stable ID / rights reference / duration:
Case IDs and result (pass, fail, blocked, skipped):
Observed job and query diagnostics (redacted):
Ground-truth window IDs and query labels, if used:
Recall@K / MRR / nDCG@K / K / stage timings:
Screenshots or safe artifact locations:
Defects, known limitations, and disposition:
Reviewer sign-off:
```

## Automation traceability summary

| Area | Key automated test modules |
|---|---|
| Profile/session/secret handling | `processing_indexing/tests/test_runtime_profiles.py`, `test_debug_support.py` |
| Media/API pipeline | `processing_indexing/tests/test_probe.py`, `test_windowing.py`, `test_api_pipeline.py`, `test_gemini_embeddings.py` |
| Persistence/schema | `processing_indexing/tests/test_qdrant_store.py`, `test_profile_qdrant_store.py`, `test_validation.py` |
| Selective captions | `processing_indexing/tests/test_selection.py`, `test_selective_pipeline.py` |
| Retrieval/decomposition/fusion/merge | `query_retrieval/tests/test_encoders.py`, `test_decomposition.py`, `test_fusion.py`, `test_merge_windows.py` |
| Rerank/verification/metrics | `query_retrieval/tests/test_reranking.py`, `test_api_reranking_boundary.py`, `test_vision_verification.py`, `test_verification.py` |
| Query/API resilience | `query_retrieval/tests/test_integration.py`, `test_comprehensive.py`, `test_kill_switches.py`, `test_qdrant_timeout.py` |
| Browser filter/build checks | `processing_debug_frontend/src/lib/filters.test.ts` and package scripts |

The catalogue is intentionally conservative: automated tests verify many
boundaries, while real-footage semantic quality, local model availability,
cloud consent, provider quota, and operator usability remain acceptance
activities that must be performed and recorded for the actual environment.
