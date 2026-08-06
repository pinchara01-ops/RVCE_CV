"""Small, credential-safe readiness probes used by the test harness.

This module is deliberately independent of the Qdrant client so the test
runner can decide whether an integration environment is available before any
fixture recreates a collection.  It never returns a configured URL, path,
query string, or credentials in its public status.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ServiceReadiness:
    """A public, redacted health result for an external test dependency."""

    available: bool
    label: str
    reason: str


def _safe_endpoint_parts(url: str) -> tuple[str, str] | None:
    """Return a redacted display label and root health endpoint, if valid."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return None

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    label = f"{parsed.scheme}://{netloc}"
    endpoint = urlunsplit((parsed.scheme, netloc, "/readyz", "", ""))
    return label, endpoint


def qdrant_readiness(url: str, *, timeout_seconds: float = 1.0) -> ServiceReadiness:
    """Probe Qdrant's readiness endpoint without exposing configuration data.

    This is intentionally a short read-only request.  ``available`` means a
    Qdrant endpoint responded successfully; it does not mean a collection or
    schema has been validated.  Those are asserted by the marked tests.
    """
    endpoint_parts = _safe_endpoint_parts(url)
    if endpoint_parts is None:
        return ServiceReadiness(
            available=False,
            label="configured Qdrant endpoint",
            reason="the configured Qdrant URL is invalid",
        )

    label, endpoint = endpoint_parts
    request = Request(endpoint, method="GET", headers={"User-Agent": "video-search-test-gate"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_status = getattr(response, "status", None)
            status = int(raw_status if raw_status is not None else response.getcode())
    except HTTPError as error:
        return ServiceReadiness(False, label, f"readiness returned HTTP {error.code}")
    except (OSError, TimeoutError, URLError, ValueError) as error:
        return ServiceReadiness(False, label, f"readiness request failed ({type(error).__name__})")

    if 200 <= status < 300:
        return ServiceReadiness(True, label, "ready")
    return ServiceReadiness(False, label, f"readiness returned HTTP {status}")
