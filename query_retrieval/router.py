"""Query router: classify a raw text query into per-modality search weights.

Primary path: LLM (Anthropic) classification, timeout-bounded.
Fallback path: keyword/rule-based classifier, always available, no network.

Public entrypoint: classify_query(query) -> {"visual": float, "audio": float,
"speech": float, "caption": float}, weights sum to 1.0.
"""
import json
import logging
import re

from query_retrieval import config

logger = logging.getLogger(__name__)

MODALITIES = ("visual", "audio", "speech", "caption")

_SYSTEM_PROMPT = """You are a query router for a multimodal video search system. \
Given a user's search query, decide how much weight to give each of 4 search \
modalities when retrieving matching video windows:

- visual: appearance, color, objects, people, actions seen on screen
- audio: non-speech sounds, noises, music, sound effects
- speech: spoken words, dialogue, quotes, what someone said
- caption: generic semantic/scene meaning, events, topics (default catch-all)

Respond with ONLY a JSON object of 4 floats summing to 1.0, no other text:
{"visual": <float>, "audio": <float>, "speech": <float>, "caption": <float>}

Examples:
Query: "person in a red jacket"
{"visual": 1.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}

Query: "loud crash sound"
{"visual": 0.0, "audio": 1.0, "speech": 0.0, "caption": 0.0}

Query: "someone says thank you"
{"visual": 0.0, "audio": 0.0, "speech": 1.0, "caption": 0.0}

Query: "a birthday celebration"
{"visual": 0.1, "audio": 0.0, "speech": 0.0, "caption": 0.9}

Query: "man shouting in a blue shirt"
{"visual": 0.4, "audio": 0.3, "speech": 0.3, "caption": 0.0}
"""

# Keyword lists for the rule-based fallback classifier.
_VISUAL_KEYWORDS = (
    "wearing", "shirt", "jacket", "dress", "color", "red", "blue", "green",
    "yellow", "black", "white", "person", "man", "woman", "dog", "cat", "car",
    "holding", "standing", "sitting", "walking", "running", "looks", "looking",
    "appears", "visible", "seen", "hat", "glasses",
)
_AUDIO_KEYWORDS = (
    "sound", "noise", "loud", "crash", "bang", "music", "song", "playing",
    "ringing", "siren", "alarm", "clap", "applause", "scream", "bark",
    "barking", "engine", "horn", "explosion",
)
_SPEECH_KEYWORDS = (
    "says", "said", "talk", "talks", "talking", "mention", "mentions",
    "mentioned", "quote", "speech", "speaking", "conversation", "dialogue",
    "asks", "asked", "answer", "answered", "shout", "shouting", "yelling",
)


def _fallback_classify(query: str) -> dict[str, float]:
    """Rule-based keyword classifier. Always returns valid weights, never raises."""
    q = query.lower()
    scores = {m: 0.0 for m in MODALITIES}

    for kw in _VISUAL_KEYWORDS:
        if kw in q:
            scores["visual"] += 1.0
    for kw in _AUDIO_KEYWORDS:
        if kw in q:
            scores["audio"] += 1.0
    for kw in _SPEECH_KEYWORDS:
        if kw in q:
            scores["speech"] += 1.0

    if sum(scores.values()) == 0:
        # No keyword hits: generic/semantic query, use caption as default catch-all.
        scores["caption"] = 1.0

    total = sum(scores.values())
    return {m: scores[m] / total for m in MODALITIES}


def _parse_llm_json(raw: str) -> dict[str, float]:
    """Defensively parse the LLM's JSON response. Raises ValueError on failure."""
    text = raw.strip()
    # Strip markdown code fences if present (```json ... ``` or ``` ... ```).
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Fall back to extracting the first {...} block if there's stray text around it.
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        text = brace_match.group(0)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON from LLM: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON is not an object")

    weights: dict[str, float] = {}
    for modality in MODALITIES:
        value = parsed.get(modality, 0.0)
        try:
            weights[modality] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Non-numeric weight for '{modality}': {value!r}") from exc

    return weights


def _llm_classify(query: str) -> dict[str, float]:
    """Call Anthropic to classify the query. Raises on any failure (caller falls back)."""
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    import anthropic  # local import: keep the dependency optional for fallback-only use

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ROUTER_MODEL,
        max_tokens=100,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f'Query: "{query}"'}],
        timeout=config.ROUTER_TIMEOUT_SECONDS,
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    return _parse_llm_json(raw)


def _threshold_and_normalize(weights: dict[str, float]) -> dict[str, float]:
    """Zero out weights below MIN_MODALITY_WEIGHT and renormalize to sum to 1.0.

    If everything ends up zero, default to caption=1.0 as a safe generic fallback.
    """
    clamped = {m: max(0.0, weights.get(m, 0.0)) for m in MODALITIES}
    total = sum(clamped.values())
    if total <= 0:
        return {**{m: 0.0 for m in MODALITIES}, "caption": 1.0}

    normalized = {m: clamped[m] / total for m in MODALITIES}
    thresholded = {m: (w if w >= config.MIN_MODALITY_WEIGHT else 0.0) for m, w in normalized.items()}

    remaining_total = sum(thresholded.values())
    if remaining_total <= 0:
        return {**{m: 0.0 for m in MODALITIES}, "caption": 1.0}

    return {m: thresholded[m] / remaining_total for m in MODALITIES}


def classify_query(query: str) -> dict[str, float]:
    """Classify a raw text query into per-modality search weights.

    Tries LLM classification first (timeout-bounded); falls back to a
    keyword-based classifier on any error, timeout, invalid JSON, or missing
    API key. Always returns valid weights summing to 1.0; never raises.
    """
    method = "llm"
    try:
        weights = _llm_classify(query)
    except Exception as exc:  # noqa: BLE001 - any LLM failure must fall back, not crash
        logger.info("LLM classification failed (%s), using fallback classifier", exc)
        method = "fallback"
        weights = _fallback_classify(query)

    final_weights = _threshold_and_normalize(weights)
    logger.info("Router method=%s query=%r weights=%s", method, query, final_weights)
    return final_weights
