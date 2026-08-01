"""Unit tests for decomposition.py's three-tier fallback ladder
(cache -> live LLM -> deterministic fallback). No real network calls -
the live tier is exercised via a mocked Gemini client.
"""
import json

import pytest

from query_retrieval import config, decomposition


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    def __init__(self, text: str):
        self._text = text

    def generate_content(self, model, contents):
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text: str):
        self.models = _FakeModels(text)


@pytest.fixture(autouse=True)
def _reset_cache_and_config(monkeypatch, tmp_path):
    # Fresh, empty cache per test (isolated from the real, pre-seeded
    # decomposition_cache.json) so cache-tier tests control their own data.
    monkeypatch.setattr(decomposition, "_cache", None)
    monkeypatch.setattr(decomposition, "CACHE_PATH", tmp_path / "decomposition_cache.json")
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key-for-tests")
    yield


def _never_call_gemini(monkeypatch):
    """Fails the test loudly if the live tier is ever reached - used to
    prove cache hits and disabled/no-key paths never touch the network."""
    def _boom():
        raise AssertionError("gemini_client.get_client() should not have been called")
    monkeypatch.setattr("query_retrieval.gemini_client.get_client", lambda: _boom())


# --- tier 1: cache ---


def test_cache_hit_returns_instantly_without_network_call(monkeypatch):
    query = "a dog barking near a fence"
    cached_entry = {
        "visual_query": "a dog near a fence",
        "audio_query": "a dog barking",
        "speech_query": query,
        "caption_query": query,
        "required_conditions": ["a dog is barking"],
        "weights": {"visual": 0.3, "audio": 0.4, "speech": 0.1, "caption": 0.2},
    }
    decomposition.CACHE_PATH.write_text(json.dumps({query: cached_entry}))
    _never_call_gemini(monkeypatch)

    result = decomposition.decompose_query(query)

    assert result.tier == "cache"
    assert result.visual_query == "a dog near a fence"
    assert result.weights == cached_entry["weights"]
    assert result.required_conditions == ["a dog is barking"]


# --- tier 2: live LLM (mocked) ---


def test_live_decomposition_parses_valid_response(monkeypatch):
    query = "person in a red jacket says thank you"
    raw = json.dumps({
        "visual_query": "person wearing a red jacket",
        "audio_query": query,
        "speech_query": "someone says thank you",
        "caption_query": query,
        "required_conditions": ["person is wearing a red jacket"],
        "weights": {"visual": 0.4, "audio": 0.1, "speech": 0.4, "caption": 0.1},
    })
    monkeypatch.setattr("query_retrieval.gemini_client.get_client", lambda: _FakeClient(raw))

    result = decomposition.decompose_query(query)

    assert result.tier == "live"
    assert result.visual_query == "person wearing a red jacket"
    assert result.speech_query == "someone says thank you"
    assert result.required_conditions == ["person is wearing a red jacket"]
    assert abs(sum(result.weights.values()) - 1.0) < 1e-9


def test_live_decomposition_normalizes_weights_that_dont_sum_to_one(monkeypatch):
    query = "loud crash"
    raw = json.dumps({
        "visual_query": query, "audio_query": query, "speech_query": query, "caption_query": query,
        "required_conditions": [],
        "weights": {"visual": 0.1, "audio": 0.3, "speech": 0.0, "caption": 0.0},  # sums to 0.4, not 1.0
    })
    monkeypatch.setattr("query_retrieval.gemini_client.get_client", lambda: _FakeClient(raw))

    result = decomposition.decompose_query(query)

    assert result.tier == "live"
    assert abs(sum(result.weights.values()) - 1.0) < 1e-9
    assert abs(result.weights["audio"] - 0.75) < 1e-9  # 0.3 / 0.4


# --- tier 3: fallback ---


def test_fallback_on_timeout(monkeypatch):
    """A genuinely slow LLM call must fall back within roughly
    DECOMPOSITION_TIMEOUT_SECONDS, not hang for the call's real duration."""
    import time

    def _slow_generate_content(model, contents):
        time.sleep(5)
        return _FakeResponse('{"visual_query": "x"}')

    fake_client = _FakeClient("irrelevant")
    fake_client.models.generate_content = _slow_generate_content
    monkeypatch.setattr("query_retrieval.gemini_client.get_client", lambda: fake_client)
    monkeypatch.setattr(config, "DECOMPOSITION_TIMEOUT_SECONDS", 0.2)

    t0 = time.time()
    result = decomposition.decompose_query("red car")
    elapsed = time.time() - t0

    assert result.tier == "fallback"
    assert result.weights == {"visual": 0.25, "audio": 0.25, "speech": 0.25, "caption": 0.25}
    assert elapsed < 2.0


def test_fallback_on_malformed_json(monkeypatch):
    monkeypatch.setattr("query_retrieval.gemini_client.get_client", lambda: _FakeClient("not valid json at all"))

    result = decomposition.decompose_query("a quiet room")

    assert result.tier == "fallback"


def test_fallback_on_missing_required_field(monkeypatch):
    raw = json.dumps({"visual_query": "x"})  # missing audio/speech/caption/weights
    monkeypatch.setattr("query_retrieval.gemini_client.get_client", lambda: _FakeClient(raw))

    result = decomposition.decompose_query("a party")

    assert result.tier == "fallback"


def test_fallback_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", False)
    _never_call_gemini(monkeypatch)

    result = decomposition.decompose_query("man shouting")

    assert result.tier == "fallback"
    assert result.weights == {"visual": 0.25, "audio": 0.25, "speech": 0.25, "caption": 0.25}


def test_fallback_when_no_api_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    _never_call_gemini(monkeypatch)

    result = decomposition.decompose_query("glass breaking")

    assert result.tier == "fallback"


def test_fallback_result_is_deterministic_and_matches_pre_decomposition_behavior():
    """The fallback tier must be IDENTICAL in effect to "no decomposition
    at all": every modality gets the unchanged original query, weights are
    equal, no required conditions - this is what makes it safe to fall
    back to mid-request without surprising the rest of the pipeline."""
    query = "someone stole the milk from the fridge"
    result = decomposition._fallback_result(query)

    assert result.visual_query == query
    assert result.audio_query == query
    assert result.speech_query == query
    assert result.caption_query == query
    assert result.required_conditions == []
    assert result.weights == {"visual": 0.25, "audio": 0.25, "speech": 0.25, "caption": 0.25}
    assert result.tier == "fallback"
