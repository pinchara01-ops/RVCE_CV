"""Text-only candidate verification via Gemini: given a retrieved
candidate's transcript/caption/matched_modalities and a query's required
conditions, check whether the evidence actually supports the match.

This is deliberately TEXT-ONLY. There is no frame/video-access field on
the payload schema today (see README "Known blockers for future work") -
this module does not invent file access to work around that; it verifies
against exactly the text evidence the pipeline already has (transcript,
caption, matched_modalities) and nothing else.

Every call is hard-timeout bounded (VERIFICATION_TIMEOUT_SECONDS, default
2.0s - see gemini_client.call_with_hard_timeout) and every failure mode
(timeout, malformed JSON, no key, flag off) collapses to exactly one
state: "verification_unavailable". This is a hard requirement, not a
convenience - a verification check that silently became a false "match"
on failure would be worse than no verification at all. See
test_verification.py::test_forced_failure_never_produces_false_positive_match.
"""
import logging

from query_retrieval import config, gemini_client
from query_retrieval.models import SearchResultItem, VerificationResult

logger = logging.getLogger(__name__)

_VERIFICATION_PROMPT = """You are verifying a single candidate video window against a search query, using ONLY the text evidence provided below - you do not have access to the actual video, audio, or frames.

Query: "{query}"
Required conditions to check: {conditions}

Evidence for this candidate:
- transcript: {transcript}
- caption: {caption}
- matched search modalities: {matched_modalities}

For each required condition, decide if the evidence satisfies it, contradicts it, or simply doesn't mention it (missing - not the same as contradicting). Then give an overall match verdict: true only if the evidence is consistent with the query and no required condition is contradicted.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"match": true, "confidence": 0.0, "satisfied_conditions": ["..."], "missing_conditions": ["..."], "contradictions": ["..."], "evidence": "one-sentence explanation"}}
"""


def _build_prompt(candidate: SearchResultItem, original_query: str, required_conditions: list[str]) -> str:
    return _VERIFICATION_PROMPT.format(
        query=original_query,
        conditions=required_conditions or "(none specified)",
        transcript=candidate.transcript or "(none)",
        caption=candidate.caption or "(none)",
        matched_modalities=", ".join(candidate.matched_modalities) or "(none)",
    )


def _live_verify(candidate: SearchResultItem, original_query: str, required_conditions: list[str]) -> dict:
    client = gemini_client.get_client()

    def _call() -> str:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=_build_prompt(candidate, original_query, required_conditions),
        )
        return response.text

    raw = gemini_client.call_with_hard_timeout(_call, config.VERIFICATION_TIMEOUT_SECONDS)
    parsed = gemini_client.parse_json_response(raw)

    if "match" not in parsed:
        raise ValueError("verification response missing 'match' field")

    return {
        "match": bool(parsed["match"]),
        "confidence": float(parsed.get("confidence", 0.0)),
        "satisfied_conditions": [str(c) for c in parsed.get("satisfied_conditions", [])],
        "missing_conditions": [str(c) for c in parsed.get("missing_conditions", [])],
        "contradictions": [str(c) for c in parsed.get("contradictions", [])],
        "evidence": str(parsed.get("evidence", "")),
    }


def verify_candidate(
    candidate: SearchResultItem, original_query: str, required_conditions: list[str]
) -> VerificationResult:
    """Verify one candidate. Never raises. `state` is always exactly one
    of "verified" / "rejected" / "verification_unavailable" - a failure
    can only ever produce "verification_unavailable", never a match."""
    if not config.ENABLE_VERIFICATION:
        logger.info("Verification tier=unavailable candidate=%s reason=disabled", candidate.window_id)
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verification_unavailable",
            reason="verification disabled (ENABLE_VERIFICATION=false)",
        )

    if not config.GEMINI_API_KEY:
        logger.info("Verification tier=unavailable candidate=%s reason=no_api_key", candidate.window_id)
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verification_unavailable",
            reason="GEMINI_API_KEY not configured",
        )

    try:
        parsed = _live_verify(candidate, original_query, required_conditions)
    except Exception as exc:  # noqa: BLE001 - any failure at all collapses to verification_unavailable
        logger.info("Verification tier=unavailable candidate=%s reason=%s", candidate.window_id, exc)
        return VerificationResult(
            candidate_id=candidate.window_id,
            state="verification_unavailable",
            reason=str(exc),
        )

    state = "verified" if parsed["match"] else "rejected"
    logger.info("Verification tier=live candidate=%s state=%s confidence=%.2f", candidate.window_id, state, parsed["confidence"])
    return VerificationResult(
        candidate_id=candidate.window_id,
        state=state,
        match=parsed["match"],
        confidence=parsed["confidence"],
        satisfied_conditions=parsed["satisfied_conditions"],
        missing_conditions=parsed["missing_conditions"],
        contradictions=parsed["contradictions"],
        evidence=parsed["evidence"],
    )
