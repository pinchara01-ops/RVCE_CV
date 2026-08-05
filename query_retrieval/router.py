"""Query router: assign per-modality search weights to a raw text query.

Rule-based only (V1 architecture decision): deterministic, no API
dependency, no network latency, reliable for demo. No LLM path.

Public entrypoint: classify_query(query) -> {"visual": float, "audio": float,
"speech": float, "caption": float}, weights sum to 1.0.
"""
import logging

from query_retrieval import config

logger = logging.getLogger(__name__)

MODALITIES = ("visual", "audio", "speech", "caption")

# Keyword lists for the rule-based classifier.
_VISUAL_KEYWORDS = (
    "wearing", "shirt", "jacket", "dress", "color", "red", "blue", "green",
    "yellow", "black", "white", "person", "man", "woman", "dog", "cat", "car",
    "holding", "standing", "sitting", "walking", "running", "looks", "looking",
    "appears", "visible", "seen", "hat", "glasses",
)
_AUDIO_KEYWORDS = (
    "sound", "noise", "loud", "crash", "bang", "music", "song", "playing",
    "ringing", "siren", "alarm", "clap", "applause", "scream", "bark",
    "barking", "engine", "horn", "explosion", "glass", "breaking", "break",
    "shatter", "shattering", "thud", "beep", "buzz", "hum", "roar", "hiss",
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
    """Assign per-modality search weights to a raw text query.

    Rule-based keyword classifier only. Always returns valid weights
    summing to 1.0; never raises.
    """
    weights = _fallback_classify(query)
    final_weights = _threshold_and_normalize(weights)
    logger.info("Router weights=%s query=%r", final_weights, query)
    return final_weights
