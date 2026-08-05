import time
import pytest
from pydantic import ValidationError
from processing_indexing.models import ActionTiming, VideoWindow
from processing_indexing.models import VLMDescription
from processing_indexing.vlm import (
    HostedQwenProvider,
    OpenAIVisionProvider,
    RetryingVLMProvider,
    VLMError,
)

WINDOW = VideoWindow(video_id="v", window_id="v_window_0000", start=0, end=1)


def test_malformed_json_is_reported():
    provider = RetryingVLMProvider(lambda *args: "not json", timeout=1, retries=1)
    with pytest.raises(VLMError, match="2 attempts"):
        provider.describe(None, WINDOW)


def test_timeout_is_reported_without_silent_success():
    def slow(*args):
        time.sleep(0.1)
        return "{}"

    provider = RetryingVLMProvider(slow, timeout=0.001, retries=0)
    started = time.monotonic()
    with pytest.raises(VLMError, match="1 attempts"):
        provider.describe(None, WINDOW)
    assert time.monotonic() - started < 0.08


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [
                {"message": {"content": '{"scene_context":"room","confidence":0.9}'}}
            ]
        }


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_hosted_provider_uses_configured_endpoint_key_model_and_validates_json():
    client = FakeClient()
    provider = HostedQwenProvider(
        "https://qwen.example/v1/", "secret", "qwen-vl", retries=0, client=client
    )
    provider._encode_frames = lambda *args: ["data:image/jpeg;base64,AA=="]
    result = provider.describe(None, WINDOW)
    url, request = client.calls[0]
    assert url == "https://qwen.example/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert request["json"]["model"] == "qwen-vl"
    assert request["json"]["response_format"] == {"type": "json_object"}
    assert result.scene_context == "room" and result.confidence == 0.9


@pytest.mark.parametrize(
    "base_url,api_key", [(None, "key"), ("https://example/v1", None)]
)
def test_hosted_provider_requires_endpoint_and_environment_key(base_url, api_key):
    with pytest.raises(ValueError):
        HostedQwenProvider(base_url, api_key, "qwen-vl")


class ParsedResponses:
    def __init__(self):
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        usage = type("Usage", (), {"model_dump": lambda self: {"input_tokens": 12}})()
        return type(
            "Response",
            (),
            {
                "output_parsed": VLMDescription(scene_context="desk", confidence=0.8),
                "usage": usage,
            },
        )()


def test_openai_provider_preserves_frame_order_limit_and_validates_structure():
    responses = ParsedResponses()
    client = type("Client", (), {"responses": responses})()
    provider = OpenAIVisionProvider("secret", max_frames=2, client=client)
    provider._encode_frames = lambda *_: [(1.0, "data:first"), (3.0, "data:second")]
    result = provider.describe(None, WINDOW)
    content = responses.calls[0]["input"][0]["content"]
    assert [item["image_url"] for item in content[1:]] == ["data:first", "data:second"]
    assert responses.calls[0]["text_format"] is VLMDescription
    assert provider.last_sanitized_request["frame_timestamps"] == [1.0, 3.0]
    assert "secret" not in str(provider.last_sanitized_request)
    assert result.scene_context == "desk"


def test_openai_provider_rejects_missing_structured_output():
    responses = type(
        "Responses",
        (),
        {
            "parse": lambda self, **kwargs: type(
                "Response", (), {"output_parsed": None, "usage": None}
            )()
        },
    )()
    client = type("Client", (), {"responses": responses})()
    provider = OpenAIVisionProvider("secret", client=client)
    provider._encode_frames = lambda *_: []
    with pytest.raises(VLMError, match="validated structured output"):
        provider.describe(None, WINDOW)


class SequencedResponses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def parse(self, **kwargs):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response(description=None, usage=None, output=None):
    return type(
        "Response",
        (),
        {"output_parsed": description, "usage": usage, "output": output or []},
    )()


def invalid_description():
    try:
        VLMDescription.model_validate({"confidence": "not-a-number"})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected invalid fixture")


def truncated_description():
    try:
        VLMDescription.model_validate_json('{"scene_context":"unfinished')
    except ValidationError as exc:
        return exc
    raise AssertionError("expected truncated fixture")


def test_openai_retries_malformed_then_valid_and_records_each_attempt():
    responses = SequencedResponses(
        [invalid_description(), response(VLMDescription(scene_context="desk"))]
    )
    provider = OpenAIVisionProvider(
        "secret", retries=1, client=type("Client", (), {"responses": responses})()
    )
    provider._encode_frames = lambda *_: []

    assert provider.describe(None, WINDOW).scene_context == "desk"
    assert [x["status"] for x in provider.attempts] == ["failed", "succeeded"]
    assert provider.attempts[0]["failure_category"] == "schema_validation"
    assert [x["attempt"] for x in provider.attempts] == [1, 2]
    assert all(x["model"] == "gpt-4.1-mini" for x in provider.attempts)
    assert "secret" not in str(provider.attempts)


def test_openai_classifies_truncated_json_separately():
    responses = SequencedResponses(
        [truncated_description(), response(VLMDescription(scene_context="desk"))]
    )
    provider = OpenAIVisionProvider(
        "secret", retries=1, client=type("Client", (), {"responses": responses})()
    )
    provider._encode_frames = lambda *_: []

    provider.describe(None, WINDOW)

    assert provider.attempts[0]["failure_category"] == "truncated_json"


def test_openai_stops_after_bounded_always_malformed_responses():
    responses = SequencedResponses([invalid_description(), invalid_description()])
    provider = OpenAIVisionProvider(
        "secret", retries=1, client=type("Client", (), {"responses": responses})()
    )
    provider._encode_frames = lambda *_: []

    with pytest.raises(VLMError, match="2 attempts"):
        provider.describe(None, WINDOW)
    assert responses.calls == 2
    assert len(provider.attempts) == 2


def test_openai_does_not_retry_deterministic_refusal():
    refusal = {"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}
    responses = SequencedResponses([response(output=[refusal])])
    provider = OpenAIVisionProvider(
        "secret", retries=2, client=type("Client", (), {"responses": responses})()
    )
    provider._encode_frames = lambda *_: []

    with pytest.raises(VLMError, match="refused"):
        provider.describe(None, WINDOW)
    assert responses.calls == 1
    assert provider.attempts[0]["failure_category"] == "refusal"


@pytest.mark.parametrize(
    "timing,duration,expected,status",
    [
        (
            ActionTiming(action="a", start_seconds=-2, end_seconds=3),
            10,
            (0, 3),
            "normalized",
        ),
        (
            ActionTiming(action="a", start_seconds=2, end_seconds=15),
            10,
            (2, 10),
            "normalized",
        ),
        (
            ActionTiming(action="a", start_seconds=1, end_seconds=9),
            10,
            (1, 9),
            "unchanged",
        ),
        (
            ActionTiming(action="a", start_seconds=1, end_seconds=8),
            3.5,
            (1, 3.5),
            "normalized",
        ),
    ],
)
def test_openai_normalizes_action_timing_to_selected_window(
    timing, duration, expected, status
):
    window = VideoWindow(
        video_id="v", window_id="v_window_0000", start=4, end=4 + duration
    )
    responses = SequencedResponses(
        [response(VLMDescription(action_timing=[timing], confidence=1))]
    )
    provider = OpenAIVisionProvider(
        "secret", retries=0, client=type("Client", (), {"responses": responses})()
    )
    provider._encode_frames = lambda *_: []

    result = provider.describe(None, window)
    assert (
        result.action_timing[0].start_seconds,
        result.action_timing[0].end_seconds,
    ) == expected
    diagnostic = provider.last_sanitized_response["timing_diagnostics"][0]
    assert diagnostic["original"] == {
        "start_seconds": timing.start_seconds,
        "end_seconds": timing.end_seconds,
    }
    assert diagnostic["status"] == status


def test_openai_rejects_reversed_action_timing_without_presenting_it():
    timing = ActionTiming(action="a", start_seconds=8, end_seconds=2)
    responses = SequencedResponses(
        [response(VLMDescription(action_timing=[timing], confidence=1))]
    )
    provider = OpenAIVisionProvider(
        "secret", retries=0, client=type("Client", (), {"responses": responses})()
    )
    provider._encode_frames = lambda *_: []

    result = provider.describe(None, WINDOW)
    assert result.action_timing == []
    assert (
        provider.last_sanitized_response["timing_diagnostics"][0]["status"]
        == "rejected"
    )


def test_failed_attempt_usage_is_preserved_when_available():
    error = invalid_description()
    error.usage = {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9}
    provider = OpenAIVisionProvider(
        "secret",
        retries=0,
        client=type("Client", (), {"responses": SequencedResponses([error])})(),
    )
    provider._encode_frames = lambda *_: []

    with pytest.raises(VLMError):
        provider.describe(None, WINDOW)
    assert provider.attempts[0]["usage_status"] == "captured"
    assert provider.attempts[0]["usage"]["total_tokens"] == 9


def test_failed_attempt_marks_usage_unavailable_instead_of_zero():
    provider = OpenAIVisionProvider(
        "secret",
        retries=0,
        client=type(
            "Client", (), {"responses": SequencedResponses([invalid_description()])}
        )(),
    )
    provider._encode_frames = lambda *_: []

    with pytest.raises(VLMError):
        provider.describe(None, WINDOW)
    assert provider.attempts[0]["usage_status"] == "unavailable"
    assert provider.attempts[0]["usage"] is None
