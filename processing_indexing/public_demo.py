"""Public-launch boundaries for samples, developer access, and paid operations.

This module deliberately contains no provider code.  It turns public input into
small, validated decisions that paid routes can enforce immediately before a
provider request begins.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import httpx
from fastapi import Request, Response


class SampleNotFound(LookupError):
    pass


_SAMPLE_COPY: dict[str, dict[str, Any]] = {
    "atm-surveillance": {
        "name": "ATM surveillance",
        "description": "Fixed-camera footage around an ATM.",
        "duration": "1:15",
        "modalities": ["video", "audio"],
        "queries": [
            "When do people start breaking open the machine?",
            "Show the moment someone approaches the ATM.",
        ],
    },
    "dashcam-road": {
        "name": "Dashcam road",
        "description": "Road footage recorded from a moving vehicle.",
        "duration": "20:00",
        "modalities": ["video", "audio"],
        "queries": ["Find the vehicle pulling over.", "Show a vehicle on the road ahead."],
    },
    "low-light-room": {
        "name": "Low-light room",
        "description": "Darkened footage that stresses visual retrieval.",
        "duration": "1:15",
        "modalities": ["video", "audio"],
        "queries": ["Find movement inside the dark room.", "When does a person become visible?"],
    },
    "multilingual-conversation": {
        "name": "Multilingual conversation",
        "description": "Conversation footage for multilingual spoken-word search.",
        "duration": "Demo clip",
        "modalities": ["video", "audio", "speech"],
        "queries": [
            "Find the moment the speakers greet each other.",
            "ಮಾತನಾಡಲು ಪ್ರಾರಂಭಿಸುವ ಕ್ಷಣವನ್ನು ತೋರಿಸಿ.",
            "बातचीत शुरू होने का क्षण दिखाएँ।",
        ],
    },
}


class PublicSampleCatalog:
    def __init__(self, samples: Mapping[str, Path]):
        self._samples = {sample_id: path.resolve() for sample_id, path in samples.items()}

    @classmethod
    def from_paths(cls, samples: Mapping[str, Path]) -> "PublicSampleCatalog":
        return cls(samples)

    @classmethod
    def from_environment(cls) -> "PublicSampleCatalog":
        names = {
            "atm-surveillance": "PUBLIC_SAMPLE_ATM_PATH",
            "dashcam-road": "PUBLIC_SAMPLE_DASHCAM_PATH",
            "low-light-room": "PUBLIC_SAMPLE_LOW_LIGHT_PATH",
            "multilingual-conversation": "PUBLIC_SAMPLE_MULTILINGUAL_PATH",
        }
        configured = {
            sample_id: Path(value)
            for sample_id, env_name in names.items()
            if (value := os.environ.get(env_name, "").strip())
        }
        return cls(configured)

    def public(self) -> list[dict[str, Any]]:
        return [
            {
                "id": sample_id,
                **copy,
                "available": bool(self._samples.get(sample_id) and self._samples[sample_id].is_file()),
            }
            for sample_id, copy in _SAMPLE_COPY.items()
        ]

    def resolve(self, sample_id: str) -> Path:
        if sample_id not in _SAMPLE_COPY or sample_id not in self._samples:
            raise SampleNotFound(sample_id)
        path = self._samples[sample_id]
        if not path.is_file():
            raise SampleNotFound(sample_id)
        return path


@dataclass(frozen=True)
class Usage:
    limit: int
    remaining: int
    reset_at: float

    def public(self) -> dict[str, Any]:
        from datetime import datetime, timezone

        return {
            "limit": self.limit,
            "remaining": max(0, self.remaining),
            "resetAt": datetime.fromtimestamp(self.reset_at, timezone.utc).isoformat(),
        }


@dataclass(frozen=True)
class Reservation:
    status: str
    usage: Usage
    cached: dict[str, Any] | None = None


class LimiterUnavailable(RuntimeError):
    pass


class LimitReached(RuntimeError):
    def __init__(self, usage: Usage):
        super().__init__("public demo limit reached")
        self.usage = usage


class BurstLimitReached(LimitReached):
    pass


class PublicDemoError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str, usage: Usage | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.usage = usage

    def public(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.usage:
            body["usage"] = self.usage.public()
        return body


_RESERVE_SCRIPT = r"""
local now = tonumber(ARGV[1])
local visitor_window = tonumber(ARGV[2])
local ip_window = tonumber(ARGV[3])
local burst_window = tonumber(ARGV[4])
local visitor_limit = tonumber(ARGV[5])
local ip_limit = tonumber(ARGV[6])
local burst_limit = tonumber(ARGV[7])
local member = ARGV[8]
local ttl = tonumber(ARGV[9])

local existing = redis.call('GET', KEYS[4])
if existing then return {2, existing} end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - visitor_window)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - ip_window)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now - burst_window)
local visitor_count = redis.call('ZCARD', KEYS[1])
local ip_count = redis.call('ZCARD', KEYS[2])
local burst_count = redis.call('ZCARD', KEYS[3])
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local reset = now + visitor_window
if #oldest == 2 then reset = tonumber(oldest[2]) + visitor_window end
if burst_count >= burst_limit then return {-2, visitor_limit - visitor_count, reset} end
if visitor_count >= visitor_limit or ip_count >= ip_limit then return {-1, visitor_limit - visitor_count, reset} end
redis.call('ZADD', KEYS[1], now, member)
redis.call('ZADD', KEYS[2], now, member)
redis.call('ZADD', KEYS[3], now, member)
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('EXPIRE', KEYS[2], ttl)
redis.call('EXPIRE', KEYS[3], ttl)
redis.call('SET', KEYS[4], 'pending', 'EX', ttl)
return {1, visitor_limit - visitor_count - 1, reset}
"""

_STATUS_SCRIPT = r"""
local now = tonumber(ARGV[1])
local visitor_window = tonumber(ARGV[2])
local ip_window = tonumber(ARGV[3])
local visitor_limit = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - visitor_window)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - ip_window)
local count = redis.call('ZCARD', KEYS[1])
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local reset = now + visitor_window
if #oldest == 2 then reset = tonumber(oldest[2]) + visitor_window end
return {visitor_limit - count, reset}
"""


class PublicDemoLimiter:
    """Atomic rolling-window limiter backed by Upstash's Redis REST API."""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        self.visitor_limit = int(os.environ.get("PUBLIC_DEMO_VISITOR_LIMIT", "2"))
        self.visitor_window = int(os.environ.get("PUBLIC_DEMO_VISITOR_WINDOW_SECONDS", "86400"))
        self.ip_limit = int(os.environ.get("PUBLIC_DEMO_IP_LIMIT", "6"))
        self.ip_window = int(os.environ.get("PUBLIC_DEMO_IP_WINDOW_SECONDS", "86400"))
        self.burst_limit = int(os.environ.get("PUBLIC_DEMO_BURST_LIMIT", "3"))
        self.burst_window = int(os.environ.get("PUBLIC_DEMO_BURST_WINDOW_SECONDS", "60"))
        self.idempotency_ttl = int(os.environ.get("PUBLIC_DEMO_IDEMPOTENCY_SECONDS", "86400"))

    @classmethod
    def from_environment(cls) -> "PublicDemoLimiter":
        url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
        token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
        if not url or not token:
            raise LimiterUnavailable("durable limiter is not configured")
        return cls(url, token)

    def _command(self, *parts: str) -> Any:
        try:
            response = httpx.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                json=list(parts),
                timeout=5.0,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise LimiterUnavailable("limiter command failed")
            return payload.get("result")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise LimiterUnavailable("limiter unavailable") from exc

    def reserve(self, visitor_hash: str, ip_hash: str, idempotency_key: str) -> Reservation:
        now = time.time()
        namespace = os.environ.get("PUBLIC_DEMO_REDIS_PREFIX", "aperture:public")
        result = self._command(
            "EVAL",
            _RESERVE_SCRIPT,
            "4",
            f"{namespace}:visitor:{visitor_hash}",
            f"{namespace}:ip:{ip_hash}",
            f"{namespace}:burst:{ip_hash}",
            f"{namespace}:idem:{visitor_hash}:{idempotency_key}",
            str(now),
            str(self.visitor_window),
            str(self.ip_window),
            str(self.burst_window),
            str(self.visitor_limit),
            str(self.ip_limit),
            str(self.burst_limit),
            secrets.token_urlsafe(18),
            str(max(self.visitor_window, self.ip_window, self.idempotency_ttl)),
        )
        if not isinstance(result, list) or not result:
            raise LimiterUnavailable("invalid limiter response")
        code = int(result[0])
        if code == 2:
            raw = result[1]
            if raw == "pending":
                return Reservation("pending", Usage(self.visitor_limit, 0, now + self.visitor_window))
            try:
                cached = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise LimiterUnavailable("invalid idempotency response") from exc
            return Reservation("complete", Usage(**cached["usageInternal"]), cached=cached["response"])
        usage = Usage(self.visitor_limit, int(result[1]), float(result[2]))
        if code == -2:
            raise BurstLimitReached(usage)
        if code == -1:
            raise LimitReached(usage)
        return Reservation("allowed", usage)

    def status(self, visitor_hash: str, ip_hash: str) -> Usage:
        now = time.time()
        namespace = os.environ.get("PUBLIC_DEMO_REDIS_PREFIX", "aperture:public")
        result = self._command(
            "EVAL",
            _STATUS_SCRIPT,
            "2",
            f"{namespace}:visitor:{visitor_hash}",
            f"{namespace}:ip:{ip_hash}",
            str(now),
            str(self.visitor_window),
            str(self.ip_window),
            str(self.visitor_limit),
        )
        if not isinstance(result, list) or len(result) != 2:
            raise LimiterUnavailable("invalid limiter response")
        return Usage(self.visitor_limit, int(result[0]), float(result[1]))

    def complete(
        self, visitor_hash: str, idempotency_key: str, response: dict[str, Any], usage: Usage
    ) -> None:
        namespace = os.environ.get("PUBLIC_DEMO_REDIS_PREFIX", "aperture:public")
        value = json.dumps(
            {
                "response": response,
                "usageInternal": {
                    "limit": usage.limit,
                    "remaining": usage.remaining,
                    "reset_at": usage.reset_at,
                },
            },
            separators=(",", ":"),
        )
        self._command(
            "SET",
            f"{namespace}:idem:{visitor_hash}:{idempotency_key}",
            value,
            "EX",
            str(self.idempotency_ttl),
        )


def opaque_visitor_id() -> str:
    return secrets.token_urlsafe(32)


def secure_hash(value: str, secret_value: str) -> str:
    if len(secret_value) < 32:
        raise LimiterUnavailable("server hashing secret is not configured")
    return hmac.new(secret_value.encode(), value.encode(), hashlib.sha256).hexdigest()


def request_ip(client_host: str | None, forwarded_for: str | None = None) -> str:
    """Use the direct peer by default; proxy headers require explicit trust."""

    candidate = client_host or "0.0.0.0"
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() == "true" and forwarded_for:
        hops = max(1, int(os.environ.get("TRUSTED_PROXY_COUNT", "1")))
        chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        if len(chain) >= hops:
            candidate = chain[-hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "0.0.0.0"


def public_launch_enabled() -> bool:
    return os.environ.get("PUBLIC_LAUNCH_MODE", "").lower() == "true"


def _signed_visitor(raw_cookie: str | None, secret_value: str) -> tuple[str, bool]:
    if raw_cookie and "." in raw_cookie:
        token, signature = raw_cookie.rsplit(".", 1)
        expected = hmac.new(secret_value.encode(), token.encode(), hashlib.sha256).hexdigest()
        if token and hmac.compare_digest(signature, expected):
            return token, False
    token = opaque_visitor_id()
    signature = hmac.new(secret_value.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{signature}", True


@dataclass
class PaidOperation:
    limiter: PublicDemoLimiter
    visitor_hash: str
    idempotency_key: str
    usage: Usage

    def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["usage"] = self.usage.public()
        self.limiter.complete(self.visitor_hash, self.idempotency_key, payload, self.usage)
        return payload


def reserve_paid_operation(
    request: Request, response: Response, idempotency_key: str | None
) -> PaidOperation | dict[str, Any] | None:
    """Reserve usage atomically immediately before a paid provider call."""

    if not public_launch_enabled():
        return None
    if not idempotency_key or len(idempotency_key) > 200:
        raise PublicDemoError(400, "INVALID_QUERY", "A valid idempotency key is required.")
    cookie_secret = os.environ.get("VISITOR_COOKIE_SECRET", "")
    ip_secret = os.environ.get("IP_HASH_SECRET", "")
    if len(cookie_secret) < 32 or len(ip_secret) < 32:
        raise PublicDemoError(
            503,
            "DEMO_LIMITER_UNAVAILABLE",
            "Live searches are temporarily unavailable. Please try again shortly.",
        )
    signed_cookie, created = _signed_visitor(request.cookies.get("aperture_visitor"), cookie_secret)
    token = signed_cookie.rsplit(".", 1)[0]
    if created:
        response.set_cookie(
            "aperture_visitor",
            signed_cookie,
            max_age=31_536_000,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
    client_ip = request_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
    )
    try:
        limiter = PublicDemoLimiter.from_environment()
        visitor_hash = secure_hash(token, cookie_secret)
        ip_hash = secure_hash(client_ip, ip_secret)
        reservation = limiter.reserve(visitor_hash, ip_hash, idempotency_key)
    except BurstLimitReached as exc:
        raise PublicDemoError(
            429,
            "PUBLIC_DEMO_LIMIT_REACHED",
            "Too many live searches were started at once. Please wait a moment.",
            exc.usage,
        ) from exc
    except LimitReached as exc:
        raise PublicDemoError(
            429,
            "PUBLIC_DEMO_LIMIT_REACHED",
            "You’ve used today’s two live searches.",
            exc.usage,
        ) from exc
    except LimiterUnavailable as exc:
        raise PublicDemoError(
            503,
            "DEMO_LIMITER_UNAVAILABLE",
            "Live searches are temporarily unavailable. Please try again shortly.",
        ) from exc
    if reservation.status == "complete":
        return reservation.cached or {}
    if reservation.status == "pending":
        raise PublicDemoError(
            409, "TEMPORARILY_UNAVAILABLE", "This search is already in progress.", reservation.usage
        )
    return PaidOperation(limiter, visitor_hash, idempotency_key, reservation.usage)


def public_usage(request: Request, response: Response) -> Usage:
    if not public_launch_enabled():
        limit = int(os.environ.get("PUBLIC_DEMO_VISITOR_LIMIT", "2"))
        return Usage(limit, limit, time.time() + int(os.environ.get("PUBLIC_DEMO_VISITOR_WINDOW_SECONDS", "86400")))
    cookie_secret = os.environ.get("VISITOR_COOKIE_SECRET", "")
    ip_secret = os.environ.get("IP_HASH_SECRET", "")
    if len(cookie_secret) < 32 or len(ip_secret) < 32:
        raise PublicDemoError(503, "DEMO_LIMITER_UNAVAILABLE", "Live searches are temporarily unavailable. Please try again shortly.")
    signed_cookie, created = _signed_visitor(request.cookies.get("aperture_visitor"), cookie_secret)
    token = signed_cookie.rsplit(".", 1)[0]
    if created:
        response.set_cookie("aperture_visitor", signed_cookie, max_age=31_536_000, secure=True, httponly=True, samesite="lax", path="/")
    client_ip = request_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
    try:
        limiter = PublicDemoLimiter.from_environment()
        return limiter.status(secure_hash(token, cookie_secret), secure_hash(client_ip, ip_secret))
    except LimiterUnavailable as exc:
        raise PublicDemoError(503, "DEMO_LIMITER_UNAVAILABLE", "Live searches are temporarily unavailable. Please try again shortly.") from exc
