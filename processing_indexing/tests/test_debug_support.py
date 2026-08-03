import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from processing_indexing.config import Settings
from processing_indexing.debug_cache import cache_invalidation
from processing_indexing.debug_jobs import Job, JobManager, safe_filename, sanitize
from processing_indexing.preflight import model_statuses


def test_preflight_reports_exact_checkpoints_without_loading(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    settings = Settings()
    statuses = {item.component: item for item in model_statuses(settings, "openai")}
    assert statuses["whisper"].checkpoint == "small"
    assert statuses["visual"].checkpoint == "microsoft/xclip-base-patch32"
    assert statuses["audio"].checkpoint == "laion/clap-htsat-unfused"
    assert statuses["text"].checkpoint == "BAAI/bge-m3"
    assert statuses["vlm"].checkpoint == "gpt-4.1-mini"
    assert all(
        not item.loading_attempted and not item.load_success
        for item in statuses.values()
    )


def test_preflight_identifies_mock_and_real_provider():
    assert model_statuses(Settings(), "mock")[-1].provider_kind == "mock"
    assert (
        model_statuses(replace(Settings(), openai_api_key="server-secret"), "openai")[
            -1
        ].provider_kind
        == "real"
    )


def test_cache_invalidation_rules():
    base = {
        "video_id": "v",
        "whisper_model": "small",
        "visual_model": "x",
        "audio_model": "a",
        "text_model": "b",
        "window_seconds": 10,
        "stride_seconds": 5,
        "vlm_provider": "openai",
        "vlm_model": "m1",
        "caption_prompt_version": "1",
        "openai_image_detail": "low",
        "openai_max_frames": 4,
    }
    threshold_change = dict(base, visual_threshold=0.9)
    assert not any(cache_invalidation(base, threshold_change).values())
    model_change = dict(base, vlm_model="m2")
    changed = cache_invalidation(base, model_change)
    assert not any(changed[x] for x in ("transcript", "visual", "audio", "speech"))
    assert changed["vlm"] and changed["caption"]
    assert not any(cache_invalidation(base, dict(base, qdrant_url="other")).values())


def test_secret_redaction_is_recursive():
    value = sanitize(
        {"OPENAI_API_KEY": "secret", "nested": {"authorization": "Bearer secret"}}
    )
    assert "secret" not in json.dumps(value)


@pytest.mark.parametrize("name", ["../video.mp4", "folder/video.mp4", "video.exe"])
def test_safe_filename_rejects_traversal_and_unsupported_types(name):
    with pytest.raises(ValueError):
        safe_filename(name)


def test_video_range_request(tmp_path, monkeypatch):
    from processing_indexing import debug_api

    manager = JobManager(tmp_path)
    video = tmp_path / "job" / "video.mp4"
    video.parent.mkdir()
    video.write_bytes(b"0123456789")
    job = Job("job", video.parent, video, {}, {})
    manager.jobs[job.id] = job
    monkeypatch.setattr(debug_api, "manager", manager)
    response = TestClient(debug_api.app).get(
        "/api/processing/jobs/job/video", headers={"Range": "bytes=2-5"}
    )
    assert response.status_code == 206 and response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"


def test_mock_results_are_blocked_from_real_collection(tmp_path):
    manager = JobManager(tmp_path)
    path = tmp_path / "j" / "video.mp4"
    path.parent.mkdir()
    path.write_bytes(b"x")
    job = Job(
        "j",
        path.parent,
        path,
        {"vlm_mode": "mock", "index_qdrant": True, "collection_name": "video_windows"},
        {},
    )
    manager.jobs[job.id] = job
    manager._run(job)
    assert job.status == "failed"
    assert "debug_ or mock_" in job.errors[0]["message"]
