"""Qdrant connection, collection setup, and per-modality search functions.

Every search_* function returns a normalized list of dicts:
    {"window_id": str, "score": float, "payload": dict}
for the common cases: a genuinely empty/missing collection, or a structured
"bad response" from a live server (e.g. querying a collection that was
never created) — both logged and returned as [], so downstream fusion code
stays simple and a not-yet-indexed collection isn't treated as an outage.

A real connection-level failure (Qdrant unreachable: connection refused,
DNS failure, timeout) is a different situation — the server isn't there to
give any response, structured or otherwise — and is NOT swallowed: it's
raised as QdrantSearchError so api.py can return a clear 503 instead of a
misleading empty result set that looks identical to "no matches".
"""
import logging

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Distance, VectorParams

from query_retrieval import config

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None


class QdrantSearchError(Exception):
    """Raised when a Qdrant search genuinely fails to reach/complete against
    the server (connection refused, timeout, DNS failure) — as opposed to a
    structured response indicating zero hits or a missing collection, which
    stays a normal empty list."""


def connect_qdrant() -> QdrantClient:
    """Return a cached Qdrant client, creating it on first call."""
    global _client
    if _client is None:
        _client = QdrantClient(
            url=config.QDRANT_URL,
            api_key=config.QDRANT_API_KEY,
            timeout=config.QDRANT_TIMEOUT_SECONDS,
        )
    return _client


def create_collection(client: QdrantClient | None = None) -> None:
    """Create the video_windows collection with named vectors. Idempotent."""
    client = client or connect_qdrant()

    if client.collection_exists(config.COLLECTION_NAME):
        logger.info("Collection %s already exists, skipping creation", config.COLLECTION_NAME)
        return

    vectors_config = {
        name: VectorParams(size=cfg["dim"], distance=Distance[cfg["distance"].upper()])
        for name, cfg in config.VECTOR_CONFIG.items()
    }
    client.create_collection(
        collection_name=config.COLLECTION_NAME,
        vectors_config=vectors_config,
    )
    logger.info("Created collection %s", config.COLLECTION_NAME)


def _search(vector_name: str, vector: list[float], top_k: int) -> list[dict]:
    """Shared search implementation for a single named vector."""
    client = connect_qdrant()
    try:
        hits = client.query_points(
            collection_name=config.COLLECTION_NAME,
            using=vector_name,
            query=vector,
            limit=top_k,
            with_payload=True,
        ).points
    except UnexpectedResponse as exc:
        # A structured HTTP response from a live server (e.g. 404 on a
        # collection that hasn't been created yet) - Qdrant is reachable,
        # there's just nothing to find. Treated as a normal empty result.
        logger.warning("Qdrant search on '%s' failed (bad response): %s", vector_name, exc)
        return []
    except Exception as exc:  # noqa: BLE001 - genuine connection failure, not a bad response
        logger.warning("Qdrant search on '%s' failed (unreachable): %s", vector_name, exc)
        raise QdrantSearchError(f"Qdrant search on '{vector_name}' failed: {exc}") from exc

    if not hits:
        logger.warning("Qdrant search on '%s' returned no results", vector_name)
        return []

    return [
        {"window_id": hit.payload.get("window_id") if hit.payload else None,
         "score": hit.score,
         "payload": hit.payload or {}}
        for hit in hits
    ]


def validate_collection_schema(client: QdrantClient | None = None) -> list[str]:
    """Compare the live Qdrant collection against the config.VECTOR_CONFIG
    contract (vector names, dims, distance metric).

    Returns a list of human-readable mismatch descriptions; an empty list
    means the schema matches. Point this at a teammate's real collection
    once it exists to catch drift (renamed vector, wrong dim, wrong
    distance) at integration time instead of mid-demo. Never raises -
    a connection or missing-collection failure is itself reported as an
    issue string, not an exception.
    """
    client = client or connect_qdrant()
    issues: list[str] = []

    try:
        if not client.collection_exists(config.COLLECTION_NAME):
            return [f"collection '{config.COLLECTION_NAME}' does not exist"]
        info = client.get_collection(config.COLLECTION_NAME)
    except Exception as exc:  # noqa: BLE001 - report connection failure as a finding, not a crash
        return [f"could not fetch collection info: {exc}"]

    live_vectors = info.config.params.vectors
    if not isinstance(live_vectors, dict):
        return [
            "collection has an unnamed single vector, expected named vectors: "
            + ", ".join(config.VECTOR_NAMES)
        ]

    for name, expected in config.VECTOR_CONFIG.items():
        live = live_vectors.get(name)
        if live is None:
            issues.append(f"missing expected vector '{name}'")
            continue
        if live.size != expected["dim"]:
            issues.append(f"vector '{name}' dim mismatch: expected {expected['dim']}, got {live.size}")
        live_distance = getattr(live.distance, "value", str(live.distance))
        if live_distance.lower() != str(expected["distance"]).lower():
            issues.append(
                f"vector '{name}' distance mismatch: expected {expected['distance']}, got {live_distance}"
            )

    for name in live_vectors:
        if name not in config.VECTOR_CONFIG:
            issues.append(f"unexpected extra vector '{name}' present in collection (not in contract)")

    return issues


def search_visual(vector: list[float], top_k: int = config.DEFAULT_TOP_K) -> list[dict]:
    return _search("visual", vector, top_k)


def search_audio(vector: list[float], top_k: int = config.DEFAULT_TOP_K) -> list[dict]:
    return _search("audio", vector, top_k)


def search_speech(vector: list[float], top_k: int = config.DEFAULT_TOP_K) -> list[dict]:
    return _search("speech", vector, top_k)


def search_caption(vector: list[float], top_k: int = config.DEFAULT_TOP_K) -> list[dict]:
    # Fetch additional candidates before filtering so unavailable captions do
    # not make an otherwise populated collection appear empty.  Pre-merge
    # development points did not carry caption_available, which is treated as
    # available for backwards compatibility.
    candidates = _search("caption", vector, top_k * 3)
    return [
        hit
        for hit in candidates
        if (hit.get("payload") or {}).get("caption_available", True)
    ][:top_k]
