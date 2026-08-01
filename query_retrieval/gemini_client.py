"""Shared Gemini client singleton, hard-timeout call wrapper, and JSON
response parser - used by decomposition.py and verification.py, the only
two Gemini call sites in this module.

The timeout mechanism (call_with_hard_timeout) deliberately does not rely
on the SDK's own request-timeout parameter: a library-level timeout only
bounds a specific network call, and can still leave the calling thread
blocked longer than expected on retries, DNS resolution, or connection
setup that happens before the timeout clock the library thinks it's
tracking even starts. Running the call in a daemon thread and hard-joining
it with a wall-clock deadline bounds the *caller's* wait time exactly,
regardless of what the underlying call is doing - if the deadline passes,
this function returns control immediately and treats it as a failure. The
daemon thread itself may still be running in the background afterwards
(Python cannot forcibly kill a thread); since it's a daemon thread, it
does not block process exit and is simply abandoned.
"""
import json
import logging
import re
import threading

from query_retrieval import config

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()


def get_client():
    """Lazy-singleton Gemini client. Raises if GEMINI_API_KEY is unset -
    callers must check config.GEMINI_API_KEY themselves first so the
    failure reason is clear in logs, not just "AttributeError somewhere"."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from google import genai  # local import: optional dependency, only needed on the live-LLM path

                _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def call_with_hard_timeout(fn, timeout_seconds: float):
    """Run fn() in a daemon thread; raise TimeoutError if it hasn't
    finished within timeout_seconds. Never blocks the caller longer than
    timeout_seconds, regardless of what fn() is actually doing.
    """
    result: dict = {}
    error: dict = {}

    def _run():
        try:
            result["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            error["exc"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        raise TimeoutError(f"LLM call exceeded {timeout_seconds}s hard timeout")
    if "exc" in error:
        raise error["exc"]
    return result["value"]


def parse_json_response(raw: str) -> dict:
    """Defensively parse an LLM's JSON response: strip markdown code
    fences if present, extract the first {...} block if there's stray
    text around it, then json.loads. Raises ValueError on any failure -
    callers treat that as "malformed JSON" and fall back accordingly.
    """
    text = raw.strip()

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        text = brace_match.group(0)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON from LLM: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON is not an object")

    return parsed
