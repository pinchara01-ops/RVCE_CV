from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    window_seconds: float = float(os.getenv("WINDOW_SECONDS", "10"))
    stride_seconds: float = float(os.getenv("STRIDE_SECONDS", "5"))
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key: str | None = os.getenv("QDRANT_API_KEY")
    collection_name: str = os.getenv("COLLECTION_NAME", "video_windows")
    device: str = os.getenv("DEVICE", "cpu")
    vlm_provider: str = os.getenv("VLM_PROVIDER", "qwen")
    vlm_model: str = os.getenv("VLM_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    vlm_timeout_seconds: int = int(os.getenv("VLM_TIMEOUT_SECONDS", "120"))


settings = Settings()
