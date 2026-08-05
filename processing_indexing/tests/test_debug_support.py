import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from processing_indexing.config import Settings
from processing_indexing.debug_cache import cache_invalidation
from processing_indexing.debug_jobs import (
    Job,
    JobManager,
    safe_filename,
    sanitize,
    summarize_openai_usage,
)
from processing_indexing.preflight import model_statuses
from processing_indexing.probe import VideoProbeError


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
    cosmos = model_statuses(Settings(), "cosmos")[-1]
    assert cosmos.device == "hosted"
    assert cosmos.checkpoint == "nvidia/cosmos3-nano-reasoner"


def test_qdrant_timeout_must_be_positive():
    with pytest.raises(ValueError, match="QDRANT_TIMEOUT_SECONDS"):
        Settings(qdrant_timeout_seconds=0)


def test_collection_health_retries_a_transient_qdrant_timeout(monkeypatch):
    from processing_indexing import library

    attempts = 0

    class FlakyClient:
        def collection_exists(self, _collection_name):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("timed out")
            return False

    monkeypatch.setattr(library, "_health_client", lambda _settings: FlakyClient())
    monkeypatch.setattr(library.time, "sleep", lambda _seconds: None)

    health = library.collection_health(Settings())

    assert attempts == 2
    assert health["reachable"] is True
    assert health["collection_exists"] is False


def test_malformed_upload_has_an_actionable_recovery_message():
    from processing_indexing import debug_api

    malformed_body = (
        b'--diag-boundary\r\n'
        b'Content-Disposition: form-data; name="video"; filename="clip.mp4"\n\n'
        b'x\r\n--diag-boundary--\r\n'
    )
    response = TestClient(debug_api.app, raise_server_exceptions=False).post(
        "/api/processing/jobs",
        content=malformed_body,
        headers={"Content-Type": "multipart/form-data; boundary=diag-boundary"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": debug_api.MULTIPART_RECOVERY_MESSAGE}


def test_unreadable_uploaded_video_returns_400(tmp_path, monkeypatch):
    from processing_indexing import debug_api

    manager = JobManager(tmp_path)

    def unreadable(*_args, **_kwargs):
        raise VideoProbeError("Video has no video stream")

    monkeypatch.setattr(manager, "create", unreadable)
    monkeypatch.setattr(debug_api, "manager", manager)

    response = TestClient(debug_api.app).post(
        "/api/processing/jobs",
        files={"video": ("clip.mp4", b"not-a-video", "video/mp4")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Video has no video stream"


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


def test_runtime_provider_key_is_private_but_available_to_active_job(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"x")
    job = Job(
        "job",
        tmp_path,
        path,
        {"vlm_mode": "cosmos", "nvidia_api_key": "[REDACTED]"},
        {},
        private_config={"vlm_mode": "cosmos", "nvidia_api_key": "real-secret"},
    )

    assert job.runtime_config()["nvidia_api_key"] == "real-secret"
    assert "real-secret" not in json.dumps(job.public())


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


def test_inner_pipeline_failure_is_not_reported_as_complete(tmp_path, monkeypatch):
    manager = JobManager(tmp_path)
    path = tmp_path / "j" / "video.mp4"
    path.parent.mkdir()
    path.write_bytes(b"x")
    job = Job("j", path.parent, path, {"vlm_mode": "selection_only"}, {})
    manager.jobs[job.id] = job

    def fail(inner_job, *_):
        inner_job.report = {"status": "failed", "errors": {"w": "visual failed"}}
        inner_job.errors = [{"window_id": "w", "message": "visual failed"}]

    monkeypatch.setattr(manager, "_execute_pipeline", fail)
    manager._run(job)
    assert job.status == "failed" and job.stage == "failed"
    assert (
        json.loads((job.directory / "exports" / "errors.json").read_text())[0][
            "window_id"
        ]
        == "w"
    )


@pytest.mark.parametrize(
    "pipeline_status,expected_status,expected_event",
    [
        ("complete", "complete", "complete"),
        ("completed_with_errors", "completed_with_errors", "completed_with_errors"),
        ("failed", "failed", "failed"),
    ],
)
def test_job_status_and_terminal_event_agree(
    tmp_path, monkeypatch, pipeline_status, expected_status, expected_event
):
    manager = JobManager(tmp_path)
    path = tmp_path / "j" / "video.mp4"
    path.parent.mkdir()
    path.write_bytes(b"x")
    job = Job("j", path.parent, path, {"vlm_mode": "selection_only"}, {})
    manager.jobs[job.id] = job

    def finish(inner_job, *_):
        inner_job.report = {"status": pipeline_status, "errors": {}}

    monkeypatch.setattr(manager, "_execute_pipeline", finish)
    manager._run(job)

    assert job.status == job.stage == expected_status
    assert job.events[-1]["event"] == expected_event


def test_cancelled_job_status_and_event_agree(tmp_path, monkeypatch):
    manager = JobManager(tmp_path)
    path = tmp_path / "j" / "video.mp4"
    path.parent.mkdir()
    path.write_bytes(b"x")
    job = Job("j", path.parent, path, {"vlm_mode": "selection_only"}, {})
    manager.jobs[job.id] = job

    def cancel(inner_job, *_):
        inner_job.report = {"status": "complete", "errors": {}}
        inner_job.cancel_requested = True

    monkeypatch.setattr(manager, "_execute_pipeline", cancel)
    manager._run(job)

    assert job.status == job.stage == "cancelled"
    assert job.report["status"] == "cancelled"
    saved = json.loads(
        (job.directory / "exports" / "processing_report.json").read_text()
    )
    assert saved["status"] == "cancelled"
    assert job.events[-1]["event"] == "cancelled"


def test_completed_with_errors_sse_is_terminal(tmp_path, monkeypatch):
    from processing_indexing import debug_api

    manager = JobManager(tmp_path)
    path = tmp_path / "j" / "video.mp4"
    path.parent.mkdir()
    path.write_bytes(b"x")
    job = Job("j", path.parent, path, {}, {}, status="completed_with_errors")
    job.events.append({"sequence": 0, "event": "completed_with_errors", "timestamp": 1})
    manager.jobs[job.id] = job
    monkeypatch.setattr(debug_api, "manager", manager)

    response = TestClient(debug_api.app).get("/api/processing/jobs/j/events")

    assert response.status_code == 200
    assert "completed_with_errors" in response.text


def test_failed_selected_window_api_contract_uses_failed_state(tmp_path, monkeypatch):
    from processing_indexing import debug_api

    manager = JobManager(tmp_path)
    path = tmp_path / "j" / "video.mp4"
    path.parent.mkdir()
    path.write_bytes(b"x")
    job = Job("j", path.parent, path, {}, {})
    job.windows = [
        {
            "index": 1,
            "selected": True,
            "vlm_call_state": "failed",
            "errors": ["structured output failed"],
        }
    ]
    manager.jobs[job.id] = job
    monkeypatch.setattr(debug_api, "manager", manager)

    row = TestClient(debug_api.app).get("/api/processing/jobs/j/windows/1").json()

    assert row["selected"] is True
    assert row["vlm_call_state"] == "failed"


def test_export_generation_duration_is_added_to_report(tmp_path, monkeypatch):
    manager = JobManager(tmp_path)
    path = tmp_path / "j" / "video.mp4"
    path.parent.mkdir()
    path.write_bytes(b"x")
    job = Job("j", path.parent, path, {}, {})
    job.report = {"stage_durations": {"export_generation": 0.0}}
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(
        "processing_indexing.debug_jobs.time.perf_counter", lambda: next(ticks)
    )

    manager._write_artifacts(job)

    saved = json.loads(
        (job.directory / "exports" / "processing_report.json").read_text()
    )
    assert saved["stage_durations"]["export_generation"] == 2.5


def test_openai_usage_separates_success_failure_and_unknown():
    debug = {
        0: {
            "attempts": [
                {
                    "status": "failed",
                    "usage_status": "captured",
                    "usage": {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
                },
                {
                    "status": "succeeded",
                    "usage_status": "captured",
                    "usage": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9},
                },
            ]
        },
        1: {
            "attempts": [
                {
                    "status": "failed",
                    "usage_status": "unavailable",
                    "usage": None,
                }
            ]
        },
    }

    usage = summarize_openai_usage(debug)

    assert usage["successful_captured"]["calls"] == 1
    assert usage["failed_captured"]["calls"] == 1
    assert usage["calls_with_unknown_usage"] == 1
    assert usage["minimum_known_usage"] == {
        "input_tokens": 12,
        "output_tokens": 3,
        "total_tokens": 15,
    }
