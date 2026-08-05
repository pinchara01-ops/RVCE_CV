"""Regression coverage for the seed/production collection separation fix.

Root cause fixed here: seed_dummy_data.py used to upsert synthetic dev/test
points directly into config.COLLECTION_NAME (the production collection),
which showed up mixed in with real indexed video data and contaminated
real search results (11 seed_a/b/c/d points found alongside 5 real
car-crash points in the live "video_windows" collection).

Requires a running Qdrant instance (see QDRANT_HOST/QDRANT_PORT env vars),
same as the other tests in this directory that exercise real Qdrant.
"""
import uuid

import pytest
from qdrant_client.models import PointStruct

from query_retrieval import config
from query_retrieval.qdrant_client import (
    check_seed_contamination,
    connect_qdrant,
    create_collection,
)
from query_retrieval.seed_dummy_data import seed


# --- 1. seed() must never target config.COLLECTION_NAME, under any config ---


def test_seed_never_targets_production_collection_name(monkeypatch):
    """Point config.COLLECTION_NAME at a distinctive sentinel value that is
    NOT config.SEED_COLLECTION_NAME, run the real seed(), and confirm the
    sentinel collection was never touched - proves seed() reads
    config.SEED_COLLECTION_NAME directly rather than following whatever
    config.COLLECTION_NAME happens to be set to."""
    sentinel = "must_never_be_written_by_seed"
    monkeypatch.setattr(config, "COLLECTION_NAME", sentinel)

    client = connect_qdrant()
    if client.collection_exists(config.SEED_COLLECTION_NAME):
        client.delete_collection(config.SEED_COLLECTION_NAME)
    if client.collection_exists(sentinel):
        client.delete_collection(sentinel)

    try:
        seed()
        assert not client.collection_exists(sentinel), (
            "seed() created/wrote to config.COLLECTION_NAME - it must only ever "
            "target config.SEED_COLLECTION_NAME"
        )
        assert client.collection_exists(config.SEED_COLLECTION_NAME)
        count = client.count(collection_name=config.SEED_COLLECTION_NAME, exact=True).count
        assert count > 0
    finally:
        if client.collection_exists(config.SEED_COLLECTION_NAME):
            client.delete_collection(config.SEED_COLLECTION_NAME)
        if client.collection_exists(sentinel):
            client.delete_collection(sentinel)


# --- 2. check_seed_contamination() ---

_TEST_COLLECTION = f"{config.COLLECTION_NAME}_test_seed_contamination_check"


@pytest.fixture
def scratch_collection():
    client = connect_qdrant()
    if client.collection_exists(_TEST_COLLECTION):
        client.delete_collection(_TEST_COLLECTION)
    create_collection(client, collection_name=_TEST_COLLECTION)
    yield client
    client.delete_collection(_TEST_COLLECTION)


def _upsert(client, video_id, caption="", transcript=""):
    dim = config.VECTOR_CONFIG["visual"]["dim"]
    client.upsert(
        collection_name=_TEST_COLLECTION,
        points=[
            PointStruct(
                id=str(uuid.uuid4()),
                vector={"visual": [0.1] * dim},
                payload={
                    "video_id": video_id,
                    "window_id": f"{video_id}_window_0000",
                    "start": 0.0,
                    "end": 5.0,
                    "caption": caption,
                    "transcript": transcript,
                },
            )
        ],
    )


def test_detects_known_seed_video_id(scratch_collection):
    _upsert(scratch_collection, "video_a", caption="A person walks across frame 0")
    result = check_seed_contamination(scratch_collection, _TEST_COLLECTION)
    assert result["checked"] is True
    assert result["contaminated_count"] == 1
    assert result["video_ids_found"] == ["video_a"]


def test_detects_known_seed_caption_text_even_with_unknown_video_id(scratch_collection):
    _upsert(scratch_collection, "video_z_unexpected", caption="A dog is barking near a fence")
    result = check_seed_contamination(scratch_collection, _TEST_COLLECTION)
    assert result["contaminated_count"] == 1


def test_clean_collection_reports_no_contamination(scratch_collection):
    _upsert(
        scratch_collection,
        "b042e25c57c656b6acd8c916afbc6c928baa2833b68675ad34e5fb3d1425ad35",
        caption="a silver sedan collides with a guardrail on the highway",
    )
    result = check_seed_contamination(scratch_collection, _TEST_COLLECTION)
    assert result["checked"] is True
    assert result["contaminated_count"] == 0
    assert result["video_ids_found"] == []


def test_no_false_positive_on_real_data_sharing_generic_words(scratch_collection):
    """Real captions can legitimately mention a dog, a person, or a car
    without being the seed data - only exact/prefix matches to the literal
    seed strings should trigger, not shared vocabulary."""
    _upsert(
        scratch_collection,
        "d94d5157-real-video",
        caption="A dog runs past a person walking near a parked car",
        transcript="the dog and its owner walked by",
    )
    result = check_seed_contamination(scratch_collection, _TEST_COLLECTION)
    assert result["contaminated_count"] == 0


def test_missing_collection_reported_not_raised():
    result = check_seed_contamination(connect_qdrant(), "does_not_exist_collection_xyz")
    assert result["checked"] is False
    assert result["contaminated_count"] == 0
