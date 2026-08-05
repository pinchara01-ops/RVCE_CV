"""External API contract (FastAPI). Wired to real Qdrant search functions,
the query router (Phase 2), real query encoders (Phase 3), weighted RRF
fusion (Phase 4), and window merging (Phase 5).
"""
import logging

from fastapi import FastAPI, Response

logging.basicConfig(level=logging.INFO)

from query_retrieval import config, encoders
from query_retrieval.fusion import weighted_rrf
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import SearchRequest, SearchResponse, SearchResultItem
from query_retrieval.qdrant_client import (
    search_audio,
    search_caption,
    search_speech,
    search_visual,
)
from query_retrieval.router import classify_query

logger = logging.getLogger(__name__)

app = FastAPI(title="Query & Retrieval Module", version="0.1.0")

_SEARCH_FNS = {
    "visual": search_visual,
    "audio": search_audio,
    "speech": search_speech,
    "caption": search_caption,
}

# Explicit readiness flag rather than relying on ASGI startup-blocking
# semantics: /health must not report ready until encoder warmup has
# actually finished, or a demo's first query eats the full model-load
# latency instead of a cheap health poll catching that window.
_encoders_ready = False


@app.on_event("startup")
def _load_encoders() -> None:
    """Eagerly load all encoder models so a broken model fails loudly at
    boot, not silently on the first demo query."""
    global _encoders_ready
    encoders.warmup()
    _encoders_ready = True


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Search across all modalities, fuse, and merge into a ranked list of
    candidate regions.

    Modality weights come from the query router (Phase 2); query vectors
    come from the real encoders (Phase 3); ranked lists are combined via
    weighted RRF (Phase 4); overlapping/adjacent same-video hits are then
    merged into single regions (Phase 5). Per-modality search depth is
    config.DEFAULT_TOP_K (a fixed candidate pool) - fusion is left
    untruncated so merging sees every candidate before anything is dropped;
    request.top_k is applied last, to the final merged regions.
    """
    query_weights = classify_query(request.query)
    query_vectors = encoders.encode_query(request.query, query_weights)

    modality_hits = {
        modality: fn(query_vectors[modality], top_k=config.DEFAULT_TOP_K)
        for modality, fn in _SEARCH_FNS.items()
        if modality in query_vectors
    }

    fused = weighted_rrf(modality_hits, query_weights)
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
        )
        for region in regions
    ]
    return SearchResponse(results=results, query_weights=query_weights)


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    if not _encoders_ready:
        response.status_code = 503
        return {"status": "loading"}
    return {"status": "ok"}
