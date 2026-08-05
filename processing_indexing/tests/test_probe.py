import json
from types import SimpleNamespace
import pytest
from processing_indexing.probe import probe_video, stable_video_id, VideoProbeError


def test_content_identity(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert stable_video_id(a) == stable_video_id(b)


def test_silent_video_is_valid(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    data = {
        "format": {"duration": "2.5", "format_name": "mov,mp4"},
        "streams": [
            {
                "codec_type": "video",
                "avg_frame_rate": "30/1",
                "width": 10,
                "height": 20,
                "codec_name": "h264",
            }
        ],
    }
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=json.dumps(data), stderr=""
        ),
    )
    assert probe_video(path).has_audio is False


def test_missing_video_stream(tmp_path, monkeypatch):
    path = tmp_path / "v"
    path.write_bytes(b"x")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout='{"format":{"duration":"1"},"streams":[]}', stderr=""
        ),
    )
    with pytest.raises(VideoProbeError, match="no video stream"):
        probe_video(path)


def test_corrupt_video(tmp_path, monkeypatch):
    path = tmp_path / "v"
    path.write_bytes(b"x")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="bad data"),
    )
    with pytest.raises(VideoProbeError, match="bad data"):
        probe_video(path)
