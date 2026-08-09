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
    video = tmp_path / "private" / "atm.mp4"
    video.parent.mkdir()
    video.write_bytes(b"sample")
    catalog = PublicSampleCatalog.from_paths({"atm-surveillance": video})

    assert catalog.public()[0]["id"] == "atm-surveillance"
    assert str(tmp_path) not in str(catalog.public())
    assert catalog.resolve("atm-surveillance") == video.resolve()
    with pytest.raises(SampleNotFound):
        catalog.resolve("../../private/atm.mp4")


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
