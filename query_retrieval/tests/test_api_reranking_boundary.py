"""API-profile tests for the recall -> precision -> evidence boundary.

These tests exercise only injected frame/model seams.  They never contact
Qdrant Cloud, load Qwen, decode video, or call a VLM provider.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from processing_indexing.api_pipeline import DEFAULT_API_GEMINI_PROFILE
from processing_indexing.runtime_profiles import API_GEMINI_FREE_V1
from processing_indexing.gemini_runtime import (
    GeminiAuthenticationError,
    GeminiQuotaError,
    GeminiSDKUnavailableError,
)
from query_retrieval import api, reranking
from query_retrieval.models import (
    SearchRequest,
    SearchResultItem,
    VerificationOptions,
    VerificationResult,
)


def _candidate(window_id: str, rrf_score: float, *, reranker_score: float | None = None) -> SearchResultItem:
    return SearchResultItem(
        video_id="demo-video",
        window_id=window_id,
        start=10.0,
        end=30.0,
        transcript=f"transcript for {window_id}",
        caption=f"caption for {window_id}",
        score=rrf_score,
        final_score=reranker_score,
        matched_modalities=["visual", "audio", "transcript", "caption"],
        source_path="processing_jobs/demo/demo.mp4",
    )


def test_api_cross_encoder_only_receives_bounded_rrf_candidate_list(monkeypatch):
    received = []

    class FakeAdapter:
        name = "test-qwen-cross-encoder"

        def __init__(self, *_args, **_kwargs):
            pass

        def score(self, evidence):
            received.append(evidence)
            return {"rrf-first": 0.1, "rrf-second": 0.9}[evidence.candidate_id]

    monkeypatch.setattr(reranking, "Qwen3VLRerankerAdapter", FakeAdapter)
    monkeypatch.setattr(
        reranking,
        "default_frame_sampler",
        lambda candidate, _max_frames: ([candidate.start, candidate.end], ["frame-a", "frame-b"]),
    )

    candidates = [
        _candidate("rrf-first", 0.99),
        _candidate("rrf-second", 0.25),
        _candidate("outside-bound", 0.98),
    ]
    results, diagnostics = api._rerank_api_candidates(
        SearchRequest(
            query="red car leaves", rerank_top_n=2, reranker_provider="local_qwen"
        ),
        candidates,
    )

    # RRF chooses the two candidates that may enter the cross-encoder.  Its
    # scores are neither exposed to nor used by that cross-encoder.
    assert [item.candidate_id for item in received] == ["rrf-first", "rrf-second"]
    assert not hasattr(received[0], "candidate")
    assert not hasattr(received[0], "score")
    assert [item.window_id for item in results] == ["rrf-second", "rrf-first"]
    assert [item.final_score for item in results] == [0.9, 0.1]
    assert diagnostics["state"] == "reranked"
    assert diagnostics["candidate_list_source"] == "rrf_top_k_only"
    assert diagnostics["rrf_score_used_for_ordering"] is False


def test_reranker_is_disabled_without_an_explicit_selection():
    # The default API profile has reranking enabled as a feature but no local
    # Qwen selection.  It therefore cannot import/download Qwen or allocate a
    # GPU merely because a search is opened.
    adapter, selection = api._explicit_qwen_reranker(SearchRequest(query="query"))
    assert adapter is None
    assert selection["reason"] == "no_explicit_local_qwen_selection"

    results, diagnostics = api._rerank_api_candidates(
        SearchRequest(query="query"), [_candidate("one", 0.9)]
    )

    assert [item.window_id for item in results] == ["one"]
    assert diagnostics["state"] == "disabled"


def test_runtime_reranker_selection_overrides_direct_request_choice():
    request = SearchRequest(query="query", reranker_provider="local_qwen")
    provider, model, source = api._reranker_selection_values(
        request,
        {
            "providers": {"reranker": "none"},
            "models": {"reranker": "disabled"},
        },
    )

    assert (provider, model, source) == ("none", "disabled", "runtime_session")


def test_official_qwen_request_model_is_an_explicit_local_opt_in():
    provider, model, source = api._reranker_selection_values(
        SearchRequest(
            query="query",
            reranker_model="Qwen/Qwen3-VL-Reranker-2B",
        )
    )

    assert (provider, model, source) == (
        "local_qwen",
        "Qwen/Qwen3-VL-Reranker-2B",
        "request_model",
    )


def test_api_verification_attaches_evidence_without_reordering_or_blending(monkeypatch):
    # These are already ordered by the fresh cross-encoder score.  Their RRF
    # scores and VLM confidences deliberately point in the opposite direction.
    reranked_first = _candidate("fresh-first", 0.01, reranker_score=0.95)
    reranked_second = _candidate("fresh-second", 0.99, reranker_score=0.05)

    def verdict(candidate, *_args):
        if candidate.window_id == "fresh-first":
            return VerificationResult(
                candidate_id=candidate.window_id,
                state="rejected",
                match=False,
                confidence=0.99,
            )
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verified",
            match=True,
            confidence=0.01,
            event_start_relative=1.0,
            event_end_relative=3.0,
        )

    monkeypatch.setattr(api, "verify_candidate", verdict)
    results, diagnostics = api._apply_api_verification_evidence(
        [reranked_first, reranked_second],
        "red car leaves",
        [],
        VerificationOptions(provider="gemini", api_key="test-only", top_n=2),
    )

    # Evidence is attached and a playable interval is refined, but no RRF or
    # VLM confidence is blended into the cross-encoder score or used to sort.
    assert [item.window_id for item in results] == ["fresh-first", "fresh-second"]
    assert [item.final_score for item in results] == [0.95, 0.05]
    assert results[0].state == "rejected"
    assert results[1].state == "verified"
    assert results[1].refined_start == 11.0
    assert results[1].refined_end == 13.0
    assert diagnostics["ordering_changed"] is False
    assert diagnostics["rrf_score_used_for_ordering"] is False
    assert diagnostics["verification_confidence_used_for_ordering"] is False


def test_api_verification_only_touches_the_bounded_final_candidates(monkeypatch):
    calls: list[str] = []

    def verdict(candidate, *_args):
        calls.append(candidate.window_id)
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verified",
            match=True,
            confidence=0.5,
        )

    monkeypatch.setattr(api, "verify_candidate", verdict)
    results, diagnostics = api._apply_api_verification_evidence(
        [_candidate("one", 0.9), _candidate("two", 0.8), _candidate("three", 0.7)],
        "query",
        [],
        VerificationOptions(provider="gemini", api_key="test-only", top_n=2),
    )

    assert calls == ["one", "two"]
    assert results[2].verification is None
    assert results[2].state == "retrieved"
    assert diagnostics["candidates_checked"] == 2
    assert diagnostics["timestamps_refined"] == 0


def test_standalone_query_validation_does_not_reflect_an_invalid_api_key():
    client = TestClient(api.app)
    secret = "standalone-do-not-reflect-" + "x" * 5_000

    response = client.post(
        "/search",
        json={"query": "find a red car", "verification": {"api_key": secret}},
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["detail"][0]["input"] == "[REDACTED]"


def test_api_cloud_retrieval_filter_requires_the_exact_embedding_contract():
    query_filter = api._api_profile_query_filter(DEFAULT_API_GEMINI_PROFILE)
    conditions = {
        condition.key: condition.match.value
        for condition in query_filter.must
    }

    assert conditions == {
        "embedding_profile": "api-gemini-free-v1",
        "embedding_provider": "gemini",
        "embedding_model": "gemini-embedding-2",
        "embedding_dimensions": 1536,
    }


def test_api_zero_top_k_does_not_spend_hosted_provider_or_qdrant_work(monkeypatch):
    calls = []

    def runtime(_request):
        calls.append("runtime")
        return {"runtime_profile_id": "api-gemini-free-v1"}, API_GEMINI_FREE_V1

    monkeypatch.setattr(api, "_api_runtime", runtime)
    response = api._search_api_profile(
        SearchRequest(
            query="red car",
            top_k=0,
            profile_id="api-gemini-free-v1",
            runtime_session_id="opaque",
        )
    )

    assert calls == ["runtime"]
    assert response.results == []
    assert response.diagnostics["state"] == "skipped_zero_top_k"


@pytest.mark.parametrize(
    ("provider_error", "status", "message"),
    [
        (
            GeminiSDKUnavailableError("google-genai missing"),
            503,
            "Gemini support is not installed",
        ),
        (
            GeminiAuthenticationError("invalid API key"),
            401,
            "Gemini rejected the API key",
        ),
        (
            GeminiQuotaError("resource exhausted"),
            429,
            "Gemini quota or rate limit",
        ),
    ],
)
def test_api_gemini_failure_messages_are_actionable_and_safe(
    provider_error, status, message
):
    response_error = api._gemini_query_http_error(provider_error)

    assert response_error.status_code == status
    assert message in str(response_error.detail)
    assert "invalid API key" not in str(response_error.detail)
