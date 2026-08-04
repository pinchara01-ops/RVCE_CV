"""Unit tests for merge_windows.py. All expected start/end/source_window_ids
are hand-verified, not just count checks - chained-merge and cross-video
bugs hide in the boundary math.
"""
from query_retrieval import config
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import FusedHit, WindowPayload

GAP = 5.0  # matches config.MERGE_GAP_SECONDS default


def _hit(window_id, video_id, start, end, score, modalities, modality_evidence=None):
    return FusedHit(
        window_id=window_id,
        fused_score=score,
        matched_modalities=modalities,
        payload=WindowPayload(video_id=video_id, window_id=window_id, start=start, end=end),
        modality_evidence=modality_evidence or [],
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


# --- bounded merge: MAX_MERGE_WINDOW_COUNT / MAX_MERGE_DURATION_SECONDS ---


def test_chain_splits_at_max_window_count_cap(monkeypatch):
    """10 windows, each gap-qualifying with the next (1s gap <= GAP=5s), so
    without a cap they'd all collapse into one region. With
    MAX_MERGE_WINDOW_COUNT=3 (duration cap disabled), the chain must split
    into ceil(10/3) = 4 regions of sizes [3, 3, 3, 1], continuing the chain
    from the window that would have exceeded the cap rather than dropping it.

    w_i: start = 2*i, end = 2*i + 1 (1s duration, 1s gap to next).
    """
    monkeypatch.setattr(config, "MAX_MERGE_WINDOW_COUNT", 3)
    monkeypatch.setattr(config, "MAX_MERGE_DURATION_SECONDS", 9999.0)

    hits = [_hit(f"w{i}", "video_a", 2.0 * i, 2.0 * i + 1.0, 1.0 - i * 0.01, ["visual"]) for i in range(10)]
    regions = merge_windows(hits)

    assert len(regions) == 4
    by_first = {r.source_window_ids[0]: r for r in regions}

    r0 = by_first["w0"]
    assert r0.source_window_ids == ["w0", "w1", "w2"]
    assert r0.start == 0.0 and r0.end == 5.0  # w2: start=4.0, end=5.0

    r3 = by_first["w3"]
    assert r3.source_window_ids == ["w3", "w4", "w5"]
    assert r3.start == 6.0 and r3.end == 11.0  # w5: start=10.0, end=11.0

    r6 = by_first["w6"]
    assert r6.source_window_ids == ["w6", "w7", "w8"]
    assert r6.start == 12.0 and r6.end == 17.0  # w8: start=16.0, end=17.0

    r9 = by_first["w9"]
    assert r9.source_window_ids == ["w9"]
    assert r9.start == 18.0 and r9.end == 19.0


def test_chain_splits_at_max_duration_cap(monkeypatch):
    """5 windows with a 2s gap between each (<= GAP=5s), but
    MAX_MERGE_DURATION_SECONDS=5.0 (window-count cap disabled) means a
    region can't span more than 5s. w0+w1 span 4s (fits), adding w2 would
    make it span 7s (exceeds) -> split there; w2+w3 spans 4s (fits), adding
    w4 would span 7s (exceeds) -> split again. Expected: [w0,w1], [w2,w3], [w4].
    """
    monkeypatch.setattr(config, "MAX_MERGE_DURATION_SECONDS", 5.0)
    monkeypatch.setattr(config, "MAX_MERGE_WINDOW_COUNT", 9999)

    hits = [
        _hit("w0", "video_a", 0.0, 1.0, 0.9, ["visual"]),
        _hit("w1", "video_a", 3.0, 4.0, 0.8, ["visual"]),   # gap=2, prospective dur=4-0=4 <=5 -> merges
        _hit("w2", "video_a", 6.0, 7.0, 0.7, ["visual"]),   # gap=2, prospective dur=7-0=7 >5 -> splits here
        _hit("w3", "video_a", 9.0, 10.0, 0.6, ["visual"]),  # gap=2, prospective dur=10-6=4 <=5 -> merges
        _hit("w4", "video_a", 12.0, 13.0, 0.5, ["visual"]), # gap=2, prospective dur=13-6=7 >5 -> splits here
    ]
    regions = merge_windows(hits)

    assert len(regions) == 3
    by_first = {r.source_window_ids[0]: r for r in regions}

    r0 = by_first["w0"]
    assert r0.source_window_ids == ["w0", "w1"]
    assert r0.start == 0.0 and r0.end == 4.0

    r2 = by_first["w2"]
    assert r2.source_window_ids == ["w2", "w3"]
    assert r2.start == 6.0 and r2.end == 10.0

    r4 = by_first["w4"]
    assert r4.source_window_ids == ["w4"]
    assert r4.start == 12.0 and r4.end == 13.0


def test_merged_region_modality_evidence_comes_from_best_hit_and_sums_to_fused_score():
    """MergedRegion.modality_evidence must come from the same constituent
    hit that fused_score/payload were taken from (the max-scoring one) -
    otherwise summing its contributions wouldn't equal fused_score."""
    from query_retrieval.models import ModalityEvidence

    weak = _hit(
        "w1", "video_a", 0.0, 5.0, 0.3, ["visual"],
        modality_evidence=[ModalityEvidence(modality="visual", rank=5, contribution=0.3)],
    )
    strong = _hit(
        "w2", "video_a", 5.0, 10.0, 0.9, ["audio", "caption"],
        modality_evidence=[
            ModalityEvidence(modality="audio", rank=1, contribution=0.5),
            ModalityEvidence(modality="caption", rank=1, contribution=0.4),
        ],
    )
    regions = merge_windows([weak, strong])

    assert len(regions) == 1
    region = regions[0]
    assert region.fused_score == 0.9
    assert sorted(e.modality for e in region.modality_evidence) == ["audio", "caption"]
    assert abs(sum(e.contribution for e in region.modality_evidence) - region.fused_score) < 1e-12


def test_bounded_merge_never_crosses_video_id(monkeypatch):
    """Caps apply per-video-chain; two different videos with identical,
    cap-exceeding chains must still each split independently and never
    merge across video_id."""
    monkeypatch.setattr(config, "MAX_MERGE_WINDOW_COUNT", 2)
    monkeypatch.setattr(config, "MAX_MERGE_DURATION_SECONDS", 9999.0)

    hits = []
    for video_id in ("video_a", "video_b"):
        for i in range(4):
            hits.append(_hit(f"{video_id}_w{i}", video_id, 2.0 * i, 2.0 * i + 1.0, 1.0, ["visual"]))

    regions = merge_windows(hits)

    assert len(regions) == 4  # 2 regions per video (4 windows / cap 2)
    assert {r.video_id for r in regions} == {"video_a", "video_b"}
    for r in regions:
        assert all(wid.startswith(r.video_id) for wid in r.source_window_ids)
