"""External API contract (FastAPI). Wired to real Qdrant search functions,
real query encoders, unweighted RRF fusion, and window merging.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

from query_retrieval import config, encoders
from query_retrieval.fusion import rrf_fuse
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import SearchRequest, SearchResponse, SearchResultItem
from query_retrieval.qdrant_client import (
    QdrantSearchError,
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

# Reused across requests (not a per-call `with ThreadPoolExecutor()`) to
# avoid paying thread-spawn cost on every query. 4 workers = one per
# modality, matching the 4 concurrent Qdrant searches issued per request.
_search_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="qdrant-search")

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

    Encoding (encoders.encode_query) and search (the 4 calls below) each
    run their own modality-calls concurrently rather than sequentially -
    see encoders.py and the thread pool above. A genuine failure (every
    encoder failed, or Qdrant is unreachable) raises HTTPException(503)
    with a descriptive error rather than silently returning an empty
    result set that would be indistinguishable from "no matches".
    """
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
            modality_evidence=region.modality_evidence,
            state="retrieved",
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
