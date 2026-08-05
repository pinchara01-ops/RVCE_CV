"""Reusable retrieval-evaluation metrics.

Recall@K, MRR@K, and temporal IoU here were previously inline in
run_baseline.py; this module is the single source of truth for them now,
plus three additions: nDCG@K (graded or binary), per-slice aggregation, and
false-positive rate over explicitly negative-labeled examples.

Every function operates on plain dicts/floats — no dependency on
query_retrieval or the eval-set Pydantic schema — so it is trivial to unit
test with hand-built synthetic ranked lists.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence


def temporal_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Intersection-over-union of two [start, end) intervals."""
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    if union <= 0:
        return 0.0
    return inter / union


def graded_relevance_at_ranks(
    results: Sequence[Mapping[str, float | str]],
    *,
    video_id: str,
    event_start_s: float,
    event_end_s: float,
) -> list[float]:
    """Per-rank relevance grade in [0, 1]: temporal IoU with the labeled event
    for same-video results, 0.0 for any other video. Rank order follows the
    order of ``results`` (assumed already ranked by the retriever)."""
    return [
        temporal_iou(r["start"], r["end"], event_start_s, event_end_s)
        if r["video_id"] == video_id
        else 0.0
        for r in results
    ]


def first_relevant_rank(relevance: Sequence[float], *, threshold: float = 0.0) -> int | None:
    """1-indexed rank of the first result with relevance strictly above
    ``threshold``, or None if no such result exists."""
    for rank, grade in enumerate(relevance, start=1):
        if grade > threshold:
            return rank
    return None


def recall_at_k(relevance: Sequence[float], k: int, *, threshold: float = 0.0) -> float:
    """1.0 if any result in the top k clears ``threshold``, else 0.0.

    This is the single-relevant-item convention (there is exactly one labeled
    event per query in this eval set), not corpus-wide recall over a set of
    many relevant items.
    """
    rank = first_relevant_rank(relevance[:k], threshold=threshold)
    return 1.0 if rank is not None else 0.0


def mrr_at_k(relevance: Sequence[float], k: int, *, threshold: float = 0.0) -> float:
    rank = first_relevant_rank(relevance[:k], threshold=threshold)
    return 1.0 / rank if rank is not None else 0.0


def ndcg_at_k(relevance: Sequence[float], k: int) -> float:
    """Standard nDCG@K, using the graded-gain formula
    ``DCG = sum((2**rel - 1) / log2(rank + 1))``. Passing binary (0/1)
    relevance grades reduces this to the standard binary nDCG.
    """
    top_k = list(relevance[:k])
    dcg = sum(
        (2**grade - 1) / math.log2(index + 2)  # rank = index+1, so log2(rank+1) = log2(index+2)
        for index, grade in enumerate(top_k)
    )
    ideal = sorted(top_k, reverse=True)
    idcg = sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def best_iou_at_k(relevance: Sequence[float], k: int) -> float:
    """Best (max) relevance grade within the top k — used as the temporal-IoU
    summary metric."""
    top_k = relevance[:k]
    return max(top_k, default=0.0)


def score_query(
    results: Sequence[Mapping[str, float | str]],
    *,
    video_id: str,
    event_start_s: float,
    event_end_s: float,
    recall_ks: Sequence[int] = (1, 5, 10),
    mrr_k: int = 10,
    ndcg_k: int = 10,
    iou_hit_threshold: float = 0.0,
) -> dict[str, float]:
    """Score one ranked ``results`` list (as returned by /search) against one
    labeled query. Returns a flat metric-name -> value dict."""
    relevance = graded_relevance_at_ranks(
        results, video_id=video_id, event_start_s=event_start_s, event_end_s=event_end_s
    )
    metrics = {
        f"recall@{k}": recall_at_k(relevance, k, threshold=iou_hit_threshold) for k in recall_ks
    }
    metrics[f"mrr@{mrr_k}"] = mrr_at_k(relevance, mrr_k, threshold=iou_hit_threshold)
    metrics[f"ndcg@{ndcg_k}"] = ndcg_at_k(relevance, ndcg_k)
    metrics["temporal_iou"] = best_iou_at_k(relevance, max(recall_ks, default=10))
    return metrics


def aggregate_by_slice(
    rows: Sequence[Mapping[str, object]],
    *,
    slice_keys: Sequence[str],
    metric_keys: Sequence[str],
) -> dict[str, dict[str, dict[str, float | None]]]:
    """Group scored rows by each of ``slice_keys`` and mean each of
    ``metric_keys`` within every group.

    Each element of ``rows`` is expected to carry both metric values (under
    ``metric_keys``) and metadata (under ``slice_keys``), e.g.:
    ``{"recall@1": 1.0, "temporal_iou": 0.6, "language": "hi", "domain": "retail"}``.

    Returns ``{"overall": {metric: mean}, <slice_key>: {<slice_value>: {metric: mean}}}``.
    A metric absent from every row in a group reports as None rather than
    silently as 0.0.
    """

    def _mean_metrics(group: Sequence[Mapping[str, object]]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for metric in metric_keys:
            values = [row[metric] for row in group if metric in row and row[metric] is not None]
            out[metric] = statistics.mean(values) if values else None  # type: ignore[arg-type]
        return out

    report: dict[str, dict[str, dict[str, float | None]]] = {"overall": _mean_metrics(rows)}  # type: ignore[assignment]
    for slice_key in slice_keys:
        groups: dict[str, list[Mapping[str, object]]] = {}
        for row in rows:
            value = str(row.get(slice_key, "unknown"))
            groups.setdefault(value, []).append(row)
        report[slice_key] = {value: _mean_metrics(group) for value, group in sorted(groups.items())}
    return report


def false_positive_rate(
    rows: Sequence[Mapping[str, object]],
    *,
    relevant_key: str = "relevant",
    hit_key: str = "is_hit",
) -> float | None:
    """Fraction of explicitly negative-labeled examples the system still
    surfaced as a top-K hit.

    Each row must carry ``relevant_key`` (False, or the string "ambiguous" —
    the eval schema's ``labels.relevant`` is boolean today, but "ambiguous"
    is accepted too since post-training/README.md section 10 treats ambiguous
    activity as a case that should never be taught as a positive) and
    ``hit_key`` (whether the system returned a top-K result matching that
    example's labeled window). Rows with ``relevant_key`` truthy (True) are
    ignored. Returns None if there are no negative-labeled rows to score.
    """
    negatives = [row for row in rows if row.get(relevant_key) in (False, "ambiguous")]
    if not negatives:
        return None
    return sum(1 for row in negatives if row.get(hit_key)) / len(negatives)
