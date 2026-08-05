import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from processing_indexing.profile_qdrant_store import (
    NamedVectorSchema,
    ProfileCollectionSchemaError,
    ProfileVectorValidationError,
    ProfileWindowRecord,
    ProfiledQdrantStore,
)


SCHEMA = (
    NamedVectorSchema("visual", 4),
    NamedVectorSchema("audio", 4),
    NamedVectorSchema("transcript", 4),
    NamedVectorSchema("caption", 4),
)


def _record(**overrides):
    payload = {
        "video_id": "video-a",
        "window_id": "video-a_window_0000",
        "start": 0.0,
        "end": 20.0,
        "embedding_profile": "api-gemini-free-v1",
    }
    payload.update(overrides.pop("payload", {}))
    vectors = {
        "visual": [0.1] * 4,
        "audio": [0.2] * 4,
        "transcript": [0.3] * 4,
        "caption": [0.4] * 4,
    }
    vectors.update(overrides.pop("vectors", {}))
    return ProfileWindowRecord(payload=payload, vectors=vectors)


def test_creates_profile_collection_and_preserves_all_named_vectors():
    client = QdrantClient(":memory:")
    store = ProfiledQdrantStore(
        client,
        collection_name="video_windows_api_gemini_free_v1",
        vector_schema=SCHEMA,
    )

    store.ensure_collection()
    store.upsert([_record()])

    records, _ = client.scroll(
        "video_windows_api_gemini_free_v1",
        limit=10,
        with_vectors=True,
        with_payload=True,
    )
    assert len(records) == 1
    assert set(records[0].vector) == {"visual", "audio", "transcript", "caption"}
    assert records[0].payload["embedding_profile"] == "api-gemini-free-v1"
    assert store.existing_window_ids("video-a") == {"video-a_window_0000"}


def test_allows_missing_optional_audio_vector_without_zero_padding():
    client = QdrantClient(":memory:")
    store = ProfiledQdrantStore(
        client,
        collection_name="api_silent_video",
        vector_schema=SCHEMA,
    )
    store.ensure_collection()
    record = _record()
    without_audio = ProfileWindowRecord(
        payload=record.payload,
        vectors={name: value for name, value in record.vectors.items() if name != "audio"},
    )
    store.upsert([without_audio])

    # Empty is not a meaningful Qdrant vector, so callers must omit it rather
    # than silently storing a zero vector for a silent source.
    with pytest.raises(ProfileVectorValidationError, match="audio dimensions"):
        store.upsert([_record(vectors={"audio": []})])


def test_rejects_dimension_drift_before_remote_write():
    client = QdrantClient(":memory:")
    store = ProfiledQdrantStore(client, collection_name="api_vectors", vector_schema=SCHEMA)
    store.ensure_collection()
    with pytest.raises(ProfileVectorValidationError, match="transcript dimensions"):
        store.upsert([_record(vectors={"transcript": [1.0]})])


def test_refuses_an_existing_collection_with_a_different_profile_schema():
    client = QdrantClient(":memory:")
    client.create_collection(
        "api_vectors",
        vectors_config={
            "visual": VectorParams(size=3, distance=Distance.COSINE),
            "audio": VectorParams(size=4, distance=Distance.COSINE),
            "transcript": VectorParams(size=4, distance=Distance.COSINE),
            "caption": VectorParams(size=4, distance=Distance.COSINE),
        },
    )
    store = ProfiledQdrantStore(client, collection_name="api_vectors", vector_schema=SCHEMA)
    with pytest.raises(ProfileCollectionSchemaError, match="visual dimensions"):
        store.ensure_collection()
