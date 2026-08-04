"""Kill-switch verification: each LLM-touching feature must degrade to
exactly today's tested behavior when its flag is off, and GROQ_API_KEY
being entirely unset must result in zero network call attempts. These are
explicit, runnable regression tests - not just claims - see README's
"Kill switch reference" table for the human-readable summary.
"""
import json

import pytest
from fastapi.testclient import TestClient

from query_retrieval import api, config, decomposition, encoders, verification
from query_retrieval.fusion import rrf_fuse
from query_retrieval.models import SearchResultItem


def _fake_search_fn(hits_by_modality, modality):
    def _fn(vector, top_k):
        return hits_by_modality[modality]
    return _fn


def _hit(window_id, video_id="video_a", start=0.0, end=5.0):
    return {
        "window_id": window_id, "score": 0.0,
        "payload": {"video_id": video_id, "window_id": window_id, "start": start, "end": end},
    }


def _never_call_groq(monkeypatch):
    def _boom():
        raise AssertionError("groq_client.get_client() should not have been called - zero network calls expected")
    monkeypatch.setattr("query_retrieval.groq_client.get_client", lambda: _boom())


# --- 1. ENABLE_QUERY_DECOMPOSITION=false: /search is score-identical to the pre-decomposition baseline ---


def test_decomposition_off_search_scores_match_unweighted_rrf_exactly(monkeypatch):
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(api, "_encoders_ready", True)
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", False)
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", False)

    dim = 4
    monkeypatch.setattr(encoders, "encode_query", lambda q: {m: [0.0] * dim for m in config.VECTOR_NAMES})

    # Distinct video_ids so merge_windows() (which merges same-video
    # overlapping windows by design) doesn't collapse these two
    # independent hits into one region and defeat the score assertions.
    hits_by_modality = {
        "visual": [_hit("w1", video_id="video_w1"), _hit("w2", video_id="video_w2")],
        "audio": [_hit("w2", video_id="video_w2"), _hit("w1", video_id="video_w1")],
        "speech": [],
        "caption": [],
    }
    monkeypatch.setattr(api, "_SEARCH_FNS", {
        m: _fake_search_fn(hits_by_modality, m) for m in config.VECTOR_NAMES
    })

    with TestClient(api.app) as client:
        resp = client.post("/search", json={"query": "anything", "top_k": 10})

    assert resp.status_code == 200
    results = resp.json()["results"]
    by_id = {r["window_id"]: r for r in results}

    # Hand-computed against rrf_fuse's exact unweighted formula (k=config.RRF_K default 60).
    k = config.RRF_K
    expected_w1 = (1.0 / (k + 1)) + (1.0 / (k + 2))  # rank 1 in visual, rank 2 in audio
    expected_w2 = (1.0 / (k + 2)) + (1.0 / (k + 1))  # rank 2 in visual, rank 1 in audio

    assert abs(by_id["w1"]["score"] - expected_w1) < 1e-12
    assert abs(by_id["w2"]["score"] - expected_w2) < 1e-12

    # Directly cross-checked against rrf_fuse(weights=None) - the exact
    # function/path used whenever decomposition is off.
    direct = rrf_fuse(hits_by_modality, k=k)
    direct_by_id = {h.window_id: h.fused_score for h in direct}
    assert abs(by_id["w1"]["score"] - direct_by_id["w1"]) < 1e-12
    assert abs(by_id["w2"]["score"] - direct_by_id["w2"]) < 1e-12


def test_decomposition_off_never_calls_decompose_query(monkeypatch):
    """With the flag off, api.py must not even attempt decomposition -
    not "decompose then discard the result", genuinely skipped."""
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(api, "_encoders_ready", True)
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", False)
    dim = 4
    monkeypatch.setattr(encoders, "encode_query", lambda q: {m: [0.0] * dim for m in config.VECTOR_NAMES})
    monkeypatch.setattr(api, "_SEARCH_FNS", {m: (lambda v, top_k: []) for m in config.VECTOR_NAMES})

    def _boom(query):
        raise AssertionError("decompose_query() should not be called when ENABLE_QUERY_DECOMPOSITION=false")
    monkeypatch.setattr(api, "decompose_query", _boom)

    with TestClient(api.app) as client:
        resp = client.post("/search", json={"query": "anything", "top_k": 10})
    assert resp.status_code == 200


# --- 2. ENABLE_VERIFICATION=false: /verify returns a clear disabled response, /health signals it too ---


def test_verification_off_verify_endpoint_returns_404_disabled(monkeypatch):
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(api, "_encoders_ready", True)
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", False)

    with TestClient(api.app) as client:
        resp = client.post("/verify", json={"candidate_ids": ["w1"], "query": "x", "required_conditions": []})

    assert resp.status_code == 404
    assert "disabled" in resp.json()["detail"].lower()


def test_verification_off_health_reports_verification_disabled(monkeypatch):
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", False)

    with TestClient(api.app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["verification_enabled"] is False


def test_verification_on_health_reports_verification_enabled(monkeypatch):
    monkeypatch.setattr(encoders, "warmup", lambda: None)
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", True)

    with TestClient(api.app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["verification_enabled"] is True


# --- 3. GROQ_API_KEY unset: zero network calls attempted, both features fall back ---


def test_no_api_key_decomposition_falls_back_with_zero_network_calls(monkeypatch):
    monkeypatch.setattr(decomposition, "_cache", {})
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    monkeypatch.setattr(config, "ENABLE_QUERY_DECOMPOSITION", True)  # even if "on", no key means no attempt
    _never_call_groq(monkeypatch)

    result = decomposition.decompose_query("a totally new uncached query")

    assert result.tier == "fallback"


def test_no_api_key_verification_unavailable_with_zero_network_calls(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    monkeypatch.setattr(config, "ENABLE_VERIFICATION", True)
    _never_call_groq(monkeypatch)

    candidate = SearchResultItem(
        video_id="v", window_id="w1", start=0.0, end=1.0, transcript="", caption="",
        score=0.1, matched_modalities=["visual"],
    )
    result = verification.verify_candidate(candidate, "anything", [])

    assert result.state == "verification_unavailable"


def test_decomposition_default_enabled_derivation_depends_only_on_key_presence():
    """Confirms config.py's documented default rule (ENABLE_QUERY_
    DECOMPOSITION defaults to True only when a key is present) against the
    actual pure function it's built from - without reloading the shared
    config module, which would mutate global state for every other test
    in this session."""
    assert config._default_decomposition_enabled(None) is False
    assert config._default_decomposition_enabled("") is False
    assert config._default_decomposition_enabled("real-key") is True


def test_bool_helper_lets_explicit_env_override_any_default(monkeypatch):
    """The force-disable-even-with-a-key-present guarantee: _bool() (what
    ENABLE_QUERY_DECOMPOSITION is built from) always lets an explicit env
    var win over whatever default was computed."""
    monkeypatch.setenv("SOME_TEST_FLAG_XYZ", "false")
    assert config._bool("SOME_TEST_FLAG_XYZ", default=True) is False

    monkeypatch.delenv("SOME_TEST_FLAG_XYZ", raising=False)
    assert config._bool("SOME_TEST_FLAG_XYZ", default=True) is True
