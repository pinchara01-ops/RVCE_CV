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
import gc
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from query_retrieval import config
from query_retrieval.models import DecompositionResult

logger = logging.getLogger(__name__)

# name -> loaded (model, tokenizer) or (model, None) for sentence-transformers
_model_cache: dict[str, tuple] = {}

# speech and caption share one BGE-M3 instance (see module docstring) - two
# threads calling .encode() on the same SentenceTransformer concurrently
# isn't documented as thread-safe, so serialize just that shared model.
# X-CLIP and CLAP each have their own instance and don't need this.
_bge_m3_lock = threading.Lock()
# Low-memory search loads one encoder at a time and must not let concurrent
# HTTP requests evict a model that another request is actively using.
_low_memory_encode_lock = threading.Lock()

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


def _release(name: str) -> None:
    """Drop a locally loaded encoder so Docker/Qdrant keeps enough RAM.

    Model files remain in Hugging Face's on-disk cache; this only evicts the
    Python model instance.  CUDA cache release is harmless on CPU-only runs.
    """
    model = _model_cache.pop(name, None)
    if model is None:
        return
    del model
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # pragma: no cover - cleanup must never break search
        pass


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


def _encode_many(queries: dict[str, str]) -> dict[str, list[float]]:
    """Encode a per-modality dict of query strings concurrently, one
    encoder call per entry. Each is a separate model forward pass (X-CLIP,
    CLAP, BGE-M3 x2) with no shared mutable state between them (see
    _bge_m3_lock for the one exception), so running them concurrently is
    safe and turns ~4 sequential model calls into roughly the cost of the
    slowest one.

    If encoding a modality fails mid-query (e.g. OOM), that modality is
    logged and dropped from the result - callers proceed with whatever
    modalities succeeded rather than failing the whole request. If every
    modality fails, an empty dict is returned and the caller (api.py)
    treats that as a hard failure, not a silent empty search.
    """
    futures = {
        _encode_executor.submit(_safe_encode, modality, _ENCODERS[modality], text): modality
        for modality, text in queries.items()
        if modality in _ENCODERS
    }
    vectors: dict[str, list[float]] = {}
    for future, modality in futures.items():
        result = future.result()
        if result is not None:
            vectors[modality] = result
    return vectors


def encode_query(query: str) -> dict[str, list[float]]:
    """Encode `query` identically for all 4 modalities, concurrently.

    Always encodes every modality (architecture change: query routing was
    removed - RRF fusion suppresses irrelevant modalities through rank/
    weight, so gating encoding on a router's per-query weights isn't
    needed). This is the path used whenever query decomposition is off
    (ENABLE_QUERY_DECOMPOSITION=false) or unavailable - see
    encode_decomposed() for the per-modality-query-text variant used when
    decomposition is on.
    """
    return _encode_many({modality: query for modality in _ENCODERS})


def _encode_low_memory(queries: dict[str, str]) -> dict[str, list[float]]:
    """Encode all requested modalities without keeping all models resident."""
    with _low_memory_encode_lock:
        vectors: dict[str, list[float]] = {}
        for modality, cache_key, encoder in (
            ("visual", "xclip", encode_visual_text),
            ("audio", "clap", encode_audio_text),
        ):
            if modality not in queries:
                continue
            try:
                value = _safe_encode(modality, encoder, queries[modality])
                if value is not None:
                    vectors[modality] = value
            finally:
                _release(cache_key)

        # Speech and caption use the same BGE-M3 instance.  Keep it only for
        # the two adjacent encodes, then release it before Qdrant retrieval.
        try:
            for modality, encoder in (
                ("speech", encode_speech_text),
                ("caption", encode_caption_text),
            ):
                if modality not in queries:
                    continue
                value = _safe_encode(modality, encoder, queries[modality])
                if value is not None:
                    vectors[modality] = value
        finally:
            _release("bge_m3")
        return vectors


def encode_query_low_memory(query: str) -> dict[str, list[float]]:
    """Four-modality query encoding for constrained local machines."""
    return _encode_low_memory({modality: query for modality in _ENCODERS})


def encode_decomposed(decomposition: DecompositionResult) -> dict[str, list[float]]:
    """Encode each modality's decomposition-specific query text with its
    own encoder, concurrently - used when query decomposition is enabled.
    Zero-weight modalities may still be encoded so a malformed live
    decomposition can fall back safely, but api.py deliberately skips their
    Qdrant searches when at least one modality has a positive weight.
    """
    return _encode_many({
        "visual": decomposition.visual_query,
        "audio": decomposition.audio_query,
        "speech": decomposition.speech_query,
        "caption": decomposition.caption_query,
    })


def encode_decomposed_low_memory(
    decomposition: DecompositionResult,
) -> dict[str, list[float]]:
    """Low-memory counterpart to ``encode_decomposed``."""
    return _encode_low_memory({
        "visual": decomposition.visual_query,
        "audio": decomposition.audio_query,
        "speech": decomposition.speech_query,
        "caption": decomposition.caption_query,
    })
