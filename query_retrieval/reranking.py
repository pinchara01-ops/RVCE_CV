"""Bounded multimodal cross-encoder reranking for fused video-search hits.

This module is deliberately a *second* retrieval stage.  It never reads a
collection or calls a vector database: callers give it the already fused top
``K`` :class:`~query_retrieval.models.SearchResultItem` candidates.  Each of
those candidates is sampled independently, then a cross-encoder sees the raw
query together with only that candidate's frames, transcript, and caption.

The resulting relevance score is fresh model output.  It is kept separate
from the first-stage RRF score (``SearchResultItem.score``), which is based on
separate embedding spaces and must not be numerically compared to a
cross-encoder score.

The default frame sampler reuses the existing verification sampler lazily.
That keeps this module import-safe in installations without OpenCV or a local
vision model, and ensures a reranker never samples frames outside its current
candidate window.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
import math
import time
from typing import Literal, Protocol, TypeAlias, runtime_checkable

from query_retrieval.models import SearchResultItem


# The hard ceiling is a guardrail, not a tuning recommendation.  A reranker
# should never accidentally turn a full-library query into hundreds or
# thousands of expensive frame decodes/model calls.
MAX_RERANK_CANDIDATES = 100
MAX_RERANK_FRAMES = 16


class RerankerUnavailable(RuntimeError):
    """A configured reranker cannot run in this process right now.

    Callers should treat this as a safe fail-open condition: retain the fused
    retrieval order and record the diagnostic state.  The exception's message
    is intentionally not exposed in returned diagnostics because provider
    exceptions can contain URLs, paths, or credentials.
    """


class RerankerInputError(ValueError):
    """The candidate evidence cannot satisfy the bounded reranker contract."""


@dataclass(frozen=True)
class CrossEncoderInput:
    """Evidence for exactly one already-retrieved candidate.

    ``frames`` are opaque data URLs (or another adapter-supported frame
    representation) and intentionally exist only for the duration of a
    reranker call.  They never appear in :class:`RerankDiagnostics`.

    Crucially, this is a deliberately score-free projection of the retrieved
    candidate.  It does not expose RRF score, vector similarity, modality
    rank, or modality evidence to a cross-encoder implementation.  The
    candidate list is the only item inherited from the recall stage.
    """

    query: str
    candidate_id: str
    candidate_start: float
    candidate_end: float
    frame_timestamps: tuple[float, ...]
    frames: tuple[str, ...]
    transcript: str
    caption: str


@dataclass(frozen=True)
class CrossEncoderScore:
    """A raw, fresh relevance score produced by a cross-encoder.

    Adapters may return this object when they want to retain a short internal
    note for the caller.  The reranking path itself only uses
    ``relevance_score`` and never combines it with RRF/vector similarities.
    """

    relevance_score: float
    provider_note: str = ""


@runtime_checkable
class MultimodalCrossEncoder(Protocol):
    """Adapter contract shared by local or hosted multimodal rerankers."""

    name: str

    def score(self, evidence: CrossEncoderInput) -> float | CrossEncoderScore:
        """Return one raw relevance score for ``evidence``.

        The score can be a calibrated probability in ``[0, 1]`` or an
        unbounded model logit.  :func:`rerank_candidates` normalizes only this
        set of cross-encoder outputs for response/display purposes.
        """


CrossEncoderRunner: TypeAlias = Callable[[CrossEncoderInput], float | CrossEncoderScore]
CrossEncoderFactory: TypeAlias = Callable[[], CrossEncoderRunner]
FrameSampler: TypeAlias = Callable[[SearchResultItem, int], tuple[Sequence[float], Sequence[str]]]


@dataclass(frozen=True)
class RerankOptions:
    """Bounded request settings for the precision stage.

    ``candidate_limit`` is applied *before* decoding frames or calling the
    cross-encoder.  Callers should pass their fused top-K candidates in rank
    order; any candidates after this limit are deliberately not returned,
    avoiding a misleading partial full-library result.
    """

    candidate_limit: int = 30
    max_frames: int = 8
    min_frames: int = 2
    # A partial model failure should not cause some fresh scores to be placed
    # above unscored candidates.  Keeping the fused order is the safe default.
    preserve_fused_order_on_partial_failure: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.candidate_limit <= MAX_RERANK_CANDIDATES:
            raise ValueError(
                f"candidate_limit must be between 1 and {MAX_RERANK_CANDIDATES}"
            )
        if not 1 <= self.max_frames <= MAX_RERANK_FRAMES:
            raise ValueError(f"max_frames must be between 1 and {MAX_RERANK_FRAMES}")
        if not 1 <= self.min_frames <= self.max_frames:
            raise ValueError("min_frames must be between 1 and max_frames")


RerankState: TypeAlias = Literal["reranked", "partial", "unavailable", "skipped"]
CandidateRerankState: TypeAlias = Literal["scored", "sampling_failed", "scoring_failed"]


@dataclass(frozen=True)
class CandidateRerankDiagnostic:
    """Safe, frame-free timing data for one bounded candidate."""

    window_id: str
    state: CandidateRerankState
    frame_count: int = 0
    sample_latency_ms: float = 0.0
    score_latency_ms: float = 0.0
    # Keep only a class name: provider exception text can leak request data.
    error_type: str | None = None


@dataclass(frozen=True)
class RerankDiagnostics:
    """Observability for the precision stage without raw frame/key leakage."""

    state: RerankState
    adapter: str
    input_candidate_count: int
    candidate_limit: int
    candidates_considered: int
    candidates_discarded_by_bound: int
    candidates_scored: int
    candidates_failed: int
    frame_sampling_latency_ms: float
    scoring_latency_ms: float
    total_latency_ms: float
    score_normalization: str = "not_applied"
    message: str = ""
    candidates: tuple[CandidateRerankDiagnostic, ...] = ()


@dataclass(frozen=True)
class RerankResult:
    """The bounded candidate list plus the rerank stage's diagnostics."""

    candidates: list[SearchResultItem]
    diagnostics: RerankDiagnostics


@dataclass(frozen=True)
class RankingMetrics:
    """Offline/labelled evaluation metrics for a ranked candidate list.

    These are intentionally separate from live query results: without known
    relevant window ids, Recall@K, MRR, and nDCG cannot be truthfully
    calculated.  The API integration can attach them to a test/evaluation run
    when labels are supplied.
    """

    evaluated: bool
    k: int
    relevant_window_count: int
    hits_at_k: int
    recall_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None


class Qwen3VLRerankerAdapter:
    """Lazy adapter seam for a Qwen3-VL-Reranker-compatible backend.

    Qwen-family reranker releases can have different processor/model calling
    conventions.  Instead of importing or downloading a potentially huge
    model at module import, this adapter accepts a small ``backend_factory``.
    The factory runs only on the first candidate and returns a callable that
    consumes :class:`CrossEncoderInput` and emits a raw relevance score.

    A production local integration can therefore construct this adapter with
    a Transformers/vLLM backend, while a hosted implementation can expose the
    same input contract.  With no factory configured, it fails safely as
    ``RerankerUnavailable``; importing this module never triggers model
    downloads, GPU allocation, or optional dependency imports.
    """

    def __init__(
        self,
        *,
        model: str = "Qwen/Qwen3-VL-Reranker",
        backend_factory: CrossEncoderFactory | None = None,
        name: str | None = None,
    ) -> None:
        self.model = model
        self.name = name or model
        self._backend_factory = backend_factory
        self._backend: CrossEncoderRunner | None = None

    @property
    def loaded(self) -> bool:
        """Whether the optional backend has been initialized this session."""

        return self._backend is not None

    def score(self, evidence: CrossEncoderInput) -> float | CrossEncoderScore:
        backend = self._load_backend()
        return backend(evidence)

    def _load_backend(self) -> CrossEncoderRunner:
        if self._backend is not None:
            return self._backend
        if self._backend_factory is None:
            raise RerankerUnavailable(
                "Qwen3-VL-Reranker backend is not configured for this process"
            )
        try:
            backend = self._backend_factory()
        except RerankerUnavailable:
            raise
        except Exception as exc:  # optional model/runtime dependency failure
            raise RerankerUnavailable("Qwen3-VL-Reranker backend could not initialize") from exc
        if not callable(backend):
            raise RerankerUnavailable("Qwen3-VL-Reranker backend is invalid")
        self._backend = backend
        return backend


def default_frame_sampler(
    candidate: SearchResultItem, max_frames: int
) -> tuple[Sequence[float], Sequence[str]]:
    """Lazily reuse the candidate-window sampler from final verification.

    Importing ``verification`` is deferred so a reranker can be configured in
    an API-only environment without eagerly importing OpenCV/vision helpers.
    The verification sampler derives timestamps from the supplied *candidate*
    start/end bounds, never from a library-wide source.
    """

    try:
        from query_retrieval.verification import _sample_frames
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise RerankerUnavailable("candidate frame sampler is unavailable") from exc
    return _sample_frames(candidate, max_frames)


def rerank_candidates(
    query: str,
    candidates: Sequence[SearchResultItem],
    adapter: MultimodalCrossEncoder | None,
    *,
    options: RerankOptions | None = None,
    frame_sampler: FrameSampler | None = None,
) -> RerankResult:
    """Precision-rerank a bounded fused top-K candidate list.

    ``candidates`` must already be sorted by first-stage fusion.  This
    function samples and scores only ``candidate_limit`` candidates; it never
    obtains or iterates over an external collection.  On an unavailable model
    or a partial failure, the safe default preserves the fused order rather
    than mixing fresh scores with vector/RRF scores.
    """

    stage_started = time.perf_counter()
    settings = options or RerankOptions()
    bounded_candidates = list(candidates[: settings.candidate_limit])
    input_count = len(candidates)
    discarded = max(0, input_count - len(bounded_candidates))
    adapter_name = _adapter_name(adapter)

    if not bounded_candidates:
        return RerankResult(
            candidates=[],
            diagnostics=_diagnostics(
                state="skipped",
                adapter=adapter_name,
                input_candidate_count=input_count,
                candidate_limit=settings.candidate_limit,
                candidates_considered=0,
                candidates_discarded_by_bound=discarded,
                candidates_scored=0,
                candidates_failed=0,
                total_started=stage_started,
                message="no fused candidates were supplied",
            ),
        )

    if adapter is None:
        return RerankResult(
            candidates=bounded_candidates,
            diagnostics=_diagnostics(
                state="unavailable",
                adapter=adapter_name,
                input_candidate_count=input_count,
                candidate_limit=settings.candidate_limit,
                candidates_considered=len(bounded_candidates),
                candidates_discarded_by_bound=discarded,
                candidates_scored=0,
                candidates_failed=0,
                total_started=stage_started,
                message="no cross-encoder is configured",
            ),
        )

    sampler = frame_sampler or default_frame_sampler
    item_diagnostics: list[CandidateRerankDiagnostic] = []
    raw_scores: list[tuple[int, SearchResultItem, float]] = []
    total_sampling = 0.0
    total_scoring = 0.0

    for index, candidate in enumerate(bounded_candidates):
        sample_started = time.perf_counter()
        try:
            timestamps, frames = _sample_candidate_frames(candidate, sampler, settings)
        except Exception as exc:
            elapsed = _elapsed_ms(sample_started)
            total_sampling += elapsed
            item_diagnostics.append(
                CandidateRerankDiagnostic(
                    window_id=candidate.window_id,
                    state="sampling_failed",
                    sample_latency_ms=elapsed,
                    error_type=type(exc).__name__,
                )
            )
            continue

        sample_elapsed = _elapsed_ms(sample_started)
        total_sampling += sample_elapsed
        score_started = time.perf_counter()
        try:
            raw_score = _coerce_score(
                adapter.score(
                    CrossEncoderInput(
                        query=query,
                        candidate_id=candidate.window_id,
                        candidate_start=float(candidate.start),
                        candidate_end=float(candidate.end),
                        frame_timestamps=timestamps,
                        frames=frames,
                        transcript=candidate.transcript or "",
                        caption=candidate.caption or "",
                    )
                )
            )
        except Exception as exc:
            score_elapsed = _elapsed_ms(score_started)
            total_scoring += score_elapsed
            item_diagnostics.append(
                CandidateRerankDiagnostic(
                    window_id=candidate.window_id,
                    state="scoring_failed",
                    frame_count=len(frames),
                    sample_latency_ms=sample_elapsed,
                    score_latency_ms=score_elapsed,
                    error_type=type(exc).__name__,
                )
            )
            continue

        score_elapsed = _elapsed_ms(score_started)
        total_scoring += score_elapsed
        raw_scores.append((index, candidate, raw_score))
        item_diagnostics.append(
            CandidateRerankDiagnostic(
                window_id=candidate.window_id,
                state="scored",
                frame_count=len(frames),
                sample_latency_ms=sample_elapsed,
                score_latency_ms=score_elapsed,
            )
        )

    failed = len(bounded_candidates) - len(raw_scores)
    if not raw_scores:
        return RerankResult(
            candidates=bounded_candidates,
            diagnostics=_diagnostics(
                state="unavailable",
                adapter=adapter_name,
                input_candidate_count=input_count,
                candidate_limit=settings.candidate_limit,
                candidates_considered=len(bounded_candidates),
                candidates_discarded_by_bound=discarded,
                candidates_scored=0,
                candidates_failed=failed,
                sample_latency_ms=total_sampling,
                scoring_latency_ms=total_scoring,
                total_started=stage_started,
                message="cross-encoder did not produce a usable candidate score",
                candidates=item_diagnostics,
            ),
        )

    normalized, normalization = _normalize_fresh_scores(raw_scores)
    scored_by_index = {
        index: _copy_with_reranker_score(candidate, normalized_score)
        for (index, candidate, _raw), normalized_score in zip(raw_scores, normalized, strict=True)
    }

    if failed and settings.preserve_fused_order_on_partial_failure:
        # Do not rank a fresh score above an unscored candidate.  The score is
        # still available for observability, but the fused order is retained.
        output = [scored_by_index.get(index, candidate) for index, candidate in enumerate(bounded_candidates)]
        state: RerankState = "partial"
        message = "partial rerank retained fused order because one or more candidates were unscored"
    else:
        # Stable tie-break only on original fused order.  Raw RRF/embedding
        # values are never used in this comparison.
        output = [
            candidate
            for _index, candidate, _score in sorted(
                (
                    (index, scored_by_index[index], normalized_score)
                    for (index, _candidate, _raw), normalized_score in zip(
                        raw_scores, normalized, strict=True
                    )
                ),
                key=lambda item: (-item[2], item[0]),
            )
        ]
        if failed:
            output.extend(
                candidate
                for index, candidate in enumerate(bounded_candidates)
                if index not in scored_by_index
            )
            state = "partial"
            message = "partial rerank placed unscored candidates after scored candidates"
        else:
            state = "reranked"
            message = ""

    return RerankResult(
        candidates=output,
        diagnostics=_diagnostics(
            state=state,
            adapter=adapter_name,
            input_candidate_count=input_count,
            candidate_limit=settings.candidate_limit,
            candidates_considered=len(bounded_candidates),
            candidates_discarded_by_bound=discarded,
            candidates_scored=len(raw_scores),
            candidates_failed=failed,
            sample_latency_ms=total_sampling,
            scoring_latency_ms=total_scoring,
            total_started=stage_started,
            score_normalization=normalization,
            message=message,
            candidates=item_diagnostics,
        ),
    )


def calculate_ranking_metrics(
    candidates: Sequence[SearchResultItem],
    relevant_window_ids: Collection[str] | None,
    *,
    k: int,
) -> RankingMetrics:
    """Calculate binary Recall@K, MRR, and nDCG@K from labelled windows.

    A live query has no ground truth, so pass ``None`` to report an explicitly
    unevaluated result instead of fabricated quality numbers.  Merged regions
    count as relevant when their own ``window_id`` or any ``source_window_ids``
    matches a labelled source window.
    """

    if k < 1:
        raise ValueError("k must be at least 1")
    if relevant_window_ids is None:
        return RankingMetrics(
            evaluated=False,
            k=k,
            relevant_window_count=0,
            hits_at_k=0,
            recall_at_k=None,
            mrr=None,
            ndcg_at_k=None,
        )

    relevant = set(relevant_window_ids)
    top_k = list(candidates[:k])
    relevant_at_rank = [_is_relevant(candidate, relevant) for candidate in top_k]
    hits = sum(relevant_at_rank)
    recall = hits / len(relevant) if relevant else 0.0
    first_hit_rank = next((index + 1 for index, hit in enumerate(relevant_at_rank) if hit), None)
    mrr = 1.0 / first_hit_rank if first_hit_rank is not None else 0.0
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, hit in enumerate(relevant_at_rank)
        if hit
    )
    ideal_hits = min(len(relevant), k)
    ideal_dcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    ndcg = dcg / ideal_dcg if ideal_dcg else 0.0
    return RankingMetrics(
        evaluated=True,
        k=k,
        relevant_window_count=len(relevant),
        hits_at_k=hits,
        recall_at_k=recall,
        mrr=mrr,
        ndcg_at_k=ndcg,
    )


def _sample_candidate_frames(
    candidate: SearchResultItem,
    sampler: FrameSampler,
    options: RerankOptions,
) -> tuple[tuple[float, ...], tuple[str, ...]]:
    timestamps, frames = sampler(candidate, options.max_frames)
    if len(timestamps) != len(frames):
        raise RerankerInputError("frame sampler returned mismatched timestamps and frames")
    pairs: list[tuple[float, str]] = []
    for timestamp, frame in zip(timestamps, frames, strict=True):
        if isinstance(timestamp, bool) or not isinstance(timestamp, (float, int)):
            raise RerankerInputError("frame sampler returned a non-numeric timestamp")
        if not math.isfinite(float(timestamp)):
            raise RerankerInputError("frame sampler returned a non-finite timestamp")
        if not isinstance(frame, str) or not frame:
            raise RerankerInputError("frame sampler returned an invalid frame")
        pairs.append((float(timestamp), frame))
        if len(pairs) == options.max_frames:
            break
    if len(pairs) < options.min_frames:
        raise RerankerInputError("not enough candidate frames for reranking")
    return tuple(timestamp for timestamp, _frame in pairs), tuple(frame for _timestamp, frame in pairs)


def _coerce_score(value: float | CrossEncoderScore) -> float:
    raw = value.relevance_score if isinstance(value, CrossEncoderScore) else value
    if isinstance(raw, bool) or not isinstance(raw, (float, int)):
        raise RerankerInputError("cross-encoder returned a non-numeric score")
    raw_float = float(raw)
    if not math.isfinite(raw_float):
        raise RerankerInputError("cross-encoder returned a non-finite score")
    return raw_float


def _normalize_fresh_scores(
    scores: Sequence[tuple[int, SearchResultItem, float]],
) -> tuple[list[float], str]:
    """Normalize cross-encoder output without touching first-stage scores."""

    raw = [score for _index, _candidate, score in scores]
    if all(0.0 <= score <= 1.0 for score in raw):
        return raw, "native_unit_interval"
    low, high = min(raw), max(raw)
    if math.isclose(low, high):
        return [1.0] * len(raw), "equal_raw_scores"
    return [(score - low) / (high - low) for score in raw], "min_max_fresh_reranker"


def _copy_with_reranker_score(candidate: SearchResultItem, final_score: float) -> SearchResultItem:
    """Return a response-safe copy while preserving the immutable RRF score."""

    return candidate.model_copy(update={"final_score": final_score})


def _adapter_name(adapter: MultimodalCrossEncoder | None) -> str:
    if adapter is None:
        return "not_configured"
    name = getattr(adapter, "name", "")
    return str(name) if name else type(adapter).__name__


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _diagnostics(
    *,
    state: RerankState,
    adapter: str,
    input_candidate_count: int,
    candidate_limit: int,
    candidates_considered: int,
    candidates_discarded_by_bound: int,
    candidates_scored: int,
    candidates_failed: int,
    total_started: float,
    sample_latency_ms: float = 0.0,
    scoring_latency_ms: float = 0.0,
    score_normalization: str = "not_applied",
    message: str = "",
    candidates: Sequence[CandidateRerankDiagnostic] = (),
) -> RerankDiagnostics:
    return RerankDiagnostics(
        state=state,
        adapter=adapter,
        input_candidate_count=input_candidate_count,
        candidate_limit=candidate_limit,
        candidates_considered=candidates_considered,
        candidates_discarded_by_bound=candidates_discarded_by_bound,
        candidates_scored=candidates_scored,
        candidates_failed=candidates_failed,
        frame_sampling_latency_ms=round(sample_latency_ms, 3),
        scoring_latency_ms=round(scoring_latency_ms, 3),
        total_latency_ms=_elapsed_ms(total_started),
        score_normalization=score_normalization,
        message=message,
        candidates=tuple(candidates),
    )


def _is_relevant(candidate: SearchResultItem, relevant_window_ids: set[str]) -> bool:
    return candidate.window_id in relevant_window_ids or bool(
        set(candidate.source_window_ids).intersection(relevant_window_ids)
    )
