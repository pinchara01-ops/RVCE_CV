"""Bounded reranker wrapper with fail-open fallback to the input ranking.

Where the existing pipeline calls a reranker (found, not guessed)
------------------------------------------------------------------
``query_retrieval/reranking.py:rerank_candidates()`` is the real cross-encoder
precision stage. It is wired in from
``query_retrieval/api.py:_rerank_api_candidates()``, called from
``query_retrieval/api.py:search()`` only on the ``use_explicit_local_precision``
path (a local Qwen reranker explicitly selected via
``SearchRequest.reranker_provider == "local_qwen"`` or a runtime session).

That existing code already bounds:

- **candidate count** — ``RerankOptions.candidate_limit`` (default 30, hard
  ceiling ``MAX_RERANK_CANDIDATES = 100``). Applied *before* frame sampling;
  candidates past the limit are dropped, not appended after scoring.
- **frame count** — ``RerankOptions.max_frames`` (default 8, hard ceiling
  ``MAX_RERANK_FRAMES = 16``).
- **failure/unavailability** — any exception during scoring, a missing
  adapter, or ``RerankerUnavailable`` all fall back to the incoming fused
  candidate order unchanged (``rerank_candidates()``'s ``"unavailable"``/
  ``"partial"`` states; ``_rerank_api_candidates()``'s outer ``except
  Exception`` clause).

Checked the whole of both files; it does **not** bound:

- **byte size** of sampled frames — nothing measures or caps
  ``CrossEncoderInput.frames`` size.
- **wall-clock timeout** on one ``adapter.score()`` call — a hanging adapter
  call blocks the whole `/search` request indefinitely; there is no
  `asyncio`/thread timeout anywhere in the call chain.
- **concurrency** — ``rerank_candidates()`` is a plain serial ``for`` loop
  over candidates; nothing limits how many reranker calls run at once across
  concurrent `/search` requests either.

This module adds those three missing bounds, plus its own independent
candidate/frame bounds, around *any* reranker callable — so it can wrap the
real ``Qwen3VLRerankerAdapter``-backed one later, or the mock used in tests
today, without importing anything from post_training/ back into
query_retrieval/. It is a standalone guard: not currently wired into
query_retrieval/api.py, ready to be adopted there when desired.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

import yaml

logger = logging.getLogger(__name__)

T = TypeVar("T")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "eval_defaults.yaml"

try:  # optional interop: recognize the real pipeline's own exception too
    from query_retrieval.reranking import RerankerUnavailable as _PipelineRerankerUnavailable
except Exception:  # pragma: no cover - query_retrieval may be unimportable in some envs
    _PipelineRerankerUnavailable = None


class RerankerUnavailableError(RuntimeError):
    """A reranker_fn should raise this to signal it cannot run right now."""


@dataclass(frozen=True)
class RerankerGuardConfig:
    max_candidates: int = 30
    max_frames: int = 8
    max_frame_bytes: int = 2_000_000
    timeout_seconds: float = 10.0
    max_concurrency: int = 4

    @classmethod
    def from_yaml(cls, path: Path = CONFIG_PATH) -> "RerankerGuardConfig":
        raw = yaml.safe_load(path.read_text()) or {}
        section = raw.get("reranker_guard", {})
        return cls(
            max_candidates=int(section.get("max_candidates", cls.max_candidates)),
            max_frames=int(section.get("max_frames", cls.max_frames)),
            max_frame_bytes=int(section.get("max_frame_bytes", cls.max_frame_bytes)),
            timeout_seconds=float(section.get("timeout_seconds", cls.timeout_seconds)),
            max_concurrency=int(section.get("max_concurrency", cls.max_concurrency)),
        )


@dataclass(frozen=True)
class RerankerGuardResult(Generic[T]):
    candidates: list[T]
    # "reranked" means the wrapped reranker ran and its output is returned.
    # Every other value means the ORIGINAL, unmodified input ranking is
    # returned in `candidates` (fail-open).
    path: str
    reason: str
    candidates_considered: int
    candidates_discarded_by_bound: int
    elapsed_ms: float


class RerankerGuard(Generic[T]):
    """Wraps a reranker callable with candidate/frame/byte/timeout/concurrency
    bounds. Fails open to the untouched input ranking on any violation."""

    def __init__(self, config: RerankerGuardConfig | None = None) -> None:
        self.config = config or RerankerGuardConfig.from_yaml()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, self.config.max_concurrency), thread_name_prefix="reranker-guard"
        )
        self._semaphore = threading.BoundedSemaphore(max(1, self.config.max_concurrency))

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> "RerankerGuard[T]":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def run(
        self,
        candidates: Sequence[T],
        reranker_fn: Callable[[list[T]], Sequence[T]],
        *,
        frame_count_fn: Callable[[T], int] | None = None,
        frame_bytes_fn: Callable[[T], int] | None = None,
    ) -> RerankerGuardResult[T]:
        """Run ``reranker_fn(bounded_candidates)`` under the configured
        bounds. ``frame_count_fn``/``frame_bytes_fn`` are optional accessors
        the caller supplies to read frame count/byte size off a candidate
        object — the guard has no opinion on candidate shape.
        """
        started = time.perf_counter()
        original = list(candidates)

        if not original:
            return self._fallback(original, "skipped", "no candidates supplied", 0, 0, started)

        bounded = original[: self.config.max_candidates]
        discarded = len(original) - len(bounded)

        if frame_count_fn is not None:
            over_budget = [c for c in bounded if frame_count_fn(c) > self.config.max_frames]
            if over_budget:
                return self._fallback(
                    original,
                    "fallback_frame_bound",
                    f"{len(over_budget)} candidate(s) exceed max_frames={self.config.max_frames}",
                    len(bounded),
                    discarded,
                    started,
                )

        if frame_bytes_fn is not None:
            over_budget = [c for c in bounded if frame_bytes_fn(c) > self.config.max_frame_bytes]
            if over_budget:
                return self._fallback(
                    original,
                    "fallback_byte_bound",
                    f"{len(over_budget)} candidate(s) exceed "
                    f"max_frame_bytes={self.config.max_frame_bytes}",
                    len(bounded),
                    discarded,
                    started,
                )

        acquired = self._semaphore.acquire(timeout=self.config.timeout_seconds)
        if not acquired:
            return self._fallback(
                original,
                "fallback_concurrency",
                f"could not acquire a reranker concurrency slot "
                f"(max_concurrency={self.config.max_concurrency}) within "
                f"timeout_seconds={self.config.timeout_seconds}",
                len(bounded),
                discarded,
                started,
            )
        try:
            future = self._executor.submit(reranker_fn, bounded)
            try:
                result = future.result(timeout=self.config.timeout_seconds)
            except FutureTimeoutError:
                return self._fallback(
                    original,
                    "fallback_timeout",
                    f"reranker exceeded timeout_seconds={self.config.timeout_seconds}",
                    len(bounded),
                    discarded,
                    started,
                )
            except _unavailable_exceptions() as exc:
                return self._fallback(
                    original, "fallback_unavailable", str(exc), len(bounded), discarded, started
                )
            except Exception as exc:  # noqa: BLE001 - any reranker failure must fail open
                return self._fallback(
                    original,
                    "fallback_exception",
                    f"{type(exc).__name__}: {exc}",
                    len(bounded),
                    discarded,
                    started,
                )
        finally:
            self._semaphore.release()

        result_list = list(result)
        if len(result_list) != len(bounded):
            return self._fallback(
                original,
                "fallback_exception",
                f"reranker returned {len(result_list)} candidates for {len(bounded)} input",
                len(bounded),
                discarded,
                started,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "reranker_guard: path=reranked candidates=%d elapsed_ms=%.1f", len(result_list), elapsed_ms
        )
        return RerankerGuardResult(
            candidates=result_list,
            path="reranked",
            reason="",
            candidates_considered=len(bounded),
            candidates_discarded_by_bound=discarded,
            elapsed_ms=elapsed_ms,
        )

    def _fallback(
        self,
        original: list[T],
        path: str,
        reason: str,
        considered: int,
        discarded: int,
        started: float,
    ) -> RerankerGuardResult[T]:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.warning("reranker_guard: path=%s reason=%s elapsed_ms=%.1f", path, reason, elapsed_ms)
        return RerankerGuardResult(
            candidates=original,
            path=path,
            reason=reason,
            candidates_considered=considered,
            candidates_discarded_by_bound=discarded,
            elapsed_ms=elapsed_ms,
        )


def _unavailable_exceptions() -> tuple[type[BaseException], ...]:
    exceptions: tuple[type[BaseException], ...] = (RerankerUnavailableError,)
    if _PipelineRerankerUnavailable is not None:
        exceptions = exceptions + (_PipelineRerankerUnavailable,)
    return exceptions
