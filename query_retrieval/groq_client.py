"""Shared Groq client singleton, hard-timeout call wrapper, and JSON
response parser - used by decomposition.py and verification.py, the only
two LLM call sites in this module.

Groq's chat completions endpoint is OpenAI-compatible
(https://api.groq.com/openai/v1/chat/completions), so this is a plain
httpx REST call - no SDK dependency needed.

gpt-oss-20b (the configured model, see config.GROQ_MODEL) returns its
chain-of-thought reasoning and its final answer as two SEPARATE fields on
the response message object: "reasoning" and "content". This is expected
API behavior, not an error. chat_completion() below deliberately parses
ONLY message["content"] and ignores message["reasoning"] entirely - if
content is empty/missing (even with a non-empty reasoning field), that is
treated as a malformed-response failure and raises, so callers fall back
exactly as they would for any other malformed response. There is no
workaround path that tries to extract JSON out of the reasoning field
instead - a response with no content is a failure, not a different
representation of success.

The timeout mechanism (call_with_hard_timeout) deliberately does not rely
on the HTTP client's own request-timeout parameter: a library-level
timeout only bounds a specific network call, and can still leave the
calling thread blocked longer than expected on retries, DNS resolution,
or connection setup that happens before the timeout clock the library
thinks it's tracking even starts. Running the call in a daemon thread and
hard-joining it with a wall-clock deadline bounds the *caller's* wait time
exactly, regardless of what the underlying call is doing - if the
deadline passes, this function returns control immediately and treats it
as a failure. The daemon thread itself may still be running in the
background afterwards (Python cannot forcibly kill a thread); since it's
a daemon thread, it does not block process exit and is simply abandoned.
"""
import json
import logging
import re
import threading

import httpx

from query_retrieval import config

logger = logging.getLogger(__name__)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"

_client = None
_client_lock = threading.Lock()


def get_client() -> httpx.Client:
    """Lazy-singleton httpx client. Raises if GROQ_API_KEY is unset -
    callers must check config.GROQ_API_KEY themselves first so the
    failure reason is clear in logs, not just an auth error somewhere."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(
                    headers={
                        "Authorization": f"Bearer {config.GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    }
                )
    return _client


def chat_completion(client: httpx.Client, prompt: str) -> str:
    """POST a single-user-message chat completion to Groq and return
    message.content only. Raises ValueError if content is empty/missing -
    including when reasoning is present but content isn't, since that is
    a malformed response for this module's purposes, not a workaround
    opportunity (see module docstring)."""
    response = client.post(
        GROQ_CHAT_COMPLETIONS_URL,
        json={
            "model": config.GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": config.GROQ_TEMPERATURE,
        },
    )
    response.raise_for_status()
    body = response.json()

    message = body["choices"][0]["message"]
    content = message.get("content")
    if not content:
        raise ValueError(
            "Groq response has no message.content "
            f"(reasoning present: {bool(message.get('reasoning'))})"
        )
    return content


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
