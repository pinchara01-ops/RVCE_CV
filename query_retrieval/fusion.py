"""Reciprocal Rank Fusion across per-modality search results.

Weighting is optional (`weights` param, default None). With weights=None,
every modality contributes on equal footing - `1/(k+rank)` with no
scaling - which is the exact formula this module has always used since
query routing was removed, and is byte-identical to that tested baseline.
This is the path api.py uses whenever ENABLE_QUERY_DECOMPOSITION is off:
the kill switch means "don't touch fusion.py's behavior at all," not "use
degenerate equal weights that happen to rank the same."

When a `weights` dict is passed (from query decomposition -
decomposition.DecompositionResult.weights, expected to sum to ~1.0 across
the 4 modalities), contribution becomes `weight * 1/(k+rank)`. A window
appearing in multiple modality lists sums every (weighted) contribution,
it is never overwritten. Since decomposition always searches all 4
modalities even for a weight-0 one (see decomposition.py), a weight of
0.0 doesn't remove a modality's hits from consideration by fusion - it
just makes their contribution to the score exactly 0.
"""
import logging

from query_retrieval import config
from query_retrieval.models import FusedHit, ModalityEvidence, WindowPayload

logger = logging.getLogger(__name__)


def rrf_fuse(
    results: dict[str, list[dict]],
    k: int = config.RRF_K,
    top_k: int | None = None,
    weights: dict[str, float] | None = None,
) -> list[FusedHit]:
    """Fuse ranked per-modality hit lists into one ranked list.

    For each modality's list, a hit at 1-indexed rank `rank` contributes
    `weight * 1 / (k + rank)` to that window_id's fused score, where
    `weight` is 1.0 for every modality if `weights` is None (today's
    default, unweighted behavior), or `weights.get(modality, 0.0)`
    otherwise. Contributions accumulate across modalities for the same
    window_id - a window appearing in multiple modality lists sums every
    contribution, it is never overwritten.

    A missing or empty modality entry in `results` is handled defensively
    rather than crashing.

    Returns hits sorted by fused_score descending, truncated to `top_k` if
    given (this is the final top_k from the API request - per-modality
    search depth is a separate, unrelated setting).
    """
    scores: dict[str, float] = {}
    payloads: dict[str, WindowPayload] = {}
    matched: dict[str, list[str]] = {}
    evidence: dict[str, list[ModalityEvidence]] = {}

    for modality, hits in results.items():
        if not hits:
            continue

        modality_weight = 1.0 if weights is None else weights.get(modality, 0.0)

        for rank, hit in enumerate(hits, start=1):
            window_id = hit.get("window_id")
            if window_id is None:
                continue

            contribution = modality_weight * (1.0 / (k + rank))
            scores[window_id] = scores.get(window_id, 0.0) + contribution
            entry = ModalityEvidence(modality=modality, rank=rank, contribution=contribution)

            if window_id not in payloads:
                payloads[window_id] = WindowPayload(**(hit.get("payload") or {}))
                matched[window_id] = [modality]
                evidence[window_id] = [entry]
            else:
                matched[window_id].append(modality)
                evidence[window_id].append(entry)

    fused = [
        FusedHit(
            window_id=window_id,
            fused_score=scores[window_id],
            payload=payloads[window_id],
            matched_modalities=matched[window_id],
            modality_evidence=evidence[window_id],
        )
        for window_id in scores
    ]
    fused.sort(key=lambda h: h.fused_score, reverse=True)

    if top_k is not None:
        fused = fused[:top_k]
    return fused
