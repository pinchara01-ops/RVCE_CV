"""Unit tests for router.py. Rule-based classifier only - no LLM path."""
from query_retrieval.router import _fallback_classify, _threshold_and_normalize, classify_query


def test_fallback_visual_query():
    weights = _fallback_classify("person in a red jacket")
    assert weights["visual"] > 0
    assert weights["visual"] == max(weights.values())


def test_fallback_audio_query():
    weights = _fallback_classify("loud crash sound")
    assert weights["audio"] > 0
    assert weights["audio"] == max(weights.values())


def test_fallback_audio_query_glass_breaking():
    """Regression: 'glass breaking' is a plausible audio-only query but had
    no matching keyword (found via test_comprehensive.py's query-variety
    sweep - it silently misclassified as caption instead of audio)."""
    weights = _fallback_classify("glass breaking")
    assert weights["audio"] > 0
    assert weights["audio"] == max(weights.values())


def test_fallback_speech_query():
    weights = _fallback_classify("someone says thank you")
    assert weights["speech"] > 0
    assert weights["speech"] == max(weights.values())


def test_fallback_caption_default_for_generic_query():
    weights = _fallback_classify("a birthday celebration")
    assert weights["caption"] == 1.0


def test_fallback_mixed_query():
    weights = _fallback_classify("man shouting in a blue shirt")
    assert weights["visual"] > 0
    assert weights["speech"] > 0


def test_fallback_always_sums_to_one():
    for q in ["red car", "loud bang", "he said hello", "a party", ""]:
        weights = _fallback_classify(q)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_threshold_zeroes_low_weights_and_renormalizes():
    weights = {"visual": 0.5, "audio": 0.03, "speech": 0.02, "caption": 0.45}
    result = _threshold_and_normalize(weights)
    assert result["audio"] == 0.0
    assert result["speech"] == 0.0
    assert abs(result["visual"] - 0.5 / 0.95) < 1e-9
    assert abs(result["caption"] - 0.45 / 0.95) < 1e-9
    assert abs(sum(result.values()) - 1.0) < 1e-9


def test_threshold_all_zero_defaults_to_caption():
    weights = {"visual": 0.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}
    result = _threshold_and_normalize(weights)
    assert result == {"visual": 0.0, "audio": 0.0, "speech": 0.0, "caption": 1.0}


def test_classify_query_matches_fallback_classifier():
    result = classify_query("person in a red jacket")
    assert result["visual"] == 1.0
    assert result["audio"] == result["speech"] == result["caption"] == 0.0


def test_classify_query_never_raises_on_empty_string():
    result = classify_query("")
    assert abs(sum(result.values()) - 1.0) < 1e-9


def test_classify_query_never_raises_on_gibberish():
    result = classify_query("asdkjfh qwoeiru zxcvbn")
    assert abs(sum(result.values()) - 1.0) < 1e-9
