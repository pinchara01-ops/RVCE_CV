"""Query decomposition: break a raw query into per-modality query text and
RRF weights via Gemini, with a three-tier fallback ladder that is never
allowed to block /search for long or fail loudly.

Tier 1 - CACHE: exact match on the raw query string in
decomposition_cache.json (pre-seeded for demo queries - see
seed_decomposition_cache.py). Instant, no network call.

Tier 2 - LIVE LLM: only if ENABLE_QUERY_DECOMPOSITION is on and a key is
configured. Hard-timeout bounded (DECOMPOSITION_TIMEOUT_SECONDS, default
1.0s - see gemini_client.call_with_hard_timeout) - deliberately tighter
than the old (removed) router's 3s, since decomposition sits directly in
the /search request path and a demo can't afford to wait on it.

Tier 3 - FALLBACK: on any failure at all (disabled, no key, timeout,
network error, malformed JSON) - a deterministic result where every
modality's query text is the original query unchanged and every weight is
equal (0.25). This is intentionally identical in effect to "no
decomposition": fusion.rrf_fuse() with all-equal weights preserves exactly
the same ranking the pre-decomposition pipeline produced (see
test_decomposition.py's regression test and fusion.py's weights=None
fast-path, which is what api.py actually uses when
ENABLE_QUERY_DECOMPOSITION is off - the fallback tier here only fires when
decomposition is *enabled* but degrades mid-request).
"""
import json
import logging
import threading
from pathlib import Path

from query_retrieval import config, gemini_client
from query_retrieval.models import DecompositionResult

logger = logging.getLogger(__name__)

MODALITIES = ("visual", "audio", "speech", "caption")

CACHE_PATH = Path(__file__).parent / "decomposition_cache.json"

_cache: dict[str, dict] | None = None
_cache_lock = threading.Lock()

_DECOMPOSITION_PROMPT = """You are a query decomposer for a multimodal video search system with 4 independent search modalities:

- visual: appearance, color, objects, people, actions seen on screen
- audio: non-speech sounds, noises, music, sound effects
- speech: spoken words, dialogue, quotes, what someone said
- caption: generic semantic/scene meaning, events, topics (default catch-all)

Given a user's raw search query, produce a per-modality query string for each of the 4 modalities (rephrase the query to emphasize what that modality would actually search for; if the whole query is already relevant to a modality as-is, you may repeat it unchanged), a list of any required/verifiable conditions implied by the query (short phrases, empty list if none), and a weight per modality (floats summing to 1.0 across the 4, 0.0 for modalities the query has no signal for - a modality can still be searched even at weight 0, so don't omit it).

Respond with ONLY a JSON object, no other text, in exactly this shape:
{"visual_query": "...", "audio_query": "...", "speech_query": "...", "caption_query": "...", "required_conditions": ["..."], "weights": {"visual": 0.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}}

Example:
Query: "a person in a red jacket says thank you near a car horn honking"
{"visual_query": "person wearing a red jacket near a car", "audio_query": "car horn honking", "speech_query": "someone says thank you", "caption_query": "a person in a red jacket says thank you near a car horn honking", "required_conditions": ["person is wearing a red jacket", "a car horn is honking", "someone says thank you"], "weights": {"visual": 0.35, "audio": 0.25, "speech": 0.25, "caption": 0.15}}
"""


def _load_cache() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    with _cache_lock:
        if _cache is not None:
            return _cache
        if CACHE_PATH.exists():
            try:
                _cache = json.loads(CACHE_PATH.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read decomposition cache %s (%s), starting empty", CACHE_PATH, exc)
                _cache = {}
        else:
            _cache = {}
    return _cache


def _fallback_result(query: str) -> DecompositionResult:
    """Deterministic, network-free. Behaviorally equivalent to "no
    decomposition" - every modality gets the original query text and an
    equal 0.25 weight."""
    return DecompositionResult(
        visual_query=query,
        audio_query=query,
        speech_query=query,
        caption_query=query,
        required_conditions=[],
        weights={m: 0.25 for m in MODALITIES},
        tier="fallback",
    )


def _validate_and_build(parsed: dict, query: str) -> DecompositionResult:
    """Raises ValueError if the parsed JSON is missing required fields -
    a partial/malformed response is treated as a full failure (triggers
    the fallback tier), not silently patched with the original query for
    just the missing fields, since a decomposition that's half real and
    half silently substituted is more confusing to debug than an honest
    all-or-nothing result."""
    missing = [f for f in ("visual_query", "audio_query", "speech_query", "caption_query") if f not in parsed]
    if missing:
        raise ValueError(f"decomposition response missing fields: {missing}")

    raw_weights = parsed.get("weights")
    if not isinstance(raw_weights, dict):
        raise ValueError("decomposition response missing/invalid 'weights'")

    weights = {m: max(0.0, float(raw_weights.get(m, 0.0))) for m in MODALITIES}
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("decomposition weights summed to 0")
    weights = {m: w / total for m, w in weights.items()}  # normalize defensively even if LLM's sum drifted from 1.0

    required_conditions = parsed.get("required_conditions", [])
    if not isinstance(required_conditions, list):
        raise ValueError("decomposition response 'required_conditions' is not a list")

    return DecompositionResult(
        visual_query=str(parsed["visual_query"]),
        audio_query=str(parsed["audio_query"]),
        speech_query=str(parsed["speech_query"]),
        caption_query=str(parsed["caption_query"]),
        required_conditions=[str(c) for c in required_conditions],
        weights=weights,
        tier="live",
    )


def _live_decompose(query: str) -> DecompositionResult:
    client = gemini_client.get_client()

    def _call() -> str:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=f'{_DECOMPOSITION_PROMPT}\n\nQuery: "{query}"',
        )
        return response.text

    raw = gemini_client.call_with_hard_timeout(_call, config.DECOMPOSITION_TIMEOUT_SECONDS)
    parsed = gemini_client.parse_json_response(raw)
    return _validate_and_build(parsed, query)


def decompose_query(query: str) -> DecompositionResult:
    """Decompose `query` via the three-tier ladder. Never raises, never
    blocks longer than DECOMPOSITION_TIMEOUT_SECONDS."""
    cache = _load_cache()
    if query in cache:
        logger.info("Decomposition tier=cache query=%r", query)
        return DecompositionResult(**{**cache[query], "tier": "cache"})

    if not config.ENABLE_QUERY_DECOMPOSITION:
        logger.info("Decomposition tier=fallback query=%r reason=disabled", query)
        return _fallback_result(query)

    if not config.GEMINI_API_KEY:
        logger.info("Decomposition tier=fallback query=%r reason=no_api_key", query)
        return _fallback_result(query)

    try:
        result = _live_decompose(query)
    except Exception as exc:  # noqa: BLE001 - any live-tier failure must fall back, never raise
        logger.info("Decomposition tier=fallback query=%r reason=%s", query, exc)
        return _fallback_result(query)

    logger.info("Decomposition tier=live query=%r weights=%s", query, result.weights)
    return result
