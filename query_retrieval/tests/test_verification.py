"""Unit tests for verification.py's verify_candidate(): the 3-state output
contract (verified / rejected / verification_unavailable) and the hard
requirement that failure can never produce a false-positive match. No
real network calls - the live tier is exercised via a mocked Groq client
(OpenAI-compatible chat completions response shape).
"""
import json

import pytest

from query_retrieval import config, verification
from query_retrieval.models import SearchResultItem


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


def _candidate(**overrides) -> SearchResultItem:
    defaults = dict(
        video_id="video_a", window_id="video_a_window_0001", start=0.0, end=5.0,
        transcript="a dog barks loudly", caption="a dog is barking near a fence",
        score=0.05, matched_modalities=["audio", "visual"],
    )
    defaults.update(overrides)
    return SearchResultItem(**defaults)


@pytest.fixture(autouse=True)
def _enable_verification(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", True)
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-key-for-tests")
    yield


# --- three states ---


def test_verified_state_on_match_true(monkeypatch):
    raw = json.dumps({
        "match": True, "confidence": 0.92,
        "satisfied_conditions": ["a dog is barking"], "missing_conditions": [], "contradictions": [],
        "evidence": "transcript confirms a dog barking",
    })
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _FakeClient(raw))

    result = verification.verify_candidate(_candidate(), "a dog barking", ["a dog is barking"])

    assert result.state == "verified"
    assert result.match is True
    assert result.confidence == 0.92
    assert result.satisfied_conditions == ["a dog is barking"]


def test_rejected_state_on_match_false(monkeypatch):
    raw = json.dumps({
        "match": False, "confidence": 0.85,
        "satisfied_conditions": [], "missing_conditions": [], "contradictions": ["no cat is mentioned anywhere"],
        "evidence": "evidence describes a dog, not a cat",
    })
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _FakeClient(raw))

    result = verification.verify_candidate(_candidate(), "a cat meowing", ["a cat is present"])

    assert result.state == "rejected"
    assert result.match is False
    assert result.contradictions == ["no cat is mentioned anywhere"]


def test_verification_ignores_reasoning_field_and_parses_content_only(monkeypatch):
    """Regression test for gpt-oss-20b's separate reasoning/content
    response fields - reasoning can disagree with content and must never
    be read."""
    raw = json.dumps({
        "match": True, "confidence": 0.9,
        "satisfied_conditions": ["a dog is barking"], "missing_conditions": [], "contradictions": [],
        "evidence": "transcript confirms a dog barking",
    })
    misleading_reasoning = json.dumps({"match": False, "confidence": 0.1})
    monkeypatch.setattr(
        "query_retrieval.groq_client.get_client",
        lambda: _FakeClient(raw, reasoning=misleading_reasoning),
    )

    result = verification.verify_candidate(_candidate(), "a dog barking", ["a dog is barking"])

    assert result.state == "verified"
    assert result.match is True
    assert result.confidence == 0.9


def test_verification_unavailable_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", False)

    result = verification.verify_candidate(_candidate(), "a dog barking", [])

    assert result.state == "verification_unavailable"
    assert result.match is None
    assert "disabled" in result.reason


def test_verification_unavailable_when_no_key(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", None)

    result = verification.verify_candidate(_candidate(), "a dog barking", [])

    assert result.state == "verification_unavailable"
    assert result.match is None


# --- hard requirement: failure never produces a false-positive match ---


@pytest.mark.parametrize("failure_reason,setup", [
    ("timeout", lambda monkeypatch: monkeypatch.setattr(
        verification, "_live_verify",
        lambda c, q, rc: (_ for _ in ()).throw(TimeoutError("exceeded 2.0s hard timeout")),
    )),
    ("malformed_json", lambda monkeypatch: monkeypatch.setattr(
        "query_retrieval.groq_client.get_client", lambda: _FakeClient("not json at all"),
    )),
    ("missing_match_field", lambda monkeypatch: monkeypatch.setattr(
        "query_retrieval.groq_client.get_client",
        lambda: _FakeClient(json.dumps({"confidence": 0.9})),
    )),
    ("empty_content_with_reasoning_present", lambda monkeypatch: monkeypatch.setattr(
        "query_retrieval.groq_client.get_client",
        lambda: _FakeClient(content="", reasoning="thought about it but ran out of budget"),
    )),
    ("network_error", lambda monkeypatch: monkeypatch.setattr(
        verification, "_live_verify",
        lambda c, q, rc: (_ for _ in ()).throw(ConnectionError("network unreachable")),
    )),
])
def test_forced_failure_never_produces_false_positive_match(monkeypatch, failure_reason, setup):
    setup(monkeypatch)

    result = verification.verify_candidate(_candidate(), "a dog barking", ["a dog is barking"])

    assert result.state == "verification_unavailable", f"failure mode {failure_reason} did not degrade cleanly"
    assert result.match is None, f"failure mode {failure_reason} must never produce match=True or match=False"
    assert result.match is not True


def test_verify_candidate_never_raises_on_unexpected_exception(monkeypatch):
    def _explode(c, q, rc):
        raise RuntimeError("something completely unexpected")

    monkeypatch.setattr(verification, "_live_verify", _explode)

    result = verification.verify_candidate(_candidate(), "anything", [])

    assert result.state == "verification_unavailable"
    assert result.match is None
