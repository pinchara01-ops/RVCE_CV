"""Unit tests for router.py. Never hits the real Anthropic API."""
from unittest.mock import patch

import pytest

from query_retrieval.router import (
    MODALITIES,
    _fallback_classify,
    _parse_llm_json,
    _threshold_and_normalize,
    classify_query,
)


def test_parse_llm_json_strips_markdown_fences():
    raw = '```json\n{"visual": 1.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}\n```'
    assert _parse_llm_json(raw) == {"visual": 1.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}


def test_parse_llm_json_raises_on_garbage():
    with pytest.raises(ValueError):
        _parse_llm_json("not json at all")


def test_fallback_visual_query():
    weights = _fallback_classify("person in a red jacket")
    assert weights["visual"] > 0
    assert weights["visual"] == max(weights.values())


def test_fallback_audio_query():
    weights = _fallback_classify("loud crash sound")
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


def test_classify_query_llm_success_path():
    with patch("query_retrieval.router._llm_classify") as mock_llm:
        mock_llm.return_value = {"visual": 1.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}
        result = classify_query("person in a red jacket")
    assert result["visual"] == 1.0
    for m in MODALITIES:
        if m != "visual":
            assert result[m] == 0.0


def test_classify_query_llm_failure_triggers_fallback():
    with patch("query_retrieval.router._llm_classify", side_effect=RuntimeError("boom")):
        result = classify_query("loud crash sound")
    assert result["audio"] > 0
    assert abs(sum(result.values()) - 1.0) < 1e-9


def test_classify_query_llm_timeout_triggers_fallback():
    with patch("query_retrieval.router._llm_classify", side_effect=TimeoutError("timed out")):
        result = classify_query("someone says thank you")
    assert result["speech"] > 0


def test_classify_query_malformed_json_triggers_fallback():
    with patch(
        "query_retrieval.router._llm_classify",
        side_effect=ValueError("Malformed JSON from LLM"),
    ):
        result = classify_query("a birthday celebration")
    assert result["caption"] == 1.0


def test_classify_query_no_api_key_triggers_fallback():
    with patch("query_retrieval.config.ANTHROPIC_API_KEY", None):
        result = classify_query("red car driving")
    assert abs(sum(result.values()) - 1.0) < 1e-9


def test_classify_query_never_raises_on_empty_string():
    with patch("query_retrieval.router._llm_classify", side_effect=RuntimeError("boom")):
        result = classify_query("")
    assert abs(sum(result.values()) - 1.0) < 1e-9
