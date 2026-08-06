# Video Search Workbench

This workbench lets a team upload a video, inspect how it is processed into multimodal video windows, persist those windows in Qdrant, and search the indexed collection from the same browser UI.

## What is in this branch

- `processing_indexing/`: local and API-based video indexing, overlapping windows, transcription, independent visual/audio/transcript/caption embeddings, selective captions, and profile-isolated Qdrant writes.
- `query_retrieval/`: independent named-vector retrieval, reciprocal-rank fusion, bounded Qwen-VL cross-encoder reranking, optional VLM verification, and 2–5 second time localisation.
- `processing_debug_frontend/`: the single Next.js UI for architecture selection, upload, inspection, and search.

The local default is deliberately safe: no API key is required for the processing UI's selection-only mode. API-based credentials are held only in the backend's in-memory, opaque session; the browser retains only its random session identifier. Restarting the backend clears every API key, and no key is written to job history, exports, diagnostics, or browser storage.

## Project handbook

The [Project Handbook](project-handbook/README.md) is the detailed design and
delivery reference for this repository. It includes:

- system architecture, data model, embedding-profile compatibility, and the
  retrieval/reranking boundary;
- UI flows, operational states, and evidence-oriented search behaviour;
- a direct dependency, model, provider, cost/access, and supply-chain
  register;
- runtime configuration and credential-handling guidance; and
- engineering process, acceptance-plan, and acceptance-case materials.

The handbook marks current implementation, selectable options, and future
scale-up work separately so design documentation does not overstate what is
already deployed.

## Quick start

If the repository has already been set up on this machine, this is the only command needed:

```powershell
.\start-local.ps1
```

For a fresh checkout, run this once instead. It creates the virtual environment and installs the Python and browser dependencies:

```powershell
.\start-local.ps1 -Setup
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000). The script starts Qdrant, the API, and the Next.js UI in the background.

## Choose an architecture first

Open **Architecture** in the UI before indexing. It shows the complete flow and lets you finalise a compatible collection/profile.

- **Self-hosted** keeps video, models, and Qdrant on the laptop. The current **Index video** path uses X-CLIP for visual retrieval, CLAP for audio, Whisper transcription, and BGE-M3 for the transcript (`speech`) and caption-text fields. It starts in selection-only mode and can use local Qwen2.5-VL for optional captions. It needs local model downloads and Qdrant/Docker for persistent indexing.
- **API-based** uses Gemini Embedding 2 for four separate named vectors and Gemini Flash-Lite for transcription, query decomposition, captions, verification, and localisation. Qdrant Cloud holds the vectors, so no local Qdrant container or local model cache is needed for indexing. It requires a Gemini key, a Qdrant Cloud URL/key, and explicit consent before footage is uploaded.

OpenAI GPT-4.1 mini and NVIDIA Cosmos Reasoner are optional paid/credit-based
caption and verification choices in the API-based profile. They are not
interchangeable embedding profiles, and they are not defaults in the
self-hosted profile.

The optional **Qwen3-VL-Reranker-2B** is a hybrid precision stage: it runs locally only after RRF selects a small candidate set, so it needs no API key but downloads its model on first use. It is never run over the full library.

For the first end-to-end test, go to **Index video**, upload an MP4/WebM/MOV, leave **selection-only** enabled, and start indexing. When the job succeeds, open **Library** to inspect each indexed window, its transcript, vector metadata, and playable source video. Then use **Search** to query that same indexed collection.

Selection-only is the safe local default: it builds visual, audio, speech, and caption-placeholder vectors without sending video frames to a vision API. Captions become available only after an optional local Qwen-VL model or hosted vision API is explicitly configured.

## What indexing does

1. The server validates and probes the uploaded video, then splits it into overlapping time windows.
2. Each window gets four complementary signals in independent named vector fields; raw vectors are never averaged or concatenated. **Self-hosted** calls its text field `speech` (the window transcript), while **API-based** calls it `transcript`; both also retain separate visual, audio, and caption fields.
3. In **Self-hosted**, those fields use the current X-CLIP, CLAP, and BGE-M3 contract. In **API-based**, they use Gemini Embedding 2 in a separate 1536-D profile/collection. Unsupported files such as WebM are converted to bounded MP4/MP3 clips before the API calls.
4. API indexing transcribes non-overlapping audio chunks, maps the timestamped text into 20-second windows with a 10-second stride, captions only a bounded set of visual-change windows, and records per-stage requests, retries, timing, and quota errors in the job diagnostics.
5. **Library** shows the stored windows, timestamps, transcript/caption metadata, exact embedding profile, vector metadata, and playable source video. It is the visual check that indexing completed correctly.

## Search and verification flow

1. **Search** expands a natural-language request into visual, audio, text, and caption prompts. Each prompt is encoded in the compatible named-vector space and retrieves its own top candidates; the text channel maps to `speech` for Self-hosted and `transcript` for API-based.
2. Reciprocal-rank fusion (RRF) creates a recall-only candidate set, then adjacent matching windows are merged. The fusion score is shown as evidence only.
3. When enabled, Qwen3-VL-Reranker sees only the raw query plus each selected candidate's sampled frames, transcript, and caption. It produces a fresh relevance score and does not receive or combine an RRF/vector score.
4. An optional VLM verification pass looks only at the final few reranked candidates. It provides evidence and can narrow a broad match to a 2–5 second playback interval; it does not scan the full library or overwrite the cross-encoder semantics.
5. Search diagnostics include per-stage latency, modality contributions, reranker state, and labelled Recall@K, MRR, and nDCG when evaluation labels are supplied. Live searches correctly report those metrics as unevaluated without ground truth.

The UI does not persist either API key in local storage, project configuration, job reports, or search responses. Provider calls require the key you enter at runtime; a missing/invalid key produces an **unavailable** verification state instead of silently treating a result as verified.

## Local test assets

`test_assets/asset_library/` is a local-only staging area for lawfully sourced evaluation videos. Its manifest records the public source, license/rights information, duration, and SHA-256. Large media files are ignored by Git deliberately. The first staged asset is a 20-minute, public-domain dashcam vehicle-burglary video, suitable for confirming the full indexing path; see `test_assets/asset_library/README.md` for its provenance.

## Manual local development

The quickest Windows setup uses the launcher from the repository root:

```powershell
# First install only
.\start-local.ps1 -Setup

# Self-hosted: local Qdrant/Docker plus the API and UI
.\start-local.ps1

# API-based: API and UI only; Qdrant Cloud is configured in Architecture
.\start-local.ps1 -ApiOnly

# Replace an older API/UI process after pulling or changing this code
.\start-local.ps1 -ApiOnly -Restart
```

`-Restart` stops only the listeners on ports 8000 and 3000 before starting this project again. Do not use it while an indexing job is still running.

Use Python 3.11 or 3.12, FFmpeg/FFprobe, Docker, Node.js, and npm. Start Qdrant with:

```powershell
docker compose up -d qdrant
```

Create the Python environment and install all dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-processing.txt -r requirements.txt
```

Start the unified API:

```powershell
$env:HF_HOME = "$PWD\.model-cache"
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:PYTHONPATH = ""
$env:QUERY_LOW_MEMORY_MODE = "1"
python -m uvicorn processing_indexing.debug_api:app --host 127.0.0.1 --port 8000
```

In a second terminal, start the browser UI:

```powershell
Set-Location processing_debug_frontend
npm install
$env:NEXT_PUBLIC_PROCESSING_API_URL = "http://127.0.0.1:8000"
npm run dev
```

Open `http://localhost:3000`.

## Tests

```powershell
pytest processing_indexing/tests -m "not integration"
pytest query_retrieval/tests -m "not qdrant" -q

# Requires Docker/Qdrant. This uses only the isolated test collection and
# fails clearly if the database is unavailable.
docker compose up -d qdrant
pytest query_retrieval/tests -m qdrant -q --require-qdrant
```

The first real indexing/search run downloads the open model weights into `.model-cache`, so it may take a little longer. The full vision-caption route can use the optional local **Qwen2.5-VL-3B** model (the laptop default) or a configured hosted vision API; it is not required for indexing or searching locally.

`QUERY_LOW_MEMORY_MODE=1` is the recommended laptop setting. It encodes with X-CLIP, CLAP, and BGE-M3 one at a time and releases each model before Qdrant retrieval, trading repeat-query speed for reliable use alongside Docker on an 8 GB GPU/limited-memory machine. The optional Qwen3-VL reranker is also loaded only for its bounded second stage. Set `QUERY_LOW_MEMORY_MODE=0` on a larger machine if you prefer resident models and faster repeated searches.
