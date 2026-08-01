"""External API contract (FastAPI). Wired to real Qdrant search functions,
the real query router (Phase 2), and real query encoders (Phase 3). RRF
fusion + result-window merging still land in Phase 4.
"""
import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)

from query_retrieval import encoders
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


@app.on_event("startup")
def _load_encoders() -> None:
    """Eagerly load all encoder models so a broken model fails loudly at
    boot, not silently on the first demo query."""
    encoders.warmup()


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Search across all modalities and merge into a flat result list.

    Modality weights come from the query router (Phase 2); query vectors
    come from the real encoders (Phase 3). The merge itself is still a
    placeholder: results are grouped by window_id and scored by max hit
    score across modalities. Phase 4 replaces this with RRF fusion.
    """
    query_weights = classify_query(request.query)
    query_vectors = encoders.encode_query(request.query, query_weights)
    merged: dict[str, SearchResultItem] = {}

    for modality, fn in _SEARCH_FNS.items():
        vector = query_vectors.get(modality)
        if vector is None:
            continue  # zero weight from router, or this modality's encoder failed
        hits = fn(vector, top_k=request.top_k)
        for hit in hits:
            window_id = hit["window_id"]
            if window_id is None:
                continue
            payload = hit["payload"]
            if window_id not in merged:
                merged[window_id] = SearchResultItem(
                    video_id=payload.get("video_id", ""),
                    window_id=window_id,
                    start=payload.get("start", 0.0),
                    end=payload.get("end", 0.0),
                    transcript=payload.get("transcript", ""),
                    caption=payload.get("caption", ""),
                    score=hit["score"],
                    matched_modalities=[modality],
                )
            else:
                existing = merged[window_id]
                existing.matched_modalities.append(modality)
                existing.score = max(existing.score, hit["score"])

    results = sorted(merged.values(), key=lambda r: r.score, reverse=True)[: request.top_k]
    return SearchResponse(results=results, query_weights=query_weights)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
