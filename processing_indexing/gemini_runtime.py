"""Safe, lazy runtime primitives for Google Gemini API calls.

The local processing profile must remain usable without the Google SDK.  This
module is therefore intentionally small and dependency-injected: importing it
does not import ``google-genai`` and callers can supply a fake client in tests.

It also centralises the two things an API-facing job must never get wrong:
provider failures are classified for the UI without exposing credentials, and
only transient/quota failures are retried.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class GeminiRuntimeError(RuntimeError):
    """Base error safe to display in diagnostics.

    The original provider exception is retained as ``__cause__`` but never
    copied into a job event or API response.
    """

    error_type = "provider_error"
    retryable = False

    def __init__(self, message: str, *, attempt: int | None = None):
        super().__init__(redact_text(message))
        self.attempt = attempt

    def diagnostic(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "retryable": self.retryable,
            "attempt": self.attempt,
            "error": redact_text(str(self)),
        }


class GeminiAuthenticationError(GeminiRuntimeError):
    error_type = "authentication"


class GeminiQuotaError(GeminiRuntimeError):
    error_type = "quota"
    retryable = True


class GeminiTransportError(GeminiRuntimeError):
    error_type = "transport"
    retryable = True


class GeminiResponseError(GeminiRuntimeError):
    error_type = "response"


class GeminiSDKUnavailableError(GeminiRuntimeError):
    error_type = "sdk_unavailable"


class GeminiInputError(GeminiRuntimeError):
    error_type = "input"


_SECRET_KEY_NAMES = re.compile(
    r"(?:api[_-]?key|authorization|token|secret|password|credential)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    # Google API keys are normally AIza-prefixed.  Keep this broad enough to
    # catch test keys too without accidentally logging any usable credential.
    (re.compile(r"AIza[\w-]{12,}"), False),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), False),
    (re.compile(r"(Bearer\s+)[^\s,;]+", re.IGNORECASE), True),
    (
        re.compile(r"([?&](?:key|api_key|token)=)[^&\s]+", re.IGNORECASE),
        True,
    ),
)


def redact_text(value: object, *, limit: int = 500) -> str:
    """Return a bounded diagnostic string with common credential forms hidden."""

    text = str(value).splitlines()[0] if value is not None else ""
    for pattern, preserve_prefix in _SECRET_PATTERNS:
        if preserve_prefix:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text[:limit]


def redact_mapping(value: Any) -> Any:
    """Recursively redact credential-shaped mapping values for event payloads."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _SECRET_KEY_NAMES.search(str(key))
            else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_mapping(item) for item in value)
    if isinstance(value, str):
        return redact_text(value, limit=2_000)
    return value


def _status_code(exc: BaseException) -> int | None:
    for value in (
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        if isinstance(value, int):
            return value
    return None


def classify_gemini_error(exc: BaseException, *, attempt: int | None = None) -> GeminiRuntimeError:
    """Normalize a Google SDK/http exception without preserving sensitive text."""

    if isinstance(exc, GeminiRuntimeError):
        if exc.attempt is None and attempt is not None:
            exc.attempt = attempt
        return exc

    message = redact_text(exc)
    text = f"{type(exc).__name__} {message}".lower()
    status = _status_code(exc)
    if status in {401, 403} or any(
        value in text for value in ("api key", "unauthenticated", "permission denied")
    ):
        return GeminiAuthenticationError(message, attempt=attempt)
    if status == 429 or any(
        value in text
        for value in (
            "resource exhausted",
            "rate limit",
            "quota",
            "too many requests",
        )
    ):
        return GeminiQuotaError(message, attempt=attempt)
    if status is not None and status >= 500:
        return GeminiTransportError(message, attempt=attempt)
    if any(
        value in text
        for value in (
            "timeout",
            "timed out",
            "connection",
            "network",
            "temporarily unavailable",
        )
    ):
        return GeminiTransportError(message, attempt=attempt)
    return GeminiRuntimeError(message, attempt=attempt)


@dataclass(frozen=True)
class GeminiRetryPolicy:
    """Bounded exponential backoff used for quota and transport errors only."""

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.initial_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds must be >= initial_delay_seconds")

    def delay_for_attempt(self, attempt: int) -> float:
        # attempt is one-based and represents the failed call.
        return min(
            self.max_delay_seconds,
            self.initial_delay_seconds * (2 ** max(0, attempt - 1)),
        )


class GeminiKeyPool:
    """Thread-safe round-robin selector that never exposes its key values."""

    def __init__(self, keys: Sequence[str]) -> None:
        normalized = tuple(dict.fromkeys(key.strip() for key in keys if key.strip()))
        if not normalized:
            raise GeminiAuthenticationError("At least one Gemini API key is required")
        self._keys = normalized
        self._index = 0
        self._lock = Lock()

    def next_key(self) -> str:
        with self._lock:
            key = self._keys[self._index]
            self._index = (self._index + 1) % len(self._keys)
            return key

    @property
    def size(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return f"GeminiKeyPool(size={self.size})"


def parse_gemini_keys_json(value: str) -> tuple[str, ...]:
    """Parse a hosted secret value without reflecting it in errors."""

    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GeminiAuthenticationError(
            "GEMINI_API_KEYS_JSON must be a JSON array of API keys"
        ) from exc
    if not isinstance(parsed, list) or any(not isinstance(key, str) for key in parsed):
        raise GeminiAuthenticationError(
            "GEMINI_API_KEYS_JSON must be a JSON array of API keys"
        )
    keys = tuple(dict.fromkeys(key.strip() for key in parsed if key.strip()))
    if not keys:
        raise GeminiAuthenticationError(
            "GEMINI_API_KEYS_JSON must contain at least one API key"
        )
    return keys


@dataclass(frozen=True)
class GeminiCallAttempt:
    attempt: int
    status: str
    error: dict[str, Any] | None = None
    delay_seconds: float = 0.0


@dataclass
class GeminiCallDiagnostics:
    """Sanitised, serialisable telemetry for a single provider request."""

    model: str
    operation: str
    attempts: list[GeminiCallAttempt] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "operation": self.operation,
            "attempts": [
                {
                    "attempt": item.attempt,
                    "status": item.status,
                    "error": item.error,
                    "delay_seconds": item.delay_seconds,
                }
                for item in self.attempts
            ],
        }


def call_with_retry(
    operation: Callable[[], T],
    *,
    policy: GeminiRetryPolicy | None = None,
    model: str,
    operation_name: str,
    sleep: Callable[[float], None] = time.sleep,
    on_attempt: Callable[[GeminiCallAttempt], None] | None = None,
) -> tuple[T, GeminiCallDiagnostics]:
    """Call a provider function and return value plus redacted attempt history."""

    resolved_policy = policy or GeminiRetryPolicy()
    diagnostics = GeminiCallDiagnostics(model=model, operation=operation_name)
    for attempt in range(1, resolved_policy.max_attempts + 1):
        try:
            result = operation()
        except BaseException as exc:  # provider SDK exceptions are third-party types
            error = classify_gemini_error(exc, attempt=attempt)
            will_retry = error.retryable and attempt < resolved_policy.max_attempts
            delay = resolved_policy.delay_for_attempt(attempt) if will_retry else 0.0
            record = GeminiCallAttempt(
                attempt=attempt,
                status="retrying" if will_retry else "failed",
                error=error.diagnostic(),
                delay_seconds=delay,
            )
            diagnostics.attempts.append(record)
            if on_attempt is not None:
                on_attempt(record)
            if not will_retry:
                raise error from exc
            if delay:
                sleep(delay)
        else:
            record = GeminiCallAttempt(attempt=attempt, status="succeeded")
            diagnostics.attempts.append(record)
            if on_attempt is not None:
                on_attempt(record)
            return result, diagnostics
    raise AssertionError("retry loop must either return or raise")  # pragma: no cover


class GeminiJsonRuntime(Protocol):
    """The small runtime surface consumed by transcription/caption adapters."""

    def generate_json(
        self,
        *,
        model: str,
        prompt: str,
        media_path: Path | None = None,
        media_mime_type: str | None = None,
        response_schema: Mapping[str, Any] | None = None,
        operation_name: str = "generate_json",
    ) -> tuple[dict[str, Any], GeminiCallDiagnostics]: ...


class GoogleGenAIRuntime:
    """Lazy production Gemini runtime backed by optional ``google-genai``.

    No client, SDK import, file upload, or network action happens until the
    first ``generate_json`` invocation.  ``client``/``types_module`` and the
    loader are injectable so this class has no network dependency in tests.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        key_pool: GeminiKeyPool | None = None,
        client: Any | None = None,
        types_module: Any | None = None,
        sdk_loader: Callable[[], tuple[Any, Any]] | None = None,
        retry_policy: GeminiRetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if key_pool is not None and api_key is not None:
            raise ValueError("Provide either api_key or key_pool, not both")
        if client is None and key_pool is None and (not api_key or not api_key.strip()):
            raise GeminiAuthenticationError("A Gemini API key is required")
        self._api_key = api_key
        self._key_pool = key_pool
        self._client = client
        self._clients_by_key: dict[str, Any] = {}
        self._client_lock = Lock()
        self._types = types_module
        self._genai: Any | None = None
        self._sdk_loader = sdk_loader or _load_google_sdk
        self.retry_policy = retry_policy or GeminiRetryPolicy()
        self._sleep = sleep

    def generate_json(
        self,
        *,
        model: str,
        prompt: str,
        media_path: Path | None = None,
        media_mime_type: str | None = None,
        extra_media: Sequence[tuple[Path, str]] | None = None,
        response_schema: Mapping[str, Any] | None = None,
        operation_name: str = "generate_json",
    ) -> tuple[dict[str, Any], GeminiCallDiagnostics]:
        if not model.strip():
            raise GeminiInputError("Gemini model must not be empty")
        if not prompt.strip():
            raise GeminiInputError("Gemini prompt must not be empty")
        if (media_path is None) != (media_mime_type is None):
            raise GeminiInputError("media path and MIME type must be supplied together")
        if media_path is not None and not media_path.is_file():
            raise GeminiInputError(f"media file does not exist: {media_path}")

        # One call can carry several files (for example a video plus the spoken
        # request), which the model receives together rather than in sequence.
        media: list[tuple[Path, str]] = []
        if media_path is not None and media_mime_type is not None:
            media.append((media_path, media_mime_type))
        for path, mime_type in extra_media or ():
            if not path.is_file():
                raise GeminiInputError(f"media file does not exist: {path}")
            if not mime_type.strip():
                raise GeminiInputError("every media file needs a MIME type")
            media.append((path, mime_type))

        return call_with_retry(
            lambda: self._generate_json_once(
                model=model,
                prompt=prompt,
                media=media,
                response_schema=response_schema,
            ),
            policy=self.retry_policy,
            model=model,
            operation_name=operation_name,
            sleep=self._sleep,
        )

    def _generate_json_once(
        self,
        *,
        model: str,
        prompt: str,
        media: Sequence[tuple[Path, str]],
        response_schema: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        client, types = self._ensure_client_and_types()
        uploads: list[Any] = []
        try:
            contents: Any = prompt
            for path, mime_type in media:
                uploads.append(self._upload_file(client, types, path, mime_type))
            if uploads:
                contents = [prompt, *uploads]
            config = _generate_config(types, response_schema=response_schema)
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return _extract_json(response)
        finally:
            for upload in uploads:
                self._delete_file_quietly(client, upload)

    def _ensure_client_and_types(self) -> tuple[Any, Any]:
        if self._types is None:
            genai, types = self._sdk_loader()
            self._genai = genai
            self._types = types
        else:
            genai = self._genai
        if self._client is not None:
            return self._client, self._types
        if self._key_pool is None:
            if genai is None:
                genai, _types = self._sdk_loader()
                self._genai = genai
            self._client = genai.Client(api_key=self._api_key)
            return self._client, self._types
        key = self._key_pool.next_key()
        with self._client_lock:
            client = self._clients_by_key.get(key)
            if client is None:
                if genai is None:
                    genai, _types = self._sdk_loader()
                    self._genai = genai
                client = genai.Client(api_key=key)
                self._clients_by_key[key] = client
        return client, self._types

    def _upload_file(self, client: Any, types: Any, path: Path, mime_type: str | None) -> Any:
        if not mime_type:
            raise GeminiInputError("uploaded media needs a MIME type")
        config_type = getattr(types, "UploadFileConfig", None)
        config = config_type(mime_type=mime_type) if config_type is not None else {"mime_type": mime_type}
        upload = client.files.upload(file=str(path), config=config)
        return self._await_active_upload(client, upload)

    def _await_active_upload(
        self,
        client: Any,
        upload: Any,
        *,
        timeout_seconds: float = 600.0,
        poll_seconds: float = 1.0,
    ) -> Any:
        """Block until an uploaded file leaves PROCESSING.

        Video uploads are not immediately usable: generate_content rejects a
        file that is still PROCESSING with FAILED_PRECONDITION.  Anything that
        does not report a state (older SDKs, injected test doubles) is returned
        untouched so this stays a no-op for them.
        """

        if _upload_state(upload) is None:
            return upload
        get_file = getattr(getattr(client, "files", None), "get", None)
        name = getattr(upload, "name", None)
        if get_file is None or not name:
            return upload

        deadline = time.monotonic() + timeout_seconds
        current = upload
        while True:
            state = _upload_state(current)
            if state is None or state == "ACTIVE":
                return current
            if state == "FAILED":
                raise GeminiResponseError("Gemini could not process the uploaded media file")
            if time.monotonic() >= deadline:
                raise GeminiTransportError(
                    "Gemini did not finish processing the uploaded media in time"
                )
            self._sleep(poll_seconds)
            current = get_file(name=name)

    @staticmethod
    def _delete_file_quietly(client: Any, upload: Any) -> None:
        name = getattr(upload, "name", None)
        if not name and isinstance(upload, Mapping):
            name = upload.get("name")
        if not name:
            return
        try:
            client.files.delete(name=name)
        except Exception:  # noqa: BLE001
            # The uploaded file expires server-side.  Cleanup failure should
            # not mask a successfully completed generation request.
            return


def _upload_state(upload: Any) -> str | None:
    """Return an uploaded file's state as an upper-case name, if it reports one."""

    state = getattr(upload, "state", None)
    if state is None and isinstance(upload, Mapping):
        state = upload.get("state")
    if state is None:
        return None
    # The SDK returns an enum; older/raw responses return a plain string.
    return str(getattr(state, "name", None) or state).upper()


def _load_google_sdk() -> tuple[Any, Any]:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise GeminiSDKUnavailableError(
            "Gemini API mode requires the optional 'google-genai' package"
        ) from exc
    return genai, types


def _generate_config(types: Any, *, response_schema: Mapping[str, Any] | None) -> Any:
    kwargs: dict[str, Any] = {
        "temperature": 0,
        "response_mime_type": "application/json",
    }
    if response_schema is not None:
        # ``response_json_schema`` is the current SDK name.  Keep a backwards
        # compatible fallback for older google-genai releases.
        kwargs["response_json_schema"] = dict(response_schema)
    config_type = getattr(types, "GenerateContentConfig", None)
    if config_type is None:
        return kwargs
    try:
        return config_type(**kwargs)
    except TypeError:
        if "response_json_schema" not in kwargs:
            raise
        kwargs["response_schema"] = kwargs.pop("response_json_schema")
        return config_type(**kwargs)


def _extract_json(response: Any) -> dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        if hasattr(parsed, "model_dump"):
            parsed = parsed.model_dump()
        if isinstance(parsed, Mapping):
            return dict(parsed)
    text = getattr(response, "text", None)
    if text is None and isinstance(response, Mapping):
        text = response.get("text")
    if not isinstance(text, str) or not text.strip():
        raise GeminiResponseError("Gemini response did not contain JSON text")
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiResponseError("Gemini response was not valid JSON") from exc
    if not isinstance(result, dict):
        raise GeminiResponseError("Gemini JSON response must be an object")
    return result
