# Runtime Configuration

## Operating modes

The application has two intentional runtime profiles. They share the same
local browser UI and FastAPI process, but they have different model, storage,
credential, and media-disclosure boundaries.

| Mode | Local requirements | Remote requirements | Where vectors live | Best fit |
|---|---|---|---|---|
| Self-hosted | Python, Node.js, FFmpeg/FFprobe, Docker/Qdrant, local model cache | None for the default indexing path | Local Qdrant | Local-only processing and development. |
| API-based | Python, Node.js, FFmpeg/FFprobe | Gemini key, Qdrant Cloud HTTPS URL/key, explicit footage consent | Qdrant Cloud | Fast startup without Docker or local embedding-model downloads. |

The API-based option is not a hosted application. The UI, FastAPI process,
video upload, temporary media preparation, and original media remain on the
laptop. Only provider calls and the selected Qdrant Cloud collection are
remote.

## Fastest supported startup

From the repository root on Windows:

```powershell
# First-time setup: create .venv and install Python and browser dependencies
.\start-local.ps1 -Setup

# Local Qdrant + API + UI
.\start-local.ps1

# API + UI only; configure Qdrant Cloud from Architecture
.\start-local.ps1 -ApiOnly

# Replace only this project's API/UI listeners after a code change
.\start-local.ps1 -ApiOnly -Restart
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) after the launcher reports
that the browser UI is ready. `-Restart` stops listeners on ports 8000 and
3000, so do not use it while an indexing job is active.

## Required software

| Dependency | Used by | Verification |
|---|---|---|
| Python 3.11 or 3.12 | FastAPI, pipelines, tests | `python --version` |
| Node.js and npm | Next.js UI | `node --version`; `npm --version` |
| FFmpeg and FFprobe | Probe, media normalisation, audio extraction | `ffmpeg -version`; `ffprobe -version` |
| Docker Desktop/Compose | Self-hosted Qdrant only | `docker compose version` |
| Qdrant container | Self-hosted named-vector persistence | `docker compose up -d qdrant` |

The local Qdrant Compose service publishes ports 6333 and 6334 without
application-level TLS or authentication. Keep it private to the development
machine/network; it is not a public production endpoint.

## Local endpoints and lifecycle

| Service | Default address | Owner | Notes |
|---|---|---|---|
| Browser UI | `http://127.0.0.1:3000` | Next.js | Local operator interface. |
| Unified API | `http://127.0.0.1:8000` | Uvicorn/FastAPI | Processing, Library, Search, runtime sessions. |
| Local Qdrant HTTP | `http://127.0.0.1:6333` | Docker Compose | Required for self-hosted collection. |
| Local Qdrant gRPC | `http://127.0.0.1:6334` | Docker Compose | Exposed by the Qdrant image. |

The launcher detects existing local listeners. If port 8000 is occupied by a
different API, it refuses to assume that process belongs to this project.
Use the launcher restart option only after confirming there is no active work
to preserve.

## Self-hosted profile configuration

The self-hosted default uses the `self-hosted-v1` contract:

| Capability | Default implementation | Operational note |
|---|---|---|
| Transcription | Faster-Whisper `small` | Model is cached/downloaded on first use. |
| Visual retrieval | `microsoft/xclip-base-patch32` | 512-D `visual` field. |
| Audio retrieval | `laion/clap-htsat-unfused` | 512-D `audio` field. |
| Transcript/caption text | `BAAI/bge-m3` | 1024-D `speech` and `caption` fields. |
| Captioning | Selection-only by default; optional local Qwen2.5-VL | The optional model is on-demand and can take time to download/load. |
| Reranking | Optional local Qwen3-VL-Reranker-2B | Loads only after a bounded candidate set exists. |
| Store | Local Qdrant `video_windows` | Docker required for persistence. |

CPU is the default device. CUDA may be selected where the installed PyTorch
runtime and hardware support it; availability must be checked at runtime, not
assumed from the presence of a GPU.

`QUERY_LOW_MEMORY_MODE=1` is the laptop-oriented setting. It loads and
releases local query encoders sequentially to reduce memory pressure. Set it
to `0` only when resident models and faster repeated queries are worth the
additional memory use.

## API-based profile configuration

The API-based default uses `api-gemini-free-v1`:

| Stage | Default provider/model | Required configuration |
|---|---|---|
| Visual/audio/transcript/caption embeddings | Gemini Embedding 2 | Gemini API key |
| Transcription, decomposition, captions, verification | Gemini Flash-Lite | Gemini API key |
| Vector store | Qdrant Cloud HTTPS endpoint | Cloud URL and API key |
| Reranker | Optional local Qwen3-VL-Reranker-2B | Local model cache/device; no provider key |
| Optional vision/verification | OpenAI GPT-4.1 mini or NVIDIA Cosmos Reasoner | Provider-specific key/credits, only if selected |

The Architecture page owns provider selection. It validates an API session,
provider choices, Qdrant Cloud URL, and explicit external-footage consent
before an API-based job is accepted. The default Gemini availability and
pricing posture is subject to provider quotas and terms; review the current
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) and
[rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) before a
large run.

## Credential rules

| Rule | Current behaviour |
|---|---|
| Entry | Keys are entered in the local Architecture UI only for selected stages. |
| Browser storage | Browser receives/stores an opaque session identifier, not the key. |
| Backend storage | The runtime session is in process memory with a bounded TTL. |
| Restart | Restarting the API clears active provider credentials. |
| Responses/diagnostics | Secret-shaped fields and values are redacted before browser/API output. |
| Source control | `.env` and secret values must never be committed. |

Use profile-stage fields for API credentials rather than placing long-lived
keys in frontend environment variables. If an external secret manager is
introduced later, it must preserve the same no-browser-secret rule.

## Environment variables and configuration files

The current launcher and backend respect runtime configuration such as:

| Setting | Role | Recommended local value |
|---|---|---|
| `HF_HOME` | Local model cache location | `$PWD\.model-cache` |
| `QUERY_LOW_MEMORY_MODE` | Sequentially release query models | `1` on constrained machines |
| `QDRANT_URL` | Local Qdrant endpoint | `http://localhost:6333` |
| `COLLECTION_NAME` | Local profile collection | `video_windows` |
| `DEVICE` | Local inference device | `cpu` unless a verified CUDA runtime is available |
| `WINDOW_SECONDS` / `STRIDE_SECONDS` | Local window policy | `10` / `5` for the current profile |

`.env.processing.example` is a convenience starting point, not a complete
source of truth for model defaults. In particular, its legacy Qwen model value
does not match the current local runtime default. Use the runtime-profile
registry and Architecture UI as the authoritative configuration contract.

## Configuration checklist

### Before self-hosted indexing

1. Start Docker Desktop.
2. Run `.\start-local.ps1` and confirm Qdrant health in the Index page.
3. Choose the **Self-hosted** profile in Architecture.
4. Confirm the intended local device and any optional model selections.
5. Upload a small, lawful test video first; inspect the Library before a long
   media run.

### Before API-based indexing

1. Run `.\start-local.ps1 -ApiOnly`.
2. Choose **API-based** in Architecture.
3. Enter a Gemini key and Qdrant Cloud URL/key in the relevant stage cards.
4. Read and accept the external-footage consent notice.
5. Run connection preflight and resolve provider/quota failures before upload.
6. Ensure the selected profile is the one you will later select in Search.

## Troubleshooting map

| Symptom | Likely boundary | First check |
|---|---|---|
| UI cannot reach API | Port 8000/API process | Restart the local API/UI after confirming no job is running. |
| Qdrant is not ready | Docker/container/local port | Start Docker, run `docker compose up -d qdrant`, inspect `docker ps`. |
| WebM upload fails later | FFmpeg/FFprobe normalisation | Confirm both executables are on `PATH`; inspect job diagnostics. |
| First index stays in model loading | Local cache/model download | Allow the first download; check network, disk, and model readiness. |
| Provider request rejected | API key, consent, quota, or network | Re-run Architecture preflight; inspect the redacted provider diagnostic. |
| Search sees no expected video | Profile or collection mismatch | Verify the Library profile badge matches the Search profile. |
| Browser exposes unexpected details | API response boundary | Stop and inspect redaction/media endpoint behaviour before sharing the UI. |

For dependency, access, and licensing notes, see the
[Dependency register](dependency-register.md). For data contracts, see
[Data and retrieval design](../design/data-and-retrieval-design.md).
