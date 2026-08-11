from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processing_indexing.public_demo import (
    BurstLimitReached,
    LimitReached,
    PublicDemoLimiter,
    PublicSampleCatalog,
    SampleNotFound,
)


def test_public_sample_catalog_exposes_opaque_metadata_and_rejects_unknown_paths(tmp_path: Path):
    video = tmp_path / "private" / "animal.webm"
    video.parent.mkdir()
    video.write_bytes(b"sample")
    catalog = PublicSampleCatalog.from_paths({"animal-belly-rub": video})

    assert catalog.public()[0]["id"] == "animal-belly-rub"
    assert str(tmp_path) not in str(catalog.public())
    assert catalog.resolve("animal-belly-rub") == video.resolve()
    with pytest.raises(SampleNotFound):
        catalog.resolve("../../private/atm.mp4")


def test_public_mode_accepts_a_bounded_personal_upload_when_enabled(monkeypatch):
    from processing_indexing import quick_demo
    from processing_indexing.debug_api import app

    monkeypatch.setenv("PUBLIC_LAUNCH_MODE", "true")
    monkeypatch.setenv("PUBLIC_UPLOADS_ENABLED", "true")
    monkeypatch.setattr(quick_demo, "_resolve_api_key", lambda *_args: "server-key")
    monkeypatch.setattr(quick_demo, "reserve_paid_operation", lambda *_args: {"duplicate": True})
    response = TestClient(app).post(
        "/api/quick/search",
        data={"query": "find the animal"},
        files={"video": ("animal.webm", b"\x1aE\xdf\xa3" + b"0" * 32, "video/webm")},
        headers={"Idempotency-Key": "upload-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"duplicate": True}


def test_sample_search_uses_allowlist_even_outside_public_mode(monkeypatch, tmp_path: Path):
    from processing_indexing import quick_demo
    from processing_indexing.debug_api import app

    sample = tmp_path / "animal.webm"
    sample.write_bytes(b"\x1aE\xdf\xa3" + b"0" * 32)
    monkeypatch.delenv("PUBLIC_LAUNCH_MODE", raising=False)
    monkeypatch.setenv("PUBLIC_SAMPLE_ANIMAL_PATH", str(sample))
    monkeypatch.setattr(quick_demo, "_resolve_api_key", lambda *_args: "server-key")
    monkeypatch.setattr(quick_demo, "reserve_paid_operation", lambda *_args: {"duplicate": True})

    response = TestClient(app).post(
        "/api/quick/search",
        data={"sample_id": "animal-belly-rub", "query": "find the animal"},
        headers={"Idempotency-Key": "sample-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"duplicate": True}


def test_limiter_interprets_atomic_allow_limit_and_duplicate_results(monkeypatch):
    limiter = PublicDemoLimiter("https://redis.invalid", "secret")
    monkeypatch.setattr(limiter, "_command", lambda *args: [1, 1, 1234.0])
    allowed = limiter.reserve("visitor", "ip", "request-1")
    assert allowed.status == "allowed"
    assert allowed.usage.remaining == 1

    monkeypatch.setattr(limiter, "_command", lambda *args: [-1, 0, 1234.0])
    with pytest.raises(LimitReached):
        limiter.reserve("visitor", "ip", "request-2")

    monkeypatch.setattr(limiter, "_command", lambda *args: [-2, 1, 1234.0])
    with pytest.raises(BurstLimitReached):
        limiter.reserve("visitor", "ip", "request-3")


def test_public_mode_rejects_unknown_samples_before_limiter_or_provider(monkeypatch):
    from processing_indexing.debug_api import app

    monkeypatch.setenv("PUBLIC_LAUNCH_MODE", "true")
    response = TestClient(app).post(
        "/api/quick/search",
        data={"sample_id": "../../private/video.mp4", "query": "find a person"},
        headers={"Idempotency-Key": "request-1"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "SAMPLE_NOT_FOUND", "message": "That sample is not available."}
    }


def test_public_mode_blocks_anonymous_developer_and_legacy_paid_routes(monkeypatch):
    from processing_indexing.debug_api import app

    monkeypatch.setenv("PUBLIC_LAUNCH_MODE", "true")
    client = TestClient(app)
    for path in ("/api/runtime/profiles", "/api/query/health"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "TEMPORARILY_UNAVAILABLE"
