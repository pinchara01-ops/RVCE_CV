"""Qdrant-backed read models for the local indexed-video UI.

The processing job manager is intentionally short lived.  This module makes
the collection the source of truth after an index run, while keeping local
filesystem paths server-side.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Callable, TypeVar

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from .config import Settings
from .models import VECTOR_DIMS
from .profile_qdrant_store import ensure_window_payload_indexes
from .runtime_profiles import redact_secrets


_LIBRARY_READ_ATTEMPTS = 3
_LIBRARY_READ_TIMEOUT_SECONDS = 4.0
_LIBRARY_DIAGNOSTICS_FILENAME = "_library_diagnostics.jsonl"
_LIBRARY_DIAGNOSTICS_MAX_BYTES = 1_000_000
_LIBRARY_DIAGNOSTICS_LOCK = threading.Lock()
_Result = TypeVar("_Result")


class LibraryReadError(RuntimeError):
    """A safe, actionable error from a persistent-library Qdrant read."""

    def __init__(
        self,
        *,
        operation: str,
        attempts: int,
        error_type: str,
        message: str,
    ) -> None:
        self.operation = operation
        self.attempts = attempts
        self.error_type = error_type
        self.safe_message = message
        label = operation.replace("_", " ")
        super().__init__(
            f"Qdrant {label} did not complete after {attempts} attempts "
            f"({error_type}): {message}. Review Library diagnostics and retry."
        )


def _library_diagnostics_path() -> Path:
    jobs_root = Path(os.getenv("PROCESSING_JOBS_DIR", "processing_jobs")).resolve()
    return jobs_root / _LIBRARY_DIAGNOSTICS_FILENAME


def _safe_library_error(settings: Settings, error: Exception) -> str:
    """Never persist or return a Qdrant key contained in a client exception."""

    text = f"{type(error).__name__}: {error}"
    return str(redact_secrets(text, (settings.qdrant_api_key or "",)))


def _library_next_action(error: Exception) -> str:
    text = f"{type(error).__name__}: {error}".lower()
    if "timeout" in text or "timed out" in text or "connection" in text:
        return "Qdrant did not respond in time. Check the active cluster and network, then retry."
    if any(token in text for token in ("unauthorized", "forbidden", "api key", "authentication")):
        return "Check the Qdrant Cloud API key in Architecture, then reconnect the API-based session."
    return "Review this safe diagnostic, confirm the selected profile and collection, then retry."


def _record_library_diagnostic(
    *,
    settings: Settings,
    operation: str,
    status: str,
    attempt: int,
    attempts: int,
    error: Exception,
    elapsed_ms: int,
) -> None:
    """Append a bounded, redacted record that survives a browser refresh.

    Indexing artifacts already live under each job. This separate log covers
    later Library reads, whose failures previously vanished behind a generic
    HTTP 503 message.
    """

    diagnostic = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "status": status,
        "attempt": attempt,
        "attempts": attempts,
        "collection_name": settings.collection_name,
        "error_type": type(error).__name__,
        "error": _safe_library_error(settings, error),
        "elapsed_ms": elapsed_ms,
        "next_action": _library_next_action(error),
    }
    path = _library_diagnostics_path()
    try:
        with _LIBRARY_DIAGNOSTICS_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _LIBRARY_DIAGNOSTICS_MAX_BYTES:
                retained = path.read_text(encoding="utf-8").splitlines()[-250:]
                path.write_text("\n".join(retained) + ("\n" if retained else ""), encoding="utf-8")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(diagnostic, ensure_ascii=False) + "\n")
    except OSError:
        # Diagnostics must never turn a recoverable library read into an error.
        pass


def list_library_diagnostics(limit: int = 100) -> list[dict[str, Any]]:
    """Return recent, already-redacted library-read diagnostics chronologically."""

    path = _library_diagnostics_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines[-max(1, min(limit, 500)) :]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _read_with_retries(
    *,
    settings: Settings,
    operation: str,
    action: Callable[[QdrantClient], _Result],
) -> _Result:
    """Run a read against fresh Qdrant clients, tolerating short Cloud stalls."""

    last_error: Exception | None = None
    for attempt in range(1, _LIBRARY_READ_ATTEMPTS + 1):
        client: QdrantClient | None = None
        started = time.perf_counter()
        try:
            client = _client(
                replace(
                    settings,
                    qdrant_timeout_seconds=_read_timeout_seconds(settings),
                )
            )
            return action(client)
        except Exception as exc:  # noqa: BLE001 - translated below to a safe UI error
            last_error = exc
            _record_library_diagnostic(
                settings=settings,
                operation=operation,
                status="retrying" if attempt < _LIBRARY_READ_ATTEMPTS else "failed",
                attempt=attempt,
                attempts=_LIBRARY_READ_ATTEMPTS,
                error=exc,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
            )
        finally:
            if client is not None:
                _close_client(client)
        if attempt < _LIBRARY_READ_ATTEMPTS:
            time.sleep(0.2 * attempt)

    assert last_error is not None
    raise LibraryReadError(
        operation=operation,
        attempts=_LIBRARY_READ_ATTEMPTS,
        error_type=type(last_error).__name__,
        message=_safe_library_error(settings, last_error),
    ) from last_error


def _client(settings: Settings) -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.qdrant_timeout_seconds,
    )


def _health_timeout_seconds(settings: Settings) -> float:
    """Give a cold local Qdrant enough time without blocking the UI indefinitely."""
    return min(settings.qdrant_timeout_seconds, 5.0)


def _read_timeout_seconds(settings: Settings) -> float:
    """Keep a Library refresh responsive even if a Cloud node is unhealthy."""

    return min(settings.qdrant_timeout_seconds, _LIBRARY_READ_TIMEOUT_SECONDS)


def _health_client(settings: Settings) -> QdrantClient:
    """Use a short timeout for the UI health probe, which is safe to retry."""
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=_health_timeout_seconds(settings),
    )


def _close_client(client: QdrantClient) -> None:
    """Release HTTP sockets from short-lived read-model clients promptly."""
    try:
        client.close()
    except Exception:  # noqa: BLE001 - a successful read must not fail on cleanup
        pass


def _summary(vector: list[float]) -> dict[str, Any]:
    return {
        "dimensions": len(vector),
        "norm": math.sqrt(sum(value * value for value in vector)),
        "minimum": min(vector) if vector else None,
        "maximum": max(vector) if vector else None,
        "finite": all(math.isfinite(value) for value in vector),
    }


def media_path_for_source(source_path: str | Path | None) -> Path | None:
    """Return a safely servable upload path, never an arbitrary local file."""
    if not source_path:
        return None
    candidate = Path(source_path).resolve()
    jobs_root = Path(os.getenv("PROCESSING_JOBS_DIR", "processing_jobs")).resolve()
    if candidate != jobs_root and jobs_root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    source_path = data.pop("source_path", "")
    data["media_available"] = media_path_for_source(source_path) is not None
    data["source_filename"] = Path(source_path).name if source_path else ""
    return data


def _collection_health_once(
    settings: Settings,
    expected_vector_dims: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    client = _health_client(settings)
    try:
        if not client.collection_exists(settings.collection_name):
            return {
                "reachable": True,
                "collection_exists": False,
                "collection_name": settings.collection_name,
                "points_count": 0,
                "vectors": {},
                "schema_valid": True,
                "schema_errors": [],
            }
        info = client.get_collection(settings.collection_name)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict):
            return {
                "reachable": True,
                "collection_exists": True,
                "collection_name": settings.collection_name,
                "points_count": info.points_count,
                "vectors": {},
                "schema_valid": False,
                "schema_errors": [
                    "The collection has one unnamed vector; this app requires four named vectors."
                ],
            }
        vector_info = {
            name: {
                "dimensions": value.size,
                "distance": getattr(value.distance, "value", str(value.distance)),
            }
            for name, value in vectors.items()
        }
        expected = dict(expected_vector_dims or VECTOR_DIMS)
        schema_errors = []
        for name, dimensions in expected.items():
            value = vectors.get(name)
            if value is None:
                schema_errors.append(f"Missing required '{name}' vector.")
            elif value.size != dimensions:
                schema_errors.append(
                    f"'{name}' has {value.size} dimensions; expected {dimensions}."
                )
        for name in vectors:
            if name not in expected:
                schema_errors.append(f"Unexpected '{name}' vector in the collection.")
        return {
            "reachable": True,
            "collection_exists": True,
            "collection_name": settings.collection_name,
            "points_count": info.points_count,
            "vectors": vector_info,
            "schema_valid": not schema_errors,
            "schema_errors": schema_errors,
        }
    finally:
        _close_client(client)


def collection_health(
    settings: Settings | None = None,
    *,
    expected_vector_dims: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Return collection diagnostics, tolerating brief local-Qdrant stalls.

    The health check is read-only and powers a visible UI badge. Retrying it
    prevents one transient HTTP timeout from presenting an otherwise usable
    collection as unavailable.
    """
    settings = settings or Settings.from_env()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return _collection_health_once(settings, expected_vector_dims)
        except Exception as exc:  # noqa: BLE001 - surface diagnostics in the UI
            last_error = exc
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    if last_error is not None:
        _record_library_diagnostic(
            settings=settings,
            operation="collection_health",
            status="failed",
            attempt=3,
            attempts=3,
            error=last_error,
            elapsed_ms=0,
        )
    return {
        "reachable": False,
        "collection_exists": False,
        "collection_name": settings.collection_name,
        "points_count": 0,
        "vectors": {},
        "schema_valid": False,
        "schema_errors": [],
        "error": str(last_error),
    }


def _filter(video_id: str | None = None, window_id: str | None = None):
    conditions = []
    if video_id:
        conditions.append(FieldCondition(key="video_id", match=MatchValue(value=video_id)))
    if window_id:
        conditions.append(FieldCondition(key="window_id", match=MatchValue(value=window_id)))
    return Filter(must=conditions) if conditions else None


def list_windows(
    *,
    settings: Settings | None = None,
    video_id: str | None = None,
    limit: int = 100,
    include_vectors: bool = False,
) -> list[dict[str, Any]]:
    settings = settings or Settings.from_env()
    def read(client: QdrantClient) -> list[dict[str, Any]]:
        if not client.collection_exists(settings.collection_name):
            return []
        ensure_window_payload_indexes(client, settings.collection_name)
        records, _ = client.scroll(
            collection_name=settings.collection_name,
            scroll_filter=_filter(video_id=video_id),
            limit=max(1, min(limit, 500)),
            with_payload=True,
            with_vectors=include_vectors,
        )
        result = []
        for record in records:
            entry = {
                "point_id": str(record.id),
                "payload": _safe_payload(record.payload),
            }
            if include_vectors:
                vectors = record.vector or {}
                entry["vectors"] = {
                    name: _summary(values)
                    for name, values in vectors.items()
                    if isinstance(values, list)
                }
            result.append(entry)
        return sorted(
            result,
            key=lambda row: (
                row["payload"].get("video_id", ""),
                row["payload"].get("start", 0),
            ),
        )

    return _read_with_retries(
        settings=settings,
        operation="indexed_windows",
        action=read,
    )


def get_window(
    window_id: str,
    *,
    settings: Settings | None = None,
    include_vectors: bool = False,
) -> dict[str, Any] | None:
    settings = settings or Settings.from_env()
    def read(client: QdrantClient) -> dict[str, Any] | None:
        if not client.collection_exists(settings.collection_name):
            return None
        ensure_window_payload_indexes(client, settings.collection_name)
        records, _ = client.scroll(
            collection_name=settings.collection_name,
            scroll_filter=_filter(window_id=window_id),
            limit=1,
            with_payload=True,
            with_vectors=include_vectors,
        )
        if not records:
            return None
        record = records[0]
        result = {"point_id": str(record.id), "payload": _safe_payload(record.payload)}
        if include_vectors:
            vectors = record.vector or {}
            result["vectors"] = {
                name: _summary(values)
                for name, values in vectors.items()
                if isinstance(values, list)
            }
        return result

    return _read_with_retries(
        settings=settings,
        operation="indexed_window",
        action=read,
    )


def list_videos(settings: Settings | None = None, limit: int = 500) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in list_windows(settings=settings, limit=limit):
        video_id = str(row["payload"].get("video_id", "unknown"))
        groups[video_id].append(row["payload"])
    return [
        {
            "video_id": video_id,
            "windows": len(rows),
            "start": min(float(row.get("start", 0)) for row in rows),
            "end": max(float(row.get("end", 0)) for row in rows),
            "source_filename": next((row.get("source_filename", "") for row in rows if row.get("source_filename")), ""),
            "media_available": any(bool(row.get("media_available")) for row in rows),
            "direct_captions": sum(bool(row.get("caption_direct")) for row in rows),
            "caption_available": sum(bool(row.get("caption_available")) for row in rows),
            "embedding_profile": next(
                (
                    str(row.get("embedding_profile"))
                    for row in rows
                    if row.get("embedding_profile")
                ),
                "self-hosted-v1",
            ),
        }
        for video_id, rows in sorted(groups.items())
    ]


def media_path_for_window(window_id: str, settings: Settings | None = None) -> Path | None:
    settings = settings or Settings.from_env()
    def read(client: QdrantClient) -> Path | None:
        if not client.collection_exists(settings.collection_name):
            return None
        ensure_window_payload_indexes(client, settings.collection_name)
        records, _ = client.scroll(
            collection_name=settings.collection_name,
            scroll_filter=_filter(window_id=window_id),
            limit=1,
            with_payload=["source_path"],
            with_vectors=False,
        )
        if not records:
            return None
        return media_path_for_source((records[0].payload or {}).get("source_path"))

    return _read_with_retries(
        settings=settings,
        operation="indexed_media",
        action=read,
    )
