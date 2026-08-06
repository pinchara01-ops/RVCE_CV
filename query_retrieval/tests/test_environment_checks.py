from __future__ import annotations

from typing import Self
from urllib.error import URLError

from query_retrieval import environment_checks


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_qdrant_readiness_uses_root_ready_endpoint_and_redacts_credentials(monkeypatch):
    seen: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response(200)

    monkeypatch.setattr(environment_checks, "urlopen", fake_urlopen)
    result = environment_checks.qdrant_readiness(
        "http://operator:never-display-this@qdrant.example.test:6333/private?api_key=also-secret"
    )

    assert result.available is True
    assert result.label == "http://qdrant.example.test:6333"
    assert seen == {"url": "http://qdrant.example.test:6333/readyz", "timeout": 1.0}
    assert "secret" not in result.label
    assert "secret" not in result.reason


def test_qdrant_readiness_reports_a_network_failure_without_reflecting_error_text(monkeypatch):
    def fake_urlopen(_request, timeout):
        assert timeout == 0.25
        raise URLError("Bearer qdrant-test-secret")

    monkeypatch.setattr(environment_checks, "urlopen", fake_urlopen)
    result = environment_checks.qdrant_readiness("http://127.0.0.1:6333", timeout_seconds=0.25)

    assert result.available is False
    assert result.label == "http://127.0.0.1:6333"
    assert result.reason == "readiness request failed (URLError)"
    assert "secret" not in result.reason


def test_qdrant_readiness_rejects_a_malformed_url_without_network_access(monkeypatch):
    def unexpected_urlopen(*_args, **_kwargs):
        raise AssertionError("a malformed URL must not trigger a network call")

    monkeypatch.setattr(environment_checks, "urlopen", unexpected_urlopen)
    result = environment_checks.qdrant_readiness("qdrant://not-an-http-endpoint")

    assert result.available is False
    assert result.label == "configured Qdrant endpoint"
    assert result.reason == "the configured Qdrant URL is invalid"
