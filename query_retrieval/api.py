"""FastAPI query contract for multimodal retrieval and evidence verification."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from processing_indexing.library import media_path_for_source
from processing_indexing.runtime_profiles import redact_validation_errors
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


@app.exception_handler(RequestValidationError)
async def safe_request_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Do not reflect malformed verification credentials in 422 responses.

    This module can run as a standalone query service as well as behind the
    processing API.  Both entry points therefore need to override FastAPI's
    default validation payload, which otherwise includes a rejected field's
    raw ``input`` value.
    """

    return JSONResponse(
        status_code=422,
        content={"detail": redact_validation_errors(exc.errors())},
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
_runtime_session_resolver: Callable[[str], dict[str, Any]] | None = None


def set_runtime_session_resolver(resolver: Callable[[str], dict[str, Any]] | None) -> None:
    """Inject the private runtime-session resolver from the host API process.

    Query retrieval remains importable as a standalone local service; only the
    API-based profile requires this resolver to obtain its opaque session's
    Qdrant/provider credentials.
    """

    global _runtime_session_resolver
    _runtime_session_resolver = resolver


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


_LOCAL_QWEN_RERANKER_PROVIDERS = frozenset({"local", "qwen", "local_qwen"})


def _reranker_selection_values(
    request: SearchRequest,
    runtime: dict[str, Any] | None = None,
) -> tuple[str, str | None, str]:
    """Return provider/model/source without importing a local model backend."""

    source = "request"
    provider = request.reranker_provider
    model = request.reranker_model
    if runtime is not None:
        configured_providers = runtime.get("providers") or {}
        if "reranker" in configured_providers:
            source = "runtime_session"
            provider = str(configured_providers.get("reranker") or "none")
            configured_models = runtime.get("models") or {}
            model = str(configured_models.get("reranker") or "") or model
    # A direct local client may opt in by naming an official Qwen reranker
    # model even when it omits the convenience provider field.  Do not treat
    # arbitrary model strings as an opt-in to ``trust_remote_code``.
    if (
        source == "request"
        and provider == "none"
        and isinstance(model, str)
        and model.startswith("Qwen/Qwen3-VL-Reranker-")
    ):
        provider = "local_qwen"
        source = "request_model"
    return provider, model, source


def _explicit_qwen_reranker(
    request: SearchRequest,
    runtime: dict[str, Any] | None = None,
) -> tuple[Any | None, dict[str, Any]]:
    """Create a lazy Qwen adapter only for an explicit local selection.

    An API-based run uses a private runtime-session selection when it exists;
    a direct local request can use ``reranker_provider=local_qwen``.  The
    default path returns no adapter and therefore cannot trigger a local
    model import, download, or GPU allocation.
    """

    provider, model, source = _reranker_selection_values(request, runtime)

    if provider not in _LOCAL_QWEN_RERANKER_PROVIDERS:
        return None, {
            "configured": False,
            "selection_source": source,
            "provider": provider,
            "reason": "no_explicit_local_qwen_selection",
        }

    try:
        from query_retrieval.qwen3_vl_backend import (
            DEFAULT_QWEN3_VL_RERANKER_MODEL,
            Qwen3VLRerankerConfig,
            create_qwen3_vl_reranker_backend,
        )
        from query_retrieval.reranking import Qwen3VLRerankerAdapter

        selected_model = model or DEFAULT_QWEN3_VL_RERANKER_MODEL
        settings = Qwen3VLRerankerConfig(model=selected_model)
        return (
            Qwen3VLRerankerAdapter(
                model=settings.model,
                backend_factory=lambda: create_qwen3_vl_reranker_backend(settings),
            ),
            {
                "configured": True,
                "selection_source": source,
                "provider": "local_qwen",
                "model": settings.model,
                "load_policy": "lazy_on_first_bounded_candidate",
            },
        )
    except Exception as exc:  # malformed optional config must keep recall alive
        logger.info("Local Qwen reranker configuration unavailable: %s", type(exc).__name__)
        return None, {
            "configured": False,
            "selection_source": source,
            "provider": "local_qwen",
            "reason": type(exc).__name__,
        }


def _rerank_api_candidates(
    request: SearchRequest,
    candidates: list[SearchResultItem],
    *,
    runtime: dict[str, Any] | None = None,
) -> tuple[list[SearchResultItem], dict[str, Any]]:
    """Run the bounded API precision stage after RRF candidate selection.

    The fused candidate list is the *only* information crossing the recall
    boundary.  The multimodal cross-encoder receives the raw query plus each
    candidate's frames/transcript/caption and returns its own fresh relevance
    score.  In particular, no RRF score, vector similarity, or modality rank
    is passed to the cross-encoder or used to order its scored candidates.

    A missing optional backend fails open to the existing fused recall order;
    this preserves recall rather than silently turning a precision-stage
    outage into an empty result set.
    """

    if not request.enable_reranking:
        return candidates, {
            "stage": "cross_encoder_precision",
            "state": "disabled",
            "candidate_list_source": "rrf_top_k_only",
            "rrf_score_used_for_ordering": False,
            "candidate_count": len(candidates),
        }

    adapter, selection = _explicit_qwen_reranker(request, runtime)
    if adapter is None:
        return candidates, {
            "stage": "cross_encoder_precision",
            "state": "disabled",
            "candidate_list_source": "rrf_top_k_only",
            "rrf_score_used_for_ordering": False,
            "candidate_count": len(candidates),
            "selection": selection,
        }

    try:
        from dataclasses import asdict

        from query_retrieval.reranking import (
            RerankOptions,
            rerank_candidates,
        )

        reranked = rerank_candidates(
            request.query,
            candidates,
            adapter,
            options=RerankOptions(candidate_limit=request.rerank_top_n),
        )
        diagnostics = asdict(reranked.diagnostics)
        diagnostics.update(
            {
                "stage": "cross_encoder_precision",
                "candidate_list_source": "rrf_top_k_only",
                "rrf_score_used_for_ordering": False,
                "selection": selection,
            }
        )
        return reranked.candidates, diagnostics
    except Exception as exc:  # optional precision layer must not remove recall
        logger.info("Cross-encoder reranking unavailable: %s", type(exc).__name__)
        return candidates, {
            "stage": "cross_encoder_precision",
            "state": "unavailable",
            "reason": type(exc).__name__,
            "candidate_list_source": "rrf_top_k_only",
            "rrf_score_used_for_ordering": False,
            "candidate_count": len(candidates),
            "selection": selection,
        }


def _apply_api_verification_evidence(
    results: list[SearchResultItem],
    query: str,
    required_conditions: list[str],
    options: VerificationOptions,
) -> tuple[list[SearchResultItem], dict[str, Any]]:
    """Attach bounded VLM evidence without changing the precision ordering.

    The API profile deliberately differs from the legacy local flow above:
    the cross-encoder has already established precision ordering.  Final VLM
    calls are limited to a few candidates solely to provide explainable
    evidence and to refine a 2--5 second playback interval.  Neither an RRF
    score nor a verification confidence is blended into ``final_score`` or
    used to reorder candidates here.
    """

    started = time.perf_counter()
    if not results:
        return results, {
            "stage": "vlm_evidence_and_localization",
            "state": "skipped",
            "candidate_count": 0,
            "candidates_checked": 0,
            "ordering_changed": False,
            "latency_ms": 0.0,
        }
    if options.provider == "none":
        return results, {
            "stage": "vlm_evidence_and_localization",
            "state": "disabled",
            "provider": "none",
            "candidate_count": len(results),
            "candidates_checked": 0,
            "ordering_changed": False,
            "latency_ms": 0.0,
        }

    candidate_limit = min(len(results), options.top_n)
    state_counts = {
        "verified": 0,
        "rejected": 0,
        "verification_unavailable": 0,
    }
    refined_count = 0
    for result in results[:candidate_limit]:
        verdict = verify_candidate(result, query, required_conditions, options)
        result.verification = verdict
        result.state = verdict.state
        state_counts[verdict.state] += 1
        if (
            verdict.state == "verified"
            and verdict.event_start_relative is not None
            and verdict.event_end_relative is not None
        ):
            result.refined_start = min(
                max(result.start + verdict.event_start_relative, result.start), result.end
            )
            result.refined_end = min(
                max(result.start + verdict.event_end_relative, result.refined_start), result.end
            )
            refined_count += 1

    # Do not sort or set ``final_score``.  The current list is exactly the
    # cross-encoder ordering (or the RRF fallback if that optional stage was
    # unavailable), and verification is evidence-only in this API profile.
    return results, {
        "stage": "vlm_evidence_and_localization",
        "state": "completed",
        "provider": options.provider,
        "candidate_count": len(results),
        "candidates_checked": candidate_limit,
        "state_counts": state_counts,
        "timestamps_refined": refined_count,
        "ordering_changed": False,
        "rrf_score_used_for_ordering": False,
        "verification_confidence_used_for_ordering": False,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _api_runtime(request: SearchRequest) -> tuple[dict[str, Any], Any]:
    """Resolve and validate the private setup for an API-profile search."""

    if not request.runtime_session_id:
        raise HTTPException(400, detail="API-based search requires the active runtime session")
    if _runtime_session_resolver is None:
        raise HTTPException(503, detail="API runtime sessions are not configured in this backend")
    try:
        runtime = _runtime_session_resolver(request.runtime_session_id)
        from processing_indexing.runtime_profiles import get_profile

        profile = get_profile(str(request.profile_id or runtime.get("runtime_profile_id") or ""))
    except Exception as exc:  # never echo third-party/session details to browser
        raise HTTPException(400, detail="The API runtime session is unavailable or expired") from exc
    if profile.id != "api-gemini-free-v1" or runtime.get("runtime_profile_id") != profile.id:
        raise HTTPException(400, detail="Runtime session profile does not match the selected API collection")
    return runtime, profile


def _self_hosted_runtime(request: SearchRequest) -> dict[str, Any] | None:
    """Resolve an optional self-hosted architecture session for local search.

    Local search remains backwards compatible without a session.  When the
    architecture UI did finalize one, this is how an explicit local Qwen
    reranker selection reaches the query process without persisting any
    browser-side configuration or credentials.
    """

    if not request.runtime_session_id:
        return None
    if request.profile_id not in {None, "self-hosted-v1"}:
        return None
    if _runtime_session_resolver is None:
        raise HTTPException(503, detail="Runtime sessions are not configured in this backend")
    try:
        runtime = _runtime_session_resolver(request.runtime_session_id)
    except Exception as exc:
        raise HTTPException(400, detail="The self-hosted runtime session is unavailable or expired") from exc
    if runtime.get("runtime_profile_id") != "self-hosted-v1":
        raise HTTPException(400, detail="Runtime session profile does not match self-hosted search")
    return runtime


def _api_verification_options(
    request: SearchRequest, runtime: dict[str, Any]
) -> VerificationOptions:
    """Make a request-local VLM option from the session, not browser keys."""

    if request.verification.api_key:
        raise HTTPException(400, detail="API-based search credentials must remain in the runtime session")
    if request.verification.provider == "none":
        return request.verification
    configured = str((runtime.get("providers") or {}).get("verification") or "gemini")
    if request.verification.provider != configured:
        raise HTTPException(
            400,
            detail="Choose the verification provider configured in API-based setup",
        )
    key_name = {
        "gemini": "gemini_api_key",
        "openai": "openai_api_key",
        "cosmos": "nvidia_api_key",
    }.get(configured)
    key = runtime.get(key_name or "")
    if not isinstance(key, str) or not key.strip():
        raise HTTPException(400, detail="The configured verification provider has no active API key")
    model = str((runtime.get("models") or {}).get("verification") or "") or None
    return request.verification.model_copy(
        update={"provider": configured, "api_key": key, "model": model}
    )


def _api_profile_query_filter(contract: Any) -> Any:
    """Limit cloud retrieval to records from the selected embedding contract.

    The collection name and named-vector schema isolate normal profile runs,
    but a same-dimension point could otherwise be inserted manually or by a
    stale worker.  Filtering on the payload contract prevents a vector from a
    different provider/model profile from entering RRF merely because its
    dimensionality happens to match.
    """

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(
        must=[
            FieldCondition(
                key="embedding_profile", match=MatchValue(value=contract.profile_id)
            ),
            FieldCondition(
                key="embedding_provider", match=MatchValue(value=contract.provider)
            ),
            FieldCondition(
                key="embedding_model", match=MatchValue(value=contract.embedding_model)
            ),
            FieldCondition(
                key="embedding_dimensions",
                match=MatchValue(value=contract.dimensions),
            ),
        ]
    )


def _gemini_query_http_error(exc: BaseException) -> HTTPException:
    """Map classified provider failures to safe, actionable search errors.

    The browser must be told whether a retry, setup change, or dependency
    install is required, but never receive a provider response that might
    contain endpoint metadata or credentials.
    """

    from processing_indexing.gemini_embeddings import (
        GeminiEmbeddingInputError,
        GeminiEmbeddingResponseError,
        GeminiEmbeddingSDKUnavailableError,
    )
    from processing_indexing.gemini_runtime import (
        GeminiAuthenticationError,
        GeminiInputError,
        GeminiQuotaError,
        GeminiResponseError,
        GeminiRuntimeError,
        GeminiSDKUnavailableError,
        GeminiTransportError,
    )

    if isinstance(exc, (GeminiEmbeddingSDKUnavailableError, GeminiSDKUnavailableError)):
        return HTTPException(
            503,
            detail=(
                "Gemini support is not installed in the backend. "
                "Install requirements.txt, then restart the backend."
            ),
        )
    if isinstance(exc, GeminiAuthenticationError):
        return HTTPException(
            401,
            detail="Gemini rejected the API key. Update it in API-based setup and retry.",
        )
    if isinstance(exc, GeminiQuotaError):
        return HTTPException(
            429,
            detail="Gemini quota or rate limit was reached. Wait briefly, then retry the search.",
        )
    if isinstance(exc, GeminiTransportError):
        return HTTPException(
            503,
            detail="Gemini is temporarily unavailable. Retry the search in a moment.",
        )
    if isinstance(exc, (GeminiEmbeddingInputError, GeminiInputError)):
        return HTTPException(
            400,
            detail="Gemini could not prepare this query. Check the selected models in API-based setup.",
        )
    if isinstance(exc, (GeminiEmbeddingResponseError, GeminiResponseError)):
        return HTTPException(
            502,
            detail="Gemini returned an unusable response. Retry the search.",
        )
    if isinstance(exc, GeminiRuntimeError):
        return HTTPException(
            502,
            detail="Gemini rejected the query request. Check API-based setup and the selected model.",
        )
    return HTTPException(
        503,
        detail="Gemini query expansion or embeddings are unavailable. Check API-based setup and retry.",
    )


def _search_api_profile(request: SearchRequest) -> SearchResponse:
    """Four-channel Gemini/Qdrant Cloud recall, then bounded precision steps."""

    started = time.perf_counter()
    runtime, profile = _api_runtime(request)
    # ``top_k=0`` is a supported probe/empty-result request in the legacy
    # API.  In a hosted profile it must not consume Gemini quota, issue four
    # Qdrant searches, or trigger optional verification merely to return an
    # empty list.
    if request.top_k == 0:
        return SearchResponse(
            results=[],
            diagnostics={
                "profile_id": profile.id,
                "state": "skipped_zero_top_k",
                "total_seconds": round(time.perf_counter() - started, 3),
            },
        )
    providers = dict(runtime.get("providers") or {})
    unsupported = {
        stage: provider
        for stage, provider in providers.items()
        if stage in {"transcription", "media_embedding", "text_embedding", "query_decomposition"}
        and provider != "gemini"
    }
    if unsupported:
        raise HTTPException(
            400,
            detail="This API search implementation currently supports the Gemini provider selection only",
        )
    gemini_key = runtime.get("gemini_api_key")
    if not isinstance(gemini_key, str) or not gemini_key.strip():
        raise HTTPException(400, detail="The active API session does not contain a Gemini API key")

    try:
        from processing_indexing.api_pipeline import (
            GeminiApiPipelineFactoryConfig,
            api_contract_from_runtime_profile,
            build_gemini_api_pipeline,
        )

        contract = api_contract_from_runtime_profile(profile)
        models = dict(runtime.get("models") or {})
        bundle = build_gemini_api_pipeline(
            GeminiApiPipelineFactoryConfig(
                gemini_api_key=gemini_key,
                embedding_model=str(models.get("media_embedding") or "gemini-embedding-2"),
                embedding_dimensions=contract.dimensions,
                generation_model=str(
                    models.get("query_decomposition") or "gemini-3.5-flash-lite"
                ),
                profile_id=contract.profile_id,
                collection_name=contract.collection_name,
            )
        )
        decomposition_started = time.perf_counter()
        plan = bundle.query_decomposer.decompose(request.query)
        decomposition = DecompositionResult(
            visual_query=plan.visual_query,
            audio_query=plan.audio_query,
            speech_query=plan.transcript_query,
            caption_query=plan.caption_query,
            required_conditions=[],
            # Gemini's plan separates text by modality; vector RRF deliberately
            # stays balanced unless a future structured plan returns weights.
            weights={"visual": 0.25, "audio": 0.25, "transcript": 0.25, "caption": 0.25},
            tier="api-gemini-expanded",
        )
        query_vectors = bundle.query_encoder.encode(plan)
        embedding_elapsed = time.perf_counter() - decomposition_started
    except HTTPException:
        raise
    except Exception as exc:  # provider details can include request metadata
        mapped = _gemini_query_http_error(exc)
        logger.info(
            "API query expansion/embedding unavailable: %s (status=%s)",
            type(exc).__name__,
            mapped.status_code,
        )
        raise mapped from exc

    per_channel_k = max(10, min(100, max(request.rerank_top_n, request.top_k * 3)))
    modality_hits: dict[str, list[dict]] = {}
    retrieval_started = time.perf_counter()
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=str(runtime["qdrant_url"]),
            api_key=str(runtime["qdrant_api_key"]),
            timeout=float(runtime.get("qdrant_timeout_seconds", 10)),
        )
        profile_filter = _api_profile_query_filter(contract)
        for modality in ("visual", "audio", "transcript", "caption"):
            points = client.query_points(
                collection_name=contract.collection_name,
                using=modality,
                query=query_vectors[modality],
                query_filter=profile_filter,
                limit=per_channel_k,
                with_payload=True,
            ).points
            modality_hits[modality] = [
                {
                    "window_id": (point.payload or {}).get("window_id"),
                    "score": point.score,
                    "payload": point.payload or {},
                }
                for point in points
            ]
    except Exception as exc:  # do not echo Cloud endpoint/key/client response
        logger.info("API Qdrant retrieval unavailable: %s", type(exc).__name__)
        raise HTTPException(503, detail="Qdrant Cloud retrieval is unavailable") from exc
    retrieval_elapsed = time.perf_counter() - retrieval_started

    fusion_started = time.perf_counter()
    fused = rrf_fuse(modality_hits, weights=decomposition.weights)
    regions = merge_windows(fused)[: request.rerank_top_n]
    fusion_elapsed = time.perf_counter() - fusion_started
    results = [_result_from_region(region) for region in regions]
    fused_results = list(results)
    diagnostics: dict[str, Any] = {
        "profile_id": profile.id,
        "collection_name": contract.collection_name,
        "recall": {
            "stage": "named_vector_rrf",
            "role": "candidate_selection_only",
            "rrf_score_is_not_cross_encoder_input": True,
        },
        "per_channel_top_k": per_channel_k,
        "channel_hit_counts": {name: len(hits) for name, hits in modality_hits.items()},
        "fused_candidates": len(fused),
        "merged_candidates": len(results),
        "query_expansion_and_embedding_seconds": round(embedding_elapsed, 3),
        "vector_retrieval_seconds": round(retrieval_elapsed, 3),
        "rrf_fusion_and_merge_seconds": round(fusion_elapsed, 3),
    }

    # RRF is recall only: it decides this bounded candidate list.  The next
    # stage is a fresh raw-evidence cross-encoder score, never a blend of the
    # RRF/vector score with a new score.
    results, diagnostics["reranking"] = _rerank_api_candidates(
        request, results, runtime=runtime
    )

    # Quality is meaningful only for a labelled evaluation query.  Surface
    # the explicit unevaluated state in ordinary searches instead of trying
    # to infer Recall@K/nDCG/MRR from embedding or reranker scores.
    try:
        from dataclasses import asdict
        from query_retrieval.reranking import calculate_ranking_metrics

        diagnostics["metrics"] = {
            "fused": asdict(
                calculate_ranking_metrics(
                    fused_results, request.relevant_window_ids, k=request.top_k
                )
            ),
            "precision_stage": asdict(
                calculate_ranking_metrics(
                    results, request.relevant_window_ids, k=request.top_k
                )
            ),
        }
    except Exception as exc:  # malformed optional labels must not break search
        diagnostics["metrics"] = {"evaluated": False, "state": type(exc).__name__}

    verification = _api_verification_options(request, runtime)
    results, diagnostics["verification"] = _apply_api_verification_evidence(
        results,
        request.query,
        decomposition.required_conditions,
        verification,
    )
    # Evaluation labels are optional.  This is intentionally a measurement
    # of the list after evidence was attached, not an assertion that a VLM
    # confidence changed its rank.
    try:
        from dataclasses import asdict
        from query_retrieval.reranking import calculate_ranking_metrics

        diagnostics["metrics"]["evidence_stage"] = asdict(
            calculate_ranking_metrics(results, request.relevant_window_ids, k=request.top_k)
        )
    except Exception as exc:  # diagnostics must not make a search fail
        diagnostics.setdefault("metrics", {})["evidence_stage"] = {
            "evaluated": False,
            "state": type(exc).__name__,
        }
    results = results[: request.top_k]
    diagnostics["verification_provider"] = verification.provider
    diagnostics["total_seconds"] = round(time.perf_counter() - started, 3)
    _remember_for_verification(results)
    return SearchResponse(results=results, decomposition=decomposition, diagnostics=diagnostics)


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Run the complete accuracy-first query path when options are enabled.

    Baseline use remains fast and local: retrieve, fuse, merge, play.  When
    the UI supplies a vision-provider key, this same request additionally
    verifies the top merged candidate regions from their real local frames,
    reranks them, and exposes refined timestamps.
    """
    if request.profile_id == "api-gemini-free-v1":
        return _search_api_profile(request)

    local_runtime = _self_hosted_runtime(request)
    local_reranker_provider, _local_reranker_model, _local_reranker_source = (
        _reranker_selection_values(request, local_runtime)
    )
    # The historic self-hosted route stays RRF + legacy verification by
    # default.  The new precision/evidence ordering is entered only after a
    # deliberate local Qwen selection in the request or architecture session.
    use_explicit_local_precision = (
        request.enable_reranking
        and local_reranker_provider in _LOCAL_QWEN_RERANKER_PROVIDERS
    )

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
    precision_candidate_limit = (
        request.rerank_top_n if request.top_k > 0 else 0
    ) if use_explicit_local_precision else request.top_k
    regions = merge_windows(fused)[:precision_candidate_limit]
    results = [_result_from_region(region) for region in regions]
    required_conditions = decomposition.required_conditions if decomposition else []

    if use_explicit_local_precision:
        fused_results = list(results)
        results, reranking_diagnostics = _rerank_api_candidates(
            request, results, runtime=local_runtime
        )
        results, verification_diagnostics = _apply_api_verification_evidence(
            results, request.query, required_conditions, request.verification
        )
        diagnostics: dict[str, Any] = {
            "profile_id": "self-hosted-v1",
            "recall": {
                "stage": "named_vector_rrf",
                "role": "candidate_selection_only",
                "rrf_score_is_not_cross_encoder_input": True,
            },
            "reranking": reranking_diagnostics,
            "verification": verification_diagnostics,
        }
        try:
            from dataclasses import asdict
            from query_retrieval.reranking import calculate_ranking_metrics

            metric_k = max(1, request.top_k)
            diagnostics["metrics"] = {
                "fused": asdict(
                    calculate_ranking_metrics(
                        fused_results, request.relevant_window_ids, k=metric_k
                    )
                ),
                "precision_stage": asdict(
                    calculate_ranking_metrics(results, request.relevant_window_ids, k=metric_k)
                ),
            }
        except Exception as exc:  # diagnostics must never remove local recall
            diagnostics["metrics"] = {"evaluated": False, "state": type(exc).__name__}
        results = results[: request.top_k]
        _remember_for_verification(results)
        _last_required_conditions[request.query] = required_conditions
        _last_required_conditions.move_to_end(request.query)
        while len(_last_required_conditions) > _RECENT_RESULTS_CACHE_SIZE:
            _last_required_conditions.popitem(last=False)
        return SearchResponse(results=results, decomposition=decomposition, diagnostics=diagnostics)

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
