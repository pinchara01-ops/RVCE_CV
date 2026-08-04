# Accuracy-first video processing and indexing

The `processing_indexing` package validates video with FFprobe, hashes content for stable identity, transcribes the full file once, creates overlapping 10-second windows at a 5-second stride, and stores separate X-CLIP, CLAP, BGE-M3 speech, and BGE-M3 caption vectors in Qdrant. X-CLIP, CLAP, transcript mapping, and speech encoding run for every window. A two-pass selector sends only key windows to Qwen, using independent visual/audio/speech cosine changes, cumulative change from the last selected window, speech transitions, periodic refreshes, and recovery after failed or low-confidence VLM results.

## Requirements

Python 3.11 or 3.12, FFmpeg/FFprobe on `PATH`, and Qdrant are required. Install `requirements-processing.txt`. Model weights are downloaded only on first provider use, never at import. Budget roughly 15–30 GB for Hugging Face caches. CPU works but is slow; CUDA with a compatible PyTorch build and ample VRAM is recommended, particularly for Qwen.

```bash
pip install -r requirements-processing.txt
docker compose up -d qdrant
copy .env.processing.example .env
python -m processing_indexing.cli video.mp4 --device cpu --json-report
python -m processing_indexing.cli path/to/videos --batch-size 8
```

Progress goes to stderr; JSON reports go to stdout. Deterministic UUID point IDs make upserts idempotent and allow safe resume. Silent windows use a documented all-zero CLAP sentinel because Qdrant requires the named vector; `has_audio=false` prevents treating it as evidence. Model/provider errors fail that window and are never replaced by fake captions or embeddings.

The collection is `video_windows`, with Cosine named vectors `visual` (512), `audio` (512), `speech` (1024), and `caption` (1024). Existing incompatible collections are rejected, never deleted.

## Selective VLM configuration

Defaults are shown in `.env.processing.example`. The initial thresholds are visual `0.12`, audio `0.15`, speech `0.18`, and combined `0.13`; weights are `0.55/0.25/0.20`. Available weights are normalized per comparison, so missing audio or speech has zero influence. First/last windows, strong individual changes, speech starts/ends, and the three-window periodic refresh remain hard triggers. `VLM_MAX_SELECTED_RATIO=0.60` limits only lower-priority combined-only candidates; it never suppresses required hard triggers.

These defaults are engineering starting points, not accuracy claims. Tune them with labelled real videos and report call reduction separately from retrieval accuracy.

`VLM_MAX_GAP_WINDOWS=3` is measured in window starts, not window duration. With the default five-second stride, the periodic refresh allows at most approximately 15 seconds between selected-window start times (`3 × 5s`), not 30 seconds.

For an OpenAI-compatible hosted Qwen vision endpoint, set `VLM_PROVIDER=openai_compatible`, `VLM_BASE_URL`, `VLM_API_KEY`, `VLM_MODEL`, `VLM_TIMEOUT_SECONDS`, and `VLM_RETRIES`. The key is read only from the environment. The provider sends temporally distributed JPEG data URLs, requests a JSON object, applies limited retries/timeouts, and validates the returned content with the same `VLMDescription` Pydantic model. Leave `VLM_PROVIDER=local` for Hugging Face inference.

Every point retains all four named vectors. Direct captions have `caption_direct=true`. A skipped window may receive bounded, action-free scene context from the nearest successful direct window and is marked `caption_inherited=true`, `vlm_processed=false`, with its source and distance. With no safe source, `caption=""` and `caption_available=false`; its caption vector is the BGE-M3 encoding of the explicit `[CAPTION UNAVAILABLE]` sentinel. This maintains the fixed Qdrant schema without fabricating evidence.

The query pipeline must give full caption contribution only to direct captions, discount inherited captions, ignore caption vectors when `caption_available=false`, never treat inherited context as proof of a window-specific action, and use the actual candidate clip for final verification.

Run fast tests with `pytest processing_indexing/tests -m "not integration"`. The integration marker is deliberately opt-in and requires a local video, cached real models, and real Qdrant.
## Processing diagnostics (Next.js + FastAPI)

The temporary diagnostics UI lives in `processing_debug_frontend/`. It talks only to the Python debug API; browser code never imports model code or accepts API keys. Model loading starts only after a user uploads, validates, and explicitly starts a job.

PowerShell setup:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-processing.txt
Copy-Item .env.processing.example .env.processing
$env:OPENAI_API_KEY = Read-Host -AsSecureString "OpenAI key" | ConvertFrom-SecureString -AsPlainText
$env:VLM_PROVIDER = "openai"
python -m uvicorn processing_indexing.debug_api:app --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
Set-Location processing_debug_frontend
npm install
$env:NEXT_PUBLIC_PROCESSING_API = "http://127.0.0.1:8000"
npm run dev
```

Open `http://localhost:3000/processing`. The official OpenAI mode uses `gpt-4.1-mini` by default with the Responses API, up to four temporally ordered low-detail frames. Configure `OPENAI_VLM_MODEL`, `OPENAI_VLM_TIMEOUT_SECONDS`, `OPENAI_VLM_RETRIES`, `OPENAI_VLM_IMAGE_DETAIL`, and `OPENAI_VLM_MAX_FRAMES` server-side. Never put `OPENAI_API_KEY` in a `NEXT_PUBLIC_` variable.

The local production checkpoints are `small` (faster-whisper, corresponding to the Systran faster-whisper small family), `microsoft/xclip-base-patch32`, `laion/clap-htsat-unfused`, `BAAI/bge-m3`, and `Qwen/Qwen2.5-VL-7B-Instruct`. Preflight reports cache presence without loading or downloading them. Selector weights and thresholds are hand-configured heuristics, not learned model weights.

Mock VLM results can be indexed only into collections whose names begin with `debug_` or `mock_`. The four named-vector dimensions remain unchanged.
