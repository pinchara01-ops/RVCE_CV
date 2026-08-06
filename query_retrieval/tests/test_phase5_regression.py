"""Phase 5 regression checks: verify moving top_k truncation from
pre-fusion to post-merge (api.py change) didn't just avoid crashing but
(a) actually changes real output where it should, and (b) holds up at
moderate scale with sane timing.
"""
import logging
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from qdrant_client.models import PointStruct

from query_retrieval import api, config, encoders
from query_retrieval.merge_windows import merge_windows
from query_retrieval.models import FusedHit, WindowPayload
from query_retrieval.qdrant_client import connect_qdrant, create_collection

logger = logging.getLogger(__name__)


def _hit(window_id, video_id, start, end, score, modalities):
    return FusedHit(
        window_id=window_id,
        fused_score=score,
        matched_modalities=modalities,
        payload=WindowPayload(video_id=video_id, window_id=window_id, start=start, end=end),
    )


# --- prove post-merge truncation actually changes output, not just "doesn't crash" ---


def test_post_merge_truncation_differs_from_pre_merge_truncation():
    """x1 outranks video_y's whole chain individually, but y1/y2/y3 chain
    into one region spanning their full timespan. With top_k=2:

    OLD (buggy) order - truncate fused list to top_k BEFORE merging:
        top 2 by score = [x1(1.0), y1(0.9)] -> y2, y3 never seen by merge
        -> video_y region ends up as just y1: source=["y1"], end=5.0

    NEW (current) order - merge everything, THEN truncate to top_k:
        merge sees all of x1,y1,y2,y3 -> video_y becomes one region
        spanning y1+y2+y3 (score still 0.9, the max) -> still ranks 2nd
        -> source=["y1","y2","y3"], end=20.0

    Same region *count* either way (2), but the actual payload differs -
    the old order would have silently produced an incomplete region,
    losing 2 of 3 constituent windows and 15s of timespan.
    """
    x1 = _hit("x1", "video_x", 0.0, 5.0, 1.0, ["visual"])
    y1 = _hit("y1", "video_y", 0.0, 5.0, 0.9, ["visual"])
    y2 = _hit("y2", "video_y", 8.0, 12.0, 0.5, ["visual"])   # gap from y1.end: 3 <= MERGE_GAP_SECONDS
    y3 = _hit("y3", "video_y", 16.0, 20.0, 0.1, ["visual"])  # gap from cluster end (12): 4 <= MERGE_GAP_SECONDS
    all_hits = [x1, y1, y2, y3]

    pre_truncated = sorted(all_hits, key=lambda h: h.fused_score, reverse=True)[:2]
    old_regions = merge_windows(pre_truncated)

    new_regions = merge_windows(all_hits)[:2]

    old_video_y = next(r for r in old_regions if r.video_id == "video_y")
    new_video_y = next(r for r in new_regions if r.video_id == "video_y")

    assert old_video_y.source_window_ids == ["y1"]
    assert old_video_y.end == 5.0

    assert new_video_y.source_window_ids == ["y1", "y2", "y3"]
    assert new_video_y.end == 20.0

    assert old_video_y.end != new_video_y.end
    assert old_video_y.source_window_ids != new_video_y.source_window_ids


# --- scale sanity check ---

_PERF_VIDEOS = 5
_CHAINS_PER_VIDEO = 8
_WINDOWS_PER_CHAIN = 5
_WINDOW_DURATION = 5.0
_CHAIN_GAP = 1000.0  # far beyond MERGE_GAP_SECONDS: chains never merge into each other
_TOTAL_WINDOWS = _PERF_VIDEOS * _CHAINS_PER_VIDEO * _WINDOWS_PER_CHAIN  # 200
_EXPECTED_REGIONS = _PERF_VIDEOS * _CHAINS_PER_VIDEO  # 40, if every chain fully collapses


def _build_perf_points() -> list[PointStruct]:
    dim = config.VECTOR_CONFIG["visual"]["dim"]
    points = []
    for v in range(_PERF_VIDEOS):
        video_id = f"video_perf_{v}"
        cursor = 0.0
        for chain in range(_CHAINS_PER_VIDEO):
            for w in range(_WINDOWS_PER_CHAIN):
                start = cursor
                end = start + _WINDOW_DURATION
                window_id = f"{video_id}_window_{chain * _WINDOWS_PER_CHAIN + w:04d}"
                payload = {
                    "video_id": video_id,
                    "window_id": window_id,
                    "start": start,
                    "end": end,
                    "transcript": "",
                    "caption": "",
                    "has_audio": False,
                    "vlm_processed": True,
                }
                vector = [((v * 97 + chain * 13 + w) % 1000) / 500.0 - 1.0] * dim  # cheap deterministic filler
                points.append(PointStruct(id=str(uuid.uuid4()), vector={"visual": vector}, payload=payload))
                cursor = end  # contiguous within a chain (gap = 0)
            cursor += _CHAIN_GAP  # big jump between chains
    return points


@pytest.fixture(scope="module")
def perf_collection():
    client = connect_qdrant()
    if client.collection_exists(config.COLLECTION_NAME):
        client.delete_collection(config.COLLECTION_NAME)
    create_collection(client)
    points = _build_perf_points()
    client.upsert(collection_name=config.COLLECTION_NAME, points=points)
    yield
    client.delete_collection(config.COLLECTION_NAME)


@pytest.fixture
def perf_api_client(monkeypatch):
    dim = config.VECTOR_CONFIG["visual"]["dim"]
    # Patch the shared encoders module in place (not api.encoders wholesale) -
    # api.py holds a reference to this same module object, and startup's
    # encoders.warmup() call must still resolve to something callable.
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    # Only "visual" key returned - the perf collection only has visual
    # vectors, so audio/speech/caption searches against it would just be
    # empty lists anyway; keeping this single-modality mock is enough to
    # exercise Qdrant + fusion + merge at scale (the "all 4 always
    # searched" behavior itself is covered in test_encoders.py).
    monkeypatch.setattr(encoders, "encode_query", lambda q: {"visual": [0.0] * dim})
    # Widen per-modality search depth so /search actually sees the full 200-point
    # candidate pool instead of the production default (15) - otherwise this
    # test would only ever exercise merge_windows() on ~15 hits regardless of
    # how many points exist, and wouldn't be a scale check of merge itself.
    monkeypatch.setattr(config, "DEFAULT_TOP_K", _TOTAL_WINDOWS)
    # Pinned off: this is a pre-decomposition scale/regression check, and a
    # real GROQ_API_KEY being present must not silently route it onto the
    # decomposition path (which would call encoders.encode_decomposed(),
    # not the encode_query() stub above).
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", False)
    with TestClient(api.app) as c:
        yield c


@pytest.mark.qdrant
def test_search_at_scale_completes_and_produces_sane_merge_count(perf_collection, perf_api_client):
    start = time.perf_counter()
    resp = perf_api_client.post("/search", json={"query": "anything", "top_k": _TOTAL_WINDOWS})
    duration = time.perf_counter() - start

    logger.info("Phase 5 scale check: /search over %d windows took %.3fs", _TOTAL_WINDOWS, duration)
    print(f"\n[scale check] /search over {_TOTAL_WINDOWS} windows across {_PERF_VIDEOS} videos took {duration:.3f}s")

    assert resp.status_code == 200
    results = resp.json()["results"]

    assert len(results) > 1, "merge collapsed everything into a single region - suspicious"
    assert len(results) < _TOTAL_WINDOWS, "nothing merged at all across 200 windows with 8 contiguous chains/video - suspicious"
    assert len(results) == _EXPECTED_REGIONS, (
        f"expected exactly {_EXPECTED_REGIONS} regions (each of the "
        f"{_PERF_VIDEOS * _CHAINS_PER_VIDEO} contiguous chains collapsing to one), got {len(results)}"
    )
    assert duration < 10.0, f"/search over {_TOTAL_WINDOWS} windows took {duration:.3f}s - unexpectedly slow"


@pytest.mark.qdrant
def test_top_k_zero_still_empty_at_scale_post_merge(perf_collection, perf_api_client):
    resp = perf_api_client.post("/search", json={"query": "anything", "top_k": 0})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.qdrant
def test_top_k_very_large_bounded_by_actual_merged_regions_not_raw_windows(perf_collection, perf_api_client):
    resp = perf_api_client.post("/search", json={"query": "anything", "top_k": 10000})
    assert resp.status_code == 200
    results = resp.json()["results"]
    # bounded by the number of merged regions that actually exist, not the
    # raw window count and not the requested top_k - proves truncation is
    # happening after merge, against real region counts, at scale.
    assert len(results) == _EXPECTED_REGIONS
