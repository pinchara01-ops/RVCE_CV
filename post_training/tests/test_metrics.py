"""Tests for post_training/evaluate/metrics.py.

All ranked lists/results below are SYNTHETIC/FAKE, hand-picked so expected
values can be verified by hand (shown in comments), not just re-derived from
the same code under test.
"""
from __future__ import annotations

import math

import pytest

from post_training.evaluate.metrics import (
    aggregate_by_slice,
    best_iou_at_k,
    false_positive_rate,
    first_relevant_rank,
    graded_relevance_at_ranks,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    score_query,
    temporal_iou,
)


# ---------------------------------------------------------------------------
# temporal_iou
# ---------------------------------------------------------------------------


def test_iou_partial_overlap():
    # intersection [5,10] = 5, union [0,15] = 15 -> 5/15
    assert temporal_iou(0, 10, 5, 15) == pytest.approx(5 / 15)


def test_iou_no_overlap():
    assert temporal_iou(0, 10, 10, 20) == 0.0


def test_iou_identical():
    assert temporal_iou(0, 10, 0, 10) == 1.0


# ---------------------------------------------------------------------------
# graded_relevance_at_ranks
# ---------------------------------------------------------------------------

# FAKE ranked results: rank1 wrong video, rank2 right video/no overlap,
# rank3 right video/partial overlap, rank4 right video/exact match.
FAKE_RESULTS = [
    {"video_id": "fake-vid-B", "start": 0.0, "end": 5.0},
    {"video_id": "fake-vid-A", "start": 20.0, "end": 25.0},
    {"video_id": "fake-vid-A", "start": 5.0, "end": 15.0},
    {"video_id": "fake-vid-A", "start": 10.0, "end": 20.0},
]


def test_graded_relevance_matches_hand_computed_iou():
    relevance = graded_relevance_at_ranks(
        FAKE_RESULTS, video_id="fake-vid-A", event_start_s=10.0, event_end_s=20.0
    )
    assert relevance[0] == 0.0  # wrong video entirely
    assert relevance[1] == 0.0  # right video, no overlap with [10,20]
    assert relevance[2] == pytest.approx(5 / 15)  # [5,15] vs [10,20]: inter=5, union=15
    assert relevance[3] == 1.0  # exact match


# ---------------------------------------------------------------------------
# first_relevant_rank / recall_at_k / mrr_at_k
# ---------------------------------------------------------------------------

# FAKE binary relevance: hit at rank 3 (1-indexed).
FAKE_RELEVANCE_HIT_AT_3 = [0.0, 0.0, 1.0, 0.0, 0.0]


def test_first_relevant_rank_hit_at_3():
    assert first_relevant_rank(FAKE_RELEVANCE_HIT_AT_3) == 3


def test_first_relevant_rank_no_hit():
    assert first_relevant_rank([0.0, 0.0, 0.0]) is None


def test_recall_at_k_before_and_after_hit():
    assert recall_at_k(FAKE_RELEVANCE_HIT_AT_3, k=1) == 0.0
    assert recall_at_k(FAKE_RELEVANCE_HIT_AT_3, k=2) == 0.0
    assert recall_at_k(FAKE_RELEVANCE_HIT_AT_3, k=3) == 1.0
    assert recall_at_k(FAKE_RELEVANCE_HIT_AT_3, k=10) == 1.0


def test_mrr_at_k_hit_at_3():
    assert mrr_at_k(FAKE_RELEVANCE_HIT_AT_3, k=10) == pytest.approx(1 / 3)
    # hit is beyond k=2, so MRR@2 must be 0
    assert mrr_at_k(FAKE_RELEVANCE_HIT_AT_3, k=2) == 0.0


# ---------------------------------------------------------------------------
# ndcg_at_k
# ---------------------------------------------------------------------------


def test_ndcg_binary_hand_computed():
    # DCG = (2^1 - 1) / log2(3 + 1) = 1 / 2 = 0.5
    # IDCG (ideal: hit at rank 1) = (2^1 - 1) / log2(1 + 1) = 1 / 1 = 1.0
    # nDCG = 0.5 / 1.0 = 0.5
    assert ndcg_at_k(FAKE_RELEVANCE_HIT_AT_3, k=10) == pytest.approx(0.5)


def test_ndcg_perfect_ranking_is_one():
    assert ndcg_at_k([1.0, 0.0, 0.0], k=10) == pytest.approx(1.0)


def test_ndcg_no_relevant_is_zero():
    assert ndcg_at_k([0.0, 0.0, 0.0], k=10) == 0.0


def test_ndcg_graded_hand_computed():
    relevance = [0.5, 1.0, 0.0]
    # Independent re-derivation of the formula (not reusing metrics.py code):
    def dcg(rels):
        return sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(rels))

    expected_dcg = dcg(relevance)
    expected_idcg = dcg(sorted(relevance, reverse=True))
    expected = expected_dcg / expected_idcg
    assert ndcg_at_k(relevance, k=3) == pytest.approx(expected)
    # Sanity: rank-1 item (1.0) contributes more than rank-2 (0.5), and the
    # ranking isn't perfectly ideal (1.0 should have been first), so nDCG < 1.
    assert 0.0 < ndcg_at_k(relevance, k=3) < 1.0


# ---------------------------------------------------------------------------
# best_iou_at_k
# ---------------------------------------------------------------------------


def test_best_iou_at_k():
    relevance = [0.1, 0.9, 0.3]
    assert best_iou_at_k(relevance, k=10) == 0.9
    assert best_iou_at_k(relevance, k=1) == 0.1


def test_best_iou_at_k_empty_is_zero():
    assert best_iou_at_k([], k=10) == 0.0


# ---------------------------------------------------------------------------
# score_query (composite)
# ---------------------------------------------------------------------------


def test_score_query_matches_individual_functions():
    metrics = score_query(
        FAKE_RESULTS,
        video_id="fake-vid-A",
        event_start_s=10.0,
        event_end_s=20.0,
        recall_ks=(1, 3, 10),
        mrr_k=10,
        ndcg_k=10,
        iou_hit_threshold=0.0,
    )
    # rank3 (index 2) is the first result with iou > 0 -> hit at rank 3
    assert metrics["recall@1"] == 0.0
    assert metrics["recall@3"] == 1.0
    assert metrics["recall@10"] == 1.0
    assert metrics["mrr@10"] == pytest.approx(1 / 3)
    assert metrics["temporal_iou"] == 1.0  # rank 4 is an exact match


# ---------------------------------------------------------------------------
# aggregate_by_slice
# ---------------------------------------------------------------------------


def test_aggregate_by_slice_groups_and_means():
    # FAKE scored rows: 2 English, 2 Hindi, recall@1 values chosen so means
    # are easy to hand-check.
    rows = [
        {"language": "en", "recall@1": 1.0, "temporal_iou": 0.8},
        {"language": "en", "recall@1": 0.0, "temporal_iou": 0.2},
        {"language": "hi", "recall@1": 1.0, "temporal_iou": 1.0},
        {"language": "hi", "recall@1": 1.0, "temporal_iou": 0.6},
    ]
    report = aggregate_by_slice(rows, slice_keys=["language"], metric_keys=["recall@1", "temporal_iou"])

    assert report["overall"]["recall@1"] == pytest.approx((1.0 + 0.0 + 1.0 + 1.0) / 4)
    assert report["language"]["en"]["recall@1"] == pytest.approx(0.5)
    assert report["language"]["en"]["temporal_iou"] == pytest.approx(0.5)
    assert report["language"]["hi"]["recall@1"] == pytest.approx(1.0)
    assert report["language"]["hi"]["temporal_iou"] == pytest.approx(0.8)


def test_aggregate_by_slice_missing_metric_is_none_not_zero():
    rows = [{"language": "en", "recall@1": 1.0}, {"language": "en"}]  # second row missing recall@1
    report = aggregate_by_slice(rows, slice_keys=["language"], metric_keys=["recall@1"])
    # Only the one present value should be averaged, not treated as 0.
    assert report["language"]["en"]["recall@1"] == pytest.approx(1.0)


def test_aggregate_by_slice_empty_group_is_none():
    report = aggregate_by_slice([], slice_keys=["language"], metric_keys=["recall@1"])
    assert report["overall"]["recall@1"] is None


# ---------------------------------------------------------------------------
# false_positive_rate
# ---------------------------------------------------------------------------


def test_false_positive_rate_hand_computed():
    # FAKE rows: 3 labeled negatives, 2 of which the system still returned
    # as a hit -> FPR = 2/3. One labeled positive row must be ignored.
    rows = [
        {"relevant": False, "is_hit": True},
        {"relevant": False, "is_hit": True},
        {"relevant": False, "is_hit": False},
        {"relevant": True, "is_hit": True},
    ]
    assert false_positive_rate(rows) == pytest.approx(2 / 3)


def test_false_positive_rate_ambiguous_counts_as_negative():
    rows = [{"relevant": "ambiguous", "is_hit": True}, {"relevant": "ambiguous", "is_hit": False}]
    assert false_positive_rate(rows) == pytest.approx(0.5)


def test_false_positive_rate_no_negatives_is_none():
    rows = [{"relevant": True, "is_hit": True}]
    assert false_positive_rate(rows) is None
