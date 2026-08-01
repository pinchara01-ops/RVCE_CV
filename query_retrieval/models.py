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
    top_k: int = Field(default=10, ge=0, le=10000)


class ModalityEvidence(BaseModel):
    """One modality's contribution to a candidate's fused RRF score:
    where it ranked in that modality's own search, and how much of the
    total fused_score that rank position contributed (1/(k+rank)). A
    candidate's modality_evidence entries always sum to its fused_score."""

    modality: str
    rank: int
    contribution: float


class SearchResultItem(BaseModel):
    video_id: str
    window_id: str
    start: float
    end: float
    transcript: str
    caption: str
    score: float
    matched_modalities: list[str]
    modality_evidence: list[ModalityEvidence] = Field(default_factory=list)
    # Only "retrieved" exists today - there's no verification stage yet.
    # A plain str (not a Literal) so a future verification stage can add
    # "verified" / "rejected" without a breaking schema change.
    state: str = "retrieved"


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


class FusedHit(BaseModel):
    """Result of unweighted RRF fusion across modality search results."""

    window_id: str
    fused_score: float
    payload: WindowPayload
    matched_modalities: list[str]
    modality_evidence: list[ModalityEvidence] = Field(default_factory=list)


class MergedRegion(BaseModel):
    """One or more overlapping/adjacent same-video FusedHits merged into a
    single candidate region."""

    video_id: str
    start: float
    end: float
    fused_score: float
    payload: WindowPayload
    matched_modalities: list[str]
    source_window_ids: list[str]
    # Score breakdown of the single constituent FusedHit that fused_score
    # was taken from (same one payload comes from) - not a merge across
    # every constituent, so entries still sum exactly to fused_score.
    modality_evidence: list[ModalityEvidence] = Field(default_factory=list)
