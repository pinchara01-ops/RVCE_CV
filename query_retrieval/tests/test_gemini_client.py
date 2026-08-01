"""Unit tests for gemini_client.py's hard-timeout wrapper and JSON parser -
shared foundation for decomposition.py and verification.py. No network
calls; the timeout mechanism is tested with plain sleep() functions.
"""
import time

import pytest

from query_retrieval.gemini_client import call_with_hard_timeout, parse_json_response


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
