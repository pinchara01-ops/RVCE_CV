"""Unit tests for decomposition.py's three-tier fallback ladder
(cache -> live LLM -> deterministic fallback). No real network calls -
the live tier is exercised via a mocked Groq client (OpenAI-compatible
chat completions response shape).
"""
import json

import pytest

from query_retrieval import config, decomposition


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _FakeClient:
    """Stands in for groq_client.get_client()'s httpx.Client - exposes
    only .post(), matching what groq_client.chat_completion() calls."""

    def __init__(self, content: str, reasoning: str | None = "some chain-of-thought reasoning"):
        self._content = content
        self._reasoning = reasoning

    def post(self, url, json):
        message = {"role": "assistant"}
        if self._reasoning is not None:
            message["reasoning"] = self._reasoning
        if self._content is not None:
            message["content"] = self._content
        return _FakeResponse({"choices": [{"message": message}]})


@pytest.fixture(autouse=True)
def _reset_cache_and_config(monkeypatch, tmp_path):
    # Fresh, empty cache per test (isolated from the real, pre-seeded
    # decomposition_cache.json) so cache-tier tests control their own data.
    monkeypatch.setattr(decomposition, "_cache", None)
    monkeypatch.setattr(decomposition, "CACHE_PATH", tmp_path / "decomposition_cache.json")
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", True)
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-key-for-tests")
    yield


def _never_call_groq(monkeypatch):
    """Fails the test loudly if the live tier is ever reached - used to
    prove cache hits and disabled/no-key paths never touch the network."""
    def _boom():
        raise AssertionError("groq_client.get_client() should not have been called")
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _boom())


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
    _never_call_groq(monkeypatch)

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
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _FakeClient(raw))

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
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _FakeClient(raw))

    result = decomposition.decompose_query(query)

    assert result.tier == "live"
    assert abs(sum(result.weights.values()) - 1.0) < 1e-9
    assert abs(result.weights["audio"] - 0.75) < 1e-9  # 0.3 / 0.4


def test_live_decomposition_ignores_reasoning_field_and_parses_content_only(monkeypatch):
    """Regression test for gpt-oss-20b's separate reasoning/content
    response fields: the reasoning field can contain anything (even
    conflicting JSON-looking text) and must never be read."""
    query = "a dog barking near a fence"
    real_content = json.dumps({
        "visual_query": "dog near a fence", "audio_query": "dog barking sound",
        "speech_query": "", "caption_query": query,
        "required_conditions": [],
        "weights": {"visual": 0.35, "audio": 0.45, "speech": 0.0, "caption": 0.2},
    })
    misleading_reasoning = json.dumps({"weights": {"visual": 1.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}})
    monkeypatch.setattr(
        "query_retrieval.groq_client.get_client",
        lambda: _FakeClient(real_content, reasoning=misleading_reasoning),
    )

    result = decomposition.decompose_query(query)

    assert result.tier == "live"
    assert result.weights["visual"] == pytest.approx(0.35)
    assert result.weights["audio"] == pytest.approx(0.45)


def test_live_decomposition_weights_are_not_all_zero_placeholder_echo(monkeypatch):
    """Regression test for the specific failure found in live testing:
    given only a schema description, gpt-oss-20b echoed the placeholder
    0.0s back literally instead of computing real weights for the query.
    A real (non-placeholder-echo) response for "a dog barking near a
    fence" must produce non-zero, non-uniform weights, not all-0.0."""
    query = "a dog barking near a fence"
    raw = json.dumps({
        "visual_query": "dog near a fence", "audio_query": "dog barking sound",
        "speech_query": "", "caption_query": query,
        "required_conditions": ["a dog is barking"],
        "weights": {"visual": 0.35, "audio": 0.45, "speech": 0.0, "caption": 0.2},
    })
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _FakeClient(raw))

    result = decomposition.decompose_query(query)

    assert result.tier == "live"
    assert not all(w == 0.0 for w in result.weights.values()), "weights must not be the all-zero placeholder-echo bug"
    assert len(set(result.weights.values())) > 1, "weights must not be uniformly equal (a different placeholder-echo shape)"
    assert result.weights["speech"] == 0.0  # correctly zeroed - no spoken words in this query


# --- tier 3: fallback ---


def test_fallback_on_timeout(monkeypatch):
    """A genuinely slow LLM call must fall back within roughly
    DECOMPOSITION_TIMEOUT_SECONDS, not hang for the call's real duration."""
    import time

    class _SlowClient:
        def post(self, url, json):
            time.sleep(5)
            return _FakeResponse({"choices": [{"message": {"content": '{"visual_query": "x"}'}}]})

    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _SlowClient())
    monkeypatch.setattr(config, "DECOMPOSITION_TIMEOUT_SECONDS", 0.2)

    t0 = time.time()
    result = decomposition.decompose_query("red car")
    elapsed = time.time() - t0

    assert result.tier == "fallback"
    assert result.weights == {"visual": 0.25, "audio": 0.25, "speech": 0.25, "caption": 0.25}
    assert elapsed < 2.0


def test_fallback_on_malformed_json(monkeypatch):
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _FakeClient("not valid json at all"))

    result = decomposition.decompose_query("a quiet room")

    assert result.tier == "fallback"


def test_fallback_on_missing_required_field(monkeypatch):
    raw = json.dumps({"visual_query": "x"})  # missing audio/speech/caption/weights
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _FakeClient(raw))

    result = decomposition.decompose_query("a party")

    assert result.tier == "fallback"


def test_fallback_on_empty_content_with_reasoning_present(monkeypatch):
    """gpt-oss-20b returning reasoning but no content (e.g. ran out of
    token budget before finishing the answer) must fall back cleanly,
    not attempt to parse the reasoning field as a workaround."""
    monkeypatch.setattr(
        "query_retrieval.groq_client.get_client",
        lambda: _FakeClient(content="", reasoning="still thinking about the weights..."),
    )

    result = decomposition.decompose_query("an outdoor scene")

    assert result.tier == "fallback"


def test_fallback_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", False)
    _never_call_groq(monkeypatch)

    result = decomposition.decompose_query("man shouting")

    assert result.tier == "fallback"
    assert result.weights == {"visual": 0.25, "audio": 0.25, "speech": 0.25, "caption": 0.25}


def test_fallback_when_no_api_key(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    _never_call_groq(monkeypatch)

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
