"""Single-call video indexing.

One request segments a video into consecutive windows and describes each one,
so the result can be inspected as an index without a vector database attached.

The vector fields on each window are PLACEHOLDERS: deterministic hashes of the
window text, not learned embeddings. They exist so the shape of the index is
visible in the UI. They carry no semantic meaning and must not be used for
similarity.
"""

from __future__ import annotations

import hashlib
import logging
import math
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .gemini_runtime import GeminiRuntimeError, GoogleGenAIRuntime
from .openai_runtime import (
    OpenAIRuntimeError,
    generate_moments as openai_generate_moments,
    is_openai_model,
    sample_frames,
)
from .search_prompt import SHARED_EDGE_CASES
from .quick_demo import (
    DEFAULT_MODEL,
    _CLIP_ROOT,
    _VIDEO_MIME,
    _language_clause,
    _probe_duration,
    _resolve_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick", tags=["quick"])

_INDEX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "windows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "caption": {"type": "string"},
                    "transcript": {"type": "string"},
                    "audio_events": {"type": "array", "items": {"type": "string"}},
                    "objects": {"type": "array", "items": {"type": "string"}},
                    "actions": {"type": "array", "items": {"type": "string"}},
                    "search_terms": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "start_seconds",
                    "end_seconds",
                    "caption",
                    "transcript",
                    "audio_events",
                    "objects",
                    "actions",
                    "search_terms",
                ],
            },
        },
    },
    "required": ["summary", "windows"],
}


def _index_prompt(duration: float | None) -> str:
    """Indexing prompt.

    An index is only as good as its worst window: anything not captured here can
    never be retrieved later, and anything invented here becomes a false match
    forever. The detail and edge-case sections are shared with the search prompt
    so both stages describe footage by the same standard.
    """

    length = f"{duration:.1f}" if duration else "unknown"
    return "\n".join(
        [
            "You are building a searchable index of a video. Every window you "
            "describe becomes a retrievable record. Anything you fail to note "
            "can never be found later; anything you invent becomes a permanent "
            "false match. Be exhaustive and be literal.",
            "",
            "SEGMENTATION",
            "",
            f"The video is {length} seconds long. Cover it from the first second "
            "to the last with consecutive windows of roughly 15-25 seconds. Split "
            "at natural scene, shot, or activity boundaries rather than at fixed "
            "offsets. Leave no gaps, do not overlap, and never run past the end.",
            "",
            "Blank, black, frozen, or corrupted stretches still occupy time. Keep "
            "them inside the timeline so later windows stay correctly placed, and "
            "describe them plainly as having no content rather than inventing "
            "any.",
            "",
            "WHAT TO CAPTURE PER WINDOW",
            "",
            "- caption: one specific sentence describing what is visible. Name "
            "the setting, who is present, and what is happening. Describe what "
            "you see, not what you assume.",
            "- transcript: speech actually heard in that window, verbatim, in the "
            "language spoken. Empty string if there is none. Never reconstruct "
            "speech from context or from the picture.",
            "- audio_events: non-speech sounds actually audible. Empty if the "
            "file has no audio or the window is silent.",
            "- objects: distinct objects visible, including small, peripheral, "
            "and partly occluded ones. Record colour precisely, distinguishing "
            "neighbouring shades: peach, salmon, coral, blush, rose, magenta, and "
            "hot pink are different. Where similar items appear together, name "
            "them separately rather than grouping them.",
            "- actions: activities taking place, described concretely.",
            "- search_terms: 10-20 other words and short phrases someone might "
            "plausibly type when looking for this window. Include synonyms and "
            "everyday alternatives for what you named above (laptop / computer / "
            "notebook), broader categories the things belong to (sedan / car / "
            "vehicle), the activity in other words (running / sprinting / "
            "fleeing), and the setting. Retrieval is literal word matching, so a "
            "word you omit here is a search that will not find this window. Only "
            "list terms that genuinely describe what is present.",
            "",
            SHARED_EDGE_CASES,
            "",
            "summary is one sentence about the video as a whole.",
        ]
    )


def _placeholder_vector(seed: str, dimensions: int) -> dict[str, Any]:
    """Deterministic stand-in for an embedding, flagged as such."""

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return {
        "dimensions": dimensions,
        "preview": [round((digest[i] / 255.0) * 2 - 1, 4) for i in range(6)],
        "checksum": digest.hex()[:16],
        "placeholder": True,
    }


def _strings_long(item: dict[str, Any], key: str) -> list[str]:
    """Like _strings but keeps a longer tail: these exist purely for recall."""

    value = item.get(key)
    if not isinstance(value, list):
        return []
    return [str(entry).strip() for entry in value if str(entry).strip()][:24]


def _strings(item: dict[str, Any], key: str) -> list[str]:
    value = item.get(key)
    if not isinstance(value, list):
        return []
    return [str(entry).strip() for entry in value if str(entry).strip()][:8]



def index_video_file(
    *,
    source: Path,
    duration: float | None,
    api_key: str,
    model: str,
    language: str,
    workspace: Path,
) -> dict[str, Any]:
    """Index one already-downloaded video. Shared by the upload and Drive paths."""

    prompt = _index_prompt(duration) + _language_clause(language)

    if is_openai_model(model):
        frames = sample_frames(source, duration, workspace)
        try:
            payload = openai_generate_moments(
                api_key=api_key,
                model=model,
                prompt=prompt,
                frames=frames,
                response_schema=_INDEX_SCHEMA,
            )
        except OpenAIRuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        provider, frames_sampled = "openai", len(frames)
    else:
        runtime = GoogleGenAIRuntime(api_key=api_key)
        try:
            payload, _ = runtime.generate_json(
                model=model,
                prompt=prompt,
                media_path=source,
                media_mime_type=_VIDEO_MIME.get(source.suffix.lower(), "video/mp4"),
                response_schema=_INDEX_SCHEMA,
                operation_name="quick_index",
            )
        except GeminiRuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        provider, frames_sampled = "gemini", 0

    request_id = uuid.uuid4().hex
    raw_windows = payload.get("windows")
    windows: list[dict[str, Any]] = []
    if isinstance(raw_windows, list):
        for position, item in enumerate(raw_windows):
            if not isinstance(item, dict):
                continue
            try:
                start = float(item.get("start_seconds"))
                end = float(item.get("end_seconds"))
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(start) and math.isfinite(end)) or not (end > start >= 0):
                continue
            if duration is not None:
                if start >= duration:
                    continue
                end = min(end, duration)

            caption = str(item.get("caption") or "").strip()
            transcript = str(item.get("transcript") or "").strip()
            window_id = f"{request_id[:8]}_w{position:03d}"
            windows.append(
                {
                    "window_id": window_id,
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "caption": caption,
                    "transcript": transcript,
                    "audio_events": _strings(item, "audio_events"),
                    "objects": _strings(item, "objects"),
                    "actions": _strings(item, "actions"),
                    "search_terms": _strings_long(item, "search_terms"),
                    "vectors": {
                        "visual": _placeholder_vector(window_id + caption, 512),
                        "audio_event": _placeholder_vector(window_id + "audio", 512),
                        "speech_text": _placeholder_vector(window_id + transcript, 1024),
                        "vlm_text": _placeholder_vector(window_id + "vlm", 1024),
                    },
                }
            )
    windows.sort(key=lambda entry: entry["start"])

    return {
        "request_id": request_id,
        "model": model,
        "provider": provider,
        "frames_sampled": frames_sampled,
        "duration_seconds": round(duration, 2) if duration else None,
        "summary": str(payload.get("summary") or "").strip(),
        "window_count": len(windows),
        "windows": windows,
        "vectors_are_placeholder": True,
    }


@router.post("/index")
async def quick_index(
    video: UploadFile = File(...),
    language: str = Form(""),
    api_key: str | None = Form(None),
    model: str | None = Form(None),
) -> dict[str, Any]:
    """Segment one video into indexed windows with a single model call."""

    resolved_model = (model or "").strip() or DEFAULT_MODEL
    resolved_key = _resolve_api_key(api_key, resolved_model)

    request_id = uuid.uuid4().hex
    workspace = _CLIP_ROOT / f"index_{request_id}"
    workspace.mkdir(parents=True, exist_ok=True)

    suffix = Path(video.filename or "upload.mp4").suffix.lower() or ".mp4"
    source = workspace / f"source{suffix}"
    try:
        with source.open("wb") as handle:
            shutil.copyfileobj(video.file, handle)
    finally:
        await video.close()

    if not source.stat().st_size:
        shutil.rmtree(workspace, ignore_errors=True)
        raise HTTPException(status_code=400, detail="The uploaded video was empty.")

    duration = _probe_duration(source)
    prompt = _index_prompt(duration) + _language_clause(language)

    try:
        if is_openai_model(resolved_model):
            frames = sample_frames(source, duration, workspace)
            frames_sampled = len(frames)
            provider = "openai"
            try:
                payload = openai_generate_moments(
                    api_key=resolved_key,
                    model=resolved_model,
                    prompt=prompt,
                    frames=frames,
                    response_schema=_INDEX_SCHEMA,
                )
            except OpenAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        else:
            frames_sampled = 0
            provider = "gemini"
            runtime = GoogleGenAIRuntime(api_key=resolved_key)
            try:
                payload, _ = runtime.generate_json(
                    model=resolved_model,
                    prompt=prompt,
                    media_path=source,
                    media_mime_type=_VIDEO_MIME.get(suffix, "video/mp4"),
                    response_schema=_INDEX_SCHEMA,
                    operation_name="quick_index",
                )
            except GeminiRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    raw_windows = payload.get("windows")
    windows: list[dict[str, Any]] = []
    if isinstance(raw_windows, list):
        for position, item in enumerate(raw_windows):
            if not isinstance(item, dict):
                continue
            try:
                start = float(item.get("start_seconds"))
                end = float(item.get("end_seconds"))
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(start) and math.isfinite(end)):
                continue
            if not (end > start >= 0):
                continue
            if duration is not None:
                if start >= duration:
                    continue
                end = min(end, duration)

            caption = str(item.get("caption") or "").strip()
            transcript = str(item.get("transcript") or "").strip()
            window_id = f"{request_id[:8]}_w{position:03d}"

            windows.append(
                {
                    "window_id": window_id,
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "caption": caption,
                    "transcript": transcript,
                    "audio_events": _strings(item, "audio_events"),
                    "objects": _strings(item, "objects"),
                    "actions": _strings(item, "actions"),
                    "search_terms": _strings_long(item, "search_terms"),
                    "vectors": {
                        "visual": _placeholder_vector(window_id + caption, 512),
                        "audio_event": _placeholder_vector(window_id + "audio", 512),
                        "speech_text": _placeholder_vector(window_id + transcript, 1024),
                        "vlm_text": _placeholder_vector(window_id + "vlm", 1024),
                    },
                }
            )

    windows.sort(key=lambda entry: entry["start"])

    return {
        "request_id": request_id,
        "model": resolved_model,
        "provider": provider,
        "frames_sampled": frames_sampled,
        "duration_seconds": round(duration, 2) if duration else None,
        "summary": str(payload.get("summary") or "").strip(),
        "window_count": len(windows),
        "windows": windows,
        "vectors_are_placeholder": True,
    }
