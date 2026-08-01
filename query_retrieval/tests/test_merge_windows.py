"""Unit tests for merge_windows.py. All expected start/end/source_window_ids
are hand-verified, not just count checks - chained-merge and cross-video
bugs hide in the boundary math.
"""
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import FusedHit, WindowPayload

GAP = 5.0  # matches config.MERGE_GAP_SECONDS default


def _hit(window_id, video_id, start, end, score, modalities):
    return FusedHit(
        window_id=window_id,
        fused_score=score,
        matched_modalities=modalities,
        payload=WindowPayload(video_id=video_id, window_id=window_id, start=start, end=end),
    )


def test_no_merges_needed_output_unchanged_except_type():
    hits = [
        _hit("w1", "video_a", 0.0, 5.0, 0.9, ["visual"]),
        _hit("w2", "video_a", 50.0, 55.0, 0.5, ["audio"]),  # gap = 45s, far beyond GAP
    ]

    regions = merge_windows(hits)

    assert len(regions) == 2
    by_id = {r.source_window_ids[0]: r for r in regions}
    assert by_id["w1"].start == 0.0 and by_id["w1"].end == 5.0
    assert by_id["w1"].fused_score == 0.9
    assert by_id["w1"].source_window_ids == ["w1"]
    assert by_id["w2"].start == 50.0 and by_id["w2"].end == 55.0
    # sorted by fused_score descending
    assert regions[0].source_window_ids == ["w1"]
    assert regions[1].source_window_ids == ["w2"]


def test_simple_pairwise_overlap_merges_to_one():
    hits = [
        _hit("w1", "video_a", 0.0, 10.0, 0.6, ["visual"]),
        _hit("w2", "video_a", 5.0, 15.0, 0.8, ["audio"]),  # overlaps w1 (5 < 10)
    ]

    regions = merge_windows(hits)

    assert len(regions) == 1
    region = regions[0]
    assert region.video_id == "video_a"
    assert region.start == 0.0
    assert region.end == 15.0
    assert region.fused_score == 0.8  # max of constituents
    assert region.payload.window_id == "w2"  # payload from highest-scoring constituent
    assert sorted(region.matched_modalities) == ["audio", "visual"]
    assert region.source_window_ids == ["w1", "w2"]


def test_chained_merge_across_non_overlapping_ends():
    # A-B overlap/gap-qualify, B-C overlap/gap-qualify, but A and C do not
    # directly qualify (16 - 5 = 11 > GAP). All three must still merge.
    a = _hit("a", "video_a", 0.0, 5.0, 0.3, ["visual"])
    b = _hit("b", "video_a", 8.0, 12.0, 0.9, ["audio"])   # gap from a.end: 8-5=3 <= GAP
    c = _hit("c", "video_a", 16.0, 20.0, 0.5, ["speech"])  # gap from cluster end (12): 16-12=4 <= GAP

    assert (c.payload.start - a.payload.end) > GAP  # sanity: a-c would NOT directly qualify

    regions = merge_windows([a, b, c])

    assert len(regions) == 1
    region = regions[0]
    assert region.start == 0.0
    assert region.end == 20.0
    assert region.fused_score == 0.9
    assert region.source_window_ids == ["a", "b", "c"]
    assert sorted(region.matched_modalities) == ["audio", "speech", "visual"]


def test_different_videos_same_timestamps_never_merge():
    hits = [
        _hit("w1", "video_a", 0.0, 5.0, 0.7, ["visual"]),
        _hit("w2", "video_b", 0.0, 5.0, 0.6, ["visual"]),  # identical timestamps, different video
    ]

    regions = merge_windows(hits)

    assert len(regions) == 2
    video_ids = {r.video_id for r in regions}
    assert video_ids == {"video_a", "video_b"}
    for region in regions:
        assert len(region.source_window_ids) == 1


def test_boundary_gap_exactly_at_threshold_merges_inclusive():
    hits = [
        _hit("w1", "video_a", 0.0, 5.0, 0.5, ["visual"]),
        _hit("w2", "video_a", 10.0, 15.0, 0.4, ["visual"]),  # gap = 10 - 5 = 5.0 == GAP exactly
    ]
    regions = merge_windows(hits)
    assert len(regions) == 1
    assert regions[0].start == 0.0 and regions[0].end == 15.0
    assert regions[0].source_window_ids == ["w1", "w2"]


def test_boundary_gap_just_over_threshold_does_not_merge():
    hits = [
        _hit("w1", "video_a", 0.0, 5.0, 0.5, ["visual"]),
        _hit("w2", "video_a", 10.0001, 15.0, 0.4, ["visual"]),  # gap = 5.0001 > GAP
    ]
    regions = merge_windows(hits)
    assert len(regions) == 2
