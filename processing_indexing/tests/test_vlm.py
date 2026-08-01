import time
import pytest
from processing_indexing.models import VideoWindow
from processing_indexing.vlm import RetryingVLMProvider, VLMError

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
