from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    window_seconds: float = 10.0
    stride_seconds: float = 5.0
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    collection_name: str = "video_windows"
    device: str = "cpu"
    batch_size: int = 8
    whisper_model: str = "small"
    vlm_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    vlm_timeout_seconds: float = 120
    vlm_retries: int = 2

    @classmethod
    def from_env(cls):
        return cls(
            window_seconds=float(os.getenv("WINDOW_SECONDS", "10")),
            stride_seconds=float(os.getenv("STRIDE_SECONDS", "5")),
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY"),
            collection_name=os.getenv("COLLECTION_NAME", "video_windows"),
            device=os.getenv("DEVICE", "cpu"),
            batch_size=int(os.getenv("BATCH_SIZE", "8")),
            whisper_model=os.getenv("WHISPER_MODEL", "small"),
            vlm_model=os.getenv("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
            vlm_timeout_seconds=float(os.getenv("VLM_TIMEOUT_SECONDS", "120")),
            vlm_retries=int(os.getenv("VLM_RETRIES", "2")),
        )


settings = Settings.from_env()
