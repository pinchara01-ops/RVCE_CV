from __future__ import annotations
import hashlib
import json

LOCAL_FIELDS = (
    "video_id",
    "whisper_model",
    "visual_model",
    "audio_model",
    "text_model",
    "window_seconds",
    "stride_seconds",
)
VLM_FIELDS = LOCAL_FIELDS + (
    "vlm_provider",
    "vlm_model",
    "caption_prompt_version",
    "openai_image_detail",
    "openai_max_frames",
)


def cache_key(stage: str, config: dict) -> str:
    fields = (
        LOCAL_FIELDS
        if stage in {"transcript", "visual", "audio", "speech"}
        else VLM_FIELDS
    )
    relevant = {key: config.get(key) for key in fields}
    raw = json.dumps(
        {"stage": stage, "config": relevant}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_invalidation(before: dict, after: dict) -> dict[str, bool]:
    stages = ("transcript", "visual", "audio", "speech", "vlm", "caption")
    return {
        stage: cache_key(stage, before) != cache_key(stage, after) for stage in stages
    }
