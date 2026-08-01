"""External API contract (FastAPI). Wired to real Qdrant search functions,
real query encoders, unweighted RRF fusion, and window merging.
"""
import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from query_retrieval import config, encoders
from query_retrieval.fusion import rrf_fuse
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import SearchRequest, SearchResponse, SearchResultItem
from query_retrieval.qdrant_client import (
    search_audio,
    search_caption,
    search_speech,
    search_visual,
)

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
    """Encode the query for all 4 modalities, search all 4 in parallel,
    fuse via unweighted RRF, and merge into a ranked list of candidate
    regions.

    No query routing: all 4 modalities are always encoded and searched -
    RRF's rank-based fusion naturally suppresses modalities irrelevant to
    a given query rather than an upstream router deciding in advance which
    to search. Per-modality search depth is config.DEFAULT_TOP_K (a fixed
    candidate pool) - fusion is left untruncated so merging sees every
    candidate before anything is dropped; request.top_k is applied last,
    to the final merged regions.
    """
    query_vectors = encoders.encode_query(request.query)

    modality_hits = {
        modality: fn(query_vectors[modality], top_k=config.DEFAULT_TOP_K)
        for modality, fn in _SEARCH_FNS.items()
        if modality in query_vectors
    }

    fused = rrf_fuse(modality_hits)
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
    return SearchResponse(results=results)


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    if not _encoders_ready:
        response.status_code = 503
        return {"status": "loading"}
    return {"status": "ok"}
