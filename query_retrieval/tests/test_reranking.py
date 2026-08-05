"""Unit tests for bounded multimodal cross-encoder reranking.

All sampling and model adapters are injected.  No video decoder, optional
Qwen dependency, model download, network call, or vector database is needed.
"""
from __future__ import annotations

import math

import pytest

from query_retrieval.models import SearchResultItem
from query_retrieval.reranking import (
    CrossEncoderInput,
    Qwen3VLRerankerAdapter,
    RerankOptions,
    calculate_ranking_metrics,
    rerank_candidates,
)


def _candidate(window_id: str, score: float, **overrides) -> SearchResultItem:
    defaults = {
        "video_id": "video-a",
        "window_id": window_id,
        "start": 10.0,
        "end": 30.0,
        "transcript": f"transcript for {window_id}",
        "caption": f"caption for {window_id}",
        "score": score,
        "matched_modalities": ["visual", "audio", "transcript", "caption"],
        "source_path": "processing_jobs/example/example.mp4",
    }
    defaults.update(overrides)
    return SearchResultItem(**defaults)


class _RecordingAdapter:
    name = "test-cross-encoder"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.inputs: list[CrossEncoderInput] = []

    def score(self, evidence: CrossEncoderInput) -> float:
        self.inputs.append(evidence)
        return self.scores[evidence.candidate_id]


def test_reranks_only_bounded_fused_candidates_with_fresh_scores():
    candidates = [
        _candidate("a", 0.99),
        _candidate("b", 0.75),
        _candidate("c", 0.50),
        _candidate("not-sampled", 0.25),
    ]
    sampled: list[str] = []

    def sampler(candidate: SearchResultItem, max_frames: int):
        sampled.append(candidate.window_id)
        # The module must cap a defensive sampler that returns too many frames.
        return [10.0, 12.0, 14.0, 16.0], ["frame-1", "frame-2", "frame-3", "frame-4"]

    adapter = _RecordingAdapter({"a": 0.1, "b": 0.4, "c": 0.9})
    result = rerank_candidates(
        "red car drives away",
        candidates,
        adapter,
        options=RerankOptions(candidate_limit=3, max_frames=3),
        frame_sampler=sampler,
    )

    assert [item.window_id for item in result.candidates] == ["c", "b", "a"]
    assert [item.score for item in result.candidates] == [0.50, 0.75, 0.99]
    assert [item.final_score for item in result.candidates] == [0.9, 0.4, 0.1]
    assert sampled == ["a", "b", "c"]
    assert [item.candidate_id for item in adapter.inputs] == ["a", "b", "c"]
    assert all(len(item.frames) == len(item.frame_timestamps) == 3 for item in adapter.inputs)
    assert adapter.inputs[0].transcript == "transcript for a"
    assert adapter.inputs[0].caption == "caption for a"
    # The adapter cannot access first-stage RRF/vector score data.  Candidate
    # selection is the only value inherited from the recall stage.
    assert not hasattr(adapter.inputs[0], "candidate")
    assert not hasattr(adapter.inputs[0], "score")
    assert result.diagnostics.state == "reranked"
    assert result.diagnostics.candidates_discarded_by_bound == 1
    assert result.diagnostics.candidates_scored == 3
    assert result.diagnostics.score_normalization == "native_unit_interval"
    assert result.diagnostics.total_latency_ms >= 0


def test_logit_scores_are_normalized_without_reading_vector_rrf_scores():
    candidates = [_candidate("a", 0.9), _candidate("b", 0.1)]
    adapter = _RecordingAdapter({"a": -5.0, "b": 5.0})

    result = rerank_candidates(
        "query",
        candidates,
        adapter,
        frame_sampler=lambda *_: ([1.0, 2.0], ["one", "two"]),
    )

    assert [item.window_id for item in result.candidates] == ["b", "a"]
    assert [item.final_score for item in result.candidates] == [1.0, 0.0]
    # The values remain available solely as first-stage retrieval evidence.
    assert [item.score for item in result.candidates] == [0.1, 0.9]
    assert result.diagnostics.score_normalization == "min_max_fresh_reranker"


def test_unavailable_qwen_adapter_fails_open_without_leaking_exception_text():
    candidates = [_candidate("a", 0.8), _candidate("b", 0.7)]
    adapter = Qwen3VLRerankerAdapter()

    result = rerank_candidates(
        "query",
        candidates,
        adapter,
        frame_sampler=lambda *_: ([1.0, 2.0], ["one", "two"]),
    )

    assert [item.window_id for item in result.candidates] == ["a", "b"]
    assert all(item.final_score is None for item in result.candidates)
    assert result.diagnostics.state == "unavailable"
    assert result.diagnostics.candidates_scored == 0
    assert result.diagnostics.candidates_failed == 2
    assert {item.error_type for item in result.diagnostics.candidates} == {"RerankerUnavailable"}
    assert "backend is not configured" not in result.diagnostics.message
    assert adapter.loaded is False


def test_qwen_backend_factory_is_lazy_and_loads_once():
    calls = 0

    def factory():
        nonlocal calls
        calls += 1

        def runner(evidence: CrossEncoderInput) -> float:
            return 0.8 if evidence.candidate_id == "first" else 0.2

        return runner

    adapter = Qwen3VLRerankerAdapter(
        model="local-qwen3-vl-reranker", backend_factory=factory
    )
    assert adapter.loaded is False
    result = rerank_candidates(
        "query",
        [_candidate("first", 0.1), _candidate("second", 0.9)],
        adapter,
        frame_sampler=lambda *_: ([1.0, 2.0], ["one", "two"]),
    )

    assert calls == 1
    assert adapter.loaded is True
    assert [item.window_id for item in result.candidates] == ["first", "second"]


def test_partial_failure_preserves_fused_order_by_default():
    candidates = [_candidate("first", 0.3), _candidate("bad", 0.2), _candidate("third", 0.1)]

    class PartialAdapter(_RecordingAdapter):
        def score(self, evidence: CrossEncoderInput) -> float:
            if evidence.candidate_id == "bad":
                raise RuntimeError("token=test-key should not leave the adapter")
            return super().score(evidence)

    adapter = PartialAdapter({"first": 0.1, "third": 0.9})
    result = rerank_candidates(
        "query",
        candidates,
        adapter,
        frame_sampler=lambda *_: ([1.0, 2.0], ["one", "two"]),
    )

    assert [item.window_id for item in result.candidates] == ["first", "bad", "third"]
    assert result.candidates[0].final_score == 0.1
    assert result.candidates[1].final_score is None
    assert result.candidates[2].final_score == 0.9
    assert result.diagnostics.state == "partial"
    assert result.diagnostics.candidates_failed == 1
    bad_diagnostic = next(item for item in result.diagnostics.candidates if item.window_id == "bad")
    assert bad_diagnostic.error_type == "RuntimeError"
    assert "test-key" not in repr(result.diagnostics)


def test_frame_sampler_contract_failure_is_safe_and_bounded():
    result = rerank_candidates(
        "query",
        [_candidate("a", 0.8), _candidate("b", 0.7)],
        _RecordingAdapter({"a": 0.9, "b": 0.1}),
        frame_sampler=lambda *_: ([1.0], ["one"]),
    )

    assert [item.window_id for item in result.candidates] == ["a", "b"]
    assert result.diagnostics.state == "unavailable"
    assert all(item.state == "sampling_failed" for item in result.diagnostics.candidates)
    assert all(item.error_type == "RerankerInputError" for item in result.diagnostics.candidates)


def test_ranking_metrics_are_only_calculated_with_ground_truth_labels():
    candidates = [
        _candidate("miss", 0.9),
        _candidate("merged", 0.8, source_window_ids=["ground-truth-a"]),
        _candidate("direct-hit", 0.7),
    ]

    no_labels = calculate_ranking_metrics(candidates, None, k=3)
    metrics = calculate_ranking_metrics(candidates, {"ground-truth-a", "direct-hit"}, k=3)

    assert no_labels.evaluated is False
    assert no_labels.recall_at_k is None
    assert metrics.evaluated is True
    assert metrics.hits_at_k == 2
    assert metrics.recall_at_k == 1.0
    assert metrics.mrr == 0.5
    expected_ndcg = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert metrics.ndcg_at_k == pytest.approx(expected_ndcg)
