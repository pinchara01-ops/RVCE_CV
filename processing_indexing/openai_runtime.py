"""OpenAI adapter for video moment search.

Gemini accepts a video file directly.  OpenAI's chat models do not: they take
images and text.  To offer the same feature on an OpenAI model, this module
samples frames at known timestamps, sends them as images labelled with those
timestamps, and asks for the same structured result.

That difference is real and is surfaced to the caller as ``frames_sampled`` so
the UI can say how the answer was produced rather than implying the model
watched the video.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OPENAI_MODELS = {
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "o4-mini",
    "o3",
    "gpt-4.1-mini",
}

# Frames sampled per request.  More frames means finer temporal resolution and
# a proportionally larger request, so this is deliberately bounded.
MAX_FRAMES = 16
FRAME_WIDTH = 512


class OpenAIRuntimeError(RuntimeError):
    """Provider failure that is safe to show in diagnostics."""


def is_openai_model(model: str) -> bool:
    name = (model or "").strip().lower()
    return name in OPENAI_MODELS or name.startswith(("gpt-", "o3", "o4"))


@dataclass(frozen=True)
class SampledFrame:
    timestamp: float
    jpeg: bytes


def sample_frames(video: Path, duration: float | None, workspace: Path) -> list[SampledFrame]:
    """Extract evenly spaced JPEG frames with their source timestamps."""

    if duration is None or not math.isfinite(duration) or duration <= 0:
        return []

    frames_dir = workspace / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    count = min(MAX_FRAMES, max(4, int(duration // 4) or 4))
    # Offset by half a step so the first frame is not the (often black) frame 0.
    step = duration / count
    frames: list[SampledFrame] = []

    for index in range(count):
        timestamp = min(duration - 0.05, step * index + step / 2)
        target = frames_dir / f"frame_{index:03d}.jpg"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={FRAME_WIDTH}:-2",
            "-q:v",
            "4",
            str(target),
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("frame sample failed at %.2fs: %s", timestamp, exc)
            continue
        if result.returncode != 0 or not target.is_file() or not target.stat().st_size:
            continue
        frames.append(SampledFrame(timestamp=timestamp, jpeg=target.read_bytes()))

    return frames


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Add the flags OpenAI's strict json_schema mode requires."""

    if schema.get("type") == "object":
        schema = dict(schema)
        schema["additionalProperties"] = False
        properties = schema.get("properties", {})
        schema["required"] = list(properties.keys())
        schema["properties"] = {
            key: _strict_schema(value) if isinstance(value, dict) else value
            for key, value in properties.items()
        }
    elif schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        schema = dict(schema)
        schema["items"] = _strict_schema(schema["items"])
    return schema


def generate_moments(
    *,
    api_key: str,
    model: str,
    prompt: str,
    frames: list[SampledFrame],
    response_schema: dict[str, Any],
    timeout: int = 240,
) -> dict[str, Any]:
    """Send sampled frames to an OpenAI chat model and parse the JSON result."""

    if not api_key.strip():
        raise OpenAIRuntimeError("An OpenAI API key is required for this model")
    if not frames:
        raise OpenAIRuntimeError(
            "No frames could be sampled from this file, so an OpenAI model has "
            "nothing to look at. Use a Gemini model for audio-only input."
        )

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"{prompt}\n\n"
                f"You are given {len(frames)} frames sampled from the video, each "
                "labelled with its timestamp in seconds. Base every timestamp you "
                "return on those labels. You may return a range spanning several "
                "frames, but never a time outside the labelled range."
            ),
        }
    ]
    for frame in frames:
        content.append({"type": "text", "text": f"Frame at {frame.timestamp:.2f}s:"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,"
                    + base64.b64encode(frame.jpeg).decode("ascii"),
                    "detail": "low",
                },
            }
        )

    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "video_moments",
                "strict": True,
                "schema": _strict_schema(response_schema),
            },
        },
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        # The key is in the request header, not the body, so this is safe to show.
        raise OpenAIRuntimeError(f"OpenAI request failed ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenAIRuntimeError(f"Could not reach OpenAI: {exc}") from exc

    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAIRuntimeError("OpenAI response had no message content") from exc

    if not isinstance(text, str) or not text.strip():
        raise OpenAIRuntimeError("OpenAI returned an empty response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenAIRuntimeError("OpenAI response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise OpenAIRuntimeError("OpenAI JSON response must be an object")
    return parsed
