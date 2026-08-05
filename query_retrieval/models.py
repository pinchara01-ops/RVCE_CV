"""Shared Pydantic models for Qdrant payloads and the public query API.

The browser never receives a source-media path or an API key.  Both may be
present transiently inside a request while the local API verifies a result,
but are deliberately excluded from any response model or debug export.
"""
from __future__ import annotations

from typing import Literal

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
    # Older seeded development points legitimately lack these fields.
    source_path: str = ""
    caption_direct: bool = True
    caption_inherited: bool = False
    caption_available: bool = True


class SearchHit(BaseModel):
    """Normalized result from a single-modality Qdrant search."""

    window_id: str
    score: float
    payload: WindowPayload


class ModalityEvidence(BaseModel):
    """One modality's contribution to a candidate's fused RRF score."""

    modality: str
    rank: int
    contribution: float


class VerificationOptions(BaseModel):
    """Ephemeral VLM settings supplied directly by the browser.

    ``api_key`` is intentionally excluded from serialisation/repr.  It is
    used for the one request only and is never stored in a job, Qdrant, cache,
    response, or log record.
    """

    provider: Literal["none", "gemini", "openai", "cosmos"] = "none"
    api_key: str | None = Field(default=None, exclude=True, repr=False, max_length=4096)
    model: str | None = Field(default=None, max_length=256)
    max_frames: int = Field(default=8, ge=2, le=16)
    # Seven is a deliberately bounded demo default: retrieval stays cheap,
    # while a VLM gets enough plausible regions to recover from a false
    # positive at rank one.
    top_n: int = Field(default=7, ge=1, le=10)
    # A verified 10–60 second merged region is still too broad to present as
    # the final answer.  The second pass samples time bins within it and asks
    # the *same* selected VLM for a short, evidence-backed span.
    enable_temporal_localization: bool = True
    temporal_target_seconds: float = Field(default=5.0, ge=2.0, le=5.0)
    temporal_max_frames: int = Field(default=12, ge=4, le=24)

    @property
    def enabled(self) -> bool:
        return self.provider != "none" and bool(self.api_key and self.api_key.strip())


class DecompositionResult(BaseModel):
    """Per-modality query text, weights, and required conditions."""

    visual_query: str
    audio_query: str
    speech_query: str
    caption_query: str
    required_conditions: list[str] = Field(default_factory=list)
    weights: dict[str, float]
    tier: str = "fallback"


class VerificationResult(BaseModel):
    """A verification result for one merged candidate region.

    A state of ``verification_unavailable`` is deliberately different from a
    rejection.  It means the VLM did not complete a trustworthy check.
    """

    candidate_id: str
    state: Literal["verified", "rejected", "verification_unavailable"]
    match: bool | None = None
    confidence: float | None = None
    satisfied_conditions: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    evidence: str = ""
    reason: str = ""
    provider: str = ""
    event_start_relative: float | None = None
    event_end_relative: float | None = None
    frame_timestamps: list[float] = Field(default_factory=list)
    # These fields make the two stages observable without exposing source
    # paths, credentials, or raw frames to the browser.  The final event
    # interval above is replaced only after a successful dense pass.
    localization_state: Literal[
        "not_attempted", "not_needed", "localized", "localization_unavailable"
    ] = "not_attempted"
    localization_reason: str = ""
    localization_evidence: str = ""
    localization_frame_timestamps: list[float] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=0, le=10000)
    # None respects the server default.  The UI can explicitly enable the
    # already-implemented decomposition flow for a demo without mutating
    # process-wide environment flags.
    enable_decomposition: bool | None = None
    # API-based collections require the opaque, backend-memory runtime
    # session that owns their Qdrant credentials and provider configuration.
    # It is not an API key and is never echoed by SearchResponse.
    profile_id: str | None = Field(default=None, max_length=128)
    runtime_session_id: str | None = Field(default=None, max_length=512)
    # The cross-encoder sees only the fused candidate set, never the full
    # vector database.  Disabled callers retain the historic RRF-only route.
    enable_reranking: bool = True
    rerank_top_n: int = Field(default=20, ge=1, le=100)
    # Local Qwen reranking is deliberately opt-in.  ``none`` means no local
    # cross-encoder is loaded or downloaded merely because a search opened.
    # API-based runs may instead select this through their private runtime
    # session; public request values cannot supply provider credentials.
    reranker_provider: Literal["none", "local_qwen"] = "none"
    reranker_model: str | None = Field(default=None, max_length=256)
    # Optional labels for a controlled evaluation run.  Live searches leave
    # this unset, so quality metrics remain explicitly "not evaluated" rather
    # than fabricated from retrieval scores.
    relevant_window_ids: list[str] | None = Field(default=None, max_length=10_000)
    verification: VerificationOptions = Field(default_factory=VerificationOptions)


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
    # The browser uses a media endpoint keyed by window_id rather than seeing
    # an absolute filesystem path.
    source_path: str = Field(default="", exclude=True, repr=False)
    media_available: bool = False
    source_window_ids: list[str] = Field(default_factory=list)
    state: Literal["retrieved", "verified", "rejected", "verification_unavailable"] = "retrieved"
    verification: VerificationResult | None = None
    # In the API-based profile this is *only* the fresh bounded
    # cross-encoder relevance score.  It is never an RRF/vector score mixed
    # with a VLM verification confidence.  The historical self-hosted route
    # retains its legacy verification-aware meaning for compatibility.
    final_score: float | None = None
    refined_start: float | None = None
    refined_end: float | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    decomposition: DecompositionResult | None = None
    # Timing/count diagnostics are public only when they contain no source
    # paths, raw vectors, provider credentials, or model responses.
    diagnostics: dict[str, object] = Field(default_factory=dict)


class FusedHit(BaseModel):
    """Result of RRF fusion across modality search results."""

    window_id: str
    fused_score: float
    payload: WindowPayload
    matched_modalities: list[str]
    modality_evidence: list[ModalityEvidence] = Field(default_factory=list)


class MergedRegion(BaseModel):
    """One or more overlapping/adjacent same-video FusedHits."""

    video_id: str
    start: float
    end: float
    fused_score: float
    payload: WindowPayload
    matched_modalities: list[str]
    source_window_ids: list[str]
    modality_evidence: list[ModalityEvidence] = Field(default_factory=list)


class VerifyRequest(BaseModel):
    """Backwards-compatible explicit verification endpoint request."""

    candidate_ids: list[str]
    query: str
    required_conditions: list[str] = Field(default_factory=list)
    verification: VerificationOptions = Field(default_factory=VerificationOptions)


class VerifyResponse(BaseModel):
    results: list[VerificationResult]
