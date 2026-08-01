# Query & Retrieval Module

## 1. Overview

This module is the **Query & Retrieval** half of a multimodal video search system built for a hackathon. Given a raw text query, it encodes the query into all 4 modality embedding spaces (visual / audio / speech / caption), searches a Qdrant collection per modality, fuses the ranked lists into one via Reciprocal Rank Fusion, merges overlapping/adjacent hits from the same video into coherent regions, and returns a single ranked JSON response.

It was built standalone against a seeded dummy Qdrant collection, in parallel with a teammate's **Processing/Indexing** module (which populates the real collection from actual video). A third teammate integrates both by pointing this module's `/search` endpoint at the real collection — no code changes required here, as long as the indexing pipeline matches the contract in **Section 4**.

A demo frontend lives in `/frontend` and already calls this module's real `/search` endpoint — see **Section 10**.

## 2. Architecture

```
                         POST /search {query, top_k}
                                   |
                                   v
                        +---------------------+
                        |   Query Encoders    |  encoders.py
                        | X-CLIP / CLAP / BGE-M3 |
                        | (always all 4 modalities, run concurrently) |
                        +---------------------+
                                   |
                        per-modality query vectors
                                   |
                                   v
                 +--------------------------------------+
                 |     Concurrent Qdrant Retrieval        |  qdrant_client.py
                 |  search_visual / _audio / _speech / _caption  |
                 |  (top DEFAULT_TOP_K per modality, thread pool) |
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
                        | bounded by MAX_MERGE_DURATION_SECONDS / |
                        | MAX_MERGE_WINDOW_COUNT (splits, doesn't drop) |
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

### Concurrent modality search

The 4 encoder calls (X-CLIP, CLAP, BGE-M3 x2) and the 4 Qdrant searches were each running **sequentially** — one modality's model call or network round-trip blocking the next for no reason, since none of the 4 depend on each other's output. Both stages now run their 4 modality-calls concurrently via a reused `ThreadPoolExecutor` (`encoders._encode_executor`, `api._search_executor`) instead of a plain loop:

- `encoders.encode_query()` submits all 4 encoder calls at once; a per-modality failure is still caught and dropped independently (unchanged behavior), it just no longer blocks the other 3 while it's happening.
- `api.search()` submits all 4 Qdrant searches at once against the same `QdrantClient` (thread-safe for concurrent requests — each is an independent HTTP call).
- The one shared-state case — `speech` and `caption` both calling `.encode()` on the *same* BGE-M3 model instance — is serialized with a small lock (`encoders._bge_m3_lock`) rather than assumed thread-safe, since sentence-transformers doesn't document concurrent-call safety for one instance.

**Real measured latency, before vs after** (10-sample steady-state average, real X-CLIP/CLAP/BGE-M3 encoders + real Qdrant against the seeded dev collection, `curl -w time_total`, first/cold request excluded from both):

| | avg | samples |
|---|---|---|
| Before (sequential) | **~358ms** | 10 |
| After (concurrent) | **~290ms** | 19 (two batches) |

About a **19% reduction** (~70ms/query) at this dev-scale collection (33 points). The saving is bounded by whichever single modality is slowest in each stage (X-CLIP/CLAP/BGE-M3 forward pass, or the slowest Qdrant search) rather than the sum of all 4 — expect the gain to matter more, not less, once real indexed data makes individual Qdrant searches slower.

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
- **pytest** — 82 tests, no real network/model calls by default

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

**Reconfirmed against the actual dev collection** (not just `config.py`/`models.py` read from memory — queried live via `GET /collections/video_windows` and a payload scroll): collection name `video_windows`, 33 points, named vectors `visual`(512, Cosine) / `audio`(512, Cosine) / `speech`(1024, Cosine) / `caption`(1024, Cosine), payload fields exactly as listed above (`video_id`, `window_id` in the `<video_id>_window_<4-digit>` format, `start`, `end`, `transcript`, `caption`, `has_audio`, `vlm_processed`) — no drift found.

**Known blocker for a future VLM stage**: there is no field on the payload today that points at an actual video file, frame, or clip — no path, URL, or byte offset, nothing to hand a VLM to look at. `vlm_processed: bool` exists but is just a flag, not a pointer to content. Adding real VLM verification later needs this field added to the indexing contract first; it isn't something this module can invent or stub in.

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
| `MAX_MERGE_DURATION_SECONDS` | no | `60.0` | caps a merged region's total time span (see Section 2 merge caps) |
| `MAX_MERGE_WINDOW_COUNT` | no | `8` | caps the number of windows chained into one merged region |
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
      "score": 0.06075604519450862,
      "matched_modalities": ["audio", "caption", "speech", "visual"],
      "modality_evidence": [
        {"modality": "visual", "rank": 1, "contribution": 0.01639344262295082},
        {"modality": "audio", "rank": 6, "contribution": 0.015151515151515152},
        {"modality": "speech", "rank": 7, "contribution": 0.014925373134328358},
        {"modality": "caption", "rank": 10, "contribution": 0.014285714285714285}
      ],
      "state": "retrieved"
    },
    {
      "video_id": "video_c",
      "window_id": "video_c_window_0002",
      "start": 10.0,
      "end": 15.0,
      "transcript": "A dog barks loudly",
      "caption": "A dog is barking near a fence",
      "score": 0.046679405392392875,
      "matched_modalities": ["audio", "speech", "visual"],
      "modality_evidence": [
        {"modality": "visual", "rank": 4, "contribution": 0.015625},
        {"modality": "audio", "rank": 7, "contribution": 0.014925373134328358},
        {"modality": "speech", "rank": 2, "contribution": 0.016129032258064516}
      ],
      "state": "retrieved"
    }
  ]
}
```

| Response field | Meaning |
|---|---|
| `matched_modalities` | which of the 4 modalities this region was actually retrieved through — a region matched on multiple modalities ranks higher via RRF summation. Since all 4 are now always searched, this is typically 2-4 modalities per hit (was usually 1-2 under the old router, which only searched what it guessed was relevant) |
| `score` | the region's fused RRF score (post-merge: max of its constituent windows' fused scores) |
| `modality_evidence` | per-modality breakdown of that score: for each matched modality, its `rank` in that modality's own Qdrant search and the `contribution` (`1/(RRF_K+rank)`) it added. Entries always sum to `score` exactly (see `tests/test_fusion.py::test_modality_evidence_contributions_sum_to_fused_score`, `tests/test_merge_windows.py::test_merged_region_modality_evidence_comes_from_best_hit_and_sums_to_fused_score`) — this is what `matched_modalities` alone couldn't show: *why* a candidate ranked where it did. |
| `state` | always `"retrieved"` today — there is no verification stage in this pipeline (see "Known blockers" below). A plain string, not an enum/Literal, specifically so a future verification stage can add `"verified"`/`"rejected"` without a breaking schema change for existing consumers. |

(`source_window_ids` — the list of original window_ids a merged region absorbed — exists on the internal `MergedRegion` model for debugging/traceability but isn't currently exposed on the external `SearchResultItem`; ask if you want it surfaced.)

**Failure responses:** `/search` returns `503 {"detail": "..."}` (FastAPI's standard `HTTPException` shape) in two cases, never a silent empty/fake result:
- Every query encoder failed (`encode_query()` returned an empty dict) → `"All query encoders failed; search is unavailable."`
- Qdrant is genuinely unreachable (connection refused/timeout/DNS failure — as opposed to a live server returning "collection not found", which still means real zero matches and stays a normal `200 {"results": []}`) → `"Qdrant is unreachable; search is unavailable: ..."`

See **Section 8, Production safety** for why this distinction exists.

### `GET /health`

Returns `503 {"status": "loading"}` until encoder warmup genuinely completes, `200 {"status": "ok"}` after. This matters because relying on implicit ASGI startup-blocking behavior would be a latent race condition — a future change to workers/lifespan handling could let a request through before warmup finishes, and a demo's first query would eat the full multi-minute cold-start cost instead of a health poll cleanly catching it. Poll this before sending real traffic.

## 7. Testing

```bash
pytest query_retrieval/tests/ -q
```

**Current status: 82/82 passing** (was 74/74 before this pass — 8 net-new tests added, one existing test rewritten in place, none deleted), ~3s, zero real network/model calls (encoders are mocked at the appropriate boundary in every test).

Coverage, by area:
- **Encoders**: shape/dim correctness per modality, all 4 always called concurrently (no gating), partial-failure isolation (one modality failing doesn't fail the request)
- **Fusion**: hand-computed unweighted RRF scores including a worked rank-1-vs-two-rank-10s example, summation-not-max verified explicitly, empty-results edge cases, **modality_evidence rank/contribution correctness and sum-to-fused_score invariant** (new)
- **Merging**: no-merge, simple overlap, chained A-B-C merge, cross-video never-merges, inclusive/exclusive gap boundary, **bounded-merge splitting at MAX_MERGE_WINDOW_COUNT and MAX_MERGE_DURATION_SECONDS with hand-verified region boundaries, cap-splitting never crosses video_id, MergedRegion.modality_evidence sums to fused_score** (new)
- **Integration/failure-path**: Qdrant genuinely unreachable → **503 with a descriptive error, not a silent empty/mock result** (behavior change - see Production safety below), all query encoders failing → **503** (new), empty query, `top_k=0` and `top_k=10000`, zero-match query, `/health` gating, schema validator pass/fail — all through the real `/search` endpoint
- **Concurrency correctness** (new): the 4 concurrent Qdrant searches don't mix up results across modalities within one request (distinct per-modality search functions + distinct video_ids, asserting each result traces back to its own modality's search)
- **Comprehensive query variety**: pure visual/audio/speech/caption-flavored, mixed, gibberish, long paragraph, single-word, emoji/unicode, empty string - all confirmed to search safely, not to any particular weight split (there isn't one anymore)
- **Comprehensive video/window variety**: short/long/silent/full-modality videos, cross-video duplicates, zero-duration and huge-timestamp windows — against real seeded data, not synthetic
- **System-level**: first-query-after-startup, 12 rapid sequential queries, 5 concurrent threaded requests (result-level cross-contamination check against known-good sequential results, using deterministic per-query-text fake vectors), malformed request bodies (422 not 500), empty-collection

**Manual sanity check** — 15 curated realistic queries with readable printed output:
```bash
python demo_queries.py
```

## 8. Known Limitations / Read Before Demo

- **No query router, no LLM/VLM component anywhere** (team decision, see Section 2) — deterministic, no network dependency, nothing to flag about availability or LLM latency. If a smarter/LLM-based router or any form of automated summarization is wanted later, that's new work against this architecture, not a flag flip.
- **Always searching all 4 modalities has a small, fixed latency cost**, now lower since encoding/search run concurrently (see Section 2, ~290ms steady-state vs ~358ms before). Qdrant search/fusion/merge are negligible against that on this dev collection size. This is a flat cost on every query regardless of content, versus the old router's variable (sometimes lower, sometimes similar) cost depending on how many modalities it guessed were relevant. The team judged this an acceptable, predictable tradeoff for the correctness gain (Section 2) — worth re-measuring against real indexed data volume before the actual demo, since Qdrant's own per-modality search cost will grow with real collection size in a way this dev-scale measurement doesn't capture.
- **Fresh machine setup needs one online run** before `HF_HUB_OFFLINE=1` works — it skips Hub metadata lookups but still needs the model weights already downloaded into the local cache from a prior online run.
- **Never run against real indexed data.** Everything tested so far (82 tests + `demo_queries.py`) runs against synthetic seed data designed to exercise specific behaviors. Real captions/transcripts from the Processing team's pipeline could be empty, malformed, extremely long, non-English, or structured differently than the synthetic data assumes. This is the single biggest unknown before demo.
- **`validate_collection_schema()` has never run against a real (non-dev) collection.** It's built and tested against the seeded dev collection, and this pass reconfirmed that dev collection matches the contract exactly (Section 4) — but the real check, pointing it at the Processing team's actual production Qdrant collection, hasn't happened because that collection doesn't exist yet. Run it first, before anything else, the moment real data is available.
- **Scale is untested.** The dev collection has 33 points; a real video corpus could be thousands or millions of windows. The latency numbers above are measured at toy scale — Qdrant's own per-modality search cost will grow with real data volume in a way this hasn't measured; concurrency should matter more at that scale, not less.
- **`MERGE_GAP_SECONDS=5.0`, `MAX_MERGE_DURATION_SECONDS=60.0`, `MAX_MERGE_WINDOW_COUNT=8`, and `DEFAULT_TOP_K=15`** are reasonable defaults chosen without real data, not validated against the Processing team's actual windowing scheme (window size, overlap convention) or typical event duration. May need retuning once real windows are indexed.
- **No load testing.** Concurrency was verified with 5 threads in-process plus the new modality-mixup test (Section 7); this is not equivalent to real concurrent production traffic.
- **No security review.** No auth, no rate limiting — input validation is pydantic type-checking only. Acceptable for an internal team demo; not acceptable if this is ever exposed beyond that.
- **Recommended before calling this handed-off**: run `validate_collection_schema()` against the real collection first, then run `demo_queries.py` (or equivalent real queries) against real indexed content, and see what breaks — that gap between synthetic and real data is the actual remaining risk, and it can only be closed with real data in hand.

### Production safety

No mock/placeholder data can silently activate on the backend. Audited `api.py` and every read path in `qdrant_client.py`/`encoders.py`:
- If **every query encoder fails** (`encode_query()` returns `{}`), `/search` returns `503 {"detail": "All query encoders failed; search is unavailable."}` — it does not proceed to search with zero vectors and return an empty-looking success.
- If **Qdrant is genuinely unreachable** (connection refused, timeout, DNS failure), `/search` returns `503 {"detail": "Qdrant is unreachable; search is unavailable: ..."}` — see `qdrant_client.QdrantSearchError`. This is deliberately distinct from a live Qdrant server reporting "collection doesn't exist" or "no hits", which are real states, not failures, and correctly stay `200 {"results": []}`.
- There is **no mock/fake data path in the backend at all** — nothing to gate, because there never was one. `qdrant_client.py`'s functions either return real Qdrant data or raise; they never fabricate results.
- Covered by `tests/test_integration.py::test_qdrant_unreachable_returns_clean_503_not_silent_empty_or_500` and `::test_all_encoders_failing_returns_clean_503_not_silent_empty`.

The frontend does have mock data (`frontend/src/data/mockResults.js`), used during frontend-only development before the backend existed. It is now:
- **Gated behind `VITE_USE_MOCK_DATA=true`** (`frontend/.env.example`), **off by default**. With it off, a backend failure surfaces as a visible error banner (`source: 'error'`), not a silent substitution of fake results.
- **Visually labeled** when active: a `⚠ MOCK MODE` banner renders above the results list (`ResultsPage.jsx`) whenever `source === 'mock'`, so mock output can't be mistaken for a real response during a demo.
- The frontend has no test runner configured in this repo (no vitest/jest in `package.json`) — this gating was verified by code inspection and manual `VITE_USE_MOCK_DATA=true`/`false` toggling, not an automated test. Adding a frontend test harness is out of scope for this pass.

### Known blockers for future work

Two upstream/downstream additions were evaluated and deliberately **not** built in this pass, per explicit scope from the team:

- **Query decomposition** (breaking a compound query into sub-queries before encoding/search) — not implemented, not stubbed.
- **VLM verification** (a vision-language model checking candidate windows against the query before returning them, distinguishing "retrieved" from "verified"/"rejected") — not implemented, not stubbed. This is also why the response `state` field only ever has one value today (`"retrieved"`) rather than pretending a verification stage exists.

Both were prototyped and removed earlier in this project's history for a concrete, measured reason: LLM/VLM call latency (Gemini, in the earlier router prototype) ranged from 1.5s to 80s+ in testing — an unacceptable and unpredictable cost against a demo-day time budget. This is a **documented decision pending team discussion**, not something forgotten or deprioritized by accident. If/when the team decides to revisit either:
- Query decomposition would slot in before `encoders.encode_query()` in `api.py`.
- VLM verification would slot in after `merge_windows()`, before the response is built — and needs the video-path/frame-access payload field flagged as a blocker in Section 4 first, since there's currently nothing for a VLM to look at.

## 9. Project Status

**Built and feature-complete for the current architecture:**
1. Project skeleton, Qdrant client, dummy data seeding
2. Query encoders (X-CLIP / CLAP / BGE-M3), always all 4 modalities
3. Unweighted RRF fusion
4. Window merging (chained, cross-video-safe)

Plus three dedicated hardening passes: a full integration/failure-path audit (Qdrant-down, malformed input, boundary top_k values, schema drift detection), a comprehensive realistic-scenario pass (query variety, video/window variety, concurrency, cold start), and a non-LLM code-review pass (this one — concurrent modality search, bounded merge caps, per-candidate modality_evidence, no-silent-mock-fallback, honest `state` field; see Section 2 and Section 8). Two upstream stages were built, evaluated, and then removed per team review as the architecture matured: a keyword-based query router (removed for a real substring-matching bug and a hard vocabulary ceiling - see Section 2), and an LLM-based VLM summarization stage (removed earlier for latency/reliability reasons, formally deferred — see "Known blockers for future work" in Section 8). The current pipeline always searches all 4 modalities and relies on RRF fusion to suppress irrelevant ones through rank.

## 10. Frontend

A demo frontend lives in `/frontend` — React + Vite, two-page flow (upload/landing → search results), styled to an editorial-archive design system (warm paper background, Fraunces/Inter/IBM Plex Mono, rust/olive/mustard accents). Not part of the Query & Retrieval contract itself; documented here because it already talks to this module directly.

**Run it:**
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```
Needs the backend running (`uvicorn query_retrieval.api:app`, default `http://localhost:8000`) for real results — see Section 5. Override the backend URL with a `VITE_API_BASE_URL` env var if it's not on the default port.

**Integration point:** `frontend/src/api/searchApi.js` is the one place that calls `POST /search`. It calls the real backend directly. Mock data (`frontend/src/data/mockResults.js`) is **not** a silent fallback for backend failure anymore — it only activates when `VITE_USE_MOCK_DATA=true` is explicitly set (off by default, see `frontend/.env.example`), and when active the UI shows a visible `⚠ MOCK MODE` banner. If the real backend errors or is unreachable, the UI now shows an error banner with the failure message instead of quietly rendering mock/fake-looking results — see Section 8, Production safety. Response shape matches `SearchResponse`/`SearchResultItem` from `query_retrieval/models.py` exactly, including the new `modality_evidence` and `state` fields, confirmed live (real fetch call, real CORS headers, real data) - no adapter needed if the contract doesn't change.

**Backend change made for this:** `api.py` now has `CORSMiddleware` (`allow_origins=["*"]`) - without it the browser silently blocks every request from the Vite dev server's origin. Wide open is fine for a team demo with no auth; tighten before exposing this beyond that.

**What's mocked, deliberately:**
- The landing page's "upload" flow simulates a processing delay — there's no real ingestion endpoint to call yet (that's the Processing/Indexing teammate's module, out of scope here).
- Video thumbnails and the timeline-position bar per result are placeholder patterns / derived pseudo-durations — this module never dealt with actual video files, only Qdrant windows/payloads, so there's nothing real to render yet. Stays mocked until file serving is decided (likely the integration teammate's call).

**Not yet verified:** no headless-browser tool was available to screenshot/click-test the actual rendered UI in this environment. What's confirmed is that it builds cleanly, every page/component transforms without error, and the real backend integration works end-to-end (verified via a simulated browser fetch, not just code review). A manual visual pass in an actual browser is still worth doing before demo day.

**Explicitly out of scope for this module** (Processing team's responsibility): video file storage, frame extraction, actual transcription/captioning/embedding generation, writing points into Qdrant. This module only *reads* from the `video_windows` collection per the contract in Section 4 — it never writes indexing data.
