from __future__ import annotations
from pathlib import Path
import os
from pydantic import BaseModel
from .config import Settings


class ModelStatus(BaseModel):
    component: str
    checkpoint: str
    device: str
    expected_dimension: int | None
    cache_available: bool
    loading_attempted: bool = False
    load_success: bool = False
    provider_kind: str = "real"
    message: str


def _hf_cache() -> Path:
    return Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def _cached(repo_id: str) -> bool:
    return (_hf_cache() / ("models--" + repo_id.replace("/", "--"))).is_dir()


def model_statuses(
    settings: Settings, vlm_mode: str | None = None
) -> list[ModelStatus]:
    mode = vlm_mode or settings.vlm_provider
    specs = [
        (
            "whisper",
            settings.whisper_model,
            f"Systran/faster-whisper-{settings.whisper_model}",
            None,
        ),
        ("visual", "microsoft/xclip-base-patch32", "microsoft/xclip-base-patch32", 512),
        ("audio", "laion/clap-htsat-unfused", "laion/clap-htsat-unfused", 512),
        ("text", "BAAI/bge-m3", "BAAI/bge-m3", 1024),
    ]
    result = []
    for component, checkpoint, cache_id, dimension in specs:
        available = _cached(cache_id)
        result.append(
            ModelStatus(
                component=component,
                checkpoint=checkpoint,
                device=settings.device,
                expected_dimension=dimension,
                cache_available=available,
                message="Cached locally; loading not attempted"
                if available
                else f"Not cached: {cache_id}. Explicit processing action may download it.",
            )
        )
    if mode == "openai":
        result.append(
            ModelStatus(
                component="vlm",
                checkpoint=settings.openai_vlm_model,
                device="hosted",
                expected_dimension=None,
                cache_available=False,
                provider_kind="real",
                message="Hosted OpenAI provider configured"
                if settings.openai_api_key
                else "OPENAI_API_KEY is not configured",
            )
        )
    elif mode == "cosmos":
        result.append(
            ModelStatus(
                component="vlm",
                checkpoint="nvidia/cosmos3-nano-reasoner",
                device="hosted",
                expected_dimension=None,
                cache_available=False,
                provider_kind="real",
                message="Hosted NVIDIA Cosmos provider; enter an NVIDIA API key for this job",
            )
        )
    elif mode == "mock":
        result.append(
            ModelStatus(
                component="vlm",
                checkpoint="deterministic-debug",
                device="none",
                expected_dimension=None,
                cache_available=True,
                provider_kind="mock",
                message="Mock provider; debug collections only",
            )
        )
    elif mode == "selection_only":
        result.append(
            ModelStatus(
                component="vlm",
                checkpoint="none",
                device="none",
                expected_dimension=None,
                cache_available=False,
                provider_kind="placeholder",
                message="VLM calls intentionally skipped",
            )
        )
    else:
        checkpoint = settings.vlm_model
        result.append(
            ModelStatus(
                component="vlm",
                checkpoint=checkpoint,
                device=settings.device,
                expected_dimension=None,
                cache_available=_cached(checkpoint),
                provider_kind="real",
                message="Local Qwen cache found; loading not attempted"
                if _cached(checkpoint)
                else "Local Qwen weights are not cached",
            )
        )
    return result
