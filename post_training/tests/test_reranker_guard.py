"""Tests for post_training/serve/reranker_guard.py.

Uses a mock reranker function that can be told to succeed, raise, or hang —
no real cross-encoder/model involved. Candidates are plain FAKE strings.
"""
from __future__ import annotations

import time

import pytest

from post_training.serve.reranker_guard import (
    RerankerGuard,
    RerankerGuardConfig,
    RerankerUnavailableError,
)

FAKE_CANDIDATES = ["fake-win-1", "fake-win-2", "fake-win-3"]


def _reverse_reranker(candidates: list[str]) -> list[str]:
    """A trivial 'reranker' that reverses order, so success is observable."""
    return list(reversed(candidates))


def _raising_reranker(candidates: list[str]) -> list[str]:
    raise RuntimeError("fake reranker crashed")


def _unavailable_reranker(candidates: list[str]) -> list[str]:
    raise RerankerUnavailableError("fake reranker backend not configured")


def _make_hanging_reranker(sleep_seconds: float):
    def _hang(candidates: list[str]) -> list[str]:
        time.sleep(sleep_seconds)
        return candidates

    return _hang


@pytest.fixture
def guard():
    config = RerankerGuardConfig(
        max_candidates=10, max_frames=8, max_frame_bytes=1000, timeout_seconds=0.3, max_concurrency=2
    )
    g = RerankerGuard(config)
    yield g
    g.close()


def test_success_path_returns_reranked_output(guard):
    result = guard.run(FAKE_CANDIDATES, _reverse_reranker)
    assert result.path == "reranked"
    assert result.candidates == list(reversed(FAKE_CANDIDATES))
    assert result.candidates_considered == len(FAKE_CANDIDATES)


def test_exception_falls_back_to_input_unchanged(guard):
    result = guard.run(FAKE_CANDIDATES, _raising_reranker)
    assert result.path == "fallback_exception"
    assert result.candidates == FAKE_CANDIDATES  # unchanged input, not the crashed output
    assert "fake reranker crashed" in result.reason


def test_unavailable_falls_back_to_input_unchanged(guard):
    result = guard.run(FAKE_CANDIDATES, _unavailable_reranker)
    assert result.path == "fallback_unavailable"
    assert result.candidates == FAKE_CANDIDATES


def test_timeout_falls_back_to_input_unchanged(guard):
    # guard.config.timeout_seconds = 0.3s; reranker sleeps 5s -> must time out.
    hanging = _make_hanging_reranker(sleep_seconds=5.0)
    started = time.perf_counter()
    result = guard.run(FAKE_CANDIDATES, hanging)
    elapsed = time.perf_counter() - started

    assert result.path == "fallback_timeout"
    assert result.candidates == FAKE_CANDIDATES
    # Proves the guard actually enforced the bound rather than blocking for
    # the full 5s hang.
    assert elapsed < 2.0


def test_candidate_count_is_bounded_before_reranker_runs():
    config = RerankerGuardConfig(max_candidates=2, timeout_seconds=1.0)
    guard = RerankerGuard(config)
    try:
        seen: list[str] = []

        def _record_and_reverse(candidates: list[str]) -> list[str]:
            seen.extend(candidates)
            return list(reversed(candidates))

        result = guard.run(FAKE_CANDIDATES, _record_and_reverse)
        assert seen == FAKE_CANDIDATES[:2]
        assert result.candidates_considered == 2
        assert result.candidates_discarded_by_bound == 1
        assert result.path == "reranked"
    finally:
        guard.close()


def test_frame_count_over_budget_falls_back_without_calling_reranker():
    config = RerankerGuardConfig(max_frames=4, timeout_seconds=1.0)
    guard = RerankerGuard(config)
    try:
        called = False

        def _should_not_run(candidates: list[str]) -> list[str]:
            nonlocal called
            called = True
            return candidates

        # FAKE frame counts: candidate 2 exceeds max_frames=4.
        fake_frame_counts = {"fake-win-1": 2, "fake-win-2": 5, "fake-win-3": 1}
        result = guard.run(
            FAKE_CANDIDATES,
            _should_not_run,
            frame_count_fn=lambda c: fake_frame_counts[c],
        )
        assert result.path == "fallback_frame_bound"
        assert result.candidates == FAKE_CANDIDATES
        assert called is False
    finally:
        guard.close()


def test_frame_bytes_over_budget_falls_back_without_calling_reranker():
    config = RerankerGuardConfig(max_frame_bytes=100, timeout_seconds=1.0)
    guard = RerankerGuard(config)
    try:
        called = False

        def _should_not_run(candidates: list[str]) -> list[str]:
            nonlocal called
            called = True
            return candidates

        fake_byte_sizes = {"fake-win-1": 50, "fake-win-2": 50, "fake-win-3": 500}
        result = guard.run(
            FAKE_CANDIDATES,
            _should_not_run,
            frame_bytes_fn=lambda c: fake_byte_sizes[c],
        )
        assert result.path == "fallback_byte_bound"
        assert result.candidates == FAKE_CANDIDATES
        assert called is False
    finally:
        guard.close()


def test_empty_candidates_is_a_no_op_skip(guard):
    result = guard.run([], _reverse_reranker)
    assert result.path == "skipped"
    assert result.candidates == []


def test_wrong_output_length_falls_back(guard):
    def _drops_a_candidate(candidates: list[str]) -> list[str]:
        return candidates[:-1]

    result = guard.run(FAKE_CANDIDATES, _drops_a_candidate)
    assert result.path == "fallback_exception"
    assert result.candidates == FAKE_CANDIDATES


def test_concurrent_calls_are_bounded_by_max_concurrency():
    # max_concurrency=1: a second call must wait for the first slot, proving
    # the semaphore actually gates concurrent reranker invocations.
    config = RerankerGuardConfig(max_concurrency=1, timeout_seconds=2.0)
    guard = RerankerGuard(config)
    try:
        import threading

        in_flight = []
        max_in_flight = []
        lock = threading.Lock()

        def _slow(candidates: list[str]) -> list[str]:
            with lock:
                in_flight.append(1)
                max_in_flight.append(len(in_flight))
            time.sleep(0.2)
            with lock:
                in_flight.pop()
            return candidates

        threads = [
            threading.Thread(target=lambda: guard.run(FAKE_CANDIDATES, _slow)) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert max(max_in_flight) == 1
    finally:
        guard.close()
