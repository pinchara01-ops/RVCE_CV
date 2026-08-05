import concurrent.futures
import base64
import json
import re
import time
from pathlib import Path
from typing import Protocol, Callable
from pydantic import ValidationError
from .models import ActionTiming, VideoWindow, VLMDescription

PROMPT = """Describe only visible evidence in this video window. Never infer sounds. Return strict JSON with keys people_and_clothing, objects_and_colours, actions, object_action_relationships, spatial_relationships, visible_text, scene_context, action_timing (action/start_seconds/end_seconds), uncertainty, and confidence (0 to 1 based only on visible evidence)."""


class VLMError(RuntimeError):
    pass


class StructuredOutputError(VLMError):
    pass


class VLMRefusalError(VLMError):
    pass


def normalize_action_timings(description: VLMDescription, duration: float):
    normalized = []
    diagnostics = []
    for timing in description.action_timing:
        original = {
            "start_seconds": timing.start_seconds,
            "end_seconds": timing.end_seconds,
        }
        if timing.end_seconds < timing.start_seconds:
            diagnostics.append(
                {
                    "action": timing.action,
                    "original": original,
                    "status": "rejected",
                    "reason": "reversed_range",
                }
            )
            continue
        start = min(duration, max(0.0, timing.start_seconds))
        end = min(duration, max(0.0, timing.end_seconds))
        status = (
            "unchanged"
            if start == timing.start_seconds and end == timing.end_seconds
            else "normalized"
        )
        normalized.append(
            ActionTiming(action=timing.action, start_seconds=start, end_seconds=end)
        )
        diagnostics.append(
            {
                "action": timing.action,
                "original": original,
                "normalized": {"start_seconds": start, "end_seconds": end},
                "status": status,
            }
        )
    description.action_timing = normalized
    return diagnostics


def _usage(value):
    usage = getattr(value, "usage", None)
    if usage is None:
        usage = getattr(getattr(value, "response", None), "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage) if isinstance(usage, dict) else None


def _contains_refusal(response):
    output = getattr(response, "output", [])
    if hasattr(output, "model_dump"):
        output = output.model_dump()
    return "refusal" in json.dumps(output, default=str).lower()


def _failure_category(exc):
    if isinstance(exc, VLMRefusalError):
        return "refusal"
    if isinstance(exc, StructuredOutputError):
        return "missing_parsed_output"
    if isinstance(exc, json.JSONDecodeError):
        return "truncated_json"
    if "lengthfinishreason" in type(exc).__name__.lower():
        return "truncated_json"
    if isinstance(exc, ValidationError) and (
        "json_invalid" in str(exc) or "eof while parsing" in str(exc).lower()
    ):
        return "truncated_json"
    if isinstance(exc, ValidationError) or "validation" in type(exc).__name__.lower():
        return "schema_validation"
    name = type(exc).__name__.lower()
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if any(value in name for value in ("timeout", "connection", "ratelimit")) or (
        isinstance(status, int) and (status == 429 or status >= 500)
    ):
        return "transport"
    return "provider_error"


def _safe_error(exc):
    first_line = str(exc).splitlines()[0][:300]
    first_line = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", first_line)
    first_line = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", first_line, flags=re.I)
    return f"{type(exc).__name__}: {first_line}"


def _json_object_from_vlm_output(raw: object) -> dict:
    """Accept a strict JSON object, including a model's fenced JSON response.

    Local instruction-tuned VLMs sometimes wrap otherwise-valid JSON in a
    Markdown fence.  We still reject prose or a non-object payload; this is a
    small compatibility boundary rather than permissive output parsing.
    """

    if not isinstance(raw, str):
        raise TypeError("VLM output must be a JSON string")
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("VLM output must be a JSON object")
    return parsed


class VLMProvider(Protocol):
    def describe(self, video_path: Path, window: VideoWindow) -> VLMDescription: ...


class RetryingVLMProvider:
    def __init__(
        self, request: Callable[[Path, VideoWindow, str], str], timeout=120, retries=2
    ):
        self.request, self.timeout, self.retries = request, timeout, retries

    def describe(self, video_path, window):
        last = None
        for _ in range(self.retries + 1):
            try:
                pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = pool.submit(self.request, video_path, window, PROMPT)
                try:
                    raw = future.result(timeout=self.timeout)
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
                return VLMDescription.model_validate(_json_object_from_vlm_output(raw))
            except Exception as exc:
                last = exc
        raise VLMError(
            f"VLM failed after {self.retries + 1} attempts: {last}"
        ) from last


class LocalQwenProvider(RetryingVLMProvider):
    def __init__(
        self,
        model_name="Qwen/Qwen2.5-VL-3B-Instruct",
        device="cpu",
        timeout=120,
        retries=2,
    ):
        self.model_name, self.device, self._model, self._processor = (
            model_name,
            device,
            None,
            None,
        )
        super().__init__(self._request, timeout, retries)

    def _request(self, video_path, window, prompt):
        import cv2
        import numpy as np
        import torch
        from PIL import Image

        if self._model is None:
            from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

            dtype = torch.float16 if self.device == "cuda" else torch.float32
            self._processor = AutoProcessor.from_pretrained(self.model_name)
            self._model = (
                Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    self.model_name, torch_dtype=dtype
                )
                .to(self.device)
                .eval()
            )
        capture = cv2.VideoCapture(str(video_path))
        frames = []
        for timestamp in np.linspace(window.start, window.end, 8, endpoint=False):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = capture.read()
            if not ok:
                capture.release()
                raise VLMError(f"Could not decode VLM frame at {timestamp}s")
            frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        capture.release()
        content = [{"type": "image", "image": frame} for frame in frames] + [
            {"type": "text", "text": prompt}
        ]
        messages = [{"role": "user", "content": content}]
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(
            text=[text], images=frames, padding=True, return_tensors="pt"
        ).to(self.device)
        with torch.inference_mode():
            generated = self._model.generate(
                **inputs, max_new_tokens=768, do_sample=False
            )
        trimmed = [out[len(inp) :] for inp, out in zip(inputs.input_ids, generated)]
        return self._processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]


class HostedQwenProvider(RetryingVLMProvider):
    """OpenAI-compatible hosted Qwen vision provider; credentials stay in memory."""

    def __init__(
        self, base_url, api_key, model_name, timeout=120, retries=2, client=None
    ):
        if not base_url:
            raise ValueError("VLM_BASE_URL is required for the hosted provider")
        if not api_key:
            raise ValueError("VLM_API_KEY is required for the hosted provider")
        import httpx

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.client = client or httpx.Client(timeout=timeout)
        super().__init__(self._request, timeout, retries)

    def _encode_frames(self, video_path, window):
        import cv2
        import numpy as np

        capture = cv2.VideoCapture(str(video_path))
        frames = []
        for timestamp in np.linspace(window.start, window.end, 8, endpoint=False):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = capture.read()
            if not ok:
                capture.release()
                raise VLMError(f"Could not decode hosted VLM frame at {timestamp}s")
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                capture.release()
                raise VLMError(f"Could not encode hosted VLM frame at {timestamp}s")
            frames.append(
                "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")
            )
        capture.release()
        return frames

    def _request(self, video_path, window, prompt):
        content = [
            {"type": "image_url", "image_url": {"url": frame}}
            for frame in self._encode_frames(video_path, window)
        ]
        content.append({"type": "text", "text": prompt})
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


NVIDIA_COSMOS_CHAT_COMPLETIONS_URL = (
    "https://integrate.api.nvidia.com/v1/chat/completions"
)
NVIDIA_COSMOS_NANO_MODEL = "nvidia/cosmos3-nano-reasoner"


def _chat_completion_usage(payload):
    """Normalize usage returned by OpenAI-compatible chat-completion APIs."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return None
    normalized = dict(usage)
    if "prompt_tokens" in normalized:
        normalized.setdefault("input_tokens", normalized["prompt_tokens"])
    if "completion_tokens" in normalized:
        normalized.setdefault("output_tokens", normalized["completion_tokens"])
    return normalized


class NvidiaCosmosProvider:
    """Hosted NVIDIA Cosmos 3 provider using temporal frame inputs.

    The caller supplies a per-job API key. This provider keeps that key only in
    memory and deliberately excludes it, prompts, and frame payloads from the
    diagnostics exposed to the rest of the indexing pipeline.
    """

    def __init__(
        self,
        api_key,
        model_name=NVIDIA_COSMOS_NANO_MODEL,
        timeout=120,
        retries=2,
        max_frames=8,
        client=None,
        clock=time.monotonic,
    ):
        if not api_key:
            raise ValueError("An NVIDIA API key is required for Cosmos VLM")
        if not model_name:
            raise ValueError("A Cosmos model name is required")
        if timeout <= 0:
            raise ValueError("Cosmos timeout must be positive")
        if retries < 0:
            raise ValueError("Cosmos retries cannot be negative")
        if max_frames < 1:
            raise ValueError("Cosmos max_frames must be at least one")

        import httpx

        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.retries = retries
        self.max_frames = max_frames
        self.client = client or httpx.Client(timeout=timeout)
        self._clock = clock
        self.last_usage = None
        self.last_sanitized_request = None
        self.last_sanitized_response = None
        self.attempts = []

    def _encode_frames(self, video_path, window):
        import cv2
        import numpy as np

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            capture.release()
            raise VLMError(f"Could not open video for Cosmos VLM: {video_path}")

        frames = []
        try:
            for timestamp in np.linspace(
                window.start, window.end, self.max_frames, endpoint=False
            ):
                capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
                ok, frame = capture.read()
                if not ok:
                    raise VLMError(f"Could not decode Cosmos frame at {timestamp}s")
                ok, encoded = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90]
                )
                if not ok:
                    raise VLMError(f"Could not encode Cosmos frame at {timestamp}s")
                frames.append(
                    (
                        float(timestamp),
                        "data:image/jpeg;base64,"
                        + base64.b64encode(encoded).decode("ascii"),
                    )
                )
        finally:
            capture.release()
        return frames

    def _request_payload(self, frames):
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_frames",
                            "video_frames": [data for _, data in frames],
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "VLMDescription",
                    "schema": VLMDescription.model_json_schema(),
                },
            },
            "temperature": 0,
            "max_tokens": 1024,
            "stream": False,
        }

    def describe(self, video_path, window):
        self.last_usage = None
        self.last_sanitized_request = None
        self.last_sanitized_response = None
        self.attempts = []

        frames = self._encode_frames(video_path, window)
        payload = self._request_payload(frames)
        self.last_sanitized_request = {
            "endpoint": NVIDIA_COSMOS_CHAT_COMPLETIONS_URL,
            "model": self.model_name,
            "frame_timestamps": [timestamp for timestamp, _ in frames],
            "frame_count": len(frames),
            "response_format": "json_schema",
        }

        last = None
        for attempt in range(1, self.retries + 2):
            started = self._clock()
            response_payload = None
            try:
                response = self.client.post(
                    NVIDIA_COSMOS_CHAT_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                response_payload = response.json()
                usage = _chat_completion_usage(response_payload)
                if usage is not None:
                    self.last_usage = usage

                try:
                    message = response_payload["choices"][0]["message"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise StructuredOutputError(
                        "NVIDIA Cosmos response did not contain a chat message"
                    ) from exc
                if message.get("refusal"):
                    raise VLMRefusalError("NVIDIA Cosmos refused the visual request")
                raw = message.get("content")
                if not isinstance(raw, str) or not raw.strip():
                    raise StructuredOutputError(
                        "NVIDIA Cosmos response did not contain structured JSON"
                    )

                result = VLMDescription.model_validate_json(raw)
                timing_diagnostics = normalize_action_timings(
                    result, window.end - window.start
                )
                self.last_sanitized_response = {
                    **result.model_dump(),
                    "timing_diagnostics": timing_diagnostics,
                }
                self.attempts.append(
                    {
                        "attempt": attempt,
                        "status": "succeeded",
                        "failure_category": None,
                        "error": None,
                        "model": self.model_name,
                        "duration_seconds": self._clock() - started,
                        "usage_status": "captured"
                        if usage is not None
                        else "unavailable",
                        "usage": usage,
                        "timing_diagnostics": timing_diagnostics,
                    }
                )
                return result
            except Exception as exc:
                last = exc
                category = _failure_category(exc)
                usage = _chat_completion_usage(response_payload) or _usage(exc)
                if usage is not None:
                    self.last_usage = usage
                self.attempts.append(
                    {
                        "attempt": attempt,
                        "status": "failed",
                        "failure_category": category,
                        "error": _safe_error(exc),
                        "model": self.model_name,
                        "duration_seconds": self._clock() - started,
                        "usage_status": "captured"
                        if usage is not None
                        else "unavailable",
                        "usage": usage,
                        "timing_diagnostics": [],
                    }
                )
                retryable = category in {
                    "truncated_json",
                    "schema_validation",
                    "missing_parsed_output",
                    "transport",
                }
                if not retryable or attempt > self.retries:
                    break

        if isinstance(last, VLMRefusalError):
            raise last
        raise VLMError(
            f"NVIDIA Cosmos structured response failed after {len(self.attempts)} "
            f"attempts: {_safe_error(last)}"
        ) from last


class OpenAIVisionProvider:
    """Official Responses API provider; the SDK client is created only on first call."""

    def __init__(
        self,
        api_key,
        model_name="gpt-4.1-mini",
        timeout=120,
        retries=2,
        image_detail="low",
        max_frames=4,
        client=None,
        clock=time.monotonic,
    ):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for VLM_PROVIDER=openai")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.retries = retries
        self.image_detail = image_detail
        self.max_frames = max_frames
        self._client = client
        self._clock = clock
        self.last_usage = None
        self.last_sanitized_request = None
        self.last_sanitized_response = None
        self.attempts = []

    def _client_instance(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key, timeout=self.timeout, max_retries=0
            )
        return self._client

    def _encode_frames(self, video_path, window):
        import cv2
        import numpy as np

        capture = cv2.VideoCapture(str(video_path))
        frames = []
        for timestamp in np.linspace(
            window.start, window.end, self.max_frames, endpoint=False
        ):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = capture.read()
            if not ok:
                capture.release()
                raise VLMError(f"Could not decode OpenAI frame at {timestamp}s")
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                capture.release()
                raise VLMError(f"Could not encode OpenAI frame at {timestamp}s")
            frames.append(
                (
                    float(timestamp),
                    "data:image/jpeg;base64,"
                    + base64.b64encode(encoded).decode("ascii"),
                )
            )
        capture.release()
        return frames

    def describe(self, video_path, window):
        self.last_usage = None
        self.last_sanitized_response = None
        self.attempts = []
        frames = self._encode_frames(video_path, window)
        content = [{"type": "input_text", "text": PROMPT}]
        content += [
            {"type": "input_image", "image_url": data, "detail": self.image_detail}
            for _, data in frames
        ]
        self.last_sanitized_request = {
            "model": self.model_name,
            "frame_timestamps": [t for t, _ in frames],
            "image_detail": self.image_detail,
            "frame_count": len(frames),
        }
        last = None
        for attempt in range(1, self.retries + 2):
            started = self._clock()
            response = None
            try:
                response = self._client_instance().responses.parse(
                    model=self.model_name,
                    input=[{"role": "user", "content": content}],
                    text_format=VLMDescription,
                )
                result = response.output_parsed
                if result is None:
                    if _contains_refusal(response):
                        raise VLMRefusalError("OpenAI refused the visual request")
                    raise StructuredOutputError(
                        "OpenAI response did not contain validated structured output"
                    )
                timing_diagnostics = normalize_action_timings(
                    result, window.end - window.start
                )
                usage = _usage(response)
                self.last_usage = usage
                self.last_sanitized_response = {
                    **result.model_dump(),
                    "timing_diagnostics": timing_diagnostics,
                }
                self.attempts.append(
                    {
                        "attempt": attempt,
                        "status": "succeeded",
                        "failure_category": None,
                        "error": None,
                        "model": self.model_name,
                        "duration_seconds": self._clock() - started,
                        "usage_status": "captured"
                        if usage is not None
                        else "unavailable",
                        "usage": usage,
                        "timing_diagnostics": timing_diagnostics,
                    }
                )
                return result
            except Exception as exc:
                last = exc
                category = _failure_category(exc)
                usage = _usage(exc) or _usage(response)
                self.attempts.append(
                    {
                        "attempt": attempt,
                        "status": "failed",
                        "failure_category": category,
                        "error": _safe_error(exc),
                        "model": self.model_name,
                        "duration_seconds": self._clock() - started,
                        "usage_status": "captured"
                        if usage is not None
                        else "unavailable",
                        "usage": usage,
                        "timing_diagnostics": [],
                    }
                )
                retryable = category in {
                    "truncated_json",
                    "schema_validation",
                    "missing_parsed_output",
                    "transport",
                }
                if not retryable or attempt > self.retries:
                    break
        if isinstance(last, VLMRefusalError):
            raise last
        raise VLMError(
            f"OpenAI structured response failed after {len(self.attempts)} attempts: "
            f"{_safe_error(last)}"
        ) from last
