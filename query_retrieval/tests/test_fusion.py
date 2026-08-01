"""Unit tests for fusion.py's weighted_rrf. All expected scores are
hand-computed, not just shape-checked - RRF formula bugs hide in the math.
"""
from query_retrieval.fusion import weighted_rrf

K = 60  # matches config.RRF_K default; tests pass k explicitly for clarity


def _hit(window_id: str, video_id: str = "v", start: float = 0.0, end: float = 5.0):
    return {
        "window_id": window_id,
        "score": 0.0,  # per-modality cosine score, irrelevant to RRF rank math
        "payload": {"video_id": video_id, "window_id": window_id, "start": start, "end": end},
    }


def test_single_modality_degrades_to_that_modalitys_ranking():
    results = {"audio": [_hit("w1"), _hit("w2"), _hit("w3")]}
    weights = {"audio": 1.0}

    fused = weighted_rrf(results, weights, k=K)

    assert [h.window_id for h in fused] == ["w1", "w2", "w3"]
    assert fused[0].fused_score == 1.0 * (1.0 / (K + 1))
    assert fused[1].fused_score == 1.0 * (1.0 / (K + 2))
    assert fused[2].fused_score == 1.0 * (1.0 / (K + 3))
    assert fused[0].matched_modalities == ["audio"]


def test_same_window_in_all_four_modalities_sums_not_max():
    # w1 at rank 1 everywhere; weights split evenly across 4 modalities.
    results = {
        "visual": [_hit("w1"), _hit("other_v")],
        "audio": [_hit("w1"), _hit("other_a")],
        "speech": [_hit("w1"), _hit("other_s")],
        "caption": [_hit("w1"), _hit("other_c")],
    }
    weights = {"visual": 0.25, "audio": 0.25, "speech": 0.25, "caption": 0.25}

    fused = weighted_rrf(results, weights, k=K)
    w1 = next(h for h in fused if h.window_id == "w1")

    expected = 4 * (0.25 * (1.0 / (K + 1)))  # same as 1.0 * 1/(K+1), but verifies summation not max
    assert w1.fused_score == expected
    assert w1.fused_score != 0.25 * (1.0 / (K + 1))  # would be wrong if max() were used instead of sum
    assert sorted(w1.matched_modalities) == ["audio", "caption", "speech", "visual"]
    # w1 must outrank every window that only appears in one modality.
    assert fused[0].window_id == "w1"


def test_empty_results_dict_returns_empty_list():
    assert weighted_rrf({}, {"visual": 1.0}, k=K) == []


def test_all_modalities_empty_lists_returns_empty_list():
    results = {"visual": [], "audio": [], "speech": [], "caption": []}
    weights = {"visual": 0.25, "audio": 0.25, "speech": 0.25, "caption": 0.25}
    assert weighted_rrf(results, weights, k=K) == []


def test_zero_weight_modality_defensively_ignored_even_if_present():
    # Contract says zero-weight modalities shouldn't be in `results` at all,
    # but fusion must not crash or contribute score if one sneaks in.
    results = {
        "visual": [_hit("w1")],
        "audio": [_hit("w1"), _hit("w2")],  # present but weight is 0 below
    }
    weights = {"visual": 1.0, "audio": 0.0}

    fused = weighted_rrf(results, weights, k=K)

    assert [h.window_id for h in fused] == ["w1"]
    assert fused[0].fused_score == 1.0 * (1.0 / (K + 1))
    assert fused[0].matched_modalities == ["visual"]  # audio contribution excluded


def test_rank1_single_modality_vs_rank10_two_modalities():
    """Worked example from the spec, using the real RRF_K=60 default.

    window_a: rank 1 in visual only, weight 0.5 -> 0.5 * 1/61 = 0.0081967...
    window_b: rank 10 in both visual and audio, weights 0.5 each
              -> 0.5*1/70 + 0.5*1/70 = 1.0/70 = 0.0142857...
    window_b wins: with k=60 damping single-modality rank differences, two
    weaker (rank 10) signals across different modalities outweigh one
    strong (rank 1) signal in only one modality - RRF rewarding cross-modal
    consensus, exactly the point of fusing multiple modalities.
    """
    visual_hits = [_hit("window_a")] + [_hit(f"filler_v{i}") for i in range(8)] + [_hit("window_b")]
    audio_hits = [_hit(f"filler_a{i}") for i in range(9)] + [_hit("window_b")]
    results = {"visual": visual_hits, "audio": audio_hits}
    weights = {"visual": 0.5, "audio": 0.5}

    fused = weighted_rrf(results, weights, k=K)
    by_id = {h.window_id: h for h in fused}

    expected_a = 0.5 * (1.0 / (K + 1))
    expected_b = 0.5 * (1.0 / (K + 10)) + 0.5 * (1.0 / (K + 10))

    assert abs(by_id["window_a"].fused_score - expected_a) < 1e-12
    assert abs(by_id["window_b"].fused_score - expected_b) < 1e-12
    assert expected_b > expected_a
    assert fused[0].window_id == "window_b"


def test_top_k_applied_after_fusion():
    results = {"visual": [_hit("w1"), _hit("w2"), _hit("w3")]}
    weights = {"visual": 1.0}
    fused = weighted_rrf(results, weights, k=K, top_k=2)
    assert len(fused) == 2
    assert [h.window_id for h in fused] == ["w1", "w2"]


def test_payload_carried_from_first_seen_modality():
    results = {
        "visual": [_hit("w1", video_id="video_visual")],
        "audio": [_hit("w1", video_id="video_audio")],
    }
    weights = {"visual": 0.6, "audio": 0.4}
    fused = weighted_rrf(results, weights, k=K)
    assert fused[0].payload.video_id == "video_visual"  # visual iterated first (dict order)


def test_uses_config_rrf_k_as_default():
    from query_retrieval import config
    import inspect

    default_k = inspect.signature(weighted_rrf).parameters["k"].default
    assert default_k == config.RRF_K
