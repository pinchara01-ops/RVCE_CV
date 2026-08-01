"""Unit tests for fusion.py's rrf_fuse. Unweighted RRF (query routing was
removed - all modalities always searched, fusion is pure rank-based). All
expected scores are hand-computed, not just shape-checked - RRF formula
bugs hide in the math.
"""
from query_retrieval.fusion import rrf_fuse

K = 60  # matches config.RRF_K default; tests pass k explicitly for clarity


def _hit(window_id: str, video_id: str = "v", start: float = 0.0, end: float = 5.0):
    return {
        "window_id": window_id,
        "score": 0.0,  # per-modality cosine score, irrelevant to RRF rank math
        "payload": {"video_id": video_id, "window_id": window_id, "start": start, "end": end},
    }


def test_single_modality_degrades_to_that_modalitys_ranking():
    results = {"audio": [_hit("w1"), _hit("w2"), _hit("w3")]}

    fused = rrf_fuse(results, k=K)

    assert [h.window_id for h in fused] == ["w1", "w2", "w3"]
    assert fused[0].fused_score == 1.0 / (K + 1)
    assert fused[1].fused_score == 1.0 / (K + 2)
    assert fused[2].fused_score == 1.0 / (K + 3)
    assert fused[0].matched_modalities == ["audio"]


def test_same_window_in_all_four_modalities_sums_not_max():
    # w1 at rank 1 in all 4 modalities.
    results = {
        "visual": [_hit("w1"), _hit("other_v")],
        "audio": [_hit("w1"), _hit("other_a")],
        "speech": [_hit("w1"), _hit("other_s")],
        "caption": [_hit("w1"), _hit("other_c")],
    }

    fused = rrf_fuse(results, k=K)
    w1 = next(h for h in fused if h.window_id == "w1")

    expected = 4 * (1.0 / (K + 1))
    assert w1.fused_score == expected
    assert w1.fused_score != 1.0 / (K + 1)  # would be wrong if max() were used instead of sum
    assert sorted(w1.matched_modalities) == ["audio", "caption", "speech", "visual"]
    # w1 must outrank every window that only appears in one modality.
    assert fused[0].window_id == "w1"


def test_empty_results_dict_returns_empty_list():
    assert rrf_fuse({}, k=K) == []


def test_all_modalities_empty_lists_returns_empty_list():
    results = {"visual": [], "audio": [], "speech": [], "caption": []}
    assert rrf_fuse(results, k=K) == []


def test_rank1_single_modality_vs_rank10_two_modalities():
    """Worked example using the real RRF_K=60 default.

    window_a: rank 1 in visual only -> 1/61 = 0.0163934...
    window_b: rank 10 in both visual and audio -> 1/70 + 1/70 = 2/70 = 0.0285714...
    window_b wins: with k=60 damping single-modality rank differences, two
    weaker (rank 10) signals across different modalities outweigh one
    strong (rank 1) signal in only one modality - RRF rewarding cross-modal
    consensus, exactly the point of fusing multiple modalities. Without a
    router pre-selecting modalities, this rank-based suppression is now the
    *only* mechanism that keeps an irrelevant modality's noise from
    dominating - worth having a hand-verified case for.
    """
    visual_hits = [_hit("window_a")] + [_hit(f"filler_v{i}") for i in range(8)] + [_hit("window_b")]
    audio_hits = [_hit(f"filler_a{i}") for i in range(9)] + [_hit("window_b")]
    results = {"visual": visual_hits, "audio": audio_hits}

    fused = rrf_fuse(results, k=K)
    by_id = {h.window_id: h for h in fused}

    expected_a = 1.0 / (K + 1)
    expected_b = 1.0 / (K + 10) + 1.0 / (K + 10)

    assert abs(by_id["window_a"].fused_score - expected_a) < 1e-12
    assert abs(by_id["window_b"].fused_score - expected_b) < 1e-12
    assert expected_b > expected_a
    assert fused[0].window_id == "window_b"


def test_top_k_applied_after_fusion():
    results = {"visual": [_hit("w1"), _hit("w2"), _hit("w3")]}
    fused = rrf_fuse(results, k=K, top_k=2)
    assert len(fused) == 2
    assert [h.window_id for h in fused] == ["w1", "w2"]


def test_payload_carried_from_first_seen_modality():
    results = {
        "visual": [_hit("w1", video_id="video_visual")],
        "audio": [_hit("w1", video_id="video_audio")],
    }
    fused = rrf_fuse(results, k=K)
    assert fused[0].payload.video_id == "video_visual"  # visual iterated first (dict order)


def test_modality_evidence_populated_with_correct_rank_and_contribution():
    results = {
        "visual": [_hit("w1"), _hit("other_v")],
        "audio": [_hit("other_a"), _hit("w1")],  # w1 at rank 2 here
    }
    fused = rrf_fuse(results, k=K)
    w1 = next(h for h in fused if h.window_id == "w1")

    by_modality = {e.modality: e for e in w1.modality_evidence}
    assert set(by_modality) == {"visual", "audio"}
    assert by_modality["visual"].rank == 1
    assert by_modality["visual"].contribution == 1.0 / (K + 1)
    assert by_modality["audio"].rank == 2
    assert by_modality["audio"].contribution == 1.0 / (K + 2)


def test_modality_evidence_contributions_sum_to_fused_score():
    results = {
        "visual": [_hit("w1"), _hit("other_v"), _hit("w2")],
        "audio": [_hit("w2"), _hit("w1")],
        "speech": [_hit("filler"), _hit("filler2"), _hit("w1")],
    }
    fused = rrf_fuse(results, k=K)

    for hit in fused:
        summed = sum(e.contribution for e in hit.modality_evidence)
        assert abs(summed - hit.fused_score) < 1e-12
        assert sorted(e.modality for e in hit.modality_evidence) == sorted(hit.matched_modalities)


def test_uses_config_rrf_k_as_default():
    from query_retrieval import config
    import inspect

    default_k = inspect.signature(rrf_fuse).parameters["k"].default
    assert default_k == config.RRF_K
