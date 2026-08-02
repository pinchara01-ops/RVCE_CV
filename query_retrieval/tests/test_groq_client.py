"""Unit tests for groq_client.py's hard-timeout wrapper, chat_completion's
content/reasoning parsing, and the JSON parser - shared foundation for
decomposition.py and verification.py. No real network calls; the timeout
mechanism is tested with plain sleep() functions, and chat_completion is
tested against a fake httpx.Client-shaped object.
"""
import time

import pytest

from query_retrieval.groq_client import call_with_hard_timeout, chat_completion, parse_json_response


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _FakeHttpxClient:
    def __init__(self, body: dict):
        self._body = body

    def post(self, url, json):
        return _FakeResponse(self._body)


def _message_body(content=None, reasoning=None):
    message = {"role": "assistant"}
    if reasoning is not None:
        message["reasoning"] = reasoning
    if content is not None:
        message["content"] = content
    return {"choices": [{"message": message}]}


def test_call_with_hard_timeout_returns_fast_result():
    assert call_with_hard_timeout(lambda: 42, timeout_seconds=1.0) == 42


def test_call_with_hard_timeout_raises_timeout_error_and_returns_promptly():
    def _slow():
        time.sleep(5)
        return "too late"

    t0 = time.time()
    with pytest.raises(TimeoutError):
        call_with_hard_timeout(_slow, timeout_seconds=0.2)
    elapsed = time.time() - t0

    # The defining property of a *hard* timeout: the caller gets control
    # back at ~timeout_seconds, not when the slow function eventually
    # finishes (5s) - a library-level timeout can fail to guarantee this.
    assert elapsed < 1.0


def test_call_with_hard_timeout_reraises_the_wrapped_functions_exception():
    def _raises():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        call_with_hard_timeout(_raises, timeout_seconds=1.0)


# --- chat_completion: content/reasoning field parsing ---


def test_chat_completion_parses_content_field():
    client = _FakeHttpxClient(_message_body(content='{"a": 1}', reasoning="thinking about it..."))
    assert chat_completion(client, "some prompt") == '{"a": 1}'


def test_chat_completion_ignores_reasoning_field_entirely():
    """Even with a large reasoning field present, only content is
    returned - reasoning is never inspected or fallen back to."""
    client = _FakeHttpxClient(_message_body(
        content='{"weights": {"visual": 0.4}}',
        reasoning='{"weights": {"visual": 0.9}}',  # deliberately different, to prove this is never read
    ))
    result = chat_completion(client, "some prompt")
    assert result == '{"weights": {"visual": 0.4}}'
    assert "0.9" not in result


def test_chat_completion_raises_on_missing_content_even_with_reasoning_present():
    """Empty/missing content is a malformed-response failure - there is no
    workaround that extracts JSON from reasoning instead."""
    client = _FakeHttpxClient(_message_body(reasoning="only reasoning, no final answer"))
    with pytest.raises(ValueError):
        chat_completion(client, "some prompt")


def test_chat_completion_raises_on_empty_content_string():
    client = _FakeHttpxClient(_message_body(content="", reasoning="some reasoning"))
    with pytest.raises(ValueError):
        chat_completion(client, "some prompt")


# --- parse_json_response ---


def test_parse_json_response_plain_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_strips_markdown_fences():
    raw = '```json\n{"a": 1, "b": 2}\n```'
    assert parse_json_response(raw) == {"a": 1, "b": 2}


def test_parse_json_response_extracts_brace_block_from_stray_text():
    raw = 'Sure, here is the JSON:\n{"a": 1}\nHope that helps!'
    assert parse_json_response(raw) == {"a": 1}


def test_parse_json_response_raises_value_error_on_garbage():
    with pytest.raises(ValueError):
        parse_json_response("not json at all")


def test_parse_json_response_raises_value_error_on_non_object_json():
    with pytest.raises(ValueError):
        parse_json_response("[1, 2, 3]")
