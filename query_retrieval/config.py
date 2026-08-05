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
# Processing/indexing uses one URL setting. Keep host/port as a backwards-
# compatible fallback for existing local .env files, but prefer the shared URL.
QDRANT_URL: str = os.getenv("QDRANT_URL", f"http://{QDRANT_HOST}:{QDRANT_PORT}")
QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY")
# A local Qdrant process can become unavailable (for example while Docker is
# restarting). Bound every request so the browser gets a clear 503 instead of
# an indefinitely spinning search button.
QDRANT_TIMEOUT_SECONDS: float = float(os.getenv("QDRANT_TIMEOUT_SECONDS", "10"))

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

# Keeping X-CLIP, CLAP, and BGE-M3 resident together can exhaust an 8 GB
# demo laptop once Docker/Qdrant is running.  The local launcher enables this
# mode: encode with one model at a time, evict it, then retrieve.  Larger
# deployments can set it to false to trade memory for lower repeat-query
# latency.
QUERY_LOW_MEMORY_MODE: bool = _bool("QUERY_LOW_MEMORY_MODE", False)

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

# A chain of gap-qualifying windows would otherwise merge without limit
# (A-B-C-D-E... all within MERGE_GAP_SECONDS of each other collapses into
# one region spanning the whole chain) - these two caps bound that. Either
# one being exceeded splits the chain into a new region; a long video with
# near-continuous activity can't swallow itself into a single giant result.
MAX_MERGE_DURATION_SECONDS: float = float(os.getenv("MAX_MERGE_DURATION_SECONDS", "60.0"))
MAX_MERGE_WINDOW_COUNT: int = _int("MAX_MERGE_WINDOW_COUNT", 8)

# --- LLM (Groq) - query decomposition and verification ---
# Both features are independently killable and both degrade to exactly
# today's tested behavior (equal-weight, no verification) on any failure -
# see decomposition.py / verification.py module docstrings and the
# README's "Kill switch reference" table.
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
# openai/gpt-oss-20b chosen over qwen/qwen3-32b after live testing both:
# gpt-oss-20b gave consistent 0.42-0.96s latency with clean JSON in a
# separate content field from its reasoning; qwen took 3.4-4.15s, dumped
# raw chain-of-thought into content itself (breaking JSON parsing), and
# failed to complete within its token budget on one run. See README
# Section 2 for the full comparison.
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
# 0 = deterministic, matches what was live-tested. Not exposed as a
# per-call override - both decomposition and verification want the same
# reproducible behavior.
GROQ_TEMPERATURE: float = 0

def _default_decomposition_enabled(key: str | None) -> bool:
    """Pure function, directly unit-testable without reloading this
    module (which would mutate shared global state for every other test
    in the same pytest session)."""
    return bool(key)


# Decomposition defaults ON when a key is present, but this is a genuinely
# separate flag from key-presence (not `bool(GROQ_API_KEY)` inline at
# every call site) specifically so it can be force-disabled even with a
# valid key - e.g. to reproduce/debug the pre-decomposition baseline
# without unsetting the key.
ENABLE_QUERY_DECOMPOSITION: bool = _bool(
    "ENABLE_QUERY_DECOMPOSITION", default=_default_decomposition_enabled(GROQ_API_KEY)
)
# Deliberately much tighter than the old (removed) router's 3s timeout -
# a daemon-thread hard-kill (see groq_client.call_with_hard_timeout),
# not a library-level timeout, so this bound is real regardless of what
# the underlying HTTP call is doing. 2.0s gives comfortable margin above
# real measured single-request latency for this call (0.2-1.3s observed
# across 10 consecutive calls from a normal network path - see README
# Section 2) without being loose enough to mask a genuine problem.
DECOMPOSITION_TIMEOUT_SECONDS: float = float(os.getenv("DECOMPOSITION_TIMEOUT_SECONDS", "2.0"))

# Verification defaults OFF even with a valid key - explicit opt-in, since
# it's a second LLM call path with its own cost/latency/failure surface.
ENABLE_VERIFICATION: bool = _bool("ENABLE_VERIFICATION", False)
VERIFICATION_TIMEOUT_SECONDS: float = float(os.getenv("VERIFICATION_TIMEOUT_SECONDS", "2.0"))
# Only the top-N candidates by fused_score get verified - cost control,
# verification is O(candidates) LLM calls, not O(1).
VERIFICATION_TOP_N: int = _int("VERIFICATION_TOP_N", 5)

# Captions copied from a nearby selected window are useful context but are
# not evidence that the skipped window itself contains the described action.
# Keep their contribution visible but below a direct VLM caption.
CAPTION_INHERITED_WEIGHT: float = float(
    os.getenv("CAPTION_INHERITED_WEIGHT", "0.5")
)
