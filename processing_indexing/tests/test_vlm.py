import time
import pytest
from processing_indexing.models import VideoWindow
from processing_indexing.vlm import HostedQwenProvider, RetryingVLMProvider, VLMError

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
