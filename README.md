# Query & Retrieval Module

## 1. Overview

This module is the **Query & Retrieval** half of a multimodal video search system built for a hackathon. Given a raw text query, it assigns per-modality weights (visual / audio / speech / caption) reflecting which are relevant, encodes the query into each relevant modality's embedding space, searches a Qdrant collection per modality, fuses the ranked lists into one, merges overlapping/adjacent hits from the same video into coherent regions, and returns a single ranked JSON response.

It was built standalone against a seeded dummy Qdrant collection, in parallel with a teammate's **Processing/Indexing** module (which populates the real collection from actual video). A third teammate integrates both by pointing this module's `/search` endpoint at the real collection — no code changes required here, as long as the indexing pipeline matches the contract in **Section 4**.

## 2. Architecture

```
                         POST /search {query, top_k}
                                   |
                                   v
                        +---------------------+
                        |    Query Router     |  router.py
                        | rule-based keyword   |
                        | classifier (V1 only) |
                        +---------------------+
                                   |
                     {visual, audio, speech, caption} weights
                                   |
                                   v
                        +---------------------+
                        |   Query Encoders    |  encoders.py
                        | X-CLIP / CLAP / BGE-M3 |
                        | (only nonzero-weight modalities) |
                        +---------------------+
                                   |
                        per-modality query vectors
                                   |
                                   v
                 +--------------------------------------+
                 |     Parallel Qdrant Retrieval          |  qdrant_client.py
                 |  search_visual / _audio / _speech / _caption  |
                 |  (top DEFAULT_TOP_K per modality)      |
                 +--------------------------------------+
                                   |
                     per-modality ranked hit lists
                                   |
                                   v
                        +---------------------+
                        |  Weighted RRF Fusion |  fusion.py
                        |  score = sum(weight * 1/(k+rank)) |
                        +---------------------+
                                   |
                       one ranked list of FusedHit
                                   |
                                   v
                        +---------------------+
                        |   Window Merging     |  merge_windows.py
                        | same video_id + overlap/gap<=5s |
                        | -> chained via running cluster end |
                        +---------------------+
                                   |
                      ranked list of MergedRegion
                                   |
                          request.top_k applied
                                   |
                                   v
                          SearchResponse JSON
```

Query encoding happens **separately per modality** rather than once: X-CLIP, CLAP, and BGE-M3 each produce embeddings in their own distinct vector space — a visual embedding and an audio embedding are not directly comparable numbers even if they happened to share a dimension, because nothing trained them to agree on what "close" means across models. Each named vector in Qdrant is only ever queried with a vector from its own corresponding encoder, never a shared/generic one.

That same cross-model incomparability is why fusion is RRF-based rank fusion rather than an average of raw cosine similarities: a 0.3 cosine score from CLAP and a 0.3 cosine score from BGE-M3 don't mean the same thing and can't be safely blended by value. RRF sidesteps this by fusing on *rank position* within each modality's own list instead, which is comparable across models by construction.

**Deviations from the original spec worth knowing about:**
- `top_k` is applied **after** fusion and merging, not before. Truncating earlier would let merge_windows() see an incomplete candidate set and silently produce narrower/incomplete regions — verified live as a real bug during a Phase 5 regression pass (see `tests/test_phase5_regression.py`).

| Stage | File |
|---|---|
| Modality weight assignment | `router.py` |
| Query embedding | `encoders.py` |
| Qdrant connection, search, schema validation, seeding | `qdrant_client.py`, `seed_dummy_data.py` |
| Fusion | `fusion.py` |
| Merging | `merge_windows.py` |
| HTTP contract | `api.py` |
| Shared types | `models.py` |
| All settings | `config.py` |

## 3. Tech Stack

- **Qdrant** — vector database, named-vector collection (`qdrant-client`)
- **FastAPI** + **pydantic** — HTTP contract and typed models
- **X-CLIP** (`microsoft/xclip-base-patch32`), **CLAP** (`laion/clap-htsat-unfused`), **BGE-M3** (`BAAI/bge-m3`) — query text encoders, via `transformers` / `sentence-transformers`, run on CPU by default
- **pytest** — 108 tests, no real network/model calls by default

**V1 is rule-based-only by design** (team decision): query routing is a deterministic keyword classifier, with no LLM/VLM component anywhere in the pipeline. No API dependency, no network latency, nothing that can be slow or flaky on demo day.

## 4. The Contract — what the Processing team must produce

This is the interface boundary. Match this exactly and integration requires zero code changes on either side.

**Qdrant collection** (from `config.py`, all env-overridable):

| Setting | Default | Env var |
|---|---|---|
| Host | `localhost` | `QDRANT_HOST` |
| Port | `6333` | `QDRANT_PORT` |
| Collection name | `video_windows` | `COLLECTION_NAME` |

**Named vectors** (exact names, dims, distance metric — all must match exactly):

| Vector name | Dim | Distance |
|---|---|---|
| `visual` | 512 | Cosine |
| `audio` | 512 | Cosine |
| `speech` | 1024 | Cosine |
| `caption` | 1024 | Cosine |

**Payload schema** (one Qdrant point per window):

| Field | Type | Notes |
|---|---|---|
| `video_id` | `str` | required |
| `window_id` | `str` | required, format: `<video_id>_window_<4-digit index>`, e.g. `abc123_window_0007` |
| `start` | `float` | seconds, required |
| `end` | `float` | seconds, required (can equal `start` for a zero-duration window — handled) |
| `transcript` | `str` | optional, default `""` |
| `caption` | `str` | optional, default `""` |
| `has_audio` | `bool` | optional, default `False` |
| `vlm_processed` | `bool` | optional, default `False` |

**Feature flags** (`ENABLE_OCR`, `ENABLE_OBJECTS`): when a flag is off upstream, the corresponding field/vector may simply be **absent** from a point (not present with a null/zero value — genuinely missing). Every read path in this module already tolerates that:
- Missing named vector on a point → that point just won't surface from a search against that vector; no error.
- Missing payload field → defaults to `""` / `False` via `WindowPayload`'s pydantic defaults, never a crash.

**Self-check before integration**: call `qdrant_client.validate_collection_schema()` against the real collection. Returns `[]` if it matches this contract exactly, or a list of human-readable mismatch strings (missing vector, wrong dim, wrong distance, unexpected extra vector) if not. Point it at the real collection the moment it exists — catches drift before it becomes an integration bug.

## 5. Setup & Running

```bash
pip install -r requirements.txt
```
(Note: `torch`/`transformers`/`sentence-transformers` were missing from `requirements.txt` for a while during development despite being required by `encoders.py` — a fresh install would've silently failed. Fixed; they're in there now.)

**Environment variables:**

| Var | Required? | Default | Purpose |
|---|---|---|---|
| `QDRANT_HOST` | no | `localhost` | Qdrant connection |
| `QDRANT_PORT` | no | `6333` | Qdrant connection |
| `QDRANT_API_KEY` | no | none | Qdrant auth, if used |
| `COLLECTION_NAME` | no | `video_windows` | contract collection name |
| `VISUAL_DIM` / `AUDIO_DIM` / `SPEECH_DIM` / `CAPTION_DIM` | no | 512/512/1024/1024 | vector dims |
| `ENABLE_OCR` / `ENABLE_OBJECTS` | no | `true` | upstream feature flags (payload presence only, not read by this module's logic) |
| `RRF_K` | no | `60` | RRF fusion constant |
| `DEFAULT_TOP_K` | no | `15` | per-modality Qdrant search depth |
| `MERGE_GAP_SECONDS` | no | `5.0` | window merge time-gap threshold |
| `MIN_MODALITY_WEIGHT` | no | `0.05` | router weights below this are zeroed |
| `DEVICE` | no | `cpu` | encoder device |
| `HF_HUB_OFFLINE` | no | unset | set to `1` once models are cached — see cold start below |

No LLM/API key configuration exists in V1 — the router is rule-based only (see Section 3), so there's no "demo-safe" toggle to remember; it behaves identically every run.

**Start Qdrant** (as used throughout development):
```bash
docker run -d --name qdrant-test -p 6333:6333 qdrant/qdrant:latest
```

**Seed dummy data** (standalone testing, no real indexing pipeline needed):
```bash
python -m query_retrieval.seed_dummy_data
```
Seeds 33 points covering: visual-only / audio-only / all-4-modality windows, overlapping same-event windows, fully disjoint windows, a deliberately near-identical "true match" pair, a deliberate hard negative, a short (2-window) video, a long video mixing tightly-clustered and far-apart windows, two different videos with near-identical content at identical timestamps (proves merge never crosses `video_id`), and edge-case timestamps (zero-duration window, very large start/end).

**Start the server:**
```bash
uvicorn query_retrieval.api:app --reload
```

**Cold start time** (encoder warmup, measured live):
- **~258s (4.3 min)** on a fresh process, even with model weights already cached locally — dominated by ~67 HTTP calls to huggingface.co for Hub metadata (commits, file listings), not actual weight loading.
- **~10s** with `HF_HUB_OFFLINE=1` set, once models are cached — skips the metadata round-trips entirely. **Requires one online run first** to populate the local HF cache; `HF_HUB_OFFLINE=1` on a machine that's never downloaded the models will fail outright.
- `/health` correctly returns `503 {"status": "loading"}` for the entire warmup window in both cases, confirmed by polling it live through a real cold start — never falsely reports ready early.

## 6. API Contract

### `POST /search`

**Request:**
```json
{"query": "dog barking", "top_k": 3}
```
| Field | Type | Notes |
|---|---|---|
| `query` | `str` | required |
| `top_k` | `int` | optional, default `10`, range `0`–`10000` |

**Response** (real output from a live run against the seeded collection):
```json
{
  "results": [
    {
      "video_id": "video_full",
      "window_id": "video_full_window_0002",
      "start": 0.0,
      "end": 12.0,
      "transcript": "Narrator describes scene 2",
      "caption": "A fully-annotated scene 2",
      "score": 0.015018315018315017,
      "matched_modalities": ["audio", "visual"]
    },
    {
      "video_id": "video_f",
      "window_id": "video_f_window_0000",
      "start": 0.0,
      "end": 5.0,
      "transcript": "completely unrelated content",
      "caption": "completely unrelated content",
      "score": 0.01092896174863388,
      "matched_modalities": ["audio"]
    }
  ],
  "query_weights": {"visual": 0.333, "audio": 0.667, "speech": 0.0, "caption": 0.0}
}
```

| Response field | Meaning |
|---|---|
| `query_weights` | router's per-modality weight split for this query (sums to 1.0) |
| `matched_modalities` | which of the 4 modalities this region was actually retrieved through — a region matched on multiple modalities ranks higher via RRF summation |
| `score` | the region's fused RRF score (post-merge: max of its constituent windows' fused scores) |

(`source_window_ids` — the list of original window_ids a merged region absorbed — exists on the internal `MergedRegion` model for debugging/traceability but isn't currently exposed on the external `SearchResultItem`; ask if you want it surfaced.)

### `GET /health`

Returns `503 {"status": "loading"}` until encoder warmup genuinely completes, `200 {"status": "ok"}` after. This matters because relying on implicit ASGI startup-blocking behavior would be a latent race condition — a future change to workers/lifespan handling could let a request through before warmup finishes, and a demo's first query would eat the full multi-minute cold-start cost instead of a health poll cleanly catching it. Poll this before sending real traffic.

## 7. Testing

```bash
pytest query_retrieval/tests/ -q
```

**Current status: 88/88 passing**, ~3s, zero real network/model calls (encoders are mocked at the appropriate boundary in every test).

Coverage, by area:
- **Router**: keyword fallback per modality + mixed queries, threshold/renormalize math, gibberish/empty-string never raising
- **Encoders**: shape/dim correctness per modality, weight-gated dispatch (zero-weight modalities never call their model), partial-failure isolation
- **Fusion**: hand-computed RRF scores including a worked rank-1-vs-two-rank-10s example, summation-not-max verified explicitly, empty/zero-weight edge cases
- **Merging**: no-merge, simple overlap, chained A-B-C merge, cross-video never-merges, inclusive/exclusive gap boundary
- **Integration/failure-path**: Qdrant genuinely unreachable, empty query, `top_k=0` and `top_k=10000`, zero-match query, `/health` gating, schema validator pass/fail — all through the real `/search` endpoint
- **Comprehensive query variety**: pure visual/audio/speech/caption, mixed, gibberish, long paragraph, single-word, emoji/unicode, empty string
- **Comprehensive video/window variety**: short/long/silent/full-modality videos, cross-video duplicates, zero-duration and huge-timestamp windows — against real seeded data, not synthetic
- **System-level**: first-query-after-startup, 12 rapid sequential queries, 5 concurrent threaded requests (no cross-contamination), malformed request bodies (422 not 500), empty-collection

**Manual sanity check** — 15 curated realistic queries with readable printed output:
```bash
python demo_queries.py
```

## 8. Known Limitations / Read Before Demo

- **V1 is rule-based-only by design** (team decision) — the keyword router is deterministic and has no network dependency, so there's nothing to flag about LLM latency or availability. If a smarter/LLM-based router or any form of automated summarization is wanted later, that's new work against this architecture, not a flag flip.
- **Fresh machine setup needs one online run** before `HF_HUB_OFFLINE=1` works — it skips Hub metadata lookups but still needs the model weights already downloaded into the local cache from a prior online run.

## 9. Project Status

**Built and feature-complete for the V1 architecture:**
1. Project skeleton, Qdrant client, dummy data seeding
2. Query router (rule-based keyword classifier)
3. Query encoders (X-CLIP / CLAP / BGE-M3)
4. Weighted RRF fusion
5. Window merging (chained, cross-video-safe)

Plus two dedicated hardening passes: a full integration/failure-path audit (Qdrant-down, malformed input, boundary top_k values, schema drift detection) and a comprehensive realistic-scenario pass (query variety, video/window variety, concurrency, cold start). An LLM-based router upgrade and VLM-based summarization stage were built and evaluated during development, then removed per team review — V1 ships rule-based-only (see Section 3).

**Explicitly out of scope for this module** (Processing team's responsibility): video file storage, frame extraction, actual transcription/captioning/embedding generation, writing points into Qdrant. This module only *reads* from the `video_windows` collection per the contract in Section 4 — it never writes indexing data.
