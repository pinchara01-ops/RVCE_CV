"""Chunked scanning for long videos.

A model given a long video estimates elapsed time from sampled frames, and that
estimate drifts: on an 8-minute file it identified the right event but placed it
at 3:20 when it actually occurs at 6:54, so the clip cut from that timestamp
showed the wrong footage entirely.

Clamping to the real duration cannot fix this, because the wrong timestamp is
still inside the file. The fix is to stop asking the model to track long
elapsed time at all: cut the video into short chunks whose offsets we know
exactly, ask about each chunk independently, then add the offset back in
arithmetic rather than trusting the model's own clock.

Chunks are re-encoded rather than stream-copied. Stream copy snaps to the
nearest keyframe, which would reintroduce exactly the timestamp error this
module exists to remove.
"""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Below this, a single pass is accurate enough and cheaper.
CHUNK_THRESHOLD_SECONDS = 150.0
CHUNK_SECONDS = 120.0
# Overlap so an event straddling a boundary is whole in at least one chunk.
CHUNK_OVERLAP_SECONDS = 5.0
MAX_CHUNKS = 12
CHUNK_WIDTH = 640
MAX_PARALLEL_CHUNKS = 3


@dataclass(frozen=True)
class Chunk:
    path: Path
    offset_seconds: float
    duration_seconds: float


def should_chunk(duration: float | None) -> bool:
    return duration is not None and duration > CHUNK_THRESHOLD_SECONDS


def _encode_chunk(source: Path, start: float, length: float, target: Path) -> bool:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{length:.3f}",
        "-vf",
        f"scale={CHUNK_WIDTH}:-2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("chunk encode failed at %.1fs: %s", start, exc)
        return False
    if result.returncode != 0:
        logger.warning(
            "chunk ffmpeg exit %s at %.1fs: %s",
            result.returncode,
            start,
            result.stderr.decode("utf-8", "replace")[:300],
        )
        return False
    return target.is_file() and target.stat().st_size > 0


def split_into_chunks(source: Path, duration: float, workspace: Path) -> list[Chunk]:
    """Cut a long video into overlapping chunks with known exact offsets."""

    chunks_dir = workspace / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    step = CHUNK_SECONDS - CHUNK_OVERLAP_SECONDS
    starts: list[float] = []
    position = 0.0
    while position < duration and len(starts) < MAX_CHUNKS:
        starts.append(position)
        position += step

    # A very long file would exceed MAX_CHUNKS; widen the step so the whole
    # video is still covered rather than silently truncating it.
    if position < duration and starts:
        step = duration / MAX_CHUNKS
        starts = [index * step for index in range(MAX_CHUNKS)]

    planned: list[tuple[float, float, Path]] = []
    for index, start in enumerate(starts):
        length = min(CHUNK_SECONDS, duration - start)
        if length <= 1.0:
            continue
        planned.append((start, length, chunks_dir / f"chunk_{index:03d}.mp4"))

    def encode(item: tuple[float, float, Path]) -> Chunk | None:
        start, length, target = item
        if not _encode_chunk(source, start, length, target):
            return None
        return Chunk(path=target, offset_seconds=start, duration_seconds=length)

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHUNKS) as pool:
        results = list(pool.map(encode, planned))

    chunks = [chunk for chunk in results if chunk is not None]
    logger.info("split %.1fs video into %d chunks", duration, len(chunks))
    return chunks
