import pytest

from query_retrieval import config, qdrant_client
from query_retrieval.qdrant_client import QdrantSearchError


def test_connect_qdrant_uses_bounded_timeout(monkeypatch):
    captured = {}

    class FakeQdrantClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(qdrant_client, "_client", None)
    monkeypatch.setattr(qdrant_client, "QdrantClient", FakeQdrantClient)
    monkeypatch.setattr(config, "QDRANT_TIMEOUT_SECONDS", 7.5)

    qdrant_client.connect_qdrant()

    assert captured["timeout"] == 7.5


def test_qdrant_search_error_does_not_reflect_a_transport_secret(monkeypatch):
    secret = "qdrant-transport-secret"

    class FailingClient:
        def query_points(self, **_kwargs):
            raise RuntimeError(f"Authorization: Bearer {secret}")

    monkeypatch.setattr(qdrant_client, "_client", FailingClient())
    with pytest.raises(QdrantSearchError) as raised:
        qdrant_client.search_visual([0.0] * config.VECTOR_CONFIG["visual"]["dim"])

    assert secret not in str(raised.value)
