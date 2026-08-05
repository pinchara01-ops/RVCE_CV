"""Ephemeral, backend-only credential sessions for runtime profiles.

Browser requests supply API keys only once when creating or updating a
session.  The browser then holds an opaque session identifier; jobs and API
responses use that identifier and never receive a key value.  The store is
process-local by design, so a backend restart clears every credential.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

from .runtime_profiles import (
    REDACTED,
    RuntimeProfile,
    RuntimeProfileError,
    ValidatedRuntimeSetup,
    credential_keys,
    redact_secrets,
    validate_runtime_setup,
)


class RuntimeSessionError(RuntimeError):
    """Base error for opaque-session lookup and lifecycle failures."""


class RuntimeSessionNotFoundError(RuntimeSessionError):
    """The browser presented an unknown or expired opaque session id."""


@dataclass(frozen=True)
class RuntimeSession:
    """A single in-memory runtime setup.

    ``_credentials`` is intentionally private.  Only backend integration code
    should call :meth:`runtime_config`; HTTP handlers must use :meth:`public`.
    """

    id: str
    profile: RuntimeProfile
    configuration: Mapping[str, Any]
    _credentials: Mapping[str, str] = field(repr=False, compare=False)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    def public(self) -> dict[str, Any]:
        """Return a browser-safe session descriptor with boolean key state only."""

        return {
            "session_id": self.id,
            "profile": self.profile.public(),
            "configuration": redact_secrets(self.configuration),
            "credentials": {
                key: bool(self._credentials.get(key)) for key in sorted(credential_keys())
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    def runtime_config(self) -> dict[str, Any]:
        """Return the private configuration for an active backend worker only.

        Callers must never serialize or log this result.  A fresh copy prevents
        accidental mutation of the live in-memory session.
        """

        config = _copy_value(self.configuration)
        config.update(dict(self._credentials))
        config.update(
            {
                "runtime_session_id": self.id,
                "runtime_profile_id": self.profile.id,
                "collection_name": self.profile.collection_name,
                "vector_schema": self.profile.vector_schema,
            }
        )
        return config

    def validated_setup(self) -> ValidatedRuntimeSetup:
        """Return the private setup object for trusted backend integrations."""

        return ValidatedRuntimeSetup(
            profile=self.profile,
            configuration=self.configuration,
            credentials=self._credentials,
        )

    def redacted_runtime_config(self) -> dict[str, Any]:
        """A safe diagnostic representation for job/config exports."""

        return redact_secrets(self.runtime_config(), tuple(self._credentials.values()))


class RuntimeSessionStore:
    """Thread-safe, process-memory store for runtime credential sessions.

    The default eight-hour TTL limits accidental long-lived credentials while
    still covering a presentation and a long indexing run.  It is not a
    persistence mechanism; instances are empty after every backend restart.
    """

    def __init__(self, *, ttl: timedelta = timedelta(hours=8)) -> None:
        if ttl <= timedelta(0):
            raise ValueError("Runtime session TTL must be positive")
        self._ttl = ttl
        self._sessions: dict[str, RuntimeSession] = {}
        self._lock = threading.RLock()

    def create(
        self,
        profile_id: str,
        configuration: Mapping[str, Any] | None = None,
        credentials: Mapping[str, Any] | None = None,
    ) -> RuntimeSession:
        setup = validate_runtime_setup(profile_id, configuration, credentials)
        with self._lock:
            self._purge_expired_locked()
            now = _utcnow()
            session = RuntimeSession(
                id=secrets.token_urlsafe(32),
                profile=setup.profile,
                configuration=MappingProxyType(_copy_value(setup.configuration)),
                _credentials=MappingProxyType(dict(setup.credentials)),
                created_at=now,
                updated_at=now,
                expires_at=now + self._ttl,
            )
            self._sessions[session.id] = session
            return session

    def update(
        self,
        session_id: str,
        *,
        configuration: Mapping[str, Any] | None = None,
        credentials: Mapping[str, Any] | None = None,
    ) -> RuntimeSession:
        """Replace public configuration and merge any supplied credential keys.

        A profile is immutable for a session.  Switching profile deliberately
        means creating a new opaque session, which avoids crossing schemas or
        carrying an unrelated provider key into a new run profile.
        """

        with self._lock:
            existing = self._get_locked(session_id)
            merged_configuration = _copy_value(existing.configuration)
            if configuration is not None:
                if not isinstance(configuration, Mapping):
                    raise RuntimeProfileError("configuration must be an object")
                merged_configuration.update(_copy_value(configuration))
            merged_credentials = dict(existing._credentials)
            if credentials is not None:
                if not isinstance(credentials, Mapping):
                    raise RuntimeProfileError("credentials must be an object")
                merged_credentials.update(dict(credentials))
            setup = validate_runtime_setup(
                existing.profile.id, merged_configuration, merged_credentials
            )
            now = _utcnow()
            refreshed = RuntimeSession(
                id=existing.id,
                profile=setup.profile,
                configuration=MappingProxyType(_copy_value(setup.configuration)),
                _credentials=MappingProxyType(dict(setup.credentials)),
                created_at=existing.created_at,
                updated_at=now,
                expires_at=now + self._ttl,
            )
            self._sessions[session_id] = refreshed
            return refreshed

    def get(self, session_id: str) -> RuntimeSession:
        with self._lock:
            return self._get_locked(session_id)

    def get_runtime_config(self, session_id: str) -> dict[str, Any]:
        """Backend-only helper for an indexing or query worker."""

        return self.get(session_id).runtime_config()

    def close(self, session_id: str) -> None:
        with self._lock:
            self._purge_expired_locked()
            if session_id not in self._sessions:
                raise RuntimeSessionNotFoundError("Runtime session was not found")
            del self._sessions[session_id]

    def clear(self) -> None:
        """Remove all credentials; useful for controlled shutdown and tests."""

        with self._lock:
            self._sessions.clear()

    def _get_locked(self, session_id: str) -> RuntimeSession:
        self._purge_expired_locked()
        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeSessionNotFoundError("Runtime session was not found")
        return session

    def _purge_expired_locked(self) -> None:
        now = _utcnow()
        for session_id, session in tuple(self._sessions.items()):
            if session.expires_at <= now:
                del self._sessions[session_id]


def parse_session_payload(payload: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Accept the UI's concise flat shape and a nested compatibility shape.

    Flat inputs keep the UI simple::

        {"profile_id": "api-gemini-free-v1", "gemini_api_key": "...",
         "qdrant_url": "...", "providers": {...}, "models": {...}}

    Nested values (``configuration`` / ``credentials``) are supported for
    non-browser callers, but values are never echoed in validation errors.
    """

    if not isinstance(payload, Mapping):
        raise RuntimeProfileError("Runtime session request must be a JSON object")
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise RuntimeProfileError("profile_id must be a non-empty string")
    allowed_top_level = {
        "profile_id",
        "configuration",
        "credentials",
        "qdrant_url",
        "qdrant_timeout_seconds",
        "window_seconds",
        "stride_seconds",
        "providers",
        "models",
        "consent_cloud_video",
        *credential_keys(),
    }
    unknown = sorted(set(payload) - allowed_top_level)
    if unknown:
        raise RuntimeProfileError(
            f"Unsupported runtime session field(s): {', '.join(str(item) for item in unknown)}"
        )
    configuration = _mapping_payload(payload.get("configuration"), "configuration")
    credentials = _mapping_payload(payload.get("credentials"), "credentials")
    for name in (
        "qdrant_url",
        "qdrant_timeout_seconds",
        "window_seconds",
        "stride_seconds",
        "providers",
        "models",
        "consent_cloud_video",
    ):
        if name in payload:
            if name in configuration:
                raise RuntimeProfileError(f"Runtime session field '{name}' was supplied twice")
            configuration[name] = payload[name]
    for name in credential_keys():
        if name in payload:
            if name in credentials:
                raise RuntimeProfileError(f"Runtime credential '{name}' was supplied twice")
            credentials[name] = payload[name]
    return profile_id.strip(), configuration, credentials


def redact_session_error(exc: Exception, session: RuntimeSession | None = None) -> str:
    """Return a safe error string without any credential literal."""

    values: tuple[str, ...] = () if session is None else tuple(session._credentials.values())
    redacted = redact_secrets(str(exc), values)
    return str(redacted).replace(REDACTED, REDACTED)


def _mapping_payload(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RuntimeProfileError(f"{name} must be an object")
    return dict(value)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _copy_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return [_copy_value(item) for item in value]
    return value
