"""Qdrant-backed read models for the local indexed-video UI.

The processing job manager is intentionally short lived.  This module makes
the collection the source of truth after an index run, while keeping local
filesystem paths server-side.
"""
from __future__ import annotations

import math
import os
import time
from collections import defaultdict
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from .config import Settings
from .models import VECTOR_DIMS


def _client(settings: Settings) -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.qdrant_timeout_seconds,
    )


def _health_client(settings: Settings) -> QdrantClient:
    """Use a short timeout for the UI health probe, which is safe to retry."""
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=min(settings.qdrant_timeout_seconds, 2.0),
    )


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
    client = _client(settings)
    if not client.collection_exists(settings.collection_name):
        return []
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
    return sorted(result, key=lambda row: (row["payload"].get("video_id", ""), row["payload"].get("start", 0)))


def get_window(
    window_id: str,
    *,
    settings: Settings | None = None,
    include_vectors: bool = False,
) -> dict[str, Any] | None:
    settings = settings or Settings.from_env()
    client = _client(settings)
    if not client.collection_exists(settings.collection_name):
        return None
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
    client = _client(settings)
    if not client.collection_exists(settings.collection_name):
        return None
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
