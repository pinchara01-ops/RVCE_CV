import concurrent.futures
import base64
import json
from pathlib import Path
from typing import Protocol, Callable
from .models import VideoWindow, VLMDescription

PROMPT = """Describe only visible evidence in this video window. Never infer sounds. Return strict JSON with keys people_and_clothing, objects_and_colours, actions, object_action_relationships, spatial_relationships, visible_text, scene_context, action_timing (action/start_seconds/end_seconds), uncertainty, and confidence (0 to 1 based only on visible evidence)."""


class VLMError(RuntimeError):
    pass


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
                return VLMDescription.model_validate(json.loads(raw))
            except Exception as exc:
                last = exc
        raise VLMError(
            f"VLM failed after {self.retries + 1} attempts: {last}"
        ) from last


class LocalQwenProvider(RetryingVLMProvider):
    def __init__(
        self,
        model_name="Qwen/Qwen2.5-VL-7B-Instruct",
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
        self.last_usage = None
        self.last_sanitized_request = None
        self.last_sanitized_response = None

    def _client_instance(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key, timeout=self.timeout, max_retries=self.retries
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
        response = self._client_instance().responses.parse(
            model=self.model_name,
            input=[{"role": "user", "content": content}],
            text_format=VLMDescription,
        )
        result = response.output_parsed
        if result is None:
            raise VLMError(
                "OpenAI response did not contain validated structured output"
            )
        self.last_usage = response.usage.model_dump() if response.usage else None
        self.last_sanitized_response = result.model_dump()
        return result
