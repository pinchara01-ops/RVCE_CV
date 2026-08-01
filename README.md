# Query & Retrieval Module

## 1. Overview

This module is the **Query & Retrieval** half of a multimodal video search system built for a hackathon. Given a raw text query, it encodes the query into all 4 modality embedding spaces (visual / audio / speech / caption), searches a Qdrant collection per modality, fuses the ranked lists into one via Reciprocal Rank Fusion, merges overlapping/adjacent hits from the same video into coherent regions, and returns a single ranked JSON response.

It was built standalone against a seeded dummy Qdrant collection, in parallel with a teammate's **Processing/Indexing** module (which populates the real collection from actual video). A third teammate integrates both by pointing this module's `/search` endpoint at the real collection — no code changes required here, as long as the indexing pipeline matches the contract in **Section 4**.

## 2. Architecture

```
                         POST /search {query, top_k}
                                   |
                                   v
                        +---------------------+
                        |   Query Encoders    |  encoders.py
                        | X-CLIP / CLAP / BGE-M3 |
                        | (always all 4 modalities) |
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
                        |      RRF Fusion      |  fusion.py
                        |  score = sum(1/(k+rank)) |
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

Query encoding happens **separately per modality** rather than once: X-CLIP, CLAP, and BGE-M3 each produce embeddings in their own distinct vector space — a visual embedding and an audio embedding are not directly comparable numbers even if they happened to share a dimension, because nothing trained them to agree on what "close" means across models. Each named vector in Qdrant is only ever queried with a vector from its own corresponding encoder, never a shared/generic one. This is now the central design fact of the pipeline: since there's no router picking a subset, every query pays the cost of all 3 models and gets a real comparable vector in each of the 4 spaces.

That same cross-model incomparability is why fusion is RRF-based rank fusion rather than an average of raw cosine similarities: a 0.3 cosine score from CLAP and a 0.3 cosine score from BGE-M3 don't mean the same thing and can't be safely blended by value. RRF sidesteps this by fusing on *rank position* within each modality's own list instead, which is comparable across models by construction.

### Why we removed query routing

V1 originally had a keyword-based router upstream of encoding, assigning per-modality weights so only "relevant" modalities got encoded and searched. It was removed for two concrete, demonstrated problems, not a hunch:

1. **A real substring-matching bug.** The router did plain `if keyword in query` matching, not word-boundary matching. `"the gardener watered the plants"` matched the visual color keyword `"red"` — because `"watered"` contains the literal substring `"r-e-d"`. This wasn't a rare edge case; the same class of bug affects any keyword that happens to be a substring of a common word (`"car"` in "scared", `"cat"` in "vacation", `"hat"` in "that").
2. **A hard vocabulary ceiling.** The router only recognized ~70 hardcoded words. Any query phrased outside that list fell back to caption-only search, silently losing visual/audio/speech signal for queries that should have used it (e.g. `"someone stole the milk"` — a visually meaningful event with no matching keyword).

Patching the keyword list indefinitely wasn't a real fix, and reintroducing an LLM router was already rejected earlier in development for latency/reliability reasons (Gemini call latency measured anywhere from 1.5s to 80s+ in testing). Instead: query encoding across all 3 models measures at **~340ms** (Section 8 has the full breakdown), which the team judged cheap enough relative to the rest of the pipeline that routing wasn't worth the complexity or the bug surface. RRF already suppresses irrelevant modalities naturally — an irrelevant modality's hits rank low within its own list and contribute a correspondingly tiny `1/(k+rank)` score — so an explicit router was solving a problem fusion already handles.

**Deviations from the original spec worth knowing about:**
- `top_k` is applied **after** fusion and merging, not before. Truncating earlier would let merge_windows() see an incomplete candidate set and silently produce narrower/incomplete regions — verified live as a real bug during a Phase 5 regression pass (see `tests/test_phase5_regression.py`).

| Stage | File |
|---|---|
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
- **pytest** — 74 tests, no real network/model calls by default

**No query routing and no LLM/VLM component anywhere in the pipeline** (team decision, see Section 2 for the full reasoning): every query always encodes and searches all 4 modalities. No API dependency, no network latency, nothing that can be slow or flaky on demo day.

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
| `DEVICE` | no | `cpu` | encoder device |
| `HF_HUB_OFFLINE` | no | unset | set to `1` once models are cached — see cold start below |

No LLM/API key configuration exists — there's no query router at all (see Section 2), so there's no "demo-safe" toggle to remember; behavior is identical every run.

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

**Response** (real output from a live run against the seeded collection, query `"someone stole the milk from the fridge"` - no keywords in that query would have matched the old router's list, and it's answered correctly anyway since all 4 modalities are always searched now):
```json
{
  "results": [
    {
      "video_id": "video_full",
      "window_id": "video_full_window_0001",
      "start": 0.0,
      "end": 12.0,
      "transcript": "Narrator describes scene 1",
      "caption": "A fully-annotated scene 1",
      "score": 0.060652161156193415,
      "matched_modalities": ["audio", "caption", "speech", "visual"]
    },
    {
      "video_id": "video_c",
      "window_id": "video_c_window_0002",
      "start": 10.0,
      "end": 15.0,
      "transcript": "A dog barks loudly",
      "caption": "A dog is barking near a fence",
      "score": 0.045504271360285405,
      "matched_modalities": ["audio", "speech", "visual"]
    }
  ]
}
```

| Response field | Meaning |
|---|---|
| `matched_modalities` | which of the 4 modalities this region was actually retrieved through — a region matched on multiple modalities ranks higher via RRF summation. Since all 4 are now always searched, this is typically 2-4 modalities per hit (was usually 1-2 under the old router, which only searched what it guessed was relevant) |
| `score` | the region's fused RRF score (post-merge: max of its constituent windows' fused scores) |

(`source_window_ids` — the list of original window_ids a merged region absorbed — exists on the internal `MergedRegion` model for debugging/traceability but isn't currently exposed on the external `SearchResultItem`; ask if you want it surfaced.)

### `GET /health`

Returns `503 {"status": "loading"}` until encoder warmup genuinely completes, `200 {"status": "ok"}` after. This matters because relying on implicit ASGI startup-blocking behavior would be a latent race condition — a future change to workers/lifespan handling could let a request through before warmup finishes, and a demo's first query would eat the full multi-minute cold-start cost instead of a health poll cleanly catching it. Poll this before sending real traffic.

## 7. Testing

```bash
pytest query_retrieval/tests/ -q
```

**Current status: 74/74 passing**, ~4s, zero real network/model calls (encoders are mocked at the appropriate boundary in every test).

Coverage, by area:
- **Encoders**: shape/dim correctness per modality, all 4 always called (no gating), partial-failure isolation (one modality failing doesn't fail the request)
- **Fusion**: hand-computed unweighted RRF scores including a worked rank-1-vs-two-rank-10s example, summation-not-max verified explicitly, empty-results edge cases
- **Merging**: no-merge, simple overlap, chained A-B-C merge, cross-video never-merges, inclusive/exclusive gap boundary
- **Integration/failure-path**: Qdrant genuinely unreachable, empty query, `top_k=0` and `top_k=10000`, zero-match query, `/health` gating, schema validator pass/fail — all through the real `/search` endpoint
- **Comprehensive query variety**: pure visual/audio/speech/caption-flavored, mixed, gibberish, long paragraph, single-word, emoji/unicode, empty string - all confirmed to search safely, not to any particular weight split (there isn't one anymore)
- **Comprehensive video/window variety**: short/long/silent/full-modality videos, cross-video duplicates, zero-duration and huge-timestamp windows — against real seeded data, not synthetic
- **System-level**: first-query-after-startup, 12 rapid sequential queries, 5 concurrent threaded requests (result-level cross-contamination check against known-good sequential results, using deterministic per-query-text fake vectors), malformed request bodies (422 not 500), empty-collection

**Manual sanity check** — 15 curated realistic queries with readable printed output:
```bash
python demo_queries.py
```

## 8. Known Limitations / Read Before Demo

- **No query router, no LLM/VLM component anywhere** (team decision, see Section 2) — deterministic, no network dependency, nothing to flag about availability or LLM latency. If a smarter/LLM-based router or any form of automated summarization is wanted later, that's new work against this architecture, not a flag flip.
- **Always searching all 4 modalities has a small, fixed latency cost.** Measured live: `encode_query()` across X-CLIP + CLAP + BGE-M3×2 takes **~340ms** (visual ~25ms, audio ~57ms, speech ~140ms, caption ~116ms), and a full `/search` call runs ~330-345ms steady-state - Qdrant search/fusion/merge are negligible against that on this dev collection size. This is a flat cost on every query regardless of content, versus the old router's variable (sometimes lower, sometimes similar) cost depending on how many modalities it guessed were relevant. The team judged this an acceptable, predictable tradeoff for the correctness gain (Section 2) — worth re-measuring against real indexed data volume before the actual demo, since Qdrant's own per-modality search cost will grow with real collection size in a way this dev-scale measurement doesn't capture.
- **Fresh machine setup needs one online run** before `HF_HUB_OFFLINE=1` works — it skips Hub metadata lookups but still needs the model weights already downloaded into the local cache from a prior online run.
- **Never run against real indexed data.** Everything tested so far (74 tests + `demo_queries.py`) runs against synthetic seed data designed to exercise specific behaviors. Real captions/transcripts from the Processing team's pipeline could be empty, malformed, extremely long, non-English, or structured differently than the synthetic data assumes. This is the single biggest unknown before demo.
- **`validate_collection_schema()` has never run against a real collection.** It's built and tested against the seeded dev collection, but the real check — pointing it at the Processing team's actual Qdrant collection — hasn't happened because that collection doesn't exist yet. Run it first, before anything else, the moment real data is available.
- **Scale is untested.** The dev collection has 33 points; a real video corpus could be thousands or millions of windows. The ~340ms encoding latency (above) is measured at toy scale — Qdrant's own per-modality search cost will grow with real data volume in a way this hasn't measured.
- **`MERGE_GAP_SECONDS=5.0` and `DEFAULT_TOP_K=15`** are reasonable defaults chosen without real data, not validated against the Processing team's actual windowing scheme (window size, overlap convention). May need retuning once real windows are indexed.
- **No load testing.** Concurrency was verified with 5 threads in-process (Section 7); this is not equivalent to real concurrent production traffic.
- **No security review.** No auth, no rate limiting — input validation is pydantic type-checking only. Acceptable for an internal team demo; not acceptable if this is ever exposed beyond that.
- **Recommended before calling this handed-off**: run `validate_collection_schema()` against the real collection first, then run `demo_queries.py` (or equivalent real queries) against real indexed content, and see what breaks — that gap between synthetic and real data is the actual remaining risk, and it can only be closed with real data in hand.

## 9. Project Status

**Built and feature-complete for the current architecture:**
1. Project skeleton, Qdrant client, dummy data seeding
2. Query encoders (X-CLIP / CLAP / BGE-M3), always all 4 modalities
3. Unweighted RRF fusion
4. Window merging (chained, cross-video-safe)

Plus two dedicated hardening passes: a full integration/failure-path audit (Qdrant-down, malformed input, boundary top_k values, schema drift detection) and a comprehensive realistic-scenario pass (query variety, video/window variety, concurrency, cold start). Two upstream stages were built, evaluated, and then removed per team review as the architecture matured: a keyword-based query router (removed for a real substring-matching bug and a hard vocabulary ceiling - see Section 2), and an LLM-based VLM summarization stage (removed earlier for latency/reliability reasons). The current pipeline always searches all 4 modalities and relies on RRF fusion to suppress irrelevant ones through rank.

**Explicitly out of scope for this module** (Processing team's responsibility): video file storage, frame extraction, actual transcription/captioning/embedding generation, writing points into Qdrant. This module only *reads* from the `video_windows` collection per the contract in Section 4 — it never writes indexing data.
