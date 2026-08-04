from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


# Keep local configuration optional and explicit.  Real environment values
# remain authoritative because load_dotenv never overrides them by default.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env.processing")
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    window_seconds: float = 10.0
    stride_seconds: float = 5.0
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_timeout_seconds: float = 10.0
    collection_name: str = "video_windows"
    device: str = "cpu"
    batch_size: int = 8
    whisper_model: str = "small"
    vlm_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    vlm_provider: str = "local"
    vlm_base_url: str | None = None
    vlm_api_key: str | None = field(default=None, repr=False)
    vlm_timeout_seconds: float = 120
    vlm_retries: int = 2
    vlm_selection_enabled: bool = True
    vlm_visual_change_threshold: float = 0.12
    vlm_audio_change_threshold: float = 0.15
    vlm_speech_change_threshold: float = 0.18
    vlm_change_weight_visual: float = 0.55
    vlm_change_weight_audio: float = 0.25
    vlm_change_weight_speech: float = 0.20
    vlm_combined_change_threshold: float = 0.13
    vlm_max_gap_windows: int = 3
    vlm_max_selected_ratio: float = 0.60
    vlm_context_neighbours: int = 1
    vlm_min_direct_confidence: float = 0.50
    openai_vlm_model: str = "gpt-4.1-mini"
    openai_api_key: str | None = field(default=None, repr=False)
    openai_vlm_timeout_seconds: float = 120
    openai_vlm_retries: int = 2
    openai_vlm_image_detail: str = "low"
    openai_vlm_max_frames: int = 4
    max_windows: int | None = None

    def __post_init__(self):
        if self.qdrant_timeout_seconds <= 0:
            raise ValueError("QDRANT_TIMEOUT_SECONDS must be positive")
        thresholds = (
            self.vlm_visual_change_threshold,
            self.vlm_audio_change_threshold,
            self.vlm_speech_change_threshold,
            self.vlm_combined_change_threshold,
        )
        if any(not 0 <= value <= 2 for value in thresholds):
            raise ValueError("VLM cosine-distance thresholds must be within 0..2")
        weights = (
            self.vlm_change_weight_visual,
            self.vlm_change_weight_audio,
            self.vlm_change_weight_speech,
        )
        if any(value < 0 for value in weights) or sum(weights) <= 0:
            raise ValueError(
                "VLM change weights must be non-negative with a positive sum"
            )
        if self.vlm_max_gap_windows < 1:
            raise ValueError("VLM_MAX_GAP_WINDOWS must be at least one")
        if not 0 <= self.vlm_max_selected_ratio <= 1:
            raise ValueError("VLM_MAX_SELECTED_RATIO must be within 0..1")
        if self.vlm_context_neighbours < 0:
            raise ValueError("VLM_CONTEXT_NEIGHBOURS must be non-negative")
        if not 0 <= self.vlm_min_direct_confidence <= 1:
            raise ValueError("VLM_MIN_DIRECT_CONFIDENCE must be within 0..1")
        if self.openai_vlm_image_detail not in {"low", "high", "auto"}:
            raise ValueError("OPENAI_VLM_IMAGE_DETAIL must be low, high, or auto")
        if self.openai_vlm_max_frames < 1:
            raise ValueError("OPENAI_VLM_MAX_FRAMES must be at least one")
        if self.max_windows is not None and self.max_windows < 1:
            raise ValueError("max_windows must be positive when configured")

    @classmethod
    def from_env(cls):
        return cls(
            window_seconds=float(os.getenv("WINDOW_SECONDS", "10")),
            stride_seconds=float(os.getenv("STRIDE_SECONDS", "5")),
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY"),
            qdrant_timeout_seconds=float(os.getenv("QDRANT_TIMEOUT_SECONDS", "10")),
            collection_name=os.getenv("COLLECTION_NAME", "video_windows"),
            device=os.getenv("DEVICE", "cpu"),
            batch_size=int(os.getenv("BATCH_SIZE", "8")),
            whisper_model=os.getenv("WHISPER_MODEL", "small"),
            vlm_model=os.getenv("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
            vlm_provider=os.getenv("VLM_PROVIDER", "local"),
            vlm_base_url=os.getenv("VLM_BASE_URL"),
            vlm_api_key=os.getenv("VLM_API_KEY"),
            vlm_timeout_seconds=float(os.getenv("VLM_TIMEOUT_SECONDS", "120")),
            vlm_retries=int(os.getenv("VLM_RETRIES", "2")),
            vlm_selection_enabled=os.getenv("VLM_SELECTION_ENABLED", "true").lower()
            in {"1", "true", "yes"},
            vlm_visual_change_threshold=float(
                os.getenv("VLM_VISUAL_CHANGE_THRESHOLD", "0.12")
            ),
            vlm_audio_change_threshold=float(
                os.getenv("VLM_AUDIO_CHANGE_THRESHOLD", "0.15")
            ),
            vlm_speech_change_threshold=float(
                os.getenv("VLM_SPEECH_CHANGE_THRESHOLD", "0.18")
            ),
            vlm_change_weight_visual=float(
                os.getenv("VLM_CHANGE_WEIGHT_VISUAL", "0.55")
            ),
            vlm_change_weight_audio=float(os.getenv("VLM_CHANGE_WEIGHT_AUDIO", "0.25")),
            vlm_change_weight_speech=float(
                os.getenv("VLM_CHANGE_WEIGHT_SPEECH", "0.20")
            ),
            vlm_combined_change_threshold=float(
                os.getenv("VLM_COMBINED_CHANGE_THRESHOLD", "0.13")
            ),
            vlm_max_gap_windows=int(os.getenv("VLM_MAX_GAP_WINDOWS", "3")),
            vlm_max_selected_ratio=float(os.getenv("VLM_MAX_SELECTED_RATIO", "0.60")),
            vlm_context_neighbours=int(os.getenv("VLM_CONTEXT_NEIGHBOURS", "1")),
            vlm_min_direct_confidence=float(
                os.getenv("VLM_MIN_DIRECT_CONFIDENCE", "0.50")
            ),
            openai_vlm_model=os.getenv("OPENAI_VLM_MODEL", "gpt-4.1-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_vlm_timeout_seconds=float(
                os.getenv("OPENAI_VLM_TIMEOUT_SECONDS", "120")
            ),
            openai_vlm_retries=int(os.getenv("OPENAI_VLM_RETRIES", "2")),
            openai_vlm_image_detail=os.getenv("OPENAI_VLM_IMAGE_DETAIL", "low"),
            openai_vlm_max_frames=int(os.getenv("OPENAI_VLM_MAX_FRAMES", "4")),
        )


settings = Settings.from_env()
