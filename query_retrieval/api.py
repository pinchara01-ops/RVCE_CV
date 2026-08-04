"""FastAPI query contract for multimodal retrieval and evidence verification."""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from processing_indexing.library import media_path_for_source
from query_retrieval import config, encoders
from query_retrieval.decomposition import decompose_query
from query_retrieval.fusion import rrf_fuse
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import (
    DecompositionResult,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    VerificationOptions,
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

app = FastAPI(title="Query & Retrieval Module", version="0.2.0")
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

_encoders_ready = False
_encoder_load_lock = threading.Lock()
_RECENT_RESULTS_CACHE_SIZE = 500
_recent_results: "OrderedDict[str, SearchResultItem]" = OrderedDict()
_last_required_conditions: "OrderedDict[str, list[str]]" = OrderedDict()


def _remember_for_verification(results: list[SearchResultItem]) -> None:
    for result in results:
        _recent_results[result.window_id] = result
        _recent_results.move_to_end(result.window_id)
    while len(_recent_results) > _RECENT_RESULTS_CACHE_SIZE:
        _recent_results.popitem(last=False)


def _load_encoders() -> None:
    """Load retrieval encoders on the first search, not application startup."""
    global _encoders_ready
    if config.QUERY_LOW_MEMORY_MODE:
        # Low-memory mode validates each model at encode time and immediately
        # evicts it.  Eager warmup would defeat the point by loading all three
        # models before the first Qdrant request.
        return
    if _encoders_ready:
        return
    with _encoder_load_lock:
        if _encoders_ready:
            return
        encoders.warmup()
        _encoders_ready = True


def _decompose(request: SearchRequest) -> DecompositionResult | None:
    """Return a usable decomposition only when enabled for this search."""
    enabled = config.ENABLE_QUERY_DECOMPOSITION if request.enable_decomposition is None else request.enable_decomposition
    if not enabled:
        return None
    # Preserve the original callable shape for configured decomposition. It
    # keeps third-party provider adapters and historical tests compatible;
    # only an explicit browser override needs the new keyword argument.
    if request.enable_decomposition is None:
        return decompose_query(request.query)
    return decompose_query(request.query, enabled=True)


def _search_vectors(
    request: SearchRequest, decomposition: DecompositionResult | None
) -> tuple[dict[str, list[float]], dict[str, float] | None]:
    if decomposition is None:
        if config.QUERY_LOW_MEMORY_MODE:
            return encoders.encode_query_low_memory(request.query), None
        return encoders.encode_query(request.query), None
    if config.QUERY_LOW_MEMORY_MODE:
        return encoders.encode_decomposed_low_memory(decomposition), decomposition.weights
    return encoders.encode_decomposed(decomposition), decomposition.weights


def _eligible_modalities(
    vectors: dict[str, list[float]], weights: dict[str, float] | None
) -> list[str]:
    if weights is None:
        return [modality for modality in _SEARCH_FNS if modality in vectors]
    active = [
        modality
        for modality in _SEARCH_FNS
        if modality in vectors and float(weights.get(modality, 0.0)) > 0
    ]
    # A malformed/live decomposition can never remove all recall.  The
    # validated fallback has equal weights, but this makes the safety rule
    # explicit if a future provider returns zeros for every modality.
    return active or [modality for modality in _SEARCH_FNS if modality in vectors]


def _result_from_region(region) -> SearchResultItem:
    return SearchResultItem(
        video_id=region.video_id,
        window_id=region.payload.window_id,
        start=region.start,
        end=region.end,
        transcript=region.payload.transcript,
        caption=region.payload.caption,
        score=region.fused_score,
        matched_modalities=region.matched_modalities,
        modality_evidence=region.modality_evidence,
        source_path=region.payload.source_path,
        media_available=media_path_for_source(region.payload.source_path) is not None,
        source_window_ids=region.source_window_ids,
    )


def _normalised_retrieval_scores(results: list[SearchResultItem]) -> dict[str, float]:
    if not results:
        return {}
    scores = [result.score for result in results]
    low, high = min(scores), max(scores)
    if abs(high - low) < 1e-12:
        return {result.window_id: 1.0 for result in results}
    return {result.window_id: (result.score - low) / (high - low) for result in results}


def _apply_verification_and_rerank(
    results: list[SearchResultItem],
    query: str,
    required_conditions: list[str],
    options: VerificationOptions,
) -> list[SearchResultItem]:
    """Verify top candidates, clamp event times, then rank evidence first.

    Rejected candidates stay visible at the bottom rather than disappearing,
    so the browser can explain why a plausible retrieval was discarded.
    """
    if options.provider == "none" or not results:
        return results

    normalised = _normalised_retrieval_scores(results)
    for result in results[: options.top_n]:
        verdict = verify_candidate(result, query, required_conditions, options)
        result.verification = verdict
        result.state = verdict.state
        retrieval_score = normalised[result.window_id]
        if verdict.state == "verified":
            confidence = verdict.confidence or 0.0
            result.final_score = 0.35 * retrieval_score + 0.65 * confidence
            if (
                verdict.event_start_relative is not None
                and verdict.event_end_relative is not None
            ):
                result.refined_start = min(
                    max(result.start + verdict.event_start_relative, result.start), result.end
                )
                result.refined_end = min(
                    max(result.start + verdict.event_end_relative, result.refined_start), result.end
                )
        elif verdict.state == "rejected":
            # A rejected candidate must never outrank a verified one merely
            # because it retrieved well.  Keep a score for transparent UI.
            result.final_score = -1.0 + 0.35 * retrieval_score
        else:
            result.final_score = 0.35 * retrieval_score

    # Results outside the paid top-N remain legitimate retrieved candidates,
    # just not VLM-checked.  Their score makes that explicit in the UI.
    for result in results[options.top_n :]:
        result.final_score = 0.35 * normalised[result.window_id]

    state_order = {
        "verified": 0,
        "retrieved": 1,
        "verification_unavailable": 1,
        "rejected": 2,
    }
    return sorted(
        results,
        key=lambda result: (
            state_order[result.state],
            -(result.final_score if result.final_score is not None else result.score),
        ),
    )


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Run the complete accuracy-first query path when options are enabled.

    Baseline use remains fast and local: retrieve, fuse, merge, play.  When
    the UI supplies a vision-provider key, this same request additionally
    verifies the top merged candidate regions from their real local frames,
    reranks them, and exposes refined timestamps.
    """
    try:
        _load_encoders()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, detail=f"Query models could not be loaded: {exc}") from exc

    decomposition = _decompose(request)
    try:
        query_vectors, weights = _search_vectors(request, decomposition)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, detail=f"Query embeddings could not be generated: {exc}") from exc
    if not query_vectors:
        raise HTTPException(503, detail="All query encoders failed; search is unavailable.")

    modalities = _eligible_modalities(query_vectors, weights)
    modality_hits: dict[str, list[dict]] = {}
    try:
        # A demo/local Qdrant instance is typically a single process on the
        # same constrained laptop as the encoders.  Serial calls make the
        # four small vector queries deterministic and avoid saturating a
        # recovering/local HTTP connection pool.  This adds only a few
        # milliseconds for normal collections and is much more reliable
        # than a fan-out burst after a cold model load.
        for modality in modalities:
            modality_hits[modality] = _SEARCH_FNS[modality](
                query_vectors[modality], config.DEFAULT_TOP_K
            )
    except QdrantSearchError as exc:
        raise HTTPException(503, detail=f"Qdrant is unreachable; search is unavailable: {exc}") from exc

    fused = rrf_fuse(modality_hits, weights=weights)
    regions = merge_windows(fused)[: request.top_k]
    results = [_result_from_region(region) for region in regions]
    required_conditions = decomposition.required_conditions if decomposition else []

    # Keep the cache for the explicit /verify endpoint too.  It holds no API
    # keys and does not expose source paths outside this process.
    _remember_for_verification(results)
    _last_required_conditions[request.query] = required_conditions
    _last_required_conditions.move_to_end(request.query)
    while len(_last_required_conditions) > _RECENT_RESULTS_CACHE_SIZE:
        _last_required_conditions.popitem(last=False)

    results = _apply_verification_and_rerank(
        results, request.query, required_conditions, request.verification
    )
    return SearchResponse(results=results, decomposition=decomposition)


@app.post("/verify", response_model=VerifyResponse)
def verify(request: VerifyRequest) -> VerifyResponse:
    """Verify cached results for API clients that prefer a second request."""
    if request.verification.provider == "none" and not config.ENABLE_VERIFICATION:
        raise HTTPException(
            status_code=404,
            detail="Verification is disabled (ENABLE_VERIFICATION=false).",
        )
    required_conditions = request.required_conditions or _last_required_conditions.get(request.query, [])
    results: list[VerificationResult] = []
    for candidate_id in request.candidate_ids[: request.verification.top_n]:
        candidate = _recent_results.get(candidate_id)
        if candidate is None:
            results.append(
                VerificationResult(
                    candidate_id=candidate_id,
                    state="verification_unavailable",
                    reason="candidate_id not found in recent /search results",
                )
            )
            continue
        if request.verification.provider == "none":
            results.append(verify_candidate(candidate, request.query, required_conditions))
        else:
            results.append(
                verify_candidate(candidate, request.query, required_conditions, request.verification)
            )
    return VerifyResponse(results=results)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok" if _encoders_ready else "on_demand",
        "verification_enabled": config.ENABLE_VERIFICATION,
        "vision_verification_supported": True,
        "decomposition_enabled": config.ENABLE_QUERY_DECOMPOSITION,
        "low_memory_mode": config.QUERY_LOW_MEMORY_MODE,
    }
