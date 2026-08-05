"""Central config. All values env-overridable."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Loaded from query_retrieval/.env regardless of the process's cwd (e.g.
# uvicorn launched from the repo root). Real environment variables set
# externally still take precedence - load_dotenv doesn't override existing
# os.environ entries by default.
load_dotenv(Path(__file__).parent / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# Qdrant connection
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT: int = _int("QDRANT_PORT", 6333)
QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY")

# Collection
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "video_windows")

# Named vectors: name -> (dim, distance)
VECTOR_CONFIG: dict[str, dict[str, int | str]] = {
    "visual": {"dim": _int("VISUAL_DIM", 512), "distance": "Cosine"},
    "audio": {"dim": _int("AUDIO_DIM", 512), "distance": "Cosine"},
    "speech": {"dim": _int("SPEECH_DIM", 1024), "distance": "Cosine"},
    "caption": {"dim": _int("CAPTION_DIM", 1024), "distance": "Cosine"},
}

VECTOR_NAMES: list[str] = list(VECTOR_CONFIG.keys())

# Feature flags — when off, corresponding field/vector may be absent from
# payload/points. All downstream code must tolerate missing fields.
ENABLE_OCR: bool = _bool("ENABLE_OCR", True)
ENABLE_OBJECTS: bool = _bool("ENABLE_OBJECTS", True)

# Reciprocal Rank Fusion constant (consumed in fusion.py's rrf_fuse())
RRF_K: int = _int("RRF_K", 60)

# Default search depth per modality
DEFAULT_TOP_K: int = _int("DEFAULT_TOP_K", 15)

# --- Query encoders (Phase 3) ---
DEVICE: str = os.getenv("DEVICE", "cpu")

# visual: X-CLIP text tower, 512-dim (matches VECTOR_CONFIG["visual"]["dim"])
XCLIP_MODEL_NAME: str = os.getenv("XCLIP_MODEL_NAME", "microsoft/xclip-base-patch32")
# audio: CLAP text tower, 512-dim (matches VECTOR_CONFIG["audio"]["dim"])
CLAP_MODEL_NAME: str = os.getenv("CLAP_MODEL_NAME", "laion/clap-htsat-unfused")
# speech + caption: BGE-M3, 1024-dim. Same model for both per contract -
# one shared encoder instance, called twice with different query text roles;
# not two separate models.
BGE_M3_MODEL_NAME: str = os.getenv("BGE_M3_MODEL_NAME", "BAAI/bge-m3")

# --- Window merging (Phase 5) ---
# Two same-video windows merge if they overlap in time, or the gap between
# one's end and the next's start is <= this many seconds.
MERGE_GAP_SECONDS: float = float(os.getenv("MERGE_GAP_SECONDS", "5.0"))
