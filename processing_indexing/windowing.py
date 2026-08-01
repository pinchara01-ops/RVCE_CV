from __future__ import annotations
from .models import TranscriptSegment, VideoWindow


def generate_windows(
    video_id: str,
    duration: float,
    window_seconds: float = 10.0,
    stride_seconds: float = 5.0,
) -> list[VideoWindow]:
    if min(duration, window_seconds, stride_seconds) <= 0:
        raise ValueError("duration, window size, and stride must be positive")
    result, index = [], 0
    while (start := index * stride_seconds) < duration:
        end = min(start + window_seconds, duration)
        result.append(
            VideoWindow(
                video_id=video_id,
                window_id=f"{video_id}_window_{index:04d}",
                index=index,
                start=start,
                end=end,
            )
        )
        if end >= duration:
            break
        index += 1
    return result


def transcript_for_window(
    segments: list[TranscriptSegment], start: float, end: float
) -> str:
    return " ".join(
        s.text.strip()
        for s in segments
        if s.start < end and s.end > start and s.text.strip()
    )
