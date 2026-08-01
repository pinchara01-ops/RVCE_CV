"""External API contract (FastAPI). Wired to real Qdrant search functions,
real query encoders, weighted RRF fusion, window merging, optional query
decomposition, and optional async candidate verification.
"""
import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from query_retrieval import config, encoders
from query_retrieval.decomposition import decompose_query
from query_retrieval.fusion import rrf_fuse
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    VerificationResult,
    VerifyRequest,
    VerifyResponse,
)
from query_retrieval.qdrant_client import (
    QdrantSearchError,
    search_audio,
    search_caption,
    search_speech,
    search_visual,
)
from query_retrieval.verification import verify_candidate

logger = logging.getLogger(__name__)

app = FastAPI(title="Query & Retrieval Module", version="0.1.0")

# The frontend (Vite dev server, localhost:5173) calls this API from a
# different origin than it's served on - without CORS enabled the browser
# blocks every fetch() with no server-side error to debug. Wide open
# origins are fine here (no auth, no cookies, hackathon demo); tighten if
# this ever serves real traffic beyond the team's own frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_SEARCH_FNS = {
    "visual": search_visual,
    "audio": search_audio,
    "speech": search_speech,
    "caption": search_caption,
}

# Reused across requests (not a per-call `with ThreadPoolExecutor()`) to
# avoid paying thread-spawn cost on every query. 4 workers = one per
# modality, matching the 4 concurrent Qdrant searches issued per request.
_search_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="qdrant-search")

# Explicit readiness flag rather than relying on ASGI startup-blocking
# semantics: /health must not report ready until encoder warmup has
# actually finished, or a demo's first query eats the full model-load
# latency instead of a cheap health poll catching that window.
_encoders_ready = False

# Bounded in-memory cache of recent /search results, keyed by window_id -
# lets /verify look up a candidate's evidence (transcript/caption/
# matched_modalities) by candidate_id alone, without the frontend having
# to resend the full candidate payload. Single-process, not persisted -
# fine for a demo; a multi-worker deployment would need a shared store
# (Redis or similar) instead. Only populated when ENABLE_VERIFICATION is
# on, since nothing ever reads it otherwise.
_RECENT_RESULTS_CACHE_SIZE = 500
_recent_results: "OrderedDict[str, SearchResultItem]" = OrderedDict()

# Required conditions from the most recent decomposition of a given query
# string - /verify needs these but a client may not resend them (the
# VerifyRequest schema allows it to supply its own; this is just a
# convenience default when it doesn't). Same bounded/single-process
# caveats as _recent_results.
_last_required_conditions: "OrderedDict[str, list[str]]" = OrderedDict()


def _remember_for_verification(results: list[SearchResultItem]) -> None:
    for result in results:
        _recent_results[result.window_id] = result
        _recent_results.move_to_end(result.window_id)
    while len(_recent_results) > _RECENT_RESULTS_CACHE_SIZE:
        _recent_results.popitem(last=False)


@app.on_event("startup")
def _load_encoders() -> None:
    """Eagerly load all encoder models so a broken model fails loudly at
    boot, not silently on the first demo query."""
    global _encoders_ready
    encoders.warmup()
    _encoders_ready = True


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Encode the query for all 4 modalities, search all 4 in parallel,
    fuse via (optionally weighted) RRF, and merge into a ranked list of
    candidate regions.

    No query routing: all 4 modalities are always encoded and searched,
    regardless of whether decomposition is on - RRF's rank-based fusion
    (optionally weighted by decomposition) naturally suppresses modalities
    irrelevant to a given query, rather than an upstream gate deciding in
    advance which to search at all. Per-modality search depth is
    config.DEFAULT_TOP_K (a fixed candidate pool) - fusion is left
    untruncated so merging sees every candidate before anything is
    dropped; request.top_k is applied last, to the final merged regions.

    When ENABLE_QUERY_DECOMPOSITION is off, this function's behavior is
    byte-identical to before decomposition existed: encoders.encode_query()
    (same query text to all 4 modalities) and rrf_fuse() with no weights
    (its exact original unweighted formula) - see fusion.py and the
    "Kill switch reference" table in the README. When on, decompose_query()
    runs first (see decomposition.py's three-tier cache/live/fallback
    ladder, hard-timeout bounded so this can add at most
    DECOMPOSITION_TIMEOUT_SECONDS of latency even in the worst case), each
    modality is encoded with its own decomposition-specific query text via
    encoders.encode_decomposed(), and fusion is weighted by the
    decomposition's per-modality weights.

    Verification (if ENABLE_VERIFICATION) does NOT happen here - it's a
    separate, later POST /verify call the frontend makes after these
    results have already rendered, specifically so a slow/failed LLM
    verification call can never add latency to this endpoint.

    Encoding and search each run their own modality-calls concurrently
    rather than sequentially - see encoders.py and the thread pool above.
    A genuine failure (every encoder failed, or Qdrant is unreachable)
    raises HTTPException(503) with a descriptive error rather than
    silently returning an empty result set that would be indistinguishable
    from "no matches".
    """
    weights = None
    required_conditions: list[str] = []

    if config.ENABLE_QUERY_DECOMPOSITION:
        decomposition = decompose_query(request.query)
        query_vectors = encoders.encode_decomposed(decomposition)
        weights = decomposition.weights
        required_conditions = decomposition.required_conditions
    else:
        query_vectors = encoders.encode_query(request.query)

    if not query_vectors:
        raise HTTPException(
            status_code=503,
            detail="All query encoders failed; search is unavailable.",
        )

    futures = {
        _search_executor.submit(fn, query_vectors[modality], config.DEFAULT_TOP_K): modality
        for modality, fn in _SEARCH_FNS.items()
        if modality in query_vectors
    }
    modality_hits: dict[str, list[dict]] = {}
    try:
        for future, modality in futures.items():
            modality_hits[modality] = future.result()
    except QdrantSearchError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Qdrant is unreachable; search is unavailable: {exc}",
        ) from exc

    fused = rrf_fuse(modality_hits, weights=weights)
    regions = merge_windows(fused)[: request.top_k]

    results = [
        SearchResultItem(
            video_id=region.video_id,
            window_id=region.payload.window_id,
            start=region.start,
            end=region.end,
            transcript=region.payload.transcript,
            caption=region.payload.caption,
            score=region.fused_score,
            matched_modalities=region.matched_modalities,
            modality_evidence=region.modality_evidence,
            state="retrieved",
        )
        for region in regions
    ]

    if config.ENABLE_VERIFICATION:
        _remember_for_verification(results)
        _last_required_conditions[request.query] = required_conditions
        _last_required_conditions.move_to_end(request.query)
        while len(_last_required_conditions) > _RECENT_RESULTS_CACHE_SIZE:
            _last_required_conditions.popitem(last=False)

    return SearchResponse(results=results)


@app.post("/verify", response_model=VerifyResponse)
def verify(request: VerifyRequest) -> VerifyResponse:
    """Verify up to VERIFICATION_TOP_N candidates (in the order given -
    expected to already be fused_score-descending, as /search returns
    them) against the original query and required_conditions.

    Deliberately a separate endpoint from /search, called after the fact
    by the frontend - never blocks or slows down the primary retrieval
    response. Disabled by default (ENABLE_VERIFICATION=false); when
    disabled this returns 404 rather than pretending to verify and
    returning "verification_unavailable" for everything, so a client can
    tell "feature off" apart from "feature on but every check failed".
    """
    if not config.ENABLE_VERIFICATION:
        raise HTTPException(
            status_code=404,
            detail="Verification is disabled (ENABLE_VERIFICATION=false).",
        )

    required_conditions = request.required_conditions or _last_required_conditions.get(request.query, [])

    results: list[VerificationResult] = []
    for candidate_id in request.candidate_ids[: config.VERIFICATION_TOP_N]:
        candidate = _recent_results.get(candidate_id)
        if candidate is None:
            results.append(VerificationResult(
                candidate_id=candidate_id,
                state="verification_unavailable",
                reason="candidate_id not found in recent /search results (expired from cache or unknown id)",
            ))
            continue
        results.append(verify_candidate(candidate, request.query, required_conditions))

    return VerifyResponse(results=results)


@app.get("/health")
def health(response: Response) -> dict:
    """`verification_enabled` lets the frontend decide whether to call
    /verify at all - checking this first (rather than firing /verify
    unconditionally and reacting to a 404) means the UI never shows even
    a brief "verifying..." flash when the feature is off server-side."""
    if not _encoders_ready:
        response.status_code = 503
        return {"status": "loading"}
    return {"status": "ok", "verification_enabled": config.ENABLE_VERIFICATION}
