"""Weighted Reciprocal Rank Fusion across per-modality search results.

RRF_K lives in config.py (added in Phase 2 for the router but never
consumed there - this is the first place it's actually used).
"""
import logging

from query_retrieval import config
from query_retrieval.models import FusedHit, WindowPayload

logger = logging.getLogger(__name__)


def weighted_rrf(
    results: dict[str, list[dict]],
    weights: dict[str, float],
    k: int = config.RRF_K,
    top_k: int | None = None,
) -> list[FusedHit]:
    """Fuse ranked per-modality hit lists into one ranked list.

    For each modality's list, a hit at 1-indexed rank `rank` contributes
    `weight * (1 / (k + rank))` to that window_id's fused score.
    Contributions accumulate across modalities for the same window_id -
    a window appearing in multiple modality lists sums every contribution,
    it is never overwritten.

    `results` should only contain modalities the caller actually searched
    (nonzero router weight, successfully encoded), but a missing/zero-weight/
    empty entry is handled defensively rather than crashing.

    Returns hits sorted by fused_score descending, truncated to `top_k` if
    given (this is the final top_k from the API request - per-modality
    search depth is a separate, unrelated setting).
    """
    scores: dict[str, float] = {}
    payloads: dict[str, WindowPayload] = {}
    matched: dict[str, list[str]] = {}

    for modality, hits in results.items():
        weight = weights.get(modality, 0.0)
        if not hits or weight <= 0.0:
            continue

        for rank, hit in enumerate(hits, start=1):
            window_id = hit.get("window_id")
            if window_id is None:
                continue

            contribution = weight * (1.0 / (k + rank))
            scores[window_id] = scores.get(window_id, 0.0) + contribution

            if window_id not in payloads:
                payloads[window_id] = WindowPayload(**(hit.get("payload") or {}))
                matched[window_id] = [modality]
            else:
                matched[window_id].append(modality)

    fused = [
        FusedHit(
            window_id=window_id,
            fused_score=scores[window_id],
            payload=payloads[window_id],
            matched_modalities=matched[window_id],
        )
        for window_id in scores
    ]
    fused.sort(key=lambda h: h.fused_score, reverse=True)

    if top_k is not None:
        fused = fused[:top_k]
    return fused
