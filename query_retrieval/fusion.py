"""Reciprocal Rank Fusion across per-modality search results.

Unweighted (architecture change: query routing was removed entirely).
There's no more per-query modality weight signal to multiply in - all 4
modalities are always searched, and RRF fuses purely on rank position. A
modality irrelevant to a given query naturally produces low-relevance
hits that rank far down its own list, contributing a tiny 1/(k+rank)
score; fusion doesn't need to be told in advance which modality matters,
rank position already reflects it.
"""
import logging

from query_retrieval import config
from query_retrieval.models import FusedHit, WindowPayload

logger = logging.getLogger(__name__)


def rrf_fuse(
    results: dict[str, list[dict]],
    k: int = config.RRF_K,
    top_k: int | None = None,
) -> list[FusedHit]:
    """Fuse ranked per-modality hit lists into one ranked list.

    For each modality's list, a hit at 1-indexed rank `rank` contributes
    `1 / (k + rank)` to that window_id's fused score - every modality
    contributes on equal footing. Contributions accumulate across
    modalities for the same window_id - a window appearing in multiple
    modality lists sums every contribution, it is never overwritten.

    A missing or empty modality entry in `results` is handled defensively
    rather than crashing.

    Returns hits sorted by fused_score descending, truncated to `top_k` if
    given (this is the final top_k from the API request - per-modality
    search depth is a separate, unrelated setting).
    """
    scores: dict[str, float] = {}
    payloads: dict[str, WindowPayload] = {}
    matched: dict[str, list[str]] = {}

    for modality, hits in results.items():
        if not hits:
            continue

        for rank, hit in enumerate(hits, start=1):
            window_id = hit.get("window_id")
            if window_id is None:
                continue

            contribution = 1.0 / (k + rank)
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
