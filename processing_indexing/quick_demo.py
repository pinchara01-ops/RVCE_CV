"""Single-call video moment search.

One request: a video plus a natural-language query goes to Gemini Flash-Lite,
which returns structured time ranges with descriptions.  Each returned range is
cut locally with ffmpeg and served back as a playable clip.

This path is deliberately independent of the indexing/Qdrant pipeline: it holds
no state, writes nothing to a vector store, and keeps no credential after the
request completes.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from .gemini_runtime import (
    GeminiRuntimeError,
    GoogleGenAIRuntime,
)
from .openai_runtime import (
    OpenAIRuntimeError,
    generate_moments as openai_generate_moments,
    is_openai_model,
    sample_frames,
)
from .search_prompt import build_search_prompt
from .public_demo import (
    PaidOperation,
    PublicDemoError,
    PublicSampleCatalog,
    SampleNotFound,
    public_launch_enabled,
    reserve_paid_operation,
)
from .chunking import (
    CHUNK_SECONDS,
    MAX_PARALLEL_CHUNKS,
    Chunk,
    should_chunk,
    split_into_chunks,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick", tags=["quick"])

DEFAULT_MODEL = os.environ.get("QUICK_DEMO_MODEL", "gemini-3.1-flash-lite")

# Top sections returned per search. Asked for in the prompt and enforced below,
# so a model that ignores the instruction still cannot exceed it.
MAX_MOMENTS = 4

# Longest single returned section. Anything longer is a region, not a moment.
MAX_SECTION_SECONDS = 30.0
MAX_QUERY_CHARACTERS = int(os.environ.get("PUBLIC_DEMO_MAX_QUERY_CHARACTERS", "1000"))
PUBLIC_VIDEO_BYTES = int(os.environ.get("PUBLIC_DEMO_MAX_VIDEO_BYTES", str(100 * 1024 * 1024)))
PUBLIC_IMAGE_BYTES = int(os.environ.get("PUBLIC_DEMO_MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
PUBLIC_AUDIO_BYTES = int(os.environ.get("PUBLIC_DEMO_MAX_AUDIO_BYTES", str(10 * 1024 * 1024)))
PUBLIC_REFERENCE_BYTES = int(
    os.environ.get("PUBLIC_DEMO_MAX_REFERENCE_BYTES", str(25 * 1024 * 1024))
)

# Clips live for the life of the backend process and are cleaned up on restart.
_CLIP_ROOT = Path(tempfile.gettempdir()) / "rvce_quick_demo"

_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".qt": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".m4v": "video/mp4",
}


def _copy_limited(upload: UploadFile, destination: Path, limit: int) -> None:
    written = 0
    with destination.open("wb") as handle:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="The selected file is too large.")
            handle.write(chunk)


def _valid_video_signature(path: Path) -> bool:
    with path.open("rb") as source:
        header = source.read(16)
    return (
        len(header) >= 12 and header[4:8] == b"ftyp"
        or header.startswith(b"\x1aE\xdf\xa3")
        or header.startswith(b"RIFF") and header[8:12] == b"AVI "
    )


def _provider_error_detail(exc: Exception) -> str:
    if public_launch_enabled():
        return "The live search provider is temporarily unavailable. Please try again."
    return str(exc)

_MOMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "description": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "start_seconds",
                    "end_seconds",
                    "description",
                    "confidence",
                ],
            },
        },
    },
    "required": ["summary", "moments"],
}


def _probe_duration(path: Path) -> float | None:
    """Return a video's duration in seconds, or None if it cannot be read."""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("duration probe failed: %s", exc)
        return None
    if result.returncode != 0:
        return None
    try:
        duration = float(result.stdout.decode("utf-8", "replace").strip())
    except ValueError:
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def _duration_clause(duration: float | None) -> str:
    """Tell the model how long the video is, in its own words.

    Without this a model will happily return a range past the end of the file,
    because nothing in the request establishes an upper bound.
    """

    if duration is None:
        return ""
    return (
        f"\n\nThis video is exactly {duration:.1f} seconds long. Every timestamp "
        f"you return must fall inside 0 to {duration:.1f} seconds. Never return a "
        "start or end beyond the end of the video."
    )


def _language_clause(language: str) -> str:
    """Ask for user-visible text in the chosen language, without touching data."""

    if not language or language.strip().lower() in {"", "english", "auto"}:
        return ""
    name = language.strip()
    return (
        f"\n\nOUTPUT LANGUAGE\n\n"
        f"The user is working in {name}. Write EVERY piece of human-readable "
        f"text you return, the summary and every description, in {name}, using "
        f"{name}'s own script rather than a transliteration into Latin letters.\n"
        f"- This applies regardless of what language is spoken in the video or "
        f"in the audio request. A request spoken in one language and answered "
        f"for a user reading {name} is still answered in {name}.\n"
        f"- When quoting speech heard in the video, give the quote in its "
        f"original language, then describe it in {name}.\n"
        f"- Proper nouns, brand names, and on-screen text keep their original "
        f"form. Numbers and timestamps stay as digits.\n"
        f"- Describe things the way a {name} speaker would name them, rather "
        f"than translating English phrasing word for word."
    )


def _multimodal_prompt(
    *, query: str, spoken: bool, image_count: int, reference_clip: bool
) -> str:
    """Build a prompt describing exactly which attachments were supplied.

    Attachments are listed in the same order they are appended to the request,
    so the model can tell the footage being searched apart from the reference
    material describing what to look for.
    """

    lines = [
        "You are locating moments in a video that match a user's request.",
        "",
        "Attached files, in order:",
        "1. The video to search. Every timestamp you return refers to this file.",
    ]
    position = 2
    if spoken:
        lines.append(
            f"{position}. An audio recording of the user speaking their request. "
            "Listen to it directly and act on what was asked. Do not merely "
            "transcribe it."
        )
        position += 1
    for _ in range(image_count):
        lines.append(
            f"{position}. A reference image showing a person, object, or scene "
            "the user wants found in the video. Match on appearance, not on the "
            "image's own background."
        )
        position += 1
    if reference_clip:
        lines.append(
            f"{position}. A short reference clip. Find moments in the search "
            "video that resemble what happens in this clip."
        )
        position += 1

    lines.append("")
    if query.strip():
        lines.append(f'The user also typed: "{query.strip()}"')
        lines.append("")
    if spoken or image_count or reference_clip:
        lines.append(
            "Treat the attachments and any typed text as one combined request; "
            "they describe the same target, not separate searches."
        )
        lines.append("")

    lines.extend(
        [
            "Interpret the request generously: consider synonyms, related actions, "
            "and visually similar events. The request may be in any language.",
            "",
            "Return every matching moment as structured JSON.",
            "",
            "Rules:",
            "- start_seconds and end_seconds are measured from the start of the "
            "search video (file 1).",
            "- Keep each moment tight: prefer 2-10 seconds around the actual event.",
            "- description is one short sentence describing what is visible in that "
            "moment, grounded only in what the video actually shows.",
            "- confidence is 0.0-1.0 for how well the moment matches the request.",
            f"- Return the {MAX_MOMENTS} best matching sections of the video, "
            "ordered by confidence, highest first. Cover distinct parts of the "
            "video rather than several overlapping ranges around one event.",
            f"- If fewer than {MAX_MOMENTS} sections genuinely match, return only "
            "those that do. Do not pad the list with weak matches.",
            "- If nothing matches, return an empty moments array and say so in "
            "summary. Do not invent a moment.",
            "- summary is one sentence: restate what was asked for, then say what "
            "you found.",
        ]
    )
    return "\n".join(lines)


def _prompt(query: str) -> str:
    return (
        "You are locating moments in a video that match a user's request.\n\n"
        f'User request: "{query}"\n\n'
        "First interpret the request generously: consider synonyms, related "
        "actions, and visually similar events, so a loosely worded request still "
        "finds the right moment. Then watch the video and return every matching "
        "moment as structured JSON.\n\n"
        "Rules:\n"
        "- start_seconds and end_seconds are measured from the start of the video.\n"
        "- Keep each moment tight: prefer 2-10 seconds around the actual event.\n"
        "- description is one short sentence describing what is visible in that "
        "moment, grounded only in what the video actually shows.\n"
        "- confidence is 0.0-1.0 for how well the moment matches the request.\n"
        f"- Return the {MAX_MOMENTS} best matching sections of the video, ordered "
        "by confidence, highest first. Cover distinct parts of the video rather "
        "than several overlapping ranges around one event.\n"
        f"- If fewer than {MAX_MOMENTS} sections genuinely match, return only "
        "those that do. Do not pad the list with weak matches.\n"
        "- If nothing in the video matches, return an empty moments array and say "
        "so in summary. Do not invent a moment.\n"
        "- summary is one sentence describing what you found overall."
    )


def _resolve_api_key(supplied: str | None, model: str = "") -> str:
    """Find a key for whichever provider the selected model belongs to."""

    if is_openai_model(model):
        key = (supplied or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No OpenAI API key available. Enter one in Developer settings, "
                    "or set OPENAI_API_KEY in the backend environment."
                ),
            )
        return key

    key = (supplied or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail=(
                "No Gemini API key available. Enter one in Developer settings, or "
                "set GEMINI_API_KEY in the backend environment."
            ),
        )
    return key


def _cut_clip(source: Path, start: float, end: float, destination: Path) -> bool:
    """Re-encode one segment. Returns False if ffmpeg produced no usable file."""

    duration = max(0.5, end - start)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        # Seeking before -i keeps this fast; re-encoding keeps it frame-accurate.
        "-ss",
        f"{max(0.0, start):.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("quick demo clip cut failed: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning(
            "quick demo ffmpeg exit %s: %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace")[:400],
        )
        return False
    return destination.is_file() and destination.stat().st_size > 0


def _coerce_moments(payload: dict[str, Any], duration: float | None) -> list[dict[str, Any]]:
    """Validate the model's ranges against the real video length.

    A model can return a range that runs past the end of the file, or is
    entirely beyond it.  Trailing overhang is clamped so the moment still
    plays; a moment that starts after the video ends is dropped, because there
    is no footage there to show.
    """

    raw = payload.get("moments")
    if not isinstance(raw, list):
        return []
    moments: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start_seconds"))
            end = float(item.get("end_seconds"))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        if not (start >= 0 and end > start):
            continue
        if duration is not None:
            if start >= duration:
                # Wholly past the end of the file; there is nothing to clip.
                logger.info("dropped moment starting at %.2fs past %.2fs duration", start, duration)
                continue
            if end > duration:
                logger.info("clamped moment end %.2fs to %.2fs duration", end, duration)
                end = duration
            if end - start < 0.3:
                continue
        # A section spanning minutes is not a located moment, it is the model
        # giving up and returning a region. Keep the opening of it, which is
        # where the event it described actually begins.
        if end - start > MAX_SECTION_SECONDS:
            logger.info("trimmed %.1fs section at %.1fs to %.0fs", end - start, start, MAX_SECTION_SECONDS)
            end = start + MAX_SECTION_SECONDS
        description = str(item.get("description") or "").strip()
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        moments.append(
            {
                "start": round(start, 2),
                "end": round(end, 2),
                "description": description,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )

    # Keep the strongest sections, and present them in playback order so the
    # results read as a walk through the video rather than a score ranking.
    moments.sort(key=lambda item: item["confidence"], reverse=True)
    top = moments[:MAX_MOMENTS]
    top.sort(key=lambda item: item["start"])
    return top


_SPOKEN_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "language": {"type": "string"},
    },
    "required": ["query", "language"],
}

_SPOKEN_QUERY_PROMPT = (
    "This audio is a person describing a moment they want to find in a video.\n\n"
    "Write down what they asked for, as a search query, in their own words.\n\n"
    "Rules:\n"
    "- Transcribe what was actually said. Do not answer the request or add detail.\n"
    "- Keep the speaker's original language. Do not translate.\n"
    "- language is the spoken language in English (for example: English, Hindi, "
    "Kannada).\n"
    "- If the audio contains no intelligible speech, return an empty query string."
)


def _transcode_to_mp3(source: Path, destination: Path) -> bool:
    """Convert recorded audio to MP3, which the provider accepts everywhere."""

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        str(destination),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("spoken query transcode failed: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning(
            "spoken query ffmpeg exit %s: %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace")[:400],
        )
        return False
    return destination.is_file() and destination.stat().st_size > 0


@router.post("/voice-query")
async def quick_voice_query(
    request: Request,
    response: Response,
    audio: UploadFile = File(...),
    api_key: str | None = Form(None),
    model: str | None = Form(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """Turn a spoken request into the search text, using the multimodal model."""

    resolved_model = (model or "").strip() or DEFAULT_MODEL
    workspace = _CLIP_ROOT / f"voice_{uuid.uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        suffix = Path(audio.filename or "clip.webm").suffix.lower() or ".webm"
        source = workspace / f"speech{suffix}"
        try:
            _copy_limited(
                audio,
                source,
                PUBLIC_AUDIO_BYTES if public_launch_enabled() else 100 * 1024 * 1024,
            )
        finally:
            await audio.close()

        if not source.stat().st_size:
            raise HTTPException(status_code=400, detail="The recording was empty.")

        # Browsers record WebM/Opus, which is not a format the provider accepts
        # for every model, so normalise to MP3 first.
        send_path, send_mime = source, "audio/mpeg"
        if suffix != ".mp3":
            converted = workspace / "speech.mp3"
            if not _transcode_to_mp3(source, converted):
                raise HTTPException(
                    status_code=400,
                    detail="The recording could not be processed. Try recording again.",
                )
            send_path = converted

        resolved_key = _resolve_api_key(None if public_launch_enabled() else api_key, resolved_model)
        paid = reserve_paid_operation(request, response, idempotency_key)
        if isinstance(paid, dict):
            return paid
        runtime = GoogleGenAIRuntime(api_key=resolved_key)
        try:
            payload, _ = runtime.generate_json(
                model=resolved_model,
                prompt=_SPOKEN_QUERY_PROMPT,
                media_path=send_path,
                media_mime_type=send_mime,
                response_schema=_SPOKEN_QUERY_SCHEMA,
                operation_name="voice_query",
            )
        except GeminiRuntimeError as exc:
            raise HTTPException(status_code=502, detail=_provider_error_detail(exc)) from exc

        result = {
            "query": str(payload.get("query") or "").strip(),
            "language": str(payload.get("language") or "").strip(),
            "model": resolved_model,
        }
        return paid.complete(result) if isinstance(paid, PaidOperation) else result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@router.post("/search")
async def quick_search(
    request: Request,
    response: Response,
    video: UploadFile | None = File(None),
    sample_id: str | None = Form(None),
    query: str = Form(""),
    audio: UploadFile | None = File(None),
    images: list[UploadFile] = File(default=[]),
    reference: UploadFile | None = File(None),
    language: str = Form(""),
    api_key: str | None = Form(None),
    model: str | None = Form(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """Upload a video and a request; get back playable clips of matching moments.

    The request is either typed text or a spoken recording.  A recording is sent
    to the model as audio alongside the video, so the model hears it natively;
    there is no speech-to-text stage in front of it.
    """

    normalized_query = (query or "").strip()
    if len(normalized_query) > MAX_QUERY_CHARACTERS:
        raise HTTPException(status_code=400, detail="The search query is too long.")
    spoken = audio is not None and bool(getattr(audio, "filename", ""))
    has_images = any(getattr(item, "filename", "") for item in (images or []))
    has_reference = reference is not None and bool(getattr(reference, "filename", ""))
    if not normalized_query and not spoken and not has_images and not has_reference:
        raise HTTPException(
            status_code=400,
            detail="Type, speak, or attach something describing what you want to find.",
        )

    # Resolve the model first: it decides which provider's key is needed.
    resolved_model = (model or "").strip() or DEFAULT_MODEL

    request_id = uuid.uuid4().hex
    workspace = _CLIP_ROOT / request_id
    workspace.mkdir(parents=True, exist_ok=True)

    public_sample: Path | None = None
    if public_launch_enabled():
        try:
            public_sample = PublicSampleCatalog.from_environment().resolve((sample_id or "").strip())
        except SampleNotFound as exc:
            raise PublicDemoError(404, "SAMPLE_NOT_FOUND", "That sample is not available.") from exc
    elif video is None:
        raise HTTPException(status_code=400, detail="Select a video to search.")

    upload_name = public_sample.name if public_sample else ((video.filename if video else "") or "upload.mp4")
    suffix = Path(upload_name).suffix.lower() or ".mp4"
    source = workspace / f"source{suffix}"
    if public_sample:
        if public_sample.stat().st_size > PUBLIC_VIDEO_BYTES:
            shutil.rmtree(workspace, ignore_errors=True)
            raise PublicDemoError(413, "FILE_TOO_LARGE", "That sample is temporarily unavailable.")
        shutil.copyfile(public_sample, source)
    elif video is not None:
        try:
            _copy_limited(video, source, 700 * 1024 * 1024)
        finally:
            await video.close()

    if not source.stat().st_size:
        shutil.rmtree(workspace, ignore_errors=True)
        raise HTTPException(status_code=400, detail="The uploaded video was empty.")
    if not _valid_video_signature(source):
        shutil.rmtree(workspace, ignore_errors=True)
        raise HTTPException(status_code=415, detail="The selected file is not a supported video.")

    mime_type = _VIDEO_MIME.get(suffix, "video/mp4")

    # A spoken request travels with the video as a second file, so the model
    # receives the audio itself rather than text produced from it.
    extra_media: list[tuple[Path, str]] = []
    spoken_used = False
    if spoken and audio is not None:
        audio_suffix = Path(audio.filename or "speech.webm").suffix.lower() or ".webm"
        raw_audio = workspace / f"request{audio_suffix}"
        try:
            _copy_limited(
                audio,
                raw_audio,
                PUBLIC_AUDIO_BYTES if public_launch_enabled() else 100 * 1024 * 1024,
            )
        finally:
            await audio.close()

        if raw_audio.stat().st_size:
            send_audio = raw_audio
            if audio_suffix != ".mp3":
                converted = workspace / "request.mp3"
                if _transcode_to_mp3(raw_audio, converted):
                    send_audio = converted
                else:
                    send_audio = None
            if send_audio is not None:
                extra_media.append((send_audio, "audio/mpeg"))
                spoken_used = True

    # Reference images: "find this person", "find this object".
    image_count = 0
    for index, item in enumerate(images or []):
        if not getattr(item, "filename", ""):
            continue
        suffix = Path(item.filename or "ref.jpg").suffix.lower() or ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
            continue
        path = workspace / f"reference_{index}{suffix}"
        try:
            _copy_limited(
                item,
                path,
                PUBLIC_IMAGE_BYTES if public_launch_enabled() else 100 * 1024 * 1024,
            )
        finally:
            await item.close()
        if path.stat().st_size:
            extra_media.append((path, _IMAGE_MIME.get(suffix, "image/jpeg")))
            image_count += 1

    # A short reference clip: "find more moments like this one".
    reference_used = False
    if reference is not None and getattr(reference, "filename", ""):
        suffix = Path(reference.filename or "ref.mp4").suffix.lower() or ".mp4"
        path = workspace / f"reference_clip{suffix}"
        try:
            _copy_limited(
                reference,
                path,
                PUBLIC_REFERENCE_BYTES if public_launch_enabled() else 700 * 1024 * 1024,
            )
        finally:
            await reference.close()
        if path.stat().st_size and _valid_video_signature(path):
            extra_media.append((path, _VIDEO_MIME.get(suffix, "video/mp4")))
            reference_used = True

    if not extra_media and not normalized_query:
        shutil.rmtree(workspace, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail="The attachments could not be processed. Try again, or type the request.",
        )

    resolved_key = _resolve_api_key(None if public_launch_enabled() else api_key, resolved_model)
    paid = reserve_paid_operation(request, response, idempotency_key)
    if isinstance(paid, dict):
        shutil.rmtree(workspace, ignore_errors=True)
        return paid
    duration = _probe_duration(source)
    prompt = (
        build_search_prompt(
            query=normalized_query,
            spoken=spoken_used,
            image_count=image_count,
            reference_clip=reference_used,
            max_moments=MAX_MOMENTS,
        )
        + _duration_clause(duration)
        + _language_clause(language)
    )

    frames_sampled = 0
    diagnostics_payload: dict[str, Any] = {"model": resolved_model}

    if is_openai_model(resolved_model):
        # OpenAI chat models take images, not video, so the footage is sampled
        # into timestamped frames first. Attachments that are not images cannot
        # be forwarded on this path.
        frames = sample_frames(source, duration, workspace)
        frames_sampled = len(frames)
        try:
            payload = openai_generate_moments(
                api_key=resolved_key,
                model=resolved_model,
                prompt=prompt,
                frames=frames,
                response_schema=_MOMENT_SCHEMA,
            )
        except OpenAIRuntimeError as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            raise HTTPException(status_code=502, detail=_provider_error_detail(exc)) from exc
        diagnostics_payload["frames_sampled"] = frames_sampled
        diagnostics_payload["provider"] = "openai"
        moments = _coerce_moments(payload, duration)
    elif should_chunk(duration) and duration is not None:
        # Long video: scan short chunks with known offsets instead of asking the
        # model to keep time across the whole file.
        chunks = split_into_chunks(source, duration, workspace)
        if not chunks:
            shutil.rmtree(workspace, ignore_errors=True)
            raise HTTPException(
                status_code=500, detail="The video could not be prepared for scanning."
            )

        runtime = GoogleGenAIRuntime(api_key=resolved_key)

        def scan(chunk: Chunk) -> list[dict[str, Any]]:
            chunk_prompt = (
                build_search_prompt(
                    query=normalized_query,
                    spoken=spoken_used,
                    image_count=image_count,
                    reference_clip=reference_used,
                    max_moments=MAX_MOMENTS,
                )
                + _duration_clause(chunk.duration_seconds)
                + _language_clause(language)
            )
            try:
                chunk_payload, _ = runtime.generate_json(
                    model=resolved_model,
                    prompt=chunk_prompt,
                    media_path=chunk.path,
                    media_mime_type="video/mp4",
                    extra_media=extra_media,
                    response_schema=_MOMENT_SCHEMA,
                    operation_name="quick_search_chunk",
                )
            except GeminiRuntimeError as exc:
                # One bad chunk should not lose the rest of the video.
                logger.warning(
                    "chunk at %.1fs failed (%s)", chunk.offset_seconds, type(exc).__name__
                )
                return []
            found = _coerce_moments(chunk_payload, chunk.duration_seconds)
            # Offsets are exact arithmetic, not the model's estimate.
            for item in found:
                item["start"] = round(item["start"] + chunk.offset_seconds, 2)
                item["end"] = round(item["end"] + chunk.offset_seconds, 2)
            return found

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHUNKS) as pool:
            per_chunk = list(pool.map(scan, chunks))

        collected = [item for group in per_chunk for item in group]
        collected.sort(key=lambda item: item["confidence"], reverse=True)

        # Overlapping chunks can surface the same event twice.
        moments = []
        for candidate in collected:
            if any(
                candidate["start"] < kept["end"] and kept["start"] < candidate["end"]
                for kept in moments
            ):
                continue
            moments.append(candidate)
            if len(moments) >= MAX_MOMENTS:
                break
        moments.sort(key=lambda item: item["start"])

        if moments:
            found = ", ".join(
                f"{item['start']:.0f}s" for item in moments[:MAX_MOMENTS]
            )
            summary = f"Scanned the full {duration:.0f}s video and found {len(moments)} matching section(s), at {found}."
        else:
            summary = f"Scanned the full {duration:.0f}s video and found no matching sections."
        payload = {"summary": summary}
        diagnostics_payload = {
            "model": resolved_model,
            "provider": "gemini",
            "strategy": "chunked",
            "chunks": len(chunks),
            "chunk_seconds": CHUNK_SECONDS,
        }
    else:
        runtime = GoogleGenAIRuntime(api_key=resolved_key)
        try:
            payload, diagnostics = runtime.generate_json(
                model=resolved_model,
                prompt=prompt,
                media_path=source,
                media_mime_type=mime_type,
                extra_media=extra_media,
                response_schema=_MOMENT_SCHEMA,
                operation_name="quick_search",
            )
        except GeminiRuntimeError as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            raise HTTPException(status_code=502, detail=_provider_error_detail(exc)) from exc
        diagnostics_payload = diagnostics.as_dict()
        diagnostics_payload["provider"] = "gemini"
        moments = _coerce_moments(payload, duration)


    results: list[dict[str, Any]] = []
    for index, moment in enumerate(moments):
        clip_name = f"clip_{index}.mp4"
        clip_path = workspace / clip_name
        playable = _cut_clip(source, moment["start"], moment["end"], clip_path)
        results.append(
            {
                **moment,
                "clip_url": f"/api/quick/clip/{request_id}/{clip_name}" if playable else None,
            }
        )

    result = {
        "request_id": request_id,
        "query": normalized_query,
        "spoken": bool(extra_media),
        "summary": str(payload.get("summary") or "").strip(),
        "model": resolved_model,
        "moments": results,
        "frames_sampled": frames_sampled,
        "diagnostics": diagnostics_payload,
    }
    return paid.complete(result) if isinstance(paid, PaidOperation) else result


@router.get("/clip/{request_id}/{clip_name}")
def quick_clip(request_id: str, clip_name: str) -> FileResponse:
    """Serve one previously cut clip."""

    # Reject anything that is not a plain generated name, so this cannot be
    # used to read arbitrary files from disk.
    if not request_id.isalnum() or not clip_name.replace("_", "").replace(".", "").isalnum():
        raise HTTPException(status_code=404, detail="Clip not found.")
    clip_path = _CLIP_ROOT / request_id / clip_name
    if not clip_path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found.")
    return FileResponse(clip_path, media_type="video/mp4")
