# Processing and Indexing Handoff

## 1. Purpose and scope

This document records the validated state of the `processing-indexing-accuracy-first` branch for the next developer. It covers upload and validation, window generation, Whisper transcription, X-CLIP visual embeddings, CLAP audio embeddings, BGE-M3 speech and caption embeddings, selective OpenAI structured captions, caption inheritance, the processing debug dashboard and exports, and the implementation status of Qdrant support.

Retrieval and query behavior are outside the validated scope of this branch.

## 2. Branch and checkpoint history

- Branch: `processing-indexing-accuracy-first`
- First confirmed real-run checkpoint: `fd0872f3792aa91f75622d43422f15c70ee581d2`
- Latest validated implementation checkpoint before this handoff: `a29570908254d6cb264f7c74ac9517470bae41be`
- Current pre-handoff HEAD: `a29570908254d6cb264f7c74ac9517470bae41be`

Both historical commits exist in the local branch history. The six latest reliability and observability fixes were verified with automated mocked/regression tests, but had not received another paid real-video rerun at the time of this handoff.

## 3. Real-video validation evidence

### Run A: short real video

- Job ID: `84e7fd0cfa474828aa5b18c3cf526443`
- Duration: approximately 12.866667 seconds
- Windows:
  - 0–10 seconds
  - 5–12.866667 seconds
- Window configuration: 10-second window, 5-second stride
- Genuine providers executed:
  - Whisper
  - `microsoft/xclip-base-patch32`
  - `laion/clap-htsat-unfused`
  - `BAAI/bge-m3` for speech text
  - OpenAI `gpt-4.1-mini` for structured visual captions
  - `BAAI/bge-m3` for caption-text embeddings
- OpenAI calls: 2
- Direct captions: 2
- Failed windows: 0
- Qdrant writes: 0
- Processing time: approximately 52.05 seconds
- Vector validation reconstructed from `window_debug.jsonl`:
  - X-CLIP: 512 dimensions, finite, norm approximately 1
  - CLAP: 512 dimensions, finite, norm approximately 1
  - BGE-M3 speech: 1024 dimensions, finite, norm approximately 1
  - BGE-M3 caption: 1024 dimensions, finite, norm approximately 1

OpenAI generated structured captions only. No OpenAI embeddings API was used; the resulting caption text was embedded by BGE-M3. The uploaded filename was not retained in the exported handoff evidence, so no filename or unsupported video description is asserted here.

Verified paths relative to `processing_jobs/84e7fd0cfa474828aa5b18c3cf526443/`:

- `exports/processing_report.json`
- `exports/errors.json`
- `exports/window_debug.jsonl`
- `exports/vlm_outputs.json`
- `exports/selector_trace.csv`
- `exports/redacted_configuration.json`
- `screenshots/overview.png`
- `screenshots/timeline.png`
- `screenshots/window-0.png`
- `screenshots/windows.png`

These job artifacts are intentionally ignored and are not part of the commit.

### Run B: longer real video

- Job ID: `89fb0a4fafcb4754951cc0c97d4b5854`
- Duration: approximately 93.093 seconds
- Total windows: 18
- Selected for OpenAI: 16
- Skipped: 2
- Calls saved: 2
- Selection rate: approximately 88.9%
- Minimum known OpenAI usage: approximately 156,622 tokens, as reported in the prior baseline handoff; this total was not independently reconstructed from the older sanitized exports
- Qdrant remained disabled
- Caption inheritance was observed in two exported windows
- Retrieval was not tested

The run exposed these defects:

- Structured-output parsing failures were not retried at application level.
- Selected failed calls could appear as skipped.
- Relative action timings could exceed window duration.
- Recoverable window failures could still result in a plain `complete` status.
- Per-stage timings were missing.
- Failed-call token usage could be ambiguous.

These defects were subsequently fixed in `a29570908254d6cb264f7c74ac9517470bae41be` with automated regression coverage. The longer real video had not been rerun against that fixed commit at handoff time; the fixes have not passed a paid real OpenAI rerun.

Verified paths relative to `processing_jobs/89fb0a4fafcb4754951cc0c97d4b5854/`:

- `exports/processing_report.json`
- `exports/errors.json`
- `exports/window_debug.jsonl`
- `exports/vlm_outputs.json`
- `exports/selector_trace.csv`
- `exports/redacted_configuration.json`

No screenshots were present in this job directory. The original uploaded filename was not retained in the exported handoff evidence and is not asserted here.

## 4. Automated validation

The latest reported non-real-model verification was:

- Ruff format: passed
- Ruff lint: passed
- Python non-real-model suite: 89 passed, 1 deselected
- Frontend tests: 2 passed
- Frontend ESLint: passed
- TypeScript typecheck: passed
- Next.js production build: passed
- Python `compileall`: passed
- FastAPI import/startup check: passed
- Frontend/API contract checks: passed
- `git diff --check`: passed
- Tracked-file secret scan: passed

These automated results are distinct from the two real runs above. Mocked tests are not proof of a real OpenAI retry succeeding, real Qdrant insertion, end-to-end retrieval, production deployment, or GPU/CUDA execution.

## 5. Implemented and validated matrix

| Component | Implemented | Automated validation | Real-video validation | Remaining limitation |
|---|---:|---|---|---|
| Upload/FFprobe validation | Yes | Automated | Real-video validated | Large-upload memory behavior not validated |
| SHA-256 video identity | Yes | Automated | Present in real-run reports | Live Qdrant idempotency not validated |
| Overlapping windows | Yes | Automated | Real-video validated | Broader duration/format coverage remains limited |
| Whisper | Yes | Automated with mocks | Real-video validated | CPU evidence only in recorded run configuration |
| Transcript-window overlap | Yes | Automated | Real-video validated in exported rows | Transcript quality not benchmarked |
| X-CLIP | Yes | Automated with mocks | Real-video validated | GPU execution not validated |
| CLAP | Yes | Automated with mocks | Real-video validated | Environmental-audio retrieval not validated |
| BGE-M3 speech embeddings | Yes | Automated with mocks | Real-video validated | Retrieval contribution not validated |
| Change-score selector | Yes | Automated | Real-video exercised | Threshold quality requires varied labelled videos |
| OpenAI structured captions | Yes | Automated with mocks | Real-video validated on pre-fix runs | Latest retry path lacks paid real rerun |
| Application-level semantic retry | Yes | Automated only | Implemented but unverified with real service | Real malformed-response recovery remains unvalidated |
| Caption timing normalization | Yes | Automated only | Implemented but unverified with real service | Latest normalization lacks paid real rerun |
| BGE-M3 caption embeddings | Yes | Automated with mocks | Real-video validated | Retrieval contribution not validated |
| Caption inheritance | Yes | Automated | Real-video validated | Temporal quality needs broader manual evaluation |
| Explicit VLM call states | Yes | Automated only for latest semantics | Not validated on post-fix real run | Needs controlled rerun |
| Job-status semantics | Yes | Automated only for latest semantics | Not validated on post-fix real run | Needs controlled rerun |
| Usage accounting | Yes | Automated only for latest semantics | Prior usage was partially reported | Failed-call SDK usage path needs real evidence |
| Per-stage timings | Yes | Automated only | Not validated on post-fix real run | Needs controlled rerun |
| Debug dashboard | Yes | Automated and build checks | Real-run artifacts/screenshots available | Live table refresh limitations remain |
| Exports | Yes | Automated | Real-run exports available | Old jobs disappear from UI after restart |
| Qdrant schema/upsert | Yes | Automated only | Not validated | Requires real Qdrant run and inspection |
| Idempotent Qdrant reprocessing | Yes | Automated only | Not validated | Requires repeated live upsert test |
| Retrieval/query integration | No validation in this branch | Out of branch scope | Not validated | Must be tested against indexed points |
| Production deployment | No | Not validated | Not validated | Development-only service/UI workflow |

## 6. Dashboard behavior

After upload and explicit job start, a developer should expect:

- An overview with status, progress, summary, and stage durations
- A windows table after completion
- Per-window transcripts
- Visual, audio, speech, and combined change scores
- Selection reasons and explicit VLM call state
- Direct, inherited, or unavailable caption provenance
- Caption confidence
- Vector dimension, norm, and finiteness summaries rather than every vector value
- A selector timeline
- Window detail pages
- Sanitized OpenAI attempts and usage
- A Qdrant payload preview
- Downloadable reports and diagnostic exports

Current limitations:

- Windows do not necessarily stream into the table live.
- A refresh may be required after completion.
- Exact frames sent to OpenAI are not presented as a polished side-by-side gallery.
- The live job registry is in memory and is cleared after backend restart.
- Artifacts remain on disk even when old jobs disappear from the UI.
- Computed embeddings are not fully reusable across new jobs.
- Full uploads are currently read into memory.
- Only one processing job runs at a time.
- Cancellation occurs at safe boundaries.

## 7. Explicitly unvalidated areas

- Real Qdrant collection creation and insertion
- Real point count and payload verification
- Idempotent reprocessing against a real Qdrant instance
- Processing-to-query/retrieval end-to-end flow
- Retrieval quality
- Latest semantic-retry behavior during a real malformed OpenAI response
- Latest status, timing, and usage fixes in a paid real rerun
- CUDA/GPU execution; current artifacts do not independently prove it
- Large-video memory behavior
- Concurrent jobs
- Production deployment
- Selector threshold quality across diverse videos

## 8. Required next validation sequence

1. Rerun the same approximately 93-second video on the latest branch with Qdrant disabled.
2. Confirm every window appears.
3. Confirm selected failures are shown as failed.
4. Confirm malformed structured output gets bounded retries.
5. Confirm relative timings stay inside the real window duration.
6. Confirm `complete` versus `completed_with_errors`.
7. Confirm per-stage timing and usage accounting.
8. Run 3–5 varied videos and manually label important windows before selector tuning.
9. Perform one controlled Qdrant-enabled run.
10. Verify collection schema, named vector dimensions, payloads, and point count.
11. Reprocess the same video and verify deterministic IDs/idempotency.
12. Validate query/retrieval against those indexed points.
13. Only then consider merging or calling the complete pipeline end-to-end validated.

## 9. Known commands

The following setup and startup commands are documented in the repository README.

PowerShell backend setup and development API:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-processing.txt
Copy-Item .env.processing.example .env.processing
$env:OPENAI_API_KEY = Read-Host -AsSecureString "OpenAI key" | ConvertFrom-SecureString -AsPlainText
$env:VLM_PROVIDER = "openai"
python -m uvicorn processing_indexing.debug_api:app --host 127.0.0.1 --port 8000
```

Frontend, in a second PowerShell window:

```powershell
Set-Location processing_debug_frontend
npm install
$env:NEXT_PUBLIC_PROCESSING_API = "http://127.0.0.1:8000"
npm run dev
```

Processing tests and checks used by the project:

```powershell
pytest processing_indexing/tests -m "not integration"
ruff format --check processing_indexing
ruff check processing_indexing
python -m compileall processing_indexing
python -c "from processing_indexing.debug_api import app; print(app.title)"
Set-Location processing_debug_frontend
npm test
npm run lint
npm run typecheck
npm run build
```

CLI and optional Qdrant commands documented by the README:

```powershell
docker compose up -d qdrant
python -m processing_indexing.cli video.mp4 --device cpu --json-report
python -m processing_indexing.cli path/to/videos --batch-size 8
```

Do not commit `.env` files, API keys, uploaded videos, model caches, processing job artifacts unless they are intentionally selected for versioning, or Qdrant data directories.

## 10. Handoff conclusion

The processing engine and post-run debugger have genuine real-video evidence for the main local model and OpenAI caption path. The latest reliability and observability fixes have automated regression evidence. Real Qdrant indexing, idempotent live storage, retrieval integration, and a paid real rerun of the latest fixes remain unvalidated.
