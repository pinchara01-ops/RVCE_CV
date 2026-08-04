# Video Search Workbench

This local prototype lets a team upload a video, inspect how it is processed into multimodal video windows, persist those windows in Qdrant, and search the indexed collection from the same browser UI.

## What is in this branch

- `processing_indexing/`: video validation, overlapping windows, Whisper, X-CLIP, CLAP, BGE-M3, selective vision-language captions, and Qdrant writes.
- `query_retrieval/`: four-modality Qdrant retrieval, reciprocal-rank fusion, result-window merging, and optional LLM decomposition/verification.
- `processing_debug_frontend/`: the single Next.js UI for upload, indexing inspection, and search.

The local default is deliberately safe: no API key is required for the processing UI's selection-only mode. When you choose a hosted VLM in the UI, its key is held only for that request/job: it is cleared from the form after submission and is redacted from job status and saved reports.

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

For the first end-to-end test, go to **Index video**, upload an MP4/WebM/MOV, leave **selection-only** enabled, and start indexing. When the job succeeds, open **Library** to inspect each indexed window, its transcript, vector metadata, and playable source video. Then use **Search** to query that same indexed collection.

Selection-only is the safe local default: it builds visual, audio, speech, and caption-placeholder vectors without sending video frames to a vision API. Captions become available only after a vision API is explicitly configured.

## What indexing does

1. The server validates and probes the uploaded video, then splits it into overlapping time windows.
2. Each window gets four complementary signals: X-CLIP visual embeddings, CLAP audio embeddings, Whisper speech/transcript, and BGE-M3 text embeddings. The window, timestamps, and generated metadata are written to Qdrant when **Save real vectors into Qdrant** is checked.
3. In **Selection only** mode, all of that runs locally and no video frames are sent to a hosted model. Selecting **OpenAI VLM captions** or **NVIDIA Cosmos Reasoner captions** additionally sends sampled frames for each window to that provider to create visual captions.
4. **Library** shows the stored windows, timestamps, transcript/caption metadata, and playable source video. It is the visual check that indexing completed correctly.

## Search and verification flow

1. **Search** can decompose a natural-language request into visual, audio, speech, and metadata subqueries. Each non-zero modality retrieves relevant windows from Qdrant and reciprocal-rank fusion combines them.
2. Nearby hits are merged into a usable video interval. Retrieval alone remains available with no key.
3. Optionally select **OpenAI** or **NVIDIA Cosmos** under **Search options**, paste the key, and submit. The API samples frames from only the top returned candidate windows and asks the VLM to check the requested event and required conditions.
4. Verified hits are reranked above rejected ones. The result card shows the VLM evidence, whether it was verified/rejected/unavailable, and a refined start/end time when the VLM could narrow it. Unchecked lower-ranked candidates are still visible, clearly marked as such.

The UI does not persist either API key in local storage, project configuration, job reports, or search responses. Provider calls require the key you enter at runtime; a missing/invalid key produces an **unavailable** verification state instead of silently treating a result as verified.

## Local test assets

`test_assets/asset_library/` is a local-only staging area for lawfully sourced evaluation videos. Its manifest records the public source, license/rights information, duration, and SHA-256. Large media files are ignored by Git deliberately. The first staged asset is a 20-minute, public-domain dashcam vehicle-burglary video, suitable for confirming the full indexing path; see `test_assets/asset_library/README.md` for its provenance.

## Manual local development

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
pytest query_retrieval/tests -q
```

The first real indexing/search run downloads the open model weights into `.model-cache`, so it may take a little longer. The full vision-caption route additionally needs a configured vision API; it is not required for indexing or searching locally.

`QUERY_LOW_MEMORY_MODE=1` is the recommended laptop setting. It encodes with X-CLIP, CLAP, and BGE-M3 one at a time and releases each model before Qdrant retrieval, trading repeat-query speed for reliable use alongside Docker on an 8 GB GPU/limited-memory machine. Set it to `0` on a larger machine if you prefer resident models and faster repeated searches.
