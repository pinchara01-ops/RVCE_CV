"""Per-modality query text encoders.

Models are loaded once via a lazy-singleton cache (first call loads and
caches; subsequent calls reuse the cached model) so a per-request encode
never pays load cost. For production/demo use, call warmup() once at
server startup so a broken model (missing weights, no GPU, OOM) fails
loudly before the first real query, not silently mid-demo.

speech and caption both use BGE-M3 - this is intentional per contract
(shared embedding space for text-vs-text semantic search), not a bug:
one model instance, two thin wrapper functions.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from query_retrieval import config

logger = logging.getLogger(__name__)

# name -> loaded (model, tokenizer) or (model, None) for sentence-transformers
_model_cache: dict[str, tuple] = {}

# speech and caption share one BGE-M3 instance (see module docstring) - two
# threads calling .encode() on the same SentenceTransformer concurrently
# isn't documented as thread-safe, so serialize just that shared model.
# X-CLIP and CLAP each have their own instance and don't need this.
_bge_m3_lock = threading.Lock()

# Reused across requests rather than a per-call `with ThreadPoolExecutor()`
# to avoid paying thread-spawn cost on every query.
_encode_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="encode")


def _load_xclip():
    import torch
    from transformers import AutoTokenizer, XCLIPModel

    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(config.XCLIP_MODEL_NAME)
    model = XCLIPModel.from_pretrained(config.XCLIP_MODEL_NAME).to(config.DEVICE).eval()
    logger.info(
        "Loaded X-CLIP text encoder '%s' on %s in %.1fs",
        config.XCLIP_MODEL_NAME, config.DEVICE, time.time() - t0,
    )
    return model, tokenizer


def _load_clap():
    import torch
    from transformers import AutoTokenizer, ClapModel

    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(config.CLAP_MODEL_NAME)
    model = ClapModel.from_pretrained(config.CLAP_MODEL_NAME).to(config.DEVICE).eval()
    logger.info(
        "Loaded CLAP text encoder '%s' on %s in %.1fs",
        config.CLAP_MODEL_NAME, config.DEVICE, time.time() - t0,
    )
    return model, tokenizer


def _load_bge_m3():
    from sentence_transformers import SentenceTransformer

    t0 = time.time()
    model = SentenceTransformer(config.BGE_M3_MODEL_NAME, device=config.DEVICE)
    logger.info(
        "Loaded BGE-M3 encoder '%s' on %s in %.1fs (shared by speech + caption)",
        config.BGE_M3_MODEL_NAME, config.DEVICE, time.time() - t0,
    )
    return model, None


def _get(name: str, loader: Callable[[], tuple]) -> tuple:
    if name not in _model_cache:
        _model_cache[name] = loader()
    return _model_cache[name]


def encode_visual_text(query: str) -> list[float]:
    """X-CLIP text encoder, 512-dim."""
    import torch

    model, tokenizer = _get("xclip", _load_xclip)
    inputs = tokenizer([query], padding=True, truncation=True, return_tensors="pt").to(config.DEVICE)
    with torch.no_grad():
        output = model.get_text_features(**inputs)
    # This transformers version returns BaseModelOutputWithPooling (not a
    # bare tensor) from get_text_features - the projected embedding lives
    # in .pooler_output, shape (batch, dim).
    features = output.pooler_output if hasattr(output, "pooler_output") else output
    return features[0].cpu().float().tolist()


def encode_audio_text(query: str) -> list[float]:
    """CLAP text encoder, 512-dim."""
    import torch

    model, tokenizer = _get("clap", _load_clap)
    inputs = tokenizer([query], padding=True, truncation=True, return_tensors="pt").to(config.DEVICE)
    with torch.no_grad():
        output = model.get_text_features(**inputs)
    features = output.pooler_output if hasattr(output, "pooler_output") else output
    return features[0].cpu().float().tolist()


def encode_speech_text(query: str) -> list[float]:
    """BGE-M3 dense encoder, 1024-dim. Shared model with encode_caption_text."""
    model, _ = _get("bge_m3", _load_bge_m3)
    with _bge_m3_lock:
        return model.encode(query, normalize_embeddings=True).tolist()


def encode_caption_text(query: str) -> list[float]:
    """BGE-M3 dense encoder, 1024-dim. Shared model with encode_speech_text."""
    model, _ = _get("bge_m3", _load_bge_m3)
    with _bge_m3_lock:
        return model.encode(query, normalize_embeddings=True).tolist()


_ENCODERS: dict[str, Callable[[str], list[float]]] = {
    "visual": encode_visual_text,
    "audio": encode_audio_text,
    "speech": encode_speech_text,
    "caption": encode_caption_text,
}


def warmup() -> None:
    """Eagerly load every encoder model. Call once at server startup so a
    broken model fails loudly at boot, not silently on the first query.
    """
    logger.info("Warming up query encoders on device=%s ...", config.DEVICE)
    _get("xclip", _load_xclip)
    _get("clap", _load_clap)
    _get("bge_m3", _load_bge_m3)  # loads once, covers both speech + caption
    logger.info("Query encoders warmup complete")


def _safe_encode(modality: str, encode_fn: Callable[[str], list[float]], query: str) -> list[float] | None:
    try:
        return encode_fn(query)
    except Exception as exc:  # noqa: BLE001 - one modality failing must not fail the request
        logger.warning("Encoding failed for modality '%s': %s", modality, exc)
        return None


def encode_query(query: str) -> dict[str, list[float]]:
    """Encode `query` for all 4 modalities, concurrently.

    Always encodes every modality (architecture change: query routing was
    removed - Weighted RRF suppresses irrelevant modalities through rank,
    so gating encoding on a router's per-query weights isn't needed). The 4
    encoder calls run in a thread pool rather than sequentially - each is a
    separate model forward pass (X-CLIP, CLAP, BGE-M3 x2) with no shared
    mutable state between them (see _bge_m3_lock for the one exception),
    so running them concurrently is safe and turns ~4 sequential model
    calls into roughly the cost of the slowest one.

    If encoding a modality fails mid-query (e.g. OOM), that modality is
    logged and dropped from the result - callers proceed with whatever
    modalities succeeded rather than failing the whole request. If every
    modality fails, an empty dict is returned and the caller (api.py)
    treats that as a hard failure, not a silent empty search.
    """
    futures = {
        _encode_executor.submit(_safe_encode, modality, encode_fn, query): modality
        for modality, encode_fn in _ENCODERS.items()
    }
    vectors: dict[str, list[float]] = {}
    for future, modality in futures.items():
        result = future.result()
        if result is not None:
            vectors[modality] = result
    return vectors
