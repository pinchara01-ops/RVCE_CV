from query_retrieval import config, qdrant_client


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
