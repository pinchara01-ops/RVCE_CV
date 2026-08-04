import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from processing_indexing.models import WindowPayload, WindowVectors
from processing_indexing.qdrant_store import CollectionSchemaError, QdrantStore


def item():
    payload = WindowPayload(
        video_id="v",
        window_id="v_window_0000",
        start=0.0,
        end=10.0,
        transcript="hello",
        caption="person waves",
        has_audio=True,
        vlm_processed=True,
        source_path="C:/videos/v.mp4",
    )
    vectors = WindowVectors(
        visual=[0.0] * 512,
        audio=[0.0] * 512,
        speech=[0.0] * 1024,
        caption=[0.0] * 1024,
    )
    return payload, vectors


def test_real_in_memory_collection_schema_payload_and_idempotency():
    client = QdrantClient(":memory:")
    store = QdrantStore(client)
    store.ensure_collection()
    store.upsert([item()])
    store.upsert([item()])
    records, _ = client.scroll(
        "video_windows", limit=10, with_payload=True, with_vectors=True
    )
    assert len(records) == 1
    assert set(records[0].vector) == {"visual", "audio", "speech", "caption"}
    assert {name: len(vector) for name, vector in records[0].vector.items()} == {
        "visual": 512,
        "audio": 512,
        "speech": 1024,
        "caption": 1024,
    }
    assert records[0].payload == item()[0].model_dump()
    assert set(records[0].vector) == {"visual", "audio", "speech", "caption"}


@pytest.mark.parametrize(
    "params,match",
    [
        (VectorParams(size=511, distance=Distance.COSINE), "dimension"),
        (VectorParams(size=512, distance=Distance.DOT), "distance"),
    ],
)
def test_incompatible_collection_is_rejected_not_recreated(params, match):
    client = QdrantClient(":memory:")
    client.create_collection(
        "video_windows",
        vectors_config={
            "visual": params,
            "audio": VectorParams(size=512, distance=Distance.COSINE),
            "speech": VectorParams(size=1024, distance=Distance.COSINE),
            "caption": VectorParams(size=1024, distance=Distance.COSINE),
        },
    )
    with pytest.raises(CollectionSchemaError, match=match):
        QdrantStore(client).ensure_collection()
    assert client.collection_exists("video_windows")
