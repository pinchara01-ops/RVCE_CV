"""Unit tests for qdrant_client.py against seeded dummy data.

Requires a running Qdrant instance (see QDRANT_HOST/QDRANT_PORT env vars).
"""
import random

import pytest

from query_retrieval import config
from query_retrieval.qdrant_client import (
    connect_qdrant,
    create_collection,
    search_audio,
    search_caption,
    search_speech,
    search_visual,
)
from query_retrieval.seed_dummy_data import seed

pytestmark = pytest.mark.qdrant


@pytest.fixture(scope="module", autouse=True)
def seeded_collection():
    client = connect_qdrant()
    if client.collection_exists(config.COLLECTION_NAME):
        client.delete_collection(config.COLLECTION_NAME)
    seed()
    yield
    client.delete_collection(config.COLLECTION_NAME)


def _rand_vec(dim: int) -> list[float]:
    return [random.uniform(-1, 1) for _ in range(dim)]


def test_search_visual_shape():
    hits = search_visual(_rand_vec(config.VECTOR_CONFIG["visual"]["dim"]), top_k=5)
    assert isinstance(hits, list)
    assert len(hits) > 0
    for hit in hits:
        assert set(hit.keys()) == {"window_id", "score", "payload"}
        assert isinstance(hit["window_id"], str)
        assert isinstance(hit["score"], float)
        assert "video_id" in hit["payload"]


def test_search_audio_shape():
    hits = search_audio(_rand_vec(config.VECTOR_CONFIG["audio"]["dim"]), top_k=5)
    assert isinstance(hits, list)
    assert len(hits) > 0


def test_search_speech_shape():
    hits = search_speech(_rand_vec(config.VECTOR_CONFIG["speech"]["dim"]), top_k=5)
    assert isinstance(hits, list)
    assert len(hits) > 0


def test_search_caption_shape():
    hits = search_caption(_rand_vec(config.VECTOR_CONFIG["caption"]["dim"]), top_k=5)
    assert isinstance(hits, list)
    assert len(hits) > 0


def test_top_k_respected():
    hits = search_visual(_rand_vec(config.VECTOR_CONFIG["visual"]["dim"]), top_k=2)
    assert len(hits) <= 2


def test_empty_collection_returns_empty_list():
    client = connect_qdrant()
    client.delete_collection(config.COLLECTION_NAME)
    create_collection(client)
    hits = search_visual(_rand_vec(config.VECTOR_CONFIG["visual"]["dim"]), top_k=5)
    assert hits == []
    # restore for any subsequent tests in module
    seed()


def test_search_nonexistent_collection_does_not_crash():
    client = connect_qdrant()
    client.delete_collection(config.COLLECTION_NAME)
    hits = search_visual(_rand_vec(config.VECTOR_CONFIG["visual"]["dim"]), top_k=5)
    assert hits == []
    create_collection(client)
    seed()
