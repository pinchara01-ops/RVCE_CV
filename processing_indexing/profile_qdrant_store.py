"""Profile-aware Qdrant persistence for API-based embedding runs.

The original :mod:`qdrant_store` intentionally enforces the local model
contract (512-D X-CLIP/CLAP and 1024-D BGE-M3).  This module keeps that
contract intact while allowing a second collection whose named-vector schema
is defined by an immutable embedding profile.

It deliberately knows nothing about Gemini or any other embedding provider.
Callers hand it validated, already-generated vectors and a payload.  That
makes a cloud collection testable with a small fake Qdrant client and prevents
one provider's dimensions from leaking into the self-hosted pipeline.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .qdrant_store import deterministic_point_id


class ProfileCollectionSchemaError(RuntimeError):
    """Raised when a cloud collection differs from its embedding profile."""


class ProfileVectorValidationError(ValueError):
    """Raised before an invalid cloud point is sent to Qdrant."""


@dataclass(frozen=True)
class NamedVectorSchema:
    """One named vector in a versioned embedding profile."""

    name: str
    dimensions: int
    distance: str = "cosine"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Named vector schema requires a name")
        if self.dimensions < 1:
            raise ValueError("Named vector dimensions must be positive")
        if self.distance.lower() != "cosine":
            raise ValueError("Only cosine distance is supported by the current profiles")


@dataclass(frozen=True)
class ProfileWindowRecord:
    """One upsert-ready point for a profile-specific Qdrant collection."""

    payload: Mapping[str, Any]
    vectors: Mapping[str, Sequence[float]]

    @property
    def window_id(self) -> str:
        value = self.payload.get("window_id")
        if not isinstance(value, str) or not value:
            raise ProfileVectorValidationError("Profile record payload requires window_id")
        return value


class ProfiledQdrantStore:
    """Persist profile-specific named vectors without changing local storage.

    Qdrant accepts points which omit an optional named vector, so silent-video
    windows can intentionally omit ``audio`` rather than storing a misleading
    zero vector.  ``visual`` is the only required field for the API profiles.
    """

    def __init__(
        self,
        client: Any,
        *,
        collection_name: str,
        vector_schema: Iterable[NamedVectorSchema],
        required_vectors: Iterable[str] = ("visual",),
        batch_size: int = 8,
        retries: int = 2,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.schema = {entry.name: entry for entry in vector_schema}
        self.required_vectors = frozenset(required_vectors)
        self.batch_size = int(batch_size)
        self.retries = int(retries)
        if not self.collection_name.strip():
            raise ValueError("Collection name must not be empty")
        if not self.schema:
            raise ValueError("At least one named vector is required")
        if not self.required_vectors.issubset(self.schema):
            unknown = sorted(self.required_vectors - set(self.schema))
            raise ValueError(f"Required vectors are not in schema: {unknown}")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.retries < 0:
            raise ValueError("retries must be non-negative")

    def ensure_collection(self) -> None:
        """Create or validate the complete named-vector profile contract."""
        from qdrant_client.models import Distance, VectorParams

        expected = {
            name: VectorParams(size=entry.dimensions, distance=Distance.COSINE)
            for name, entry in self.schema.items()
        }
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=expected,
            )
            return

        live = self.client.get_collection(self.collection_name).config.params.vectors
        errors: list[str] = []
        if not isinstance(live, dict):
            errors.append("collection has an unnamed vector, expected named vectors")
        else:
            if set(live) != set(expected):
                errors.append(
                    "vector names: expected "
                    f"{sorted(expected)}, got {sorted(live)}"
                )
            for name, entry in self.schema.items():
                current = live.get(name)
                if current is None:
                    continue
                if int(current.size) != entry.dimensions:
                    errors.append(
                        f"{name} dimensions: expected {entry.dimensions}, got {current.size}"
                    )
                actual_distance = str(current.distance).lower().split(".")[-1]
                if actual_distance != entry.distance.lower():
                    errors.append(
                        f"{name} distance: expected {entry.distance}, got {actual_distance}"
                    )
        if errors:
            raise ProfileCollectionSchemaError("; ".join(errors))

    def _validate_record(self, record: ProfileWindowRecord) -> dict[str, list[float]]:
        vectors = {name: list(values) for name, values in record.vectors.items()}
        missing = self.required_vectors - set(vectors)
        if missing:
            raise ProfileVectorValidationError(
                f"{record.window_id} is missing required vectors: {sorted(missing)}"
            )
        unexpected = set(vectors) - set(self.schema)
        if unexpected:
            raise ProfileVectorValidationError(
                f"{record.window_id} contains unknown vectors: {sorted(unexpected)}"
            )
        for name, vector in vectors.items():
            expected = self.schema[name].dimensions
            if len(vector) != expected:
                raise ProfileVectorValidationError(
                    f"{record.window_id} {name} dimensions: expected {expected}, got {len(vector)}"
                )
            if not all(isinstance(value, (int, float)) for value in vector):
                raise ProfileVectorValidationError(
                    f"{record.window_id} {name} contains non-numeric values"
                )
        return vectors

    def upsert(self, records: Sequence[ProfileWindowRecord]) -> None:
        """Write records in bounded retryable batches."""
        from qdrant_client.models import PointStruct

        for offset in range(0, len(records), self.batch_size):
            batch = records[offset : offset + self.batch_size]
            points = [
                PointStruct(
                    id=deterministic_point_id(record.window_id),
                    vector=self._validate_record(record),
                    payload=dict(record.payload),
                )
                for record in batch
            ]
            for attempt in range(self.retries + 1):
                try:
                    self.client.upsert(
                        collection_name=self.collection_name,
                        points=points,
                        wait=True,
                    )
                    break
                except Exception:
                    if attempt >= self.retries:
                        raise
                    time.sleep(2**attempt)

    def existing_window_ids(self, video_id: str) -> set[str]:
        """Return profile-specific window IDs already stored for one video."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        records, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="video_id", match=MatchValue(value=video_id))]
            ),
            limit=10_000,
            with_payload=["window_id"],
            with_vectors=False,
        )
        return {
            str((record.payload or {}).get("window_id"))
            for record in records
            if (record.payload or {}).get("window_id")
        }
