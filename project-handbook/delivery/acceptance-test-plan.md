# Acceptance Test Plan

## Purpose

This plan defines the evidence needed to accept a release of Video Search
Workbench. It covers the complete operator journey: selecting a compatible
runtime profile, indexing a video, inspecting indexed windows, retrieving
candidate moments, applying bounded precision stages, and presenting a safe,
playable result.

The plan is intentionally evidence-led. A passing mocked unit test proves a
contract; it does not prove that a model has downloaded, a cloud provider has
quota, or a specific video produces useful semantic matches. Those claims
require the separate local or cloud acceptance runs defined below.

## Scope

### In scope

- Both profile contracts: `self-hosted-v1` and `api-gemini-free-v1`.
- Upload, media probing, windowing, transcription mapping, independent
  modality vectors, caption selection, and profile-safe Qdrant writes.
- Library inspection and browser-safe media access.
- Query decomposition, per-modality retrieval, reciprocal-rank fusion (RRF),
  adjacent-window merging, optional local Qwen reranking, optional VLM
  verification, and temporal localisation.
- Credential/session handling, consent gating, diagnostics redaction, retry
  behaviour, cancellation, and recoverable failures.
- Browser build, lint, type checks, and the existing frontend filter tests.

### Out of scope for this release gate

- A claim of universal recognition quality across every camera, language,
  lighting condition, or event type.
- Provider uptime, rate limits, billing outcomes, or model quality guarantees;
  these belong to the chosen external provider.
- Multi-user tenancy, production identity management, remote object storage,
  and high-availability orchestration. The current job registry is
  process-local and the browser/API run on the operator's machine.
- A general performance service-level objective. The repository includes a
  small deterministic scale regression, but no approved hardware-independent
  latency target exists yet.

## Product quality objectives

| Objective | Acceptance question | Primary evidence |
|---|---|---|
| Correctness | Are windows deterministic, bounded, and persisted under the correct vector contract? | Unit/contract tests plus an indexed-video inspection |
| Retrieval integrity | Are four compatible channels searched independently, fused at rank level, and merged only within one video? | Fusion, merge, decomposition, and labelled retrieval tests |
| Precision integrity | Does the reranker score raw query plus bounded candidate evidence without access to RRF/vector scores? | Reranker-boundary tests and a manual diagnostic review |
| Safety | Are API keys, raw frames, and server paths excluded from public outputs and diagnostics? | Redaction and response-contract tests; browser/network inspection |
| Resilience | Do unavailable models, bad media, quota errors, Qdrant errors, and cancellation result in safe states rather than false success? | Negative-path tests and a controlled manual failure run |
| Explainability | Can an operator see profile, stage progress, modality evidence, provenance, and refined timestamps? | Job diagnostics, Library, and Search acceptance cases |
| Build quality | Does the browser code build and type-check, and do Python contracts pass? | Commands in the execution checklist |

## Test levels and current automated coverage

| Level | What it proves | Existing evidence | What it does not prove |
|---|---|---|---|
| Pure unit | Deterministic functions and validation contracts | Windowing, schema validation, selection, fusion, merge, metrics, and parsing tests | Real media/model/provider behaviour |
| Adapter and API contract | Public status, profile, response, redaction, and error behaviour using injected seams | FastAPI `TestClient` tests, profile/session tests, Gemini/Qdrant adapter tests | A live provider account, local model cache, or Cloud collection |
| Local integration | Qdrant query schema, collection creation, bounded search, and merge behaviour against a local test collection | `query_retrieval/tests/test_integration.py`, `test_comprehensive.py`, `test_phase5_regression.py`, and `test_qdrant_client.py` are explicitly marked `qdrant` | End-to-end semantic quality on a real video |
| Browser quality | Client-side filtering and build/static checks | Vitest filter tests, ESLint, TypeScript, Next build; all executed in the repository quality workflow | Full browser automation or assistive-technology certification |
| Manual end-to-end | The actual route/profile/model/device/user journey | Cases in [Acceptance test cases](acceptance-test-cases.md) | Repeatability unless recorded with the supplied evidence template |
| Controlled cloud smoke | Consent, API session, Qdrant Cloud, quota/error handling, and a small isolated collection | Manual run with a disposable test video and cloud account | A free-tier capacity promise or production load test |

The relevant automated test directories are
[`processing_indexing/tests`](../../processing_indexing/tests),
[`query_retrieval/tests`](../../query_retrieval/tests), and
[`processing_debug_frontend/src/lib/filters.test.ts`](../../processing_debug_frontend/src/lib/filters.test.ts).
Many provider, model, media, and Qdrant seams are deliberately injected in
those tests. This keeps the fast suite offline and repeatable.

## Test environments

### E1 - Contract environment

Python 3.11 or 3.12, the repository virtual environment, and frontend npm
dependencies. No API keys, downloaded model weights, or live cloud access are
required for the deterministic and mocked tests.

### E2 - Self-hosted acceptance environment

E1 plus FFmpeg/FFprobe, Docker Desktop with local Qdrant, and a supported
test video. The default local workflow uses the launcher and stores the
interactive collection separately from the test collection. The repository
test safeguard sets `COLLECTION_NAME=video_windows_query_test`; do not point
tests at a collection containing operator data.

### E3 - API-based acceptance environment

E1 plus a fresh backend session, a Qdrant Cloud URL/key, a Gemini key, and an
operator decision to grant the explicit cloud-video consent. Use a disposable
test collection/account and a video that may legitimately be sent to the
selected provider. Optional OpenAI, NVIDIA, or local Qwen choices must be
tested only when deliberately selected.

### Test data and labels

Use lawful, non-sensitive footage with a written provenance record. Maintain a
small controlled set:

| Asset class | Purpose | Required property |
|---|---|---|
| Short MP4 with audio | Baseline local indexing/search | At least one visible and one spoken/audible event |
| WebM with audio | API media-normalisation check | Converts into bounded provider-ready video/audio clips |
| Silent MP4 | Missing-audio behaviour | Must index without transcript/audio vectors in the API profile |
| Corrupt/non-video input | Recovery behaviour | Must be rejected with an actionable error |
| Labelled reference video | Retrieval measurement | Exact relevant source `window_id` values for each query |

For a labelled evaluation query, record the profile ID, video SHA-256 or
stable video ID, query text, expected event interval, and the relevant source
window IDs. A merged result is relevant if its own `window_id` or one of its
`source_window_ids` is labelled relevant, matching the implementation in
[`calculate_ranking_metrics`](../../query_retrieval/reranking.py).

## Quality metric semantics

Quality metrics are evaluation metrics, not confidence indicators. They are
calculated only when `relevant_window_ids` are supplied for a controlled
query. A normal live search must show them as **unevaluated**, not invent a
score from model confidence or RRF.

| Measure | Exact meaning in this implementation | Interpretation |
|---|---|---|
| Recall@K | Relevant retrieved candidates among the labelled relevant window IDs, divided by the number of labelled relevant IDs | Did the recall stage bring known relevant evidence into the top K? |
| MRR | Reciprocal of the rank of the first relevant candidate, or `0` when no candidate is relevant | How early does the first useful candidate appear? |
| nDCG@K | Binary discounted gain for relevant candidates, normalised by the ideal binary ordering | Does the whole top-K order place labelled evidence near the top? |
| Retrieval latency | Elapsed time reported around compatible query encoding, named-vector search, fusion, and merge | A stage measurement, not a quality score |
| Rerank latency | Frame sampling plus fresh cross-encoder scoring for the bounded selected candidates | Exposes cost of the precision stage |
| Verification/localisation latency | Evidence and temporal refinement time for only the final bounded candidates | Exposes optional final-stage cost |

Do not compare or average values across these score families:

- **RRF score** is an order-based recall signal accumulated from modality
  ranks.
- **Reranker `final_score`** in the API path is a fresh cross-encoder
  relevance score for the selected candidates only.
- **VLM verification confidence** is evidence metadata and does not replace
  the fresh reranker ordering in the API path.

The test harness must record the configured K, profile, model choices,
hardware, network condition, and whether model weights were already cached.
Without those conditions, a latency comparison is not meaningful.

## Test execution checklist

Run these from the repository root after installing the normal project
dependencies. Commands are a release check, not a claim that they have
already passed for every environment.

```powershell
# Python contract and mocked tests
python -m pytest processing_indexing/tests -m "not integration"

# Offline retrieval contracts: intentionally exclude tests that recreate a
# local Qdrant collection. This works without Docker.
python -m pytest query_retrieval/tests -m "not qdrant" -q

# Qdrant integration: the marked tests use only video_windows_query_test.
# --require-qdrant makes a missing/unhealthy database a clear failure rather
# than a misleading timeout or skipped integration claim.
docker compose up -d qdrant
python -m pytest query_retrieval/tests -m qdrant -q --require-qdrant

# Browser quality checks
Set-Location processing_debug_frontend
npm test
npm run lint
npm run typecheck
npm run build
```

Before the Qdrant command, start local Qdrant. The root test hook performs a
short read-only `/readyz` probe and deliberately redacts URL credentials,
paths, and query strings from any public failure message. The repository's
explicitly marked real-stack test is a
documented opt-in placeholder and currently skips until a real video, cached
models, and Qdrant fixture are intentionally supplied. It must not be counted
as live end-to-end evidence.

For an operator acceptance run, start the correct route with
[`start-local.ps1`](../../start-local.ps1): default mode for local Qdrant or
`-ApiOnly` for API-based mode. Follow the relevant cases in the companion
document and attach the evidence record to the release/PR.

## Entry and exit criteria

### Entry criteria

1. A clean build candidate is available and no indexing job is running.
2. The intended profile, collection, provider configuration, and test asset
   are identified.
3. The required test environment is healthy: FFmpeg, Qdrant, browser/API, or
   cloud preflight as applicable.
4. Test footage is approved for local processing and, for API-based runs,
   explicit cloud upload consent is present.
5. A labelled query set exists before measuring ranking metrics.

### Exit criteria

1. All P0 and P1 cases applicable to the selected profile pass, or an
   exception is documented and accepted by the release owner.
2. Python and browser checks complete successfully in the recorded
environment.
3. A self-hosted run proves a video can reach Library and Search, or an
   API-based smoke run proves the equivalent cloud path. A release claiming
   both profiles needs evidence for both.
4. No tested public response, job diagnostic, export, or browser storage
   inspection exposes an API key, raw frame payload, or server filesystem
   path.
5. At least one labelled query records Recall@K, MRR, nDCG@K, per-stage
   latency, and the result's refined interval when verification/localisation
   is enabled.
6. Failures, skipped cases, provider quota limits, and environmental
   constraints are written down rather than relabelled as passes.

## Defect handling and evidence

| Severity | Definition | Release disposition |
|---|---|---|
| P0 | Data/credential exposure, corruption of an incompatible collection, false success after an indexing failure, or unsafe media/path access | Block release |
| P1 | A required profile cannot index/search a supported test asset, or recall/precision boundary is violated | Block unless explicitly waived with a safe fallback |
| P2 | Diagnostics, UI state, optional provider, or non-critical result detail is wrong but safe fallback works | Record and schedule; assess user impact |
| P3 | Cosmetic or documentation-only inconsistency without behaviour impact | Record for follow-up |

Attach the following to every manual or cloud run:

```text
Run ID / date:
Commit:
Profile and collection:
Device / OS / Python / Node:
Model and provider selections:
Test asset stable ID and rights reference:
Cases run / passed / failed / skipped:
Query labels and Recall@K, MRR, nDCG@K (if evaluated):
Stage timings and request/retry counts:
Screenshots or safe diagnostic export location:
Known limits or provider messages (redacted):
Reviewer and disposition:
```

## Known limitations to keep visible during acceptance

- The local model path can download weights on its first real run; a successful
  mocked test does not eliminate that startup cost or connectivity dependency.
- The local Qwen reranker is an explicit, bounded opt-in. If its backend is
  unavailable, the safe behaviour is to preserve fused retrieval order and
  report an unavailable diagnostic.
- Cloud provider quota, file limits, and request latency vary outside this
  repository. Test both the success path and a safe quota/error response.
- The current test suite has strong contract coverage but not end-to-end
  browser automation or a committed real-media/golden-relevance benchmark.
  Manual acceptance evidence is therefore a required complement, not an
  optional embellishment.
