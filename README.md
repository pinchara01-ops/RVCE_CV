# Accuracy-first video processing and indexing

The `processing_indexing` package validates video with FFprobe, hashes content for stable identity, transcribes the full file once, creates overlapping 10-second windows at a 5-second stride, and stores separate X-CLIP, CLAP, BGE-M3 speech, and BGE-M3 Qwen-caption vectors in Qdrant.

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

Run fast tests with `pytest processing_indexing/tests -m "not integration"`. The integration marker is deliberately opt-in and requires a local video, cached real models, and real Qdrant.
