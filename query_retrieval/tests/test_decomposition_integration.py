"""End-to-end checks that decomposition and verification are wired into
api.py correctly: a weight-0 modality is still searched (never skipped),
decomposition weights actually flow into fused scores through the real
/search endpoint, and /verify never adds latency to /search.
"""
import time

import pytest
from fastapi.testclient import TestClient

from query_retrieval import api, config, encoders
from query_retrieval.models import DecompositionResult


def _hit(window_id, video_id, start=0.0, end=5.0):
    return {
        "window_id": window_id, "score": 0.0,
        "payload": {"video_id": video_id, "window_id": window_id, "start": start, "end": end},
    }


@pytest.fixture
def decomposition_client(monkeypatch):
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(api, "_encoders_ready", True)
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", True)
    with TestClient(api.app) as c:
        yield c


def test_weight_zero_modality_is_still_searched_not_skipped(monkeypatch, decomposition_client):
    """A modality decomposition weights at 0.0 must still be encoded and
    searched - the weight only applies in fusion scoring, never as a
    search-skip gate (Part A.3)."""
    decomposition_result = DecompositionResult(
        visual_query="a red car", audio_query="a red car", speech_query="a red car", caption_query="a red car",
        required_conditions=[], weights={"visual": 1.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}, tier="live",
    )
    monkeypatch.setattr(api, "decompose_query", lambda q: decomposition_result)

    dim = 4
    monkeypatch.setattr(encoders, "encode_decomposed", lambda d: {m: [0.0] * dim for m in config.VECTOR_NAMES})

    calls = {"visual": 0, "audio": 0, "speech": 0, "caption": 0}

    def _make_recording_fn(modality):
        def _fn(vector, top_k):
            calls[modality] += 1
            return []
        return _fn

    monkeypatch.setattr(api, "_SEARCH_FNS", {m: _make_recording_fn(m) for m in config.VECTOR_NAMES})

    resp = decomposition_client.post("/search", json={"query": "a red car", "top_k": 10})

    assert resp.status_code == 200
    # Every modality was actually called, including the three weighted at 0.0.
    assert calls == {"visual": 1, "audio": 1, "speech": 1, "caption": 1}


def test_decomposition_weights_flow_into_fused_scores(monkeypatch, decomposition_client):
    decomposition_result = DecompositionResult(
        visual_query="q", audio_query="q", speech_query="q", caption_query="q",
        required_conditions=[], weights={"visual": 0.7, "audio": 0.3, "speech": 0.0, "caption": 0.0}, tier="live",
    )
    monkeypatch.setattr(api, "decompose_query", lambda q: decomposition_result)
    dim = 4
    monkeypatch.setattr(encoders, "encode_decomposed", lambda d: {m: [0.0] * dim for m in config.VECTOR_NAMES})

    hits_by_modality = {
        "visual": [_hit("w1", "video_w1")],
        "audio": [_hit("w1", "video_w1")],
        "speech": [],
        "caption": [],
    }
    monkeypatch.setattr(api, "_SEARCH_FNS", {
        m: (lambda v, top_k, m=m: hits_by_modality[m]) for m in config.VECTOR_NAMES
    })

    resp = decomposition_client.post("/search", json={"query": "q", "top_k": 10})
    assert resp.status_code == 200
    result = resp.json()["results"][0]

    k = config.RRF_K
    expected = 0.7 * (1.0 / (k + 1)) + 0.3 * (1.0 / (k + 1))
    assert abs(result["score"] - expected) < 1e-12

    evidence_by_modality = {e["modality"]: e for e in result["modality_evidence"]}
    assert abs(evidence_by_modality["visual"]["contribution"] - 0.7 * (1.0 / (k + 1))) < 1e-12
    assert abs(evidence_by_modality["audio"]["contribution"] - 0.3 * (1.0 / (k + 1))) < 1e-12


# --- /verify does not block /search timing ---


def test_verify_does_not_block_search_and_search_timing_is_unaffected(monkeypatch):
    """Simulates a slow verification call and proves /search's response
    time is unaffected - verification is a separate, later call, never
    inline with retrieval."""
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(api, "_encoders_ready", True)
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", False)
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", True)
    dim = 4
    monkeypatch.setattr(encoders, "encode_query", lambda q: {m: [0.0] * dim for m in config.VECTOR_NAMES})
    monkeypatch.setattr(api, "_SEARCH_FNS", {
        m: (lambda v, top_k: [_hit("w1", "video_w1")] if v is not None else [])
        for m in config.VECTOR_NAMES
    })

    def _slow_verify_candidate(candidate, query, required_conditions):
        time.sleep(1.5)
        from query_retrieval.models import VerificationResult
        return VerificationResult(candidate_id=candidate.window_id, state="verified", match=True, confidence=0.9)

    monkeypatch.setattr(api, "verify_candidate", _slow_verify_candidate)

    with TestClient(api.app) as client:
        t0 = time.time()
        search_resp = client.post("/search", json={"query": "anything", "top_k": 10})
        search_elapsed = time.time() - t0
        assert search_resp.status_code == 200
        # /search itself must be fast - the slow verify_candidate is never called during /search.
        assert search_elapsed < 1.0

        window_id = search_resp.json()["results"][0]["window_id"]

        t1 = time.time()
        verify_resp = client.post("/verify", json={
            "candidate_ids": [window_id], "query": "anything", "required_conditions": [],
        })
        verify_elapsed = time.time() - t1

    assert verify_resp.status_code == 200
    assert verify_resp.json()["results"][0]["state"] == "verified"
    # The slow path only shows up in /verify's own timing, confirming it
    # really is a separate call - not proof by itself that /search is
    # unaffected (that's search_elapsed above), but ties the two together.
    assert verify_elapsed >= 1.5
