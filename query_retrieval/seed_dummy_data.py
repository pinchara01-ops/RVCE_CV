"""Insert realistic fake points into Qdrant for standalone Phase 1 testing.

Covers: visual-only windows, audio-only windows, overlapping-in-time
windows across two videos representing the same event across modalities,
and fully disjoint windows. Run directly: `python -m query_retrieval.seed_dummy_data`.
"""
import logging
import random
import uuid

from qdrant_client.models import PointStruct

from query_retrieval import config
from query_retrieval.qdrant_client import connect_qdrant, create_collection

logger = logging.getLogger(__name__)


def _vec(dim: int) -> list[float]:
    return [random.uniform(-1, 1) for _ in range(dim)]


def _window_id(video_id: str, index: int) -> str:
    return f"{video_id}_window_{index:04d}"


def _point(
    video_id: str,
    index: int,
    start: float,
    end: float,
    vectors: dict[str, list[float]],
    transcript: str = "",
    caption: str = "",
    has_audio: bool = False,
    vlm_processed: bool = False,
) -> PointStruct:
    window_id = _window_id(video_id, index)
    payload = {
        "video_id": video_id,
        "window_id": window_id,
        "start": start,
        "end": end,
        "transcript": transcript,
        "caption": caption,
        "has_audio": has_audio,
        "vlm_processed": vlm_processed,
    }
    return PointStruct(id=str(uuid.uuid4()), vector=vectors, payload=payload)


def build_points() -> list[PointStruct]:
    dims = {name: cfg["dim"] for name, cfg in config.VECTOR_CONFIG.items()}
    points: list[PointStruct] = []

    # video_a: visual-only windows (no audio track at all)
    for i in range(3):
        start = i * 5.0
        points.append(
            _point(
                "video_a", i, start, start + 5.0,
                vectors={"visual": _vec(dims["visual"]), "caption": _vec(dims["caption"])},
                caption=f"A person walks across frame {i}",
                has_audio=False,
                vlm_processed=True,
            )
        )

    # video_b: audio-only windows (e.g. voiceover-only segment, no frames indexed)
    for i in range(3):
        start = i * 5.0
        points.append(
            _point(
                "video_b", i, start, start + 5.0,
                vectors={"audio": _vec(dims["audio"]), "speech": _vec(dims["speech"])},
                transcript=f"Speaker discusses topic {i}",
                has_audio=True,
            )
        )

    # video_c: overlapping-in-time windows across modalities describing the
    # same event (e.g. a dog barking is captured in visual, audio, speech, caption)
    overlap_start, overlap_end = 10.0, 15.0
    points.append(
        _point(
            "video_c", 2, overlap_start, overlap_end,
            vectors={
                "visual": _vec(dims["visual"]),
                "audio": _vec(dims["audio"]),
                "speech": _vec(dims["speech"]),
                "caption": _vec(dims["caption"]),
            },
            transcript="A dog barks loudly",
            caption="A dog is barking near a fence",
            has_audio=True,
            vlm_processed=True,
        )
    )

    # video_d: fully disjoint windows, no shared time or event with others
    for i in range(4):
        start = i * 20.0
        points.append(
            _point(
                "video_d", i, start, start + 20.0,
                vectors={
                    "visual": _vec(dims["visual"]),
                    "caption": _vec(dims["caption"]),
                },
                caption=f"Static landscape shot {i}",
                has_audio=False,
                vlm_processed=True,
            )
        )

    return points


def seed() -> None:
    client = connect_qdrant()
    create_collection(client)
    points = build_points()
    client.upsert(collection_name=config.COLLECTION_NAME, points=points)
    logger.info("Seeded %d dummy points into '%s'", len(points), config.COLLECTION_NAME)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()
