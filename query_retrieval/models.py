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


class DecompositionResult(BaseModel):
    """Output of decomposition.decompose_query(): per-modality query text
    plus RRF weights. Always fully populated regardless of which of the
    three fallback tiers (cache/live/deterministic) produced it - the
    deterministic tier just sets every *_query to the original query
    unchanged and every weight to 0.25, which is what makes it
    behaviorally equivalent to "no decomposition" for search purposes
    (see decomposition.py, fusion.rrf_fuse's weights=None default)."""

    visual_query: str
    audio_query: str
    speech_query: str
    caption_query: str
    required_conditions: list[str] = Field(default_factory=list)
    weights: dict[str, float]
    # Which of cache / live / fallback actually produced this result -
    # exposed for logging/debugging, not required by any caller.
    tier: str = "fallback"


class VerificationResult(BaseModel):
    """Output of verification.verify_candidate() for one candidate.

    `state` is always one of three values - "verified" (LLM checked and
    matched), "rejected" (LLM checked and did not match), or
    "verification_unavailable" (the check itself failed/timed out/was
    disabled - NOT the same as "rejected", and must never be reported as
    a match). `match`/`confidence`/etc are only populated when state is
    "verified" or "rejected"; they stay None/empty on "unavailable".
    """

    candidate_id: str
    state: str
    match: bool | None = None
    confidence: float | None = None
    satisfied_conditions: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    evidence: str = ""
    reason: str = ""


class VerifyRequest(BaseModel):
    """candidate_ids are expected in fused_score-descending order, as
    returned by /search's `results[].window_id` - this endpoint doesn't
    re-sort them, it just truncates to the first VERIFICATION_TOP_N."""

    candidate_ids: list[str]
    query: str
    required_conditions: list[str] = Field(default_factory=list)


class VerifyResponse(BaseModel):
    results: list[VerificationResult]
