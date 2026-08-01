# Query & Retrieval Module

## 1. Overview

This module is the **Query & Retrieval** half of a multimodal video search system built for a hackathon. Given a raw text query, it optionally decomposes the query per-modality via an LLM (Gemini), encodes it into all 4 modality embedding spaces (visual / audio / speech / caption) regardless, searches a Qdrant collection per modality, fuses the ranked lists into one via (optionally weighted) Reciprocal Rank Fusion, merges overlapping/adjacent hits from the same video into coherent regions, and returns a single ranked JSON response. A separate, optional, non-blocking `/verify` endpoint can text-check the top candidates against the query afterward.

Every LLM-touching piece (decomposition, verification) is independently toggleable and fails safe: off, missing key, timeout, or malformed response all degrade to exactly the same behavior as if the feature didn't exist. See **"Kill switch reference"** in Section 8.

It was built standalone against a seeded dummy Qdrant collection, in parallel with a teammate's **Processing/Indexing** module (which populates the real collection from actual video). A third teammate integrates both by pointing this module's `/search` endpoint at the real collection — no code changes required here, as long as the indexing pipeline matches the contract in **Section 4**.

A demo frontend lives in `/frontend` and already calls this module's real `/search` endpoint — see **Section 10**.

## 2. Architecture

```
                         POST /search {query, top_k}
                                   |
                                   v
                        +--------------------------+
                        |  Query Decomposition     |  decomposition.py
                        |  (if ENABLE_QUERY_        |
                        |   DECOMPOSITION)          |
                        |  cache -> live Gemini     |
                        |  (hard 2.0s timeout) ->   |
                        |  deterministic fallback   |
                        +--------------------------+
                                   |
                    per-modality query text + weights
                        (unchanged query + equal
                         weights if decomposition is
                         off or falls back)
                                   |
                                   v
                        +---------------------+
                        |   Query Encoders    |  encoders.py
                        | X-CLIP / CLAP / BGE-M3 |
                        | (always all 4 modalities, run concurrently - |
                        |  a weight-0 modality is still encoded/searched) |
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
                        |  (Weighted) RRF Fusion |  fusion.py
                        |  score = sum(weight * 1/(k+rank)) |
                        |  weight=1.0/modality if no decomposition |
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
                          SearchResponse JSON  (state: "retrieved")

     ... later, separately, only if the frontend calls it ...

          POST /verify {candidate_ids, query, required_conditions}
                                   |
                                   v
                        +---------------------+
                        |    Verification      |  verification.py
                        |  (if ENABLE_VERIFICATION) |
                        |  text-only: transcript + caption + |
                        |  matched_modalities as evidence,  |
                        |  hard 2.0s timeout per candidate,  |
                        |  top VERIFICATION_TOP_N only        |
                        +---------------------+
                                   |
                                   v
                  verified / rejected / verification_unavailable
```

**This never blocks or slows down `/search`.** `/verify` is a separate HTTP call the frontend fires only after `/search`'s results have already rendered - a slow or failed LLM verification call adds latency to `/verify`, never to `/search`. See "Non-blocking verification design" below.

Query encoding happens **separately per modality** rather than once: X-CLIP, CLAP, and BGE-M3 each produce embeddings in their own distinct vector space — a visual embedding and an audio embedding are not directly comparable numbers even if they happened to share a dimension, because nothing trained them to agree on what "close" means across models. Each named vector in Qdrant is only ever queried with a vector from its own corresponding encoder, never a shared/generic one. This is now the central design fact of the pipeline: since there's no router picking a subset, every query pays the cost of all 3 models and gets a real comparable vector in each of the 4 spaces.

That same cross-model incomparability is why fusion is RRF-based rank fusion rather than an average of raw cosine similarities: a 0.3 cosine score from CLAP and a 0.3 cosine score from BGE-M3 don't mean the same thing and can't be safely blended by value. RRF sidesteps this by fusing on *rank position* within each modality's own list instead, which is comparable across models by construction.

### Why we removed query routing

V1 originally had a keyword-based router upstream of encoding, assigning per-modality weights so only "relevant" modalities got encoded and searched. It was removed for two concrete, demonstrated problems, not a hunch:

1. **A real substring-matching bug.** The router did plain `if keyword in query` matching, not word-boundary matching. `"the gardener watered the plants"` matched the visual color keyword `"red"` — because `"watered"` contains the literal substring `"r-e-d"`. This wasn't a rare edge case; the same class of bug affects any keyword that happens to be a substring of a common word (`"car"` in "scared", `"cat"` in "vacation", `"hat"` in "that").
2. **A hard vocabulary ceiling.** The router only recognized ~70 hardcoded words. Any query phrased outside that list fell back to caption-only search, silently losing visual/audio/speech signal for queries that should have used it (e.g. `"someone stole the milk"` — a visually meaningful event with no matching keyword).

Patching the keyword list indefinitely wasn't a real fix. An LLM router was also considered and set aside at the time citing latency/reliability concerns - those concerns turned out to be based on measurements taken from inside a constrained sandboxed dev environment, not real-world Gemini API performance (see below, same issue this pass's own initial measurements ran into and corrected). The router's removal itself is still correct regardless, based on the two concrete bugs above. RRF already suppresses irrelevant modalities naturally — an irrelevant modality's hits rank low within its own list and contribute a correspondingly tiny `1/(k+rank)` score — so an explicit router was solving a problem fusion already handles.

### Reintroducing an LLM step - query decomposition and verification

Query decomposition and text-only verification are now implemented, deliberately designed to avoid the specific failure mode that got the earlier LLM router idea shelved: that implementation made `/search` synchronously wait on a single Gemini call with no hard ceiling on how long it could actually take (a *library-level* timeout parameter, not a real hard-kill). This implementation is architecturally different in three ways:

1. **A three-tier fallback ladder, not a single call.** `decomposition.py`'s `decompose_query()` tries, in order: an exact-match local cache (instant, no network), then a live Gemini call bounded by a genuinely hard timeout (see #2), then a deterministic fallback that's behaviorally identical to "no decomposition at all". Any failure at any tier - timeout, network error, malformed JSON, missing key, flag off - falls through to the next tier; the fallback tier can never itself fail. See `decomposition.py`'s module docstring and `tests/test_decomposition.py`.
2. **A genuine hard timeout, not a library one.** `gemini_client.call_with_hard_timeout()` runs the LLM call in a daemon thread and hard-joins it with a wall-clock deadline (`DECOMPOSITION_TIMEOUT_SECONDS`, default **2.0s** - see the latency numbers below for why) - the calling code gets control back at the deadline regardless of what the underlying HTTP call is doing, unlike an SDK's own `timeout=` parameter which only bounds a specific request and can still leave the caller blocked on retries/DNS/connection setup it isn't tracking. See `tests/test_gemini_client.py::test_call_with_hard_timeout_raises_timeout_error_and_returns_promptly`.
3. **Verification is a separate, later, non-blocking call - never inline with retrieval.** Even bounded by a hard timeout, decomposition adding to every `/search` call was judged an acceptable cost (it directly improves retrieval quality by weighting modalities), but a *second* LLM call per candidate for verification was not worth that same risk stacked on top. So verification lives entirely behind its own `POST /verify` endpoint, called by the frontend only after `/search` has already returned and rendered results - a slow or completely failed verification pass has zero effect on `/search`'s response time, ever (see `tests/test_decomposition_integration.py::test_verify_does_not_block_search_and_search_timing_is_unaffected`).

Both features are still fully killable independently of each other and of `GEMINI_API_KEY`'s presence - see the **Kill switch reference** table in Section 8.

**Real measured latency:**

| Scenario | avg | notes |
|---|---|---|
| `ENABLE_QUERY_DECOMPOSITION=false` (baseline `/search`) | **~290ms** | no Gemini call involved |
| Decomposition on, **cache hit** | **~266ms** | no measurable overhead vs. baseline - no network call either, real Gemini-derived weights served from `decomposition_cache.json` |
| Live decomposition call (Gemini `gemini-2.5-flash`), measured from a normal (non-sandboxed) network path | **0.2s - 1.3s across 10 consecutive calls** | ordinary single-request API latency, nothing unusual |

Query decomposition works correctly and completes within normal API response time on a standard network connection - it is not slow or unreliable by nature. `DECOMPOSITION_TIMEOUT_SECONDS` defaults to **2.0s**, comfortably above the observed 1.3s upper end, so live decomposition should complete well within budget under normal conditions rather than triggering the fallback tier on ordinary latency variance.

An earlier version of these latency measurements, taken from inside this project's sandboxed development environment, showed live Gemini calls consistently taking 4-10s and occasionally far more - that made it look like the live tier would time out routinely even at a generous timeout. That was a false signal from the sandbox's own network path, not a real characteristic of the Gemini API or this module's implementation; testing from a real machine outside the sandbox showed ordinary latency instead (the table above). The three-tier fallback ladder is unaffected by this correction and remains exactly as designed - it's **standard defensive design for any external API dependency** (genuine network issues, transient API unavailability, a key running out of quota), not a workaround for a latency problem that doesn't actually exist.

Real example decomposition (`"a dog barking near a fence"`, live Gemini call, now cached): `visual_query="dog near a fence"`, `audio_query="dog barking sounds"`, `speech_query=""`, `caption_query="a dog barking near a fence"`, `weights={"visual": 0.4, "audio": 0.4, "speech": 0.0, "caption": 0.2}`, `required_conditions=["a dog is barking", "a fence is present", "the dog is near the fence"]` - correctly zeroed `speech`, split `visual`/`audio` evenly, derived real verification conditions.

`/verify` latency hasn't been measured live yet (a separate open item - see "Known blockers" below), but there's no reason to expect it to behave differently from decomposition's call shape above; `VERIFICATION_TIMEOUT_SECONDS` (2.0s) should give it the same comfortable margin.

### Weighted RRF

`fusion.py`'s `rrf_fuse()` takes an optional `weights` dict (modality → float). Two modes, selected by whether `weights` is `None` or not:

- **`weights=None`** (used whenever `ENABLE_QUERY_DECOMPOSITION` is off): every modality contributes `1/(k+rank)`, unscaled — the exact original formula this module has used since query routing was removed. This is what makes the kill switch guarantee in Section 8 exact, not approximate.
- **`weights={...}`** (used whenever decomposition is on, fed from `DecompositionResult.weights`): contribution becomes `weight * 1/(k+rank)`, summed the same way. Since Part A of this pipeline always searches all 4 modalities regardless of their assigned weight (see "Reintroducing an LLM step" above), a weight of `0.0` doesn't remove a modality's hits from fusion's input — it just makes their contribution to the score exactly `0`, which is provably tested (`tests/test_fusion.py::test_zero_weight_modality_contributes_zero_but_is_not_dropped`).

decomposition.py's own fallback tier (used when decomposition is *on* but degrades mid-request - see the ladder above) sets every weight to `0.25` rather than `None`. That's not the same code path as the kill switch: a uniform `0.25` scales every term by the same constant, which provably preserves ranking and top-k selection exactly (`tests/test_fusion.py::test_equal_weight_fallback_preserves_ranking_of_unweighted_baseline`) even though the raw `score` numbers differ from the `weights=None` baseline by that constant factor. In practice this only matters if something reads absolute score values across requests; nothing in this pipeline does.

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
| Query decomposition (optional) | `decomposition.py` |
| Verification (optional, separate endpoint) | `verification.py` |
| Shared Gemini client/timeout/JSON parsing | `gemini_client.py` |
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
- **Gemini** (`gemini-2.5-flash` by default, via `google-genai`) — optional, for query decomposition and text-only verification; both features are independently killable and degrade to exactly the pre-LLM behavior on any failure (see Section 8's Kill switch reference)
- **pytest** — 124 tests, no real network/model calls by default (Gemini calls are mocked at the client boundary in every test)

No query routing (a keyword-based classifier, removed for a real substring-matching bug and a hard vocabulary ceiling — see Section 2) and no VLM/frame-based verification (blocked on a missing payload field — see Section 8) remain out of this pipeline. Query decomposition and text-only verification *are* now in the pipeline, both LLM-based, both off by default or fail-safe when on — see Section 2.

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

**Known blocker for a future frame-based/VLM verification stage**: there is no field on the payload today that points at an actual video file, frame, or clip — no path, URL, or byte offset, nothing to hand a VLM to look at. `vlm_processed: bool` exists but is just a flag, not a pointer to content. The verification that does exist (`verification.py`, `POST /verify`) is deliberately **text-only** for exactly this reason — it checks `transcript`/`caption`/`matched_modalities` against the query, never frames. Upgrading it to look at actual video content needs this field added to the indexing contract first; it isn't something this module can invent or stub in.

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
| `GEMINI_API_KEY` | no | none | enables the live tier of decomposition/verification when present (in `query_retrieval/.env`, gitignored) |
| `GEMINI_MODEL` | no | `gemini-2.5-flash` | model used for both decomposition and verification |
| `ENABLE_QUERY_DECOMPOSITION` | no | `true` if `GEMINI_API_KEY` is set, else `false` | see Section 8 Kill switch reference |
| `DECOMPOSITION_TIMEOUT_SECONDS` | no | `2.0` | hard per-request timeout for the live decomposition call — comfortable margin above observed real-world latency (0.2s-1.3s, see Section 2) |
| `ENABLE_VERIFICATION` | no | `false` | explicit opt-in even with a key present — see Section 8 |
| `VERIFICATION_TIMEOUT_SECONDS` | no | `2.0` | hard per-candidate timeout for the live verification call |
| `VERIFICATION_TOP_N` | no | `5` | only the top-N candidates by fused_score get verified per `/verify` call |

`GEMINI_API_KEY` unset (or `ENABLE_QUERY_DECOMPOSITION`/`ENABLE_VERIFICATION` explicitly `false`) means zero network calls are ever attempted for either feature — see Section 8's Kill switch reference for exactly what's tested.

**Start Qdrant** (as used throughout development):
```bash
docker run -d --name qdrant-test -p 6333:6333 qdrant/qdrant:latest
```

**Seed dummy data** (standalone testing, no real indexing pipeline needed):
```bash
python -m query_retrieval.seed_dummy_data
```
Seeds 33 points covering: visual-only / audio-only / all-4-modality windows, overlapping same-event windows, fully disjoint windows, a deliberately near-identical "true match" pair, a deliberate hard negative, a short (2-window) video, a long video mixing tightly-clustered and far-apart windows, two different videos with near-identical content at identical timestamps (proves merge never crosses `video_id`), and edge-case timestamps (zero-duration window, very large start/end).

**Pre-seed the decomposition cache** (optional, needs a real `GEMINI_API_KEY`; demo queries then hit the cache tier and never touch the network):
```bash
python -m query_retrieval.seed_decomposition_cache
```
Populates `decomposition_cache.json` with real Gemini decompositions for a curated demo query list (extends `demo_queries.py`'s list). **Only partially run for this repo's committed cache** — an earlier Gemini key's free-tier daily quota (20 requests/day) was exhausted by connectivity testing before the full `DEMO_QUERIES` list could be pre-seeded; a fresh key was then used to seed 3 real entries directly (not the full list, to conserve that key's quota too - see Section 2 for one of those entries as a real example). `decomposition_cache.json` currently has these 3 entries; the other ~17 queries in `DEMO_QUERIES` still need a seeding run before a real demo — quick to do given normal decomposition latency (Section 2), the only constraint is free-tier request quota. The script and cache-lookup mechanism are also exercised by `tests/test_decomposition.py`'s cache-hit test (against a temp cache file, not the real one).

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
| `state` | always `"retrieved"` from `/search` — retrieval and verification are separate stages (see `POST /verify` below), so `/search`'s own response never says "verified"/"rejected" itself. A plain string, not an enum/Literal, so it can carry other values from other stages without a breaking schema change for existing consumers. |

(`source_window_ids` — the list of original window_ids a merged region absorbed — exists on the internal `MergedRegion` model for debugging/traceability but isn't currently exposed on the external `SearchResultItem`; ask if you want it surfaced.)

Note: this example response was captured with query decomposition off (unweighted RRF); with `ENABLE_QUERY_DECOMPOSITION` on (the default when a key is present), `score` and `modality_evidence[].contribution` reflect the decomposition's per-modality weights instead — the response *shape* is identical either way, only the numbers differ. See "Weighted RRF" below.

**Failure responses:** `/search` returns `503 {"detail": "..."}` (FastAPI's standard `HTTPException` shape) in two cases, never a silent empty/fake result:
- Every query encoder failed (`encode_query()` returned an empty dict) → `"All query encoders failed; search is unavailable."`
- Qdrant is genuinely unreachable (connection refused/timeout/DNS failure — as opposed to a live server returning "collection not found", which still means real zero matches and stays a normal `200 {"results": []}`) → `"Qdrant is unreachable; search is unavailable: ..."`

Query decomposition failing (timeout, malformed JSON, no key) is deliberately **not** in this list — it falls back internally (see Section 2) and never surfaces as a `/search` failure at all.

See **Section 8, Production safety** for why this distinction exists.

### `POST /verify`

Separate from `/search` on purpose — see "Non-blocking verification design" in Section 2. Disabled by default (`ENABLE_VERIFICATION=false`); check `GET /health`'s `verification_enabled` field before calling this, so the UI never fires it (and never shows a "verifying…" state) when it's off.

**Request:**
```json
{"candidate_ids": ["video_full_window_0001", "video_c_window_0002"], "query": "someone stole the milk from the fridge", "required_conditions": []}
```
| Field | Type | Notes |
|---|---|---|
| `candidate_ids` | `list[str]` | required — `window_id`s from a prior `/search` response, expected in fused_score-descending order (as `/search` already returns them); truncated server-side to the first `VERIFICATION_TOP_N` |
| `query` | `str` | required — the original search query |
| `required_conditions` | `list[str]` | optional — if empty, falls back to whatever `decompose_query()` most recently derived for this exact query string (if decomposition is on), else empty |

**Response** (shape, not real - no live Gemini calls could be made this session, see the latency note in Section 2):
```json
{
  "results": [
    {
      "candidate_id": "video_full_window_0001",
      "state": "verified",
      "match": true,
      "confidence": 0.92,
      "satisfied_conditions": ["someone stole something"],
      "missing_conditions": [],
      "contradictions": [],
      "evidence": "transcript describes an item being taken",
      "reason": ""
    },
    {
      "candidate_id": "video_c_window_0002",
      "state": "verification_unavailable",
      "match": null,
      "confidence": null,
      "satisfied_conditions": [],
      "missing_conditions": [],
      "contradictions": [],
      "evidence": "",
      "reason": "LLM call exceeded 2.0s hard timeout"
    }
  ]
}
```

| Response field | Meaning |
|---|---|
| `state` | exactly one of `"verified"` (LLM checked, matched), `"rejected"` (LLM checked, did not match), or `"verification_unavailable"` (the check itself failed/timed out/candidate not found - **never** the same as `"rejected"`, and a failure can never produce `"verified"` either - see `tests/test_verification.py::test_forced_failure_never_produces_false_positive_match`) |
| `match` / `confidence` | only populated when `state` is `"verified"`/`"rejected"`; `null` on `"verification_unavailable"` |
| `evidence` | one-sentence LLM explanation of the verdict (only on verified/rejected) |
| `reason` | human-readable failure reason (only on `verification_unavailable`) |

**Disabled response:** `404 {"detail": "Verification is disabled (ENABLE_VERIFICATION=false)."}` — a clear "feature off" signal, distinct from every candidate individually coming back `verification_unavailable` (which would mean "on, but every check failed").

### `GET /health`

Returns `503 {"status": "loading"}` until encoder warmup genuinely completes, `200 {"status": "ok", "verification_enabled": <bool>}` after. The `503` case matters because relying on implicit ASGI startup-blocking behavior would be a latent race condition — a future change to workers/lifespan handling could let a request through before warmup finishes, and a demo's first query would eat the full multi-minute cold-start cost instead of a health poll cleanly catching it. Poll this before sending real traffic. `verification_enabled` lets the frontend decide whether to ever call `/verify` at all (see above).

## 7. Testing

```bash
pytest query_retrieval/tests/ -q
```

**Current status: 124/124 passing** (was 82/82 before this pass — 42 net-new tests across 5 new files plus additions to `test_fusion.py`, none deleted), ~6s, zero real network calls to Gemini or Qdrant-unreachable paths (Gemini is mocked at the client boundary in every test; encoders are mocked at the model-loader boundary).

Coverage, by area:
- **Encoders**: shape/dim correctness per modality, all 4 always called concurrently (no gating), partial-failure isolation (one modality failing doesn't fail the request)
- **Fusion**: hand-computed unweighted RRF scores including a worked rank-1-vs-two-rank-10s example, summation-not-max verified explicitly, empty-results edge cases, modality_evidence rank/contribution correctness and sum-to-fused_score invariant, **weighted RRF: weights=None byte-identical to the unweighted baseline, weight scaling per modality, a weight-0 modality still contributes an evidence entry (just worth 0), equal-weight-fallback preserves ranking exactly** (new)
- **Merging**: no-merge, simple overlap, chained A-B-C merge, cross-video never-merges, inclusive/exclusive gap boundary, bounded-merge splitting at MAX_MERGE_WINDOW_COUNT and MAX_MERGE_DURATION_SECONDS with hand-verified region boundaries, cap-splitting never crosses video_id, MergedRegion.modality_evidence sums to fused_score
- **Integration/failure-path**: Qdrant genuinely unreachable → 503 with a descriptive error, all query encoders failing → 503, empty query, `top_k=0` and `top_k=10000`, zero-match query, `/health` gating, schema validator pass/fail, 4 concurrent Qdrant searches don't mix up results across modalities — all through the real `/search` endpoint
- **`gemini_client.py`** (new, `test_gemini_client.py`): the hard-timeout wrapper genuinely returns control at the deadline for a function that's still running (not when it eventually finishes), re-raises the wrapped function's real exception, and the JSON parser handles markdown fences / stray text / garbage / non-object JSON
- **`decomposition.py`** (new, `test_decomposition.py`): cache-hit returns without any network call attempted, live-tier parses a mocked valid response and normalizes weights that don't sum to 1.0, fallback triggers correctly on timeout / malformed JSON / missing required fields / flag off / no key, and the fallback result is asserted field-by-field to be behaviorally identical to "no decomposition"
- **`verification.py`** (new, `test_verification.py`): all three states (verified/rejected/verification_unavailable) produced correctly, and a parametrized test forcing 4 different failure modes (timeout, malformed JSON, missing `match` field, network error, plus an unexpected-exception case) each individually asserts `state == "verification_unavailable"` and `match is None` — the hard requirement that failure can never look like a match
- **Weighted-fusion + decomposition wiring** (new, `test_decomposition_integration.py`): a modality decomposition assigns weight 0.0 is still actually searched (call-counted, not just weight-checked), decomposition weights measurably flow through to the real `/search` response's `score`/`modality_evidence`, and `/verify` genuinely does not add latency to `/search` (a mocked 1.5s-slow verification call proves `/search`'s own response time is unaffected)
- **Kill switches** (new, `test_kill_switches.py`): `ENABLE_QUERY_DECOMPOSITION=false` produces `/search` scores that hand-computation-match the unweighted RRF formula exactly (not just "similar ranking") and never calls `decompose_query()` at all; `ENABLE_VERIFICATION=false` makes `/verify` return 404 and `/health` report `verification_enabled: false`; `GEMINI_API_KEY` unset makes both decomposition and verification fall back/unavailable with zero network calls attempted; the `ENABLE_QUERY_DECOMPOSITION` default-derivation logic (on only when a key is present) is tested directly against its pure function
- **Comprehensive query variety**: pure visual/audio/speech/caption-flavored, mixed, gibberish, long paragraph, single-word, emoji/unicode, empty string
- **Comprehensive video/window variety**: short/long/silent/full-modality videos, cross-video duplicates, zero-duration and huge-timestamp windows — against real seeded data, not synthetic
- **System-level**: first-query-after-startup, 12 rapid sequential queries, 5 concurrent threaded requests (result-level cross-contamination check), malformed request bodies (422 not 500), empty-collection

All pre-existing test fixtures that exercise the pipeline through the real `/search` endpoint (`test_integration.py`, `test_comprehensive.py`, `test_phase5_regression.py`) now explicitly pin `ENABLE_QUERY_DECOMPOSITION=False` (and `ENABLE_VERIFICATION=False`) via `monkeypatch` - this is necessary, not incidental: `GEMINI_API_KEY` is present in this repo's `query_retrieval/.env`, so decomposition defaults **on**, and without this pin every one of those 82 pre-existing tests would have silently started exercising the decomposition code path instead of the pipeline they were written to test.

**Manual sanity check** — 15 curated realistic queries with readable printed output:
```bash
python demo_queries.py
```

## 8. Known Limitations / Read Before Demo

- **Always searching all 4 modalities has a small, fixed latency cost**, lower since encoding/search run concurrently (~290ms steady-state; see Section 2 for the concurrency numbers and the decomposition latency numbers). Qdrant search/fusion/merge are negligible against that on this dev collection size — worth re-measuring against real indexed data volume before the actual demo, since Qdrant's own per-modality search cost will grow with real collection size in a way this dev-scale measurement doesn't capture.
- **`decomposition_cache.json` is only partially seeded** — 3 of the ~20 curated `DEMO_QUERIES` (see `seed_decomposition_cache.py`) have real cached entries; the rest still hit the live/fallback tiers until a full seeding run is done. Run `python -m query_retrieval.seed_decomposition_cache` to fill in the rest before a real demo - this is quick and cheap now that live decomposition is confirmed to run at normal API latency (Section 2), not something to budget extra time around.
- **`/verify` still has no real measured latency** — its non-blocking timing behavior is proven by tests, but a live Gemini call for verification specifically hasn't been made yet. No reason to expect it to behave differently from decomposition's now-confirmed-normal call latency, but it's still an open item.
- **Fresh machine setup needs one online run** before `HF_HUB_OFFLINE=1` works — it skips Hub metadata lookups but still needs the model weights already downloaded into the local cache from a prior online run.
- **Never run against real indexed data.** Everything tested so far (124 tests + `demo_queries.py`) runs against synthetic seed data designed to exercise specific behaviors. Real captions/transcripts from the Processing team's pipeline could be empty, malformed, extremely long, non-English, or structured differently than the synthetic data assumes. This is the single biggest unknown before demo.
- **`validate_collection_schema()` has never run against a real (non-dev) collection.** It's built and tested against the seeded dev collection, and this pass reconfirmed that dev collection matches the contract exactly (Section 4) — but the real check, pointing it at the Processing team's actual production Qdrant collection, hasn't happened because that collection doesn't exist yet. Run it first, before anything else, the moment real data is available.
- **Scale is untested.** The dev collection has 33 points; a real video corpus could be thousands or millions of windows. The latency numbers above are measured at toy scale — Qdrant's own per-modality search cost will grow with real data volume in a way this hasn't measured; concurrency should matter more at that scale, not less.
- **`MERGE_GAP_SECONDS=5.0`, `MAX_MERGE_DURATION_SECONDS=60.0`, `MAX_MERGE_WINDOW_COUNT=8`, and `DEFAULT_TOP_K=15`** are reasonable defaults chosen without real data, not validated against the Processing team's actual windowing scheme (window size, overlap convention) or typical event duration. May need retuning once real windows are indexed.
- **No load testing.** Concurrency was verified with 5 threads in-process plus the modality-mixup test (Section 7); this is not equivalent to real concurrent production traffic.
- **No security review.** No auth, no rate limiting — input validation is pydantic type-checking only. Acceptable for an internal team demo; not acceptable if this is ever exposed beyond that.
- **Recommended before calling this handed-off**: run `validate_collection_schema()` against the real collection first, then run `demo_queries.py` (or equivalent real queries) against real indexed content, and see what breaks — that gap between synthetic and real data is the actual remaining risk, and it can only be closed with real data in hand.

### Kill switch reference

Every LLM-touching behavior is independently controllable and verified by an explicit runnable test, not just a claim — see `tests/test_kill_switches.py`.

| Env var | Effect when set | Verified by |
|---|---|---|
| `ENABLE_QUERY_DECOMPOSITION=false` | `/search` never calls `decompose_query()` at all; behavior and scores are byte-identical to the pre-decomposition baseline (`rrf_fuse(weights=None)`, its exact original formula) | `test_decomposition_off_search_scores_match_unweighted_rrf_exactly`, `test_decomposition_off_never_calls_decompose_query` |
| `ENABLE_VERIFICATION=false` (default) | `POST /verify` returns `404 {"detail": "Verification is disabled..."}`; `GET /health` reports `verification_enabled: false`; the frontend checks this before ever calling `/verify`, so no "verifying…" state is shown | `test_verification_off_verify_endpoint_returns_404_disabled`, `test_verification_off_health_reports_verification_disabled` |
| `GEMINI_API_KEY` unset | Both decomposition and verification skip the live tier entirely with **zero network call attempts** (proven by a mock that raises if the Gemini client is ever constructed) - decomposition falls back deterministically, verification returns `verification_unavailable` | `test_no_api_key_decomposition_falls_back_with_zero_network_calls`, `test_no_api_key_verification_unavailable_with_zero_network_calls` |
| `ENABLE_QUERY_DECOMPOSITION` unset, `GEMINI_API_KEY` set | Decomposition defaults **on** (live tier attempted, falls back on failure) | `test_decomposition_default_enabled_derivation_depends_only_on_key_presence` |
| `ENABLE_QUERY_DECOMPOSITION=false`, `GEMINI_API_KEY` set | Decomposition stays off - explicit flag always wins over key presence, for reproducing/debugging the pre-decomposition baseline without unsetting a working key | `test_bool_helper_lets_explicit_env_override_any_default` |
| Any live LLM call timing out, erroring, or returning malformed JSON | Decomposition falls back (tier 3); verification returns `verification_unavailable` for that candidate only - **never** silently becomes a match | `test_decomposition.py`'s fallback tests, `test_forced_failure_never_produces_false_positive_match` |
| `VITE_USE_MOCK_DATA=true` (frontend, off by default) | Frontend shows a visible `⚠ MOCK MODE` banner and never calls the real backend | see "Production safety" below |

### Production safety

No mock/placeholder data can silently activate on the backend. Audited `api.py` and every read path in `qdrant_client.py`/`encoders.py`/`decomposition.py`/`verification.py`:
- If **every query encoder fails** (`encode_query()`/`encode_decomposed()` returns `{}`), `/search` returns `503 {"detail": "All query encoders failed; search is unavailable."}` — it does not proceed to search with zero vectors and return an empty-looking success.
- If **Qdrant is genuinely unreachable** (connection refused, timeout, DNS failure), `/search` returns `503 {"detail": "Qdrant is unreachable; search is unavailable: ..."}` — see `qdrant_client.QdrantSearchError`. This is deliberately distinct from a live Qdrant server reporting "collection doesn't exist" or "no hits", which are real states, not failures, and correctly stay `200 {"results": []}`.
- There is **no mock/fake data path in the backend at all** — nothing to gate, because there never was one. `qdrant_client.py`'s functions either return real Qdrant data or raise; they never fabricate results.
- **A failed/timed-out/malformed LLM call never silently substitutes a plausible-looking result.** Decomposition failing falls back to unweighted-equivalent behavior (not a fabricated decomposition); verification failing returns `verification_unavailable` (not a fabricated `match: true`) - see the Kill switch reference table above.
- Covered by `tests/test_integration.py::test_qdrant_unreachable_returns_clean_503_not_silent_empty_or_500`, `::test_all_encoders_failing_returns_clean_503_not_silent_empty`, and the decomposition/verification fallback tests above.

The frontend does have mock data (`frontend/src/data/mockResults.js`), used during frontend-only development before the backend existed. It is now:
- **Gated behind `VITE_USE_MOCK_DATA=true`** (`frontend/.env.example`), **off by default**. With it off, a backend failure surfaces as a visible error banner (`source: 'error'`), not a silent substitution of fake results.
- **Visually labeled** when active: a `⚠ MOCK MODE` banner renders above the results list (`ResultsPage.jsx`) whenever `source === 'mock'`, so mock output can't be mistaken for a real response during a demo.
- The frontend has no test runner configured in this repo (no vitest/jest in `package.json`) — this gating was verified by code inspection and manual `VITE_USE_MOCK_DATA=true`/`false` toggling, not an automated test. Adding a frontend test harness is out of scope for this pass.

### Known blockers for future work

**Query decomposition and text-only verification are now implemented** (this pass) - they were evaluated, prototyped, and previously deferred pending team decision on demo-day LLM latency risk (see Section 2's "Reintroducing an LLM step"); that decision has now been made and both are built, tested, and independently killable.

What's still genuinely blocked, not forgotten:

- **Frame-based / VLM verification** (looking at actual video frames, not just transcript/caption text) — blocked on a real schema gap, not a scope decision: there is no field on the Qdrant payload today that points at an actual video file, frame, or clip (Section 4). `verification.py` is deliberately text-only for exactly this reason. Upgrading it needs that field added to the indexing contract first; it isn't something this module can invent or stub in.
- **This repo's `decomposition_cache.json` has only 3 real entries, not the full curated list** — the pre-seeding mechanism works (confirmed live - see Section 2 for a real example decomposition), it just wasn't run to completion for the full `DEMO_QUERIES` list yet (see Section 5's pre-seed instructions).
- **Real `/verify` latency numbers are still needed** — the endpoint's non-blocking design and timing behavior are proven (Section 2, Section 7), but a live Gemini call for verification specifically hasn't been made yet.

## 9. Project Status

**Built and feature-complete for the current architecture:**
1. Project skeleton, Qdrant client, dummy data seeding
2. Query encoders (X-CLIP / CLAP / BGE-M3), always all 4 modalities, encoded concurrently
3. Weighted RRF fusion (unweighted when decomposition is off - byte-identical to the original)
4. Window merging (chained, cross-video-safe, bounded)
5. Query decomposition (`decomposition.py`) - cache → live Gemini (hard-timeout) → deterministic fallback
6. Text-only candidate verification (`verification.py`, `POST /verify`) - separate, non-blocking, three-state, fail-safe

Plus four dedicated hardening/feature passes: a full integration/failure-path audit (Qdrant-down, malformed input, boundary top_k values, schema drift detection), a comprehensive realistic-scenario pass (query variety, video/window variety, concurrency, cold start), a non-LLM code-review pass (concurrent modality search, bounded merge caps, per-candidate modality_evidence, no-silent-mock-fallback, honest `state` field), and this pass (query decomposition + verification, reintroducing an LLM step deliberately architected to avoid the earlier LLM router's timeout problem — see Section 2). A keyword-based query router was built, evaluated, and removed earlier for a real substring-matching bug and a hard vocabulary ceiling (Section 2) and has not been reintroduced; RRF fusion (now optionally weighted by decomposition) still does the work a router would have done. Frame-based/VLM verification remains a documented blocker — see "Known blockers for future work" in Section 8.

## 10. Frontend

A demo frontend lives in `/frontend` — React + Vite, two-page flow (upload/landing → search results), styled to an editorial-archive design system (warm paper background, Fraunces/Inter/IBM Plex Mono, rust/olive/mustard accents). Not part of the Query & Retrieval contract itself; documented here because it already talks to this module directly.

**Run it:**
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```
Needs the backend running (`uvicorn query_retrieval.api:app`, default `http://localhost:8000`) for real results — see Section 5. Override the backend URL with a `VITE_API_BASE_URL` env var if it's not on the default port.

**Integration point:** `frontend/src/api/searchApi.js` is the one place that calls `POST /search`, `POST /verify`, and `GET /health`. It calls the real backend directly. Mock data (`frontend/src/data/mockResults.js`) is **not** a silent fallback for backend failure anymore — it only activates when `VITE_USE_MOCK_DATA=true` is explicitly set (off by default, see `frontend/.env.example`), and when active the UI shows a visible `⚠ MOCK MODE` banner. If the real backend errors or is unreachable, the UI now shows an error banner with the failure message instead of quietly rendering mock/fake-looking results — see Section 8, Production safety. Response shape matches `SearchResponse`/`SearchResultItem` from `query_retrieval/models.py` exactly, including the `modality_evidence` and `state` fields, confirmed live (real fetch call, real CORS headers, real data) - no adapter needed if the contract doesn't change.

**Verification wiring (`ResultsPage.jsx`):** after `/search` results render (never before, never blocking that render), the page checks `GET /health`'s `verification_enabled` field; only if `true` does it fire `POST /verify` for all the rendered candidates in the background. Each `ResultRow` shows a badge that starts as `verifying…`, then resolves to a green `✓ verified NN%` confidence badge, a rust `✕ did not match` indicator, or a muted italic `verification unavailable` label - the three states are visually distinct on purpose, so a failed check can never be mistaken for a rejection or a match (`ResultRow.jsx`'s `VerificationBadge`). When `ENABLE_VERIFICATION` is off server-side, `verification_enabled` is `false`, `/verify` is never called, and no badge (not even `verifying…`) ever appears.

**Backend change made for this:** `api.py` now has `CORSMiddleware` (`allow_origins=["*"]`) - without it the browser silently blocks every request from the Vite dev server's origin. Wide open is fine for a team demo with no auth; tighten before exposing this beyond that.

**What's mocked, deliberately:**
- The landing page's "upload" flow simulates a processing delay — there's no real ingestion endpoint to call yet (that's the Processing/Indexing teammate's module, out of scope here).
- Video thumbnails and the timeline-position bar per result are placeholder patterns / derived pseudo-durations — this module never dealt with actual video files, only Qdrant windows/payloads, so there's nothing real to render yet. Stays mocked until file serving is decided (likely the integration teammate's call).

**Not yet verified:** no headless-browser tool was available to screenshot/click-test the actual rendered UI in this environment. What's confirmed is that it builds cleanly, every page/component transforms without error, and the real backend integration works end-to-end (verified via a simulated browser fetch, not just code review). A manual visual pass in an actual browser is still worth doing before demo day.

**Explicitly out of scope for this module** (Processing team's responsibility): video file storage, frame extraction, actual transcription/captioning/embedding generation, writing points into Qdrant. This module only *reads* from the `video_windows` collection per the contract in Section 4 — it never writes indexing data.
