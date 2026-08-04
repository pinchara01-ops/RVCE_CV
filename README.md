# Video Search Workbench

This local prototype lets a team upload a video, inspect how it is processed into multimodal video windows, persist those windows in Qdrant, and search the indexed collection from the same browser UI.

## What is in this branch

- `processing_indexing/`: video validation, overlapping windows, Whisper, X-CLIP, CLAP, BGE-M3, selective vision-language captions, and Qdrant writes.
- `query_retrieval/`: four-modality Qdrant retrieval, reciprocal-rank fusion, result-window merging, and optional LLM decomposition/verification.
- `processing_debug_frontend/`: the single Next.js UI for upload, indexing inspection, and search.

The local default is deliberately safe: no API key is required for the processing UI's selection-only mode, and query decomposition/verification remain disabled unless keys and flags are explicitly configured.

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
