# Processing and Indexing — Accuracy-First Contract

## Fixed V1 decisions

- Use one overlapping window scale: 10-second windows with a 5-second stride.
- Transcribe the complete video once with timestamped Whisper output, then attach overlapping transcript segments to each window.
- Process every window with X-CLIP, CLAP, and the Qwen VLM. Do not gate VLM calls using embedding-change thresholds.
- Embed transcript text and VLM captions separately with BGE-M3.
- Keep all four vectors separate; never concatenate or average them.
- Upsert one deterministic Qdrant point per window so reprocessing the same video is idempotent.
- Short/long dual windows are not part of V1.

## Required flow

1. Validate the video and derive a stable video ID.
2. Probe duration, streams, codec, FPS, and audio presence with FFprobe.
3. Extract/transcribe the full audio once. Silent video must remain indexable.
4. Generate windows: 0–10, 5–15, 10–20, including a final clipped window when needed.
5. For every window:
   - X-CLIP visual vector (512 dimensions).
   - CLAP audio vector (512 dimensions); define and test silent-window handling.
   - Overlapping Whisper transcript and BGE-M3 speech vector (1024 dimensions).
   - Detailed structured Qwen caption and BGE-M3 caption vector (1024 dimensions).
6. Validate dimensions, finite values, timestamps, IDs, and payload fields.
7. Create/validate the Qdrant collection and batch-upsert points.
8. Return machine-readable progress, counts, failures, and elapsed time.

## Qwen caption requirements

For every window, describe only supported evidence and include people/clothing, objects/colours, actions, object-action relationships, spatial relationships, visible text, scene/context, and approximate action timing inside the window. Do not invent sounds from frames. Return validated JSON first, then store a normalized searchable text caption.

## Qdrant contract

Collection: `video_windows`; distance: Cosine for every vector.

| Named vector | Dimension |
|---|---:|
| visual | 512 |
| audio | 512 |
| speech | 1024 |
| caption | 1024 |

Required payload per point:

```json
{
  "video_id": "stable-id",
  "window_id": "stable-id_window_0007",
  "start": 35.0,
  "end": 45.0,
  "transcript": "...",
  "caption": "...",
  "has_audio": true,
  "vlm_processed": true,
  "source_path": "/or/resolvable/url/video.mp4"
}
```

The query branch currently requires all fields except `source_path`; `source_path` is added now because query-time VLM verification needs to retrieve the real clip later.

## Required modules

- `probe.py`: FFprobe metadata and validation.
- `windowing.py`: deterministic overlapping windows and transcript alignment.
- `transcription.py`: full-video Whisper provider.
- `visual_encoder.py`: X-CLIP window encoder.
- `audio_encoder.py`: CLAP window encoder.
- `text_encoder.py`: BGE-M3 transcript/caption encoder.
- `vlm.py`: Qwen provider, structured output validation, retries/timeouts.
- `qdrant_store.py`: schema validation and idempotent batch upsert.
- `pipeline.py`: orchestration, progress, partial-failure reporting.
- `cli.py`: process one file or a directory.
- `tests/`: unit tests plus an optional real-model integration marker.

## Acceptance checks

- Window boundaries are correct for short, exact-length, fractional, and final partial windows.
- Transcript segments are mapped by timestamp, not duplicated blindly.
- Every successful point has exactly four correctly sized finite vectors.
- A silent video indexes successfully without fabricated audio evidence.
- Reprocessing does not duplicate points.
- Interrupted batch processing can resume safely.
- Collection mismatch fails with a useful error.
- One real test video can be indexed and searched by the query branch.
- Mocked tests prove plumbing only; report real-video accuracy separately.
