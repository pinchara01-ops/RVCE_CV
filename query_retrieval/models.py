"""Shared pydantic models for payload and API contracts."""
from pydantic import BaseModel, Field


class WindowPayload(BaseModel):
    """Payload schema stored on each Qdrant point.

    Fields gated by feature flags (caption, transcript) may be absent
    upstream; defaults here keep parsing graceful.
    """

    video_id: str
    window_id: str
    start: float
    end: float
    transcript: str = ""
    caption: str = ""
    has_audio: bool = False
    vlm_processed: bool = False


class SearchHit(BaseModel):
    """Normalized result from a single-modality Qdrant search."""

    window_id: str
    score: float
    payload: WindowPayload


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, gt=0, le=100)


class SearchResultItem(BaseModel):
    video_id: str
    window_id: str
    start: float
    end: float
    transcript: str
    caption: str
    score: float
    matched_modalities: list[str]


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query_weights: dict[str, float]
