"""Integration checks: real Qdrant, real encoders wiring (mocked at the
model-loader boundary to stay fast/network-free), exercised through the
actual /search endpoint - not just individual unit functions.

No query router (architecture change): all 4 modalities are always
encoded and searched.
"""
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient as RealQdrantClient

from query_retrieval import api, config, encoders
from query_retrieval.qdrant_client import (
    connect_qdrant,
    search_visual,
    validate_collection_schema,
)
from query_retrieval.seed_dummy_data import (
    ANCHOR_VECTORS,
    HARD_NEGATIVE_WINDOW_ID,
    NEAR_MATCH_WINDOW_IDS,
    seed,
)

import query_retrieval.qdrant_client as qdrant_client_module


@pytest.fixture(scope="module", autouse=True)
def seeded_collection():
    client = connect_qdrant()
    if client.collection_exists(config.COLLECTION_NAME):
        client.delete_collection(config.COLLECTION_NAME)
    seed()
    yield
    client.delete_collection(config.COLLECTION_NAME)


@pytest.fixture
def api_client(monkeypatch):
    """TestClient with encoder warmup stubbed out - loading real X-CLIP/CLAP/
    BGE-M3 in every test run would be multi-minute and network-dependent."""
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(api, "_encoders_ready", True)
    with TestClient(api.app) as c:
        yield c


def _fake_encode_query(vector_dim_map):
    """Build a fake encoders.encode_query that returns a zero vector for
    all 4 modalities, without touching real models."""

    def _fake(query: str) -> dict[str, list[float]]:
        return {m: [0.0] * dim for m, dim in vector_dim_map.items()}

    return _fake


# --- 1. near-identical pair ranks at the top for a query aimed at it ---


def test_near_identical_pair_ranks_top_and_hard_negative_ranks_last():
    # top_k must cover the whole collection, not just "a generous-looking
    # number" - a top_k smaller than the total point count can silently
    # exclude the true hard negative from the returned (and thus "last")
    # ranking as the seed data grows (bug found live when seed_dummy_data
    # grew from 14 to 33 points: top_k=20 cut off the hard negative).
    hits = search_visual(ANCHOR_VECTORS["visual"], top_k=1000)
    assert len(hits) > 0

    ranked_ids = [h["window_id"] for h in hits]
    top_two = set(ranked_ids[:2])
    assert top_two == set(NEAR_MATCH_WINDOW_IDS), (
        f"expected {NEAR_MATCH_WINDOW_IDS} at top, got ranking {ranked_ids}"
    )
    assert ranked_ids[-1] == HARD_NEGATIVE_WINDOW_ID, (
        f"expected hard negative {HARD_NEGATIVE_WINDOW_ID} ranked last, got {ranked_ids}"
    )


# --- 2. failure path tests ---


def test_qdrant_unreachable_returns_clean_response_not_500(api_client, monkeypatch):
    broken_client = RealQdrantClient(host="localhost", port=1, timeout=2)
    monkeypatch.setattr(qdrant_client_module, "_client", broken_client)
    dims = {m: config.VECTOR_CONFIG[m]["dim"] for m in config.VECTOR_NAMES}
    monkeypatch.setattr(api, "encoders", type("E", (), {"encode_query": staticmethod(_fake_encode_query(dims))})())

    resp = api_client.post("/search", json={"query": "person in a red jacket", "top_k": 5})

    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_empty_query_string_does_not_crash(api_client, monkeypatch):
    dims = {m: config.VECTOR_CONFIG[m]["dim"] for m in config.VECTOR_NAMES}
    monkeypatch.setattr(api, "encoders", type("E", (), {"encode_query": staticmethod(_fake_encode_query(dims))})())

    resp = api_client.post("/search", json={"query": "", "top_k": 5})

    assert resp.status_code == 200
    assert isinstance(resp.json()["results"], list)


def test_top_k_zero_returns_empty_results_not_an_error(api_client, monkeypatch):
    dims = {m: config.VECTOR_CONFIG[m]["dim"] for m in config.VECTOR_NAMES}
    monkeypatch.setattr(api, "encoders", type("E", (), {"encode_query": staticmethod(_fake_encode_query(dims))})())

    resp = api_client.post("/search", json={"query": "a dog barking", "top_k": 0})

    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_top_k_very_large_does_not_crash(api_client, monkeypatch):
    dims = {m: config.VECTOR_CONFIG[m]["dim"] for m in config.VECTOR_NAMES}
    monkeypatch.setattr(api, "encoders", type("E", (), {"encode_query": staticmethod(_fake_encode_query(dims))})())

    resp = api_client.post("/search", json={"query": "a dog barking", "top_k": 10000})

    assert resp.status_code == 200
    body = resp.json()
    # only a handful of dummy points exist; must return what's available, not 10000, not error
    assert 0 <= len(body["results"]) < 100


def test_zero_matches_returns_empty_results_cleanly(api_client, monkeypatch):
    monkeypatch.setattr(api, "_SEARCH_FNS", {
        "visual": lambda vector, top_k: [],
        "audio": lambda vector, top_k: [],
        "speech": lambda vector, top_k: [],
        "caption": lambda vector, top_k: [],
    })
    dims = {m: config.VECTOR_CONFIG[m]["dim"] for m in config.VECTOR_NAMES}
    monkeypatch.setattr(api, "encoders", type("E", (), {"encode_query": staticmethod(_fake_encode_query(dims))})())

    resp = api_client.post("/search", json={"query": "something nobody indexed", "top_k": 5})

    assert resp.status_code == 200
    assert resp.json()["results"] == []


# --- 3. /health readiness gating ---


def test_health_reports_not_ready_before_warmup(monkeypatch):
    monkeypatch.setattr(encoders, "warmup", lambda: None)  # keep startup fast, no real model load
    with TestClient(api.app) as c:
        # startup already flipped _encoders_ready True via the stubbed warmup;
        # force it back down to simulate "warmup still running mid-startup"
        monkeypatch.setattr(api, "_encoders_ready", False)
        resp = c.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "loading"


def test_health_reports_ready_after_warmup(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- 4. schema drift check ---


def test_validate_collection_schema_passes_on_dev_collection():
    issues = validate_collection_schema()
    assert issues == [], f"schema drift detected against contract: {issues}"


def test_validate_collection_schema_reports_missing_collection(monkeypatch):
    monkeypatch.setattr(config, "COLLECTION_NAME", "this_collection_does_not_exist")
    issues = validate_collection_schema()
    assert len(issues) == 1
    assert "does not exist" in issues[0]
