"""Evidence-aware candidate verification for the query pipeline.

The historical Groq verifier is retained as a backwards-compatible
text-only endpoint.  The integrated search flow uses an ephemeral OpenAI or
NVIDIA Cosmos credential to sample frames from the locally uploaded source
video, verify the actual candidate region, and return a bounded event time.
No credential or source path leaves the local API process.
"""
from __future__ import annotations

import base64
import json
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


def _sample_frames(candidate: SearchResultItem, max_frames: int) -> tuple[list[float], list[str]]:
    """Return ordered JPEG data URLs from a safely served local upload."""
    path = media_path_for_source(candidate.source_path)
    if path is None:
        raise FileNotFoundError("candidate source video is unavailable locally")

    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise ValueError(f"could not open candidate video: {Path(path).name}")
    start = max(0.0, float(candidate.start))
    end = max(start, float(candidate.end))
    # A zero-length test/damaged region still gets one readable frame.
    duration = max(end - start, 0.001)
    count = max(2, int(max_frames))
    timestamps = [start + duration * index / count for index in range(count)]
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


def _openai_vision_verify(
    prompt: str, frames: list[str], options: VerificationOptions
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
        text_format=_VisionVerificationOutput,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise ValueError("OpenAI returned no structured verification output")
    return parsed.model_dump()


def _cosmos_vision_verify(
    prompt: str, frames: list[str], options: VerificationOptions
) -> dict[str, Any]:
    """Call hosted Cosmos through NVIDIA's OpenAI-compatible endpoint."""
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "candidate_verification",
            "schema": _VisionVerificationOutput.model_json_schema(),
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
        raise ValueError("Cosmos response did not contain JSON text")
    return groq_client.parse_json_response(content)


def _bounded_time(value: Any, duration: float) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return min(max(number, 0.0), duration)


def _vision_result(
    candidate: SearchResultItem,
    original_query: str,
    required_conditions: list[str],
    options: VerificationOptions,
) -> VerificationResult:
    frame_timestamps, frames = _sample_frames(candidate, options.max_frames)
    prompt = _build_vision_prompt(candidate, original_query, required_conditions)
    if options.provider == "openai":
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
    return VerificationResult(
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
