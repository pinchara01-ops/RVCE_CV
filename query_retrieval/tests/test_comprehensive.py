"""Comprehensive realistic-scenario coverage: query variety, video/window
variety, and system-level behavior (cold start, concurrency, malformed
requests, empty collection).

Real Qdrant, real router (rule-based only, V1 architecture). Encoders are
mocked (zero vectors) to stay fast/network-free - these tests are about
routing, retrieval plumbing, and merge correctness at realistic data
scale, not embedding quality.
"""
import threading

import pytest
from fastapi.testclient import TestClient

from query_retrieval import api, config, encoders
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import FusedHit, WindowPayload
from query_retrieval.qdrant_client import connect_qdrant, create_collection, search_audio
from query_retrieval.seed_dummy_data import (
    DUP_VIDEO_IDS,
    EDGE_CASE_VIDEO_ID,
    FULL_MODALITY_VIDEO_ID,
    LONG_VIDEO_ID,
    SHORT_VIDEO_ID,
    seed,
)


@pytest.fixture(scope="module", autouse=True)
def seeded_collection():
    client = connect_qdrant()
    if client.collection_exists(config.COLLECTION_NAME):
        client.delete_collection(config.COLLECTION_NAME)
    seed()
    yield
    client.delete_collection(config.COLLECTION_NAME)


def _fake_encode_query(query, weights):
    dims = {m: config.VECTOR_CONFIG[m]["dim"] for m in config.VECTOR_NAMES}
    return {m: [0.0] * dims[m] for m, w in weights.items() if w > 0}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(api, "_encoders_ready", True)
    monkeypatch.setattr(encoders, "encode_query", _fake_encode_query)
    with TestClient(api.app) as c:
        yield c


def _search(client, query, top_k=10):
    resp = client.post("/search", json={"query": query, "top_k": top_k})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _fetch_video_hits(video_id: str) -> list[FusedHit]:
    """Fetch all real seeded points for a video_id and wrap them as
    FusedHits, so merge_windows() can be exercised against real seed data
    (not hand-typed synthetic data) without needing the full router/encoder
    pipeline."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    qclient = connect_qdrant()
    points, _ = qclient.scroll(
        collection_name=config.COLLECTION_NAME,
        scroll_filter=Filter(must=[FieldCondition(key="video_id", match=MatchValue(value=video_id))]),
        limit=100,
        with_payload=True,
    )
    return [
        FusedHit(
            window_id=p.payload["window_id"],
            fused_score=1.0,
            matched_modalities=["visual"],
            payload=WindowPayload(**p.payload),
        )
        for p in points
    ]


# ============================================================
# 1. QUERY VARIETY - via real /search calls
# ============================================================


@pytest.mark.parametrize("query", ["red car", "person wearing glasses"])
def test_pure_visual_query(client, query):
    body = _search(client, query)
    weights = body["query_weights"]
    assert weights["visual"] == max(weights.values())
    assert isinstance(body["results"], list)


@pytest.mark.parametrize("query", ["dog barking", "glass breaking"])
def test_pure_audio_query(client, query):
    body = _search(client, query)
    weights = body["query_weights"]
    assert weights["audio"] == max(weights.values())


@pytest.mark.parametrize("query", ["someone says hello", "person mentions their name"])
def test_pure_speech_query(client, query):
    body = _search(client, query)
    weights = body["query_weights"]
    assert weights["speech"] == max(weights.values())


@pytest.mark.parametrize("query", ["a celebration", "an outdoor scene"])
def test_pure_caption_semantic_query(client, query):
    body = _search(client, query)
    weights = body["query_weights"]
    assert weights["caption"] == 1.0  # no keyword hits -> default catch-all


def test_mixed_ambiguous_query(client):
    body = _search(client, "man shouting while driving")
    weights = body["query_weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert weights["speech"] > 0  # "shouting" is a speech keyword


def test_nonsense_gibberish_query_degrades_to_caption(client):
    body = _search(client, "asdkjfh qwoeiru zxcvbn qqqqq")
    assert body["query_weights"]["caption"] == 1.0


def test_very_long_paragraph_query_does_not_crash(client):
    paragraph = (
        "In this scene we observe a series of events unfolding across the frame, "
        "with multiple people entering and exiting the space over time. "
    ) * 20  # ~280 words
    body = _search(client, paragraph)
    assert isinstance(body["results"], list)
    assert abs(sum(body["query_weights"].values()) - 1.0) < 1e-9


def test_single_word_query(client):
    body = _search(client, "dog")
    assert abs(sum(body["query_weights"].values()) - 1.0) < 1e-9


@pytest.mark.parametrize("query", [
    "🐶🔥💥 loud bang!!",
    "日本語のクエリです",
    "café münü naïve",
    "!@#$%^&*()_+-=[]{}",
])
def test_special_characters_emoji_non_english_do_not_crash(client, query):
    body = _search(client, query)
    assert isinstance(body["results"], list)
    assert abs(sum(body["query_weights"].values()) - 1.0) < 1e-9


def test_empty_string_query_reconfirmed(client):
    body = _search(client, "")
    assert body["query_weights"] == {"visual": 0.0, "audio": 0.0, "speech": 0.0, "caption": 1.0}


# ============================================================
# 2. VIDEO/WINDOW VARIETY - against real seeded data
# ============================================================


def test_short_video_two_windows_merge_into_one_region():
    hits = _fetch_video_hits(SHORT_VIDEO_ID)
    assert len(hits) == 2
    regions = merge_windows(hits)
    assert len(regions) == 1
    assert regions[0].start == 0.0
    assert regions[0].end == 6.0


def test_long_video_mixed_clusters_merge_correctly():
    hits = _fetch_video_hits(LONG_VIDEO_ID)
    assert len(hits) == 10
    regions = merge_windows(hits)
    # cluster1 (0,2,4,6 -> [0,8]), cluster2 (50,52,54 -> [50,56]),
    # isolated (120 -> [120,122]), cluster3 (200,203 -> [200,205])
    assert len(regions) == 4
    spans = sorted((r.start, r.end) for r in regions)
    assert spans == [(0.0, 8.0), (50.0, 56.0), (120.0, 122.0), (200.0, 205.0)]


def test_silent_video_windows_absent_from_audio_search():
    hits = search_audio([0.0] * config.VECTOR_CONFIG["audio"]["dim"], top_k=100)
    video_ids = {h["payload"].get("video_id") for h in hits}
    assert "video_a" not in video_ids  # video_a has no audio vector at all


def test_full_modality_video_indexed_on_all_four_vectors():
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    qclient = connect_qdrant()
    points, _ = qclient.scroll(
        collection_name=config.COLLECTION_NAME,
        scroll_filter=Filter(must=[FieldCondition(key="video_id", match=MatchValue(value=FULL_MODALITY_VIDEO_ID))]),
        limit=100,
        with_payload=True,
        with_vectors=True,
    )
    assert len(points) == 3
    for p in points:
        assert set(p.vector.keys()) == set(config.VECTOR_NAMES)


def test_near_identical_content_different_videos_never_merges():
    hits_a = _fetch_video_hits(DUP_VIDEO_IDS[0])
    hits_b = _fetch_video_hits(DUP_VIDEO_IDS[1])
    regions = merge_windows(hits_a + hits_b)
    assert len(regions) == 2  # same timestamps, different video_id -> stays separate
    assert {r.video_id for r in regions} == set(DUP_VIDEO_IDS)


def test_edge_case_zero_duration_window_does_not_crash_merge():
    hits = _fetch_video_hits(EDGE_CASE_VIDEO_ID)
    regions = merge_windows(hits)
    zero_dur = next(r for r in regions if r.start == 50.0)
    assert zero_dur.start == zero_dur.end == 50.0


def test_edge_case_large_timestamps_pass_through_unchanged():
    hits = _fetch_video_hits(EDGE_CASE_VIDEO_ID)
    regions = merge_windows(hits)
    large = next(r for r in regions if r.start == 99999.0)
    assert large.end == 100005.0


# ============================================================
# 3. SYSTEM-LEVEL
# ============================================================


def test_first_query_immediately_after_startup_works(monkeypatch):
    """Simulates the moment right after warmup completes - the first real
    request must work correctly, not just after some warm-up period."""
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(encoders, "encode_query", _fake_encode_query)
    with TestClient(api.app) as c:
        resp = c.post("/search", json={"query": "a dog barking", "top_k": 5})
    assert resp.status_code == 200
    assert isinstance(resp.json()["results"], list)


def test_rapid_sequential_queries_no_crash(client):
    queries = [
        "red car", "dog barking", "someone says hello", "a celebration",
        "man shouting", "loud crash", "an outdoor scene", "person wearing glasses",
        "glass breaking", "a party", "quiet room", "bright light",
    ]
    for q in queries:
        body = _search(client, q)
        assert isinstance(body["results"], list)
        assert abs(sum(body["query_weights"].values()) - 1.0) < 1e-9


def test_concurrent_requests_no_crash_no_cross_contamination(client):
    queries = ["red car", "dog barking", "someone says hello", "a celebration", "man shouting"]
    results: dict[int, dict] = {}
    errors: list[Exception] = []

    def _worker(idx: int, query: str) -> None:
        try:
            results[idx] = _search(client, query, top_k=5)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i, q)) for i, q in enumerate(queries)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent requests raised: {errors}"
    assert len(results) == len(queries)
    # each response's weights should reflect its own query, not a neighbor's -
    # visual-dominant vs audio-dominant vs speech-dominant vs caption-default
    assert results[0]["query_weights"]["visual"] == max(results[0]["query_weights"].values())
    assert results[1]["query_weights"]["audio"] == max(results[1]["query_weights"].values())
    assert results[2]["query_weights"]["speech"] == max(results[2]["query_weights"].values())
    assert results[3]["query_weights"]["caption"] == 1.0


def test_malformed_request_missing_query_field(client):
    resp = client.post("/search", json={"top_k": 5})
    assert resp.status_code == 422


def test_malformed_request_wrong_types(client):
    resp = client.post("/search", json={"query": 12345, "top_k": "not-a-number"})
    assert resp.status_code == 422


def test_malformed_request_empty_body(client):
    resp = client.post("/search", json={})
    assert resp.status_code == 422


def test_empty_collection_reconfirmed_after_all_recent_changes(client):
    qclient = connect_qdrant()
    qclient.delete_collection(config.COLLECTION_NAME)
    create_collection(qclient)
    body = _search(client, "a dog barking")
    assert body["results"] == []
    # restore for any subsequent tests in this module
    seed()
