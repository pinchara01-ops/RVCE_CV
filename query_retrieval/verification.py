"""Evidence-aware candidate verification for the query pipeline.

The historical Groq verifier is retained as a backwards-compatible
text-only endpoint.  The integrated search flow uses an ephemeral OpenAI or
NVIDIA Cosmos credential to sample frames from the locally uploaded source
video, verify the actual candidate region, and return a bounded event time.
No credential or source path leaves the local API process.
"""
from __future__ import annotations

import base64
import logging
import math
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from processing_indexing.library import media_path_for_source
from query_retrieval import config, groq_client
from query_retrieval.models import (
    SearchResultItem,
    VerificationOptions,
    VerificationResult,
)

logger = logging.getLogger(__name__)

_OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"
_COSMOS_DEFAULT_MODEL = "nvidia/cosmos3-nano-reasoner"
_GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"
_COSMOS_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


class _VisionVerificationOutput(BaseModel):
    """Strict schema sent to either hosted vision provider."""

    match: bool
    confidence: float = Field(ge=0, le=1)
    satisfied_conditions: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    evidence: str = ""
    event_start_relative: float | None = None
    event_end_relative: float | None = None


class _TemporalLocalizationOutput(BaseModel):
    """Strict response for the second, dense temporal inspection pass."""

    match: bool
    confidence: float = Field(ge=0, le=1)
    evidence: str = ""
    event_start_relative: float | None = None
    event_end_relative: float | None = None


_TEXT_ONLY_PROMPT = """You are verifying a single candidate video window against a search query, using ONLY the text evidence provided below - you do not have access to the actual video, audio, or frames.

Query: "{query}"
Required conditions to check: {conditions}

Evidence for this candidate:
- transcript: {transcript}
- caption: {caption}
- matched search modalities: {matched_modalities}

For each required condition, decide if the evidence satisfies it, contradicts it, or simply doesn't mention it (missing - not the same as contradicting). Then give an overall match verdict: true only if the evidence is consistent with the query and no required condition is contradicted.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"match": true, "confidence": 0.0, "satisfied_conditions": ["..."], "missing_conditions": ["..."], "contradictions": ["..."], "evidence": "one-sentence explanation"}}
"""

_VISION_PROMPT = """You are verifying a candidate region from an actual video search result. You receive chronological sampled frames from the candidate region, plus transcript and retrieval evidence.

Original query: "{query}"
Candidate region: {start:.2f}s to {end:.2f}s in the source video ({duration:.2f}s long)
Required conditions: {conditions}
Transcript: {transcript}
Existing indexing caption: {caption}
Retrieval evidence: matched modalities = {matched_modalities}

Rules:
1. Check EVERY required condition. A partial match is not a match: if any required condition is missing or contradicted, set match to false.
2. You can use frames for visible people, objects, actions, scene and timing. Do not infer an audible event only because a visual event looks plausible.
3. The `audio` retrieval modality is only weak supporting evidence for a non-speech sound. If the requested sound cannot be supported by transcript or retrieval evidence, mark it missing rather than inventing it.
4. If match is true, give the narrowest event interval you can identify as seconds relative to the candidate region. If the event spans the entire candidate, use 0 and the candidate duration. If timing is uncertain, leave both timing fields null.
5. Be conservative about intent and crime labels. Describe observable evidence and uncertainty.

Return ONLY JSON matching this schema:
{{"match": true, "confidence": 0.0, "satisfied_conditions": ["..."], "missing_conditions": ["..."], "contradictions": ["..."], "evidence": "short evidence summary", "event_start_relative": 0.0, "event_end_relative": 0.0}}
"""

_TEMPORAL_LOCALIZATION_PROMPT = """You are the second, temporal-localisation pass for a video search result. A first VLM pass has already verified that this candidate matches the query. You receive densely sampled frames in chronological order from the candidate's remaining broad region.

Original query: "{query}"
Required conditions: {conditions}
Candidate region: {candidate_start:.2f}s to {candidate_end:.2f}s in the source video ({candidate_duration:.2f}s long)
Focus region: {focus_start:.2f}s to {focus_end:.2f}s relative to the candidate region
Frame timestamps in source-video seconds, in the exact order supplied: {frame_timestamps}
Transcript: {transcript}
Existing indexing caption: {caption}

Rules:
1. Locate the narrowest interval that is directly supported by the frames. Normally target 2–{target_seconds:.1f} seconds; a shorter interval is allowed when the evidence is truly briefer. Never return an interval longer than {target_seconds:.1f} seconds.
2. Return timing relative to the whole candidate region (0 means the candidate start), not relative to the focus region or source video.
3. Keep both timing values inside the focus region. If the frames do not support an exact interval, set `match` to false and both timing values to null. Do not guess.
4. Do not infer an audible event merely from visible frames. Be conservative about intent and crime labels.

Return ONLY JSON matching this schema:
{{"match": true, "confidence": 0.0, "evidence": "short evidence summary", "event_start_relative": 0.0, "event_end_relative": 0.0}}
"""


def _build_text_only_prompt(
    candidate: SearchResultItem, original_query: str, required_conditions: list[str]
) -> str:
    return _TEXT_ONLY_PROMPT.format(
        query=original_query,
        conditions=required_conditions or "(none specified)",
        transcript=candidate.transcript or "(none)",
        caption=candidate.caption or "(none)",
        matched_modalities=", ".join(candidate.matched_modalities) or "(none)",
    )


def _build_vision_prompt(
    candidate: SearchResultItem, original_query: str, required_conditions: list[str]
) -> str:
    duration = max(0.0, candidate.end - candidate.start)
    return _VISION_PROMPT.format(
        query=original_query,
        conditions=required_conditions or "(none specified)",
        start=candidate.start,
        end=candidate.end,
        duration=duration,
        transcript=candidate.transcript or "(none)",
        caption=candidate.caption or "(none)",
        matched_modalities=", ".join(candidate.matched_modalities) or "(none)",
    )


def _build_temporal_localization_prompt(
    candidate: SearchResultItem,
    original_query: str,
    required_conditions: list[str],
    focus_start_relative: float,
    focus_end_relative: float,
    frame_timestamps: list[float],
    target_seconds: float,
) -> str:
    """Build the explicit second-pass contract with frame-time evidence."""
    duration = max(0.0, candidate.end - candidate.start)
    return _TEMPORAL_LOCALIZATION_PROMPT.format(
        query=original_query,
        conditions=required_conditions or "(none specified)",
        candidate_start=candidate.start,
        candidate_end=candidate.end,
        candidate_duration=duration,
        focus_start=focus_start_relative,
        focus_end=focus_end_relative,
        frame_timestamps=", ".join(f"{timestamp:.2f}s" for timestamp in frame_timestamps),
        transcript=candidate.transcript or "(none)",
        caption=candidate.caption or "(none)",
        target_seconds=target_seconds,
    )


def _sample_frames_at_timestamps(
    candidate: SearchResultItem, timestamps: list[float]
) -> tuple[list[float], list[str]]:
    """Decode ordered JPEG data URLs at exact source-video timestamps.

    This is the decoder seam used by both verification passes.  Tests can
    replace the higher-level samplers and therefore never open a video file.
    """
    path = media_path_for_source(candidate.source_path)
    if path is None:
        raise FileNotFoundError("candidate source video is unavailable locally")

    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise ValueError(f"could not open candidate video: {Path(path).name}")
    images: list[str] = []
    decoded: list[float] = []
    try:
        for timestamp in timestamps:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            ok, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88]
            )
            if not ok:
                continue
            images.append(
                "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")
            )
            decoded.append(timestamp)
    finally:
        capture.release()
    if len(images) < 2:
        raise ValueError("could not decode enough candidate frames for verification")
    return decoded, images


def _sample_frames(candidate: SearchResultItem, max_frames: int) -> tuple[list[float], list[str]]:
    """Return uniformly spaced frames for the broad first verification pass."""
    start = max(0.0, float(candidate.start))
    end = max(start, float(candidate.end))
    # A zero-length test/damaged region still gets one readable frame.
    duration = max(end - start, 0.001)
    count = max(2, int(max_frames))
    timestamps = [start + duration * index / count for index in range(count)]
    return _sample_frames_at_timestamps(candidate, timestamps)


def _dense_sample_frames(
    candidate: SearchResultItem,
    focus_start_relative: float,
    focus_end_relative: float,
    target_seconds: float,
    max_frames: int,
) -> tuple[list[float], list[str]]:
    """Sample bounded, evenly distributed 2–5 second time bins.

    The method deliberately caps the request size.  For a typical 20-second
    candidate and the default target of five seconds it sends two frames per
    bin (eight frames).  Larger merged regions gracefully fall back to one
    representative frame per bin, never exceeding ``max_frames``.
    """
    candidate_duration = max(0.0, float(candidate.end) - float(candidate.start))
    start = min(max(float(focus_start_relative), 0.0), candidate_duration)
    end = min(max(float(focus_end_relative), start), candidate_duration)
    span = end - start
    if span <= 0:
        raise ValueError("temporal localisation focus region is empty")

    target = min(max(float(target_seconds), 2.0), 5.0)
    frame_limit = max(4, int(max_frames))
    bin_count = max(1, math.ceil(span / target))
    # Favour two samples per bin whenever that is still bounded.  This gives
    # the VLM temporal order within a normal 10–20 second candidate without
    # turning a long merged region into an unbounded frame upload.
    samples_per_bin = 2 if bin_count * 2 <= frame_limit else 1
    if bin_count > frame_limit:
        selected_bin_indexes = [
            round(index * (bin_count - 1) / (frame_limit - 1))
            for index in range(frame_limit)
        ]
    else:
        selected_bin_indexes = list(range(bin_count))

    timestamps: list[float] = []
    for index in selected_bin_indexes:
        bin_start = start + index * target
        bin_end = min(end, bin_start + target)
        width = max(0.001, bin_end - bin_start)
        if samples_per_bin == 2:
            offsets = (0.25, 0.75)
        else:
            offsets = (0.5,)
        for offset in offsets:
            timestamps.append(candidate.start + bin_start + width * offset)

    # Two neighbouring rounded selections can point at the same time bin.
    # Preserve order while de-duplicating so prompts and frames always align.
    ordered_unique = list(dict.fromkeys(round(timestamp, 6) for timestamp in timestamps))
    if len(ordered_unique) < 2:
        raise ValueError("could not create enough temporal localisation samples")
    return _sample_frames_at_timestamps(candidate, ordered_unique)


def _openai_vision_verify(
    prompt: str,
    frames: list[str],
    options: VerificationOptions,
    *,
    response_model: type[BaseModel] = _VisionVerificationOutput,
) -> dict[str, Any]:
    """Call the Responses API with a strict Pydantic schema."""
    from openai import OpenAI

    client = OpenAI(
        api_key=options.api_key,
        timeout=config.VERIFICATION_TIMEOUT_SECONDS,
        max_retries=0,
    )
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    content.extend(
        {"type": "input_image", "image_url": frame, "detail": "low"}
        for frame in frames
    )
    response = client.responses.parse(
        model=options.model or _OPENAI_DEFAULT_MODEL,
        input=[{"role": "user", "content": content}],
        text_format=response_model,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise ValueError("OpenAI returned no structured verification output")
    return parsed.model_dump()


def _cosmos_vision_verify(
    prompt: str,
    frames: list[str],
    options: VerificationOptions,
    *,
    response_model: type[BaseModel] = _VisionVerificationOutput,
) -> dict[str, Any]:
    """Call hosted Cosmos through NVIDIA's OpenAI-compatible endpoint."""
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "candidate_verification",
            "schema": response_model.model_json_schema(),
        },
    }
    payload = {
        "model": options.model or _COSMOS_DEFAULT_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "video_frames", "video_frames": frames},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 700,
        "response_format": response_format,
    }
    with httpx.Client(timeout=config.VERIFICATION_TIMEOUT_SECONDS) as client:
        response = client.post(
            _COSMOS_URL,
            headers={
                "Authorization": f"Bearer {options.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    content = body["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise TypeError("Cosmos response did not contain JSON text")
    return groq_client.parse_json_response(content)


def _gemini_vision_verify(
    prompt: str,
    candidate: SearchResultItem,
    options: VerificationOptions,
    *,
    response_model: type[BaseModel] = _VisionVerificationOutput,
) -> dict[str, Any]:
    """Run Gemini against one bounded candidate clip, never the library.

    The API-profile path stores source media locally while vectors live in
    Qdrant Cloud.  We transcode only the already-fused candidate interval to
    a temporary MP4, upload it for this call, and let the Gemini runtime
    delete the remote file afterwards.  No raw API key or media path is
    included in a response or diagnostic.
    """

    from processing_indexing.api_pipeline import FfmpegMediaPreparer
    from processing_indexing.gemini_runtime import GoogleGenAIRuntime
    from processing_indexing.models import VideoWindow

    source = media_path_for_source(candidate.source_path)
    if source is None:
        raise FileNotFoundError("candidate source video is unavailable locally")
    window = VideoWindow(
        video_id=candidate.video_id,
        window_id=candidate.window_id,
        start=max(0.0, float(candidate.start)),
        end=max(float(candidate.end), float(candidate.start) + 0.001),
    )
    session = FfmpegMediaPreparer().begin(
        source,
        video_id=candidate.video_id,
        has_audio=bool(candidate.transcript.strip()),
    )
    try:
        clip = session.prepare_video_window(window)
        payload, _diagnostics = GoogleGenAIRuntime(api_key=str(options.api_key)).generate_json(
            model=options.model or _GEMINI_DEFAULT_MODEL,
            prompt=prompt,
            media_path=clip.path,
            media_mime_type=clip.mime_type,
            response_schema=response_model.model_json_schema(),
            operation_name="verification",
        )
        return payload
    finally:
        session.cleanup()


def _temporal_vision_localize(
    prompt: str,
    frames: list[str],
    options: VerificationOptions,
    *,
    candidate: SearchResultItem | None = None,
) -> dict[str, Any]:
    """Use the selected first-pass VLM for structured time localisation."""
    if options.provider == "openai":
        return _openai_vision_verify(
            prompt,
            frames,
            options,
            response_model=_TemporalLocalizationOutput,
        )
    if options.provider == "cosmos":
        return _cosmos_vision_verify(
            prompt,
            frames,
            options,
            response_model=_TemporalLocalizationOutput,
        )
    if options.provider == "gemini":
        if candidate is None:
            raise ValueError("Gemini localisation requires the candidate media")
        return _gemini_vision_verify(
            prompt,
            candidate,
            options,
            response_model=_TemporalLocalizationOutput,
        )
    raise ValueError(f"unsupported vision provider: {options.provider}")


def _bounded_time(value: Any, duration: float) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return min(max(number, 0.0), duration)


def _valid_time_range(
    start: float | None, end: float | None, duration: float
) -> tuple[float, float] | None:
    """Return a finite, non-empty candidate-relative time range."""
    if start is None or end is None:
        return None
    bounded_start = _bounded_time(start, duration)
    bounded_end = _bounded_time(end, duration)
    if bounded_start is None or bounded_end is None:
        return None
    if bounded_end < bounded_start:
        bounded_start, bounded_end = bounded_end, bounded_start
    if bounded_end - bounded_start <= 1e-6:
        return None
    return bounded_start, bounded_end


def _temporal_focus(
    result: VerificationResult, candidate_duration: float
) -> tuple[float, float]:
    """Prefer a broad first-pass interval; otherwise inspect the candidate."""
    first_pass = _valid_time_range(
        result.event_start_relative, result.event_end_relative, candidate_duration
    )
    if first_pass is not None:
        return first_pass
    return 0.0, candidate_duration


def _localize_verified_candidate(
    candidate: SearchResultItem,
    result: VerificationResult,
    original_query: str,
    required_conditions: list[str],
    options: VerificationOptions,
) -> VerificationResult:
    """Densely inspect a broad verified region without changing its verdict.

    Localisation is refinement, not a second gate.  If sampling or the VLM
    cannot establish a short span, the first verified result remains visible
    and explicitly records why no exact moment is being claimed.
    """
    if not options.enable_temporal_localization:
        result.localization_reason = "temporal localisation disabled for this request"
        return result

    candidate_duration = max(0.0, candidate.end - candidate.start)
    focus_start, focus_end = _temporal_focus(result, candidate_duration)
    if focus_end - focus_start <= options.temporal_target_seconds:
        result.localization_state = "not_needed"
        result.localization_reason = "first verification already returned a short interval"
        return result

    try:
        frame_timestamps, frames = _dense_sample_frames(
            candidate,
            focus_start,
            focus_end,
            options.temporal_target_seconds,
            options.temporal_max_frames,
        )
        prompt = _build_temporal_localization_prompt(
            candidate,
            original_query,
            required_conditions,
            focus_start,
            focus_end,
            frame_timestamps,
            options.temporal_target_seconds,
        )
        if options.provider == "gemini":
            parsed = _temporal_vision_localize(prompt, frames, options, candidate=candidate)
        else:
            # Preserve the historical three-argument seam used by existing
            # OpenAI/Cosmos tests and integrations.
            parsed = _temporal_vision_localize(prompt, frames, options)
        output = _TemporalLocalizationOutput.model_validate(parsed)
        proposed = _valid_time_range(
            output.event_start_relative, output.event_end_relative, candidate_duration
        )
        if not output.match or proposed is None:
            result.localization_state = "localization_unavailable"
            result.localization_reason = "VLM could not establish a bounded event interval"
            result.localization_frame_timestamps = frame_timestamps
            return result

        localized_start, localized_end = proposed
        # The second VLM must not drift outside the evidence it was shown or
        # claim a broad result as an exact event.  A very short event is valid
        # (e.g. an impact); only an over-wide response is rejected.
        if (
            localized_start < focus_start - 1e-6
            or localized_end > focus_end + 1e-6
            or localized_end - localized_start > options.temporal_target_seconds + 1e-6
        ):
            result.localization_state = "localization_unavailable"
            result.localization_reason = "VLM returned an interval outside the bounded localisation contract"
            result.localization_frame_timestamps = frame_timestamps
            return result

        result.event_start_relative = localized_start
        result.event_end_relative = localized_end
        result.localization_state = "localized"
        result.localization_evidence = output.evidence
        result.localization_frame_timestamps = frame_timestamps
        return result
    except Exception as exc:  # noqa: BLE001 - first-pass result remains valid
        logger.info(
            "Temporal localisation unavailable candidate=%s provider=%s reason=%s",
            candidate.window_id,
            options.provider,
            type(exc).__name__,
        )
        result.localization_state = "localization_unavailable"
        result.localization_reason = f"{options.provider} temporal localisation failed: {type(exc).__name__}"
        return result


def _vision_result(
    candidate: SearchResultItem,
    original_query: str,
    required_conditions: list[str],
    options: VerificationOptions,
) -> VerificationResult:
    prompt = _build_vision_prompt(candidate, original_query, required_conditions)
    if options.provider == "gemini":
        # Gemini consumes the bounded MP4 directly, rather than a lossy
        # sampling of frames.  The result remains a candidate-only call.
        frame_timestamps, frames = [], []
        parsed = _gemini_vision_verify(prompt, candidate, options)
    else:
        frame_timestamps, frames = _sample_frames(candidate, options.max_frames)
    if options.provider == "gemini":
        pass
    elif options.provider == "openai":
        parsed = _openai_vision_verify(prompt, frames, options)
    elif options.provider == "cosmos":
        parsed = _cosmos_vision_verify(prompt, frames, options)
    else:  # Defensive, even though the request model validates this literal.
        raise ValueError(f"unsupported vision provider: {options.provider}")

    output = _VisionVerificationOutput.model_validate(parsed)
    duration = max(0.0, candidate.end - candidate.start)
    event_start = _bounded_time(output.event_start_relative, duration)
    event_end = _bounded_time(output.event_end_relative, duration)
    if event_start is not None and event_end is not None and event_end < event_start:
        event_start, event_end = event_end, event_start

    # A requirement that the provider cannot establish is a partial result,
    # not a true match, even if the provider optimistically said `match=true`.
    is_partial = bool(required_conditions and (output.missing_conditions or output.contradictions))
    match = bool(output.match) and not is_partial
    result = VerificationResult(
        candidate_id=candidate.window_id,
        state="verified" if match else "rejected",
        match=match,
        confidence=max(0.0, min(1.0, float(output.confidence))),
        satisfied_conditions=output.satisfied_conditions,
        missing_conditions=output.missing_conditions,
        contradictions=output.contradictions,
        evidence=output.evidence,
        reason="partial match rejected" if is_partial else "",
        provider=options.provider,
        event_start_relative=event_start,
        event_end_relative=event_end,
        frame_timestamps=frame_timestamps,
    )
    if match:
        return _localize_verified_candidate(
            candidate, result, original_query, required_conditions, options
        )
    return result


def _legacy_live_verify(
    candidate: SearchResultItem, original_query: str, required_conditions: list[str]
) -> dict[str, Any]:
    client = groq_client.get_client()

    def _call() -> str:
        return groq_client.chat_completion(
            client, _build_text_only_prompt(candidate, original_query, required_conditions)
        )

    raw = groq_client.call_with_hard_timeout(_call, config.VERIFICATION_TIMEOUT_SECONDS)
    parsed = groq_client.parse_json_response(raw)
    if "match" not in parsed:
        raise ValueError("verification response missing 'match' field")
    return {
        "match": bool(parsed["match"]),
        "confidence": float(parsed.get("confidence", 0.0)),
        "satisfied_conditions": [str(c) for c in parsed.get("satisfied_conditions", [])],
        "missing_conditions": [str(c) for c in parsed.get("missing_conditions", [])],
        "contradictions": [str(c) for c in parsed.get("contradictions", [])],
        "evidence": str(parsed.get("evidence", "")),
    }


# Kept as a named compatibility seam for the historical verification tests and
# callers.  New code should pass VerificationOptions and use the VLM path.
_live_verify = _legacy_live_verify


def verify_candidate(
    candidate: SearchResultItem,
    original_query: str,
    required_conditions: list[str],
    options: VerificationOptions | None = None,
) -> VerificationResult:
    """Verify one candidate and never turn a failure into a positive match."""
    if options is not None and options.provider != "none":
        if not options.enabled:
            return VerificationResult(
                candidate_id=candidate.window_id,
                state="verification_unavailable",
                reason=f"{options.provider} API key is required for verification",
                provider=options.provider,
            )
        try:
            return _vision_result(candidate, original_query, required_conditions, options)
        except Exception as exc:  # noqa: BLE001 - failure must remain explicit
            logger.info(
                "Vision verification unavailable candidate=%s provider=%s reason=%s",
                candidate.window_id,
                options.provider,
                type(exc).__name__,
            )
            return VerificationResult(
                candidate_id=candidate.window_id,
                state="verification_unavailable",
                reason=f"{options.provider} verification failed: {type(exc).__name__}",
                provider=options.provider,
            )

    # Legacy text-only endpoint, kept for existing API clients.  It is never
    # selected by the new browser flow because it cannot inspect real frames.
    if not config.ENABLE_VERIFICATION:
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verification_unavailable",
            reason="verification disabled (ENABLE_VERIFICATION=false)",
        )
    if not config.GROQ_API_KEY:
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verification_unavailable",
            reason="GROQ_API_KEY not configured",
        )
    try:
        parsed = _live_verify(candidate, original_query, required_conditions)
    except Exception as exc:  # noqa: BLE001
        logger.info("Text verification unavailable candidate=%s reason=%s", candidate.window_id, type(exc).__name__)
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verification_unavailable",
            reason=f"text verification failed: {type(exc).__name__}",
        )

    return VerificationResult(
        candidate_id=candidate.window_id,
        state="verified" if parsed["match"] else "rejected",
        match=parsed["match"],
        confidence=max(0.0, min(1.0, parsed["confidence"])),
        satisfied_conditions=parsed["satisfied_conditions"],
        missing_conditions=parsed["missing_conditions"],
        contradictions=parsed["contradictions"],
        evidence=parsed["evidence"],
        provider="text_only",
    )
