from __future__ import annotations

import json
import hmac
import logging
import math
import mimetypes
import os
import re
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from query_retrieval import api as query_api
from query_retrieval.models import (
    SearchRequest,
    SearchResponse,
    VerifyRequest,
    VerifyResponse,
)

from .config import Settings
from .debug_jobs import JobManager, sanitize
from .library import (
    LibraryReadError,
    collection_health,
    get_window,
    list_library_diagnostics,
    list_videos,
    list_windows,
    media_path_for_window,
)
from .preflight import model_statuses
from .probe import VideoProbeError
from .public_demo import (
    PublicDemoError,
    PublicSampleCatalog,
    SampleNotFound,
    public_launch_enabled,
    public_usage,
)
from .quick_demo import router as quick_demo_router
from .quick_index import router as quick_index_router
from .drive_connector import router as drive_router
from .drive_library import router as drive_library_router
from .runtime_profiles import (
    RuntimeProfileError,
    get_profile,
    list_profiles_public,
    qdrant_preflight,
    redact_secrets,
    redact_validation_errors,
)
from .runtime_sessions import (
    RuntimeSessionNotFoundError,
    RuntimeSessionStore,
    parse_session_payload,
)

app = FastAPI(title="Processing Debug API")
logger = logging.getLogger(__name__)
MULTIPART_PARSE_ERROR = "There was an error parsing the body"
MULTIPART_RECOVERY_MESSAGE = (
    "The upload could not be read. Re-select the video and retry, keeping this page open until the upload completes."
)
_LOCAL_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3017",
    "http://127.0.0.1:3017",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
# Deployed frontends are added at runtime: set ALLOWED_ORIGINS to a
# comma-separated list of origins, or to "*" to allow any (demo only).
_EXTRA_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
# Vercel preview deployments get a new hostname per commit, so match the
# project's whole subdomain space rather than pinning one URL.
_ORIGIN_REGEX = os.environ.get("ALLOWED_ORIGIN_REGEX") or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_LOCAL_ORIGINS + _EXTRA_ORIGINS,
    allow_origin_regex=_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.exception_handler(PublicDemoError)
async def public_demo_error(_request: Request, exc: PublicDemoError):
    return JSONResponse(status_code=exc.status_code, content=exc.public())


_DEVELOPER_PREFIXES = (
    "/api/runtime",
    "/api/processing",
    "/api/index",
    "/api/diagnostics",
    "/api/query",
    "/api/quick/index",
    "/api/quick/drive",
    "/api/quick/library",
    "/search",
    "/verify",
)


@app.middleware("http")
async def protect_developer_routes(request: Request, call_next):
    if public_launch_enabled() and request.url.path.startswith(_DEVELOPER_PREFIXES):
        enabled = os.environ.get("DEVELOPER_FEATURES_ENABLED", "").lower() == "true"
        expected = os.environ.get("DEVELOPER_ADMIN_TOKEN", "")
        supplied = request.headers.get("authorization", "")
        valid = bool(expected) and supplied.startswith("Bearer ") and hmac.compare_digest(
            supplied[7:], expected
        )
        if not enabled or not valid:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "TEMPORARILY_UNAVAILABLE",
                        "message": "Developer functionality is not available in the public demo.",
                    }
                },
            )
    return await call_next(request)
# Ephemeral by design: credentials live only in this process and are cleared on
# backend restart.  Worker integration reads private config by opaque id; HTTP
# responses always call RuntimeSession.public().
runtime_sessions = RuntimeSessionStore()
manager = JobManager(runtime_config_resolver=runtime_sessions.get_runtime_config)
query_api.set_runtime_session_resolver(runtime_sessions.get_runtime_config)

# Stateless single-call video search and indexing; independent of the
# Qdrant-backed pipeline above.
app.include_router(quick_demo_router)
app.include_router(quick_index_router)
app.include_router(drive_router)
app.include_router(drive_library_router)

# Local evaluation corpus, served read-only so the Tests page can play the
# actual files it describes.
_TEST_ASSETS = Path(__file__).resolve().parent.parent / "test_assets" / "asset_library" / "media"
if _TEST_ASSETS.is_dir():
    app.mount("/api/test-assets", StaticFiles(directory=str(_TEST_ASSETS)), name="test-assets")

_PUBLIC_SAMPLES = PublicSampleCatalog.from_environment()


@app.get("/api/public/samples")
def public_samples():
    return {"samples": _PUBLIC_SAMPLES.public()}


@app.get("/api/public/usage")
def public_demo_usage(request: Request, response: Response):
    return {"usage": public_usage(request, response).public()}


@app.get("/api/public/samples/{sample_id}/media")
def public_sample_media(sample_id: str):
    try:
        path = _PUBLIC_SAMPLES.resolve(sample_id)
    except SampleNotFound as exc:
        raise PublicDemoError(404, "SAMPLE_NOT_FOUND", "That sample is not available.") from exc
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "video/mp4")


# An API-based indexing job deliberately owns only per-upload tuning.  Cloud
# endpoint, collection, provider/model contract, and credentials live in the
# opaque runtime session and are applied immediately before execution.  This
# allowlist keeps callers from smuggling a secret-shaped value into the public
# job configuration or overriding the session's immutable embedding contract.
_API_JOB_CONFIG_FIELDS = frozenset(
    {
        "profile_id",
        "runtime_session_id",
        "window_seconds",
        "stride_seconds",
        "max_windows",
        "index_qdrant",
    }
)


def _api_job_config_error() -> ValueError:
    """Return a generic rejection that never reflects submitted config data."""

    return ValueError(
        "API-based indexing accepts only the active runtime session and "
        "per-upload window/index settings. Configure cloud endpoints, "
        "providers, models, and credentials in the active runtime session."
    )


def _positive_api_job_number(value, field: str) -> float:
    """Validate an API job tuning value without echoing its submitted value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(  # noqa: TRY004 - API input errors share one public 400 contract
            f"API-based {field} must be a positive number"
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"API-based {field} must be a positive number")
    return number


def _normalize_api_job_configuration(config: dict, session) -> dict:
    """Return the only public, non-secret configuration valid for an API job.

    The session object is trusted backend state.  All fields it owns are
    intentionally excluded here so public job history can never contain a
    Qdrant endpoint/key, provider choice, model identifier, or profile schema.
    """

    if set(config) - _API_JOB_CONFIG_FIELDS:
        raise _api_job_config_error()
    profile_id = config.get("profile_id")
    if not isinstance(profile_id, str) or profile_id != session.profile.id:
        raise ValueError("Runtime session profile does not match the indexing job")
    session_id = config.get("runtime_session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("API-based indexing requires an active runtime session")

    normalized = {
        "profile_id": session.profile.id,
        "runtime_session_id": session_id,
    }
    if "window_seconds" in config:
        normalized["window_seconds"] = _positive_api_job_number(
            config["window_seconds"], "window_seconds"
        )
    if "stride_seconds" in config:
        normalized["stride_seconds"] = _positive_api_job_number(
            config["stride_seconds"], "stride_seconds"
        )
    effective_window = normalized.get(
        "window_seconds", float(session.configuration["window_seconds"])
    )
    effective_stride = normalized.get(
        "stride_seconds", float(session.configuration["stride_seconds"])
    )
    if effective_stride > effective_window:
        raise ValueError("API-based stride_seconds must not exceed window_seconds")
    if "max_windows" in config:
        value = config["max_windows"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or int(value) != value
            or value < 0
        ):
            raise ValueError("API-based max_windows must be a whole number greater than or equal to zero")
        normalized["max_windows"] = int(value)
    if "index_qdrant" in config:
        if not isinstance(config["index_qdrant"], bool):
            raise ValueError("API-based index_qdrant must be true or false")
        normalized["index_qdrant"] = config["index_qdrant"]
    return normalized


@app.exception_handler(RequestValidationError)
async def safe_request_validation_error(
    _request: Request, exc: RequestValidationError
):
    """Prevent FastAPI's default 422 body from reflecting API keys.

    ``Field(exclude=True)`` protects successful response serialisation, but
    not Pydantic's default validation diagnostics.  Query and verification
    requests can still be malformed before their route handler runs, so make
    the app-level 422 response follow the same redaction rule as runtime
    session endpoints.
    """

    return JSONResponse(
        status_code=422,
        content={"detail": redact_validation_errors(exc.errors())},
    )


@app.exception_handler(StarletteHTTPException)
async def friendly_upload_parse_error(request: Request, exc: StarletteHTTPException):
    """Make FastAPI's opaque pre-endpoint multipart error actionable.

    File/Form parameters are parsed before ``create_job`` is invoked, so this
    narrow handler is the only place to recover from a malformed or interrupted
    upload without changing unrelated API errors.
    """
    if (
        request.url.path == "/api/processing/jobs"
        and exc.status_code == 400
        and exc.detail == MULTIPART_PARSE_ERROR
    ):
        cause = type(exc.__cause__).__name__ if exc.__cause__ else "unknown"
        logger.warning("Processing upload multipart parse failed (cause=%s)", cause)
        return JSONResponse(status_code=400, content={"detail": MULTIPART_RECOVERY_MESSAGE})
    if public_launch_enabled() and request.url.path.startswith("/api/quick/"):
        categories = {
            400: ("INVALID_QUERY", "Check the request and try again."),
            413: ("FILE_TOO_LARGE", "The selected file is too large."),
            415: ("UNSUPPORTED_FILE", "That file type is not supported."),
            502: ("SEARCH_FAILED", "The live search could not be completed."),
            504: ("PROCESSING_TIMEOUT", "The search took too long to complete."),
        }
        code, message = categories.get(
            exc.status_code, ("TEMPORARILY_UNAVAILABLE", "This operation is temporarily unavailable.")
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message}},
            headers=exc.headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


def media_response(path, request: Request):
    """Serve a local indexed upload with browser range-request support."""
    size = path.stat().st_size
    content_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    header = request.headers.get("range")
    if not header:
        return FileResponse(path, media_type=content_type)
    match = re.match(r"bytes=(\d*)-(\d*)", header)
    if not match:
        raise HTTPException(416, "Invalid range")
    start = int(match.group(1) or 0)
    end = min(int(match.group(2) or size - 1), size - 1)
    if start > end or start >= size:
        raise HTTPException(416, "Range outside file")
    with path.open("rb") as stream:
        stream.seek(start)
        data = stream.read(end - start + 1)
    return Response(
        data,
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
        },
    )


def job_or_404(job_id):
    try:
        return manager.get(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found")


@app.get("/api/processing/preflight")
def preflight():
    return {
        "models": [
            x.model_dump() for x in model_statuses(Settings.from_env(), "selection_only")
        ]
    }


# --- Runtime profile and credential-session API ----------------------------
#
# API clients post keys once to create a session, then only pass the opaque
# session id to later calls.  The endpoint intentionally reads raw JSON rather
# than a Pydantic request model: FastAPI's default validation error can echo an
# invalid input value, which is unacceptable for credential-bearing requests.


async def _runtime_json(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Runtime session body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Runtime session body must be a JSON object")
    return payload


def _runtime_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RuntimeSessionNotFoundError):
        return HTTPException(404, "Runtime session was not found")
    if isinstance(exc, RuntimeProfileError):
        # Runtime-profile validation errors name fields but never echo a key.
        return HTTPException(400, str(exc))
    # Do not log the exception text or traceback here: a third-party client or
    # malformed request can embed a credential in either one.
    logger.error("Unexpected runtime-session failure (%s)", type(exc).__name__)
    return HTTPException(500, "Runtime session request could not be completed")


@app.get("/api/runtime/profiles")
def runtime_profiles():
    """List browser-safe profile contracts and selectable provider options."""

    return {"profiles": list_profiles_public()}


@app.post("/api/runtime/session", status_code=201)
async def create_runtime_session(request: Request):
    """Create an opaque, in-memory credential session for one profile."""

    try:
        profile_id, configuration, credentials = parse_session_payload(
            await _runtime_json(request)
        )
        return runtime_sessions.create(
            profile_id, configuration, credentials
        ).public()
    except Exception as exc:
        raise _runtime_http_error(exc) from exc


@app.get("/api/runtime/session/{session_id}")
def get_runtime_session(session_id: str):
    try:
        return runtime_sessions.get(session_id).public()
    except Exception as exc:
        raise _runtime_http_error(exc) from exc


@app.put("/api/runtime/session/{session_id}")
async def update_runtime_session(session_id: str, request: Request):
    """Update setup values without returning, logging, or persisting keys."""

    try:
        payload = await _runtime_json(request)
        # Profile changes intentionally create a fresh session so an existing
        # worker cannot cross an embedding schema boundary midway through a run.
        if "profile_id" in payload:
            current = runtime_sessions.get(session_id)
            if payload["profile_id"] != current.profile.id:
                raise RuntimeProfileError(
                    "Changing runtime profile requires creating a new runtime session"
                )
            payload = dict(payload)
            del payload["profile_id"]
        profile_id, configuration, credentials = parse_session_payload(
            {"profile_id": runtime_sessions.get(session_id).profile.id, **payload}
        )
        # ``profile_id`` is checked above and retained only to use the same
        # strict payload parser as creation.
        del profile_id
        return runtime_sessions.update(
            session_id,
            configuration=configuration,
            credentials=credentials,
        ).public()
    except Exception as exc:
        raise _runtime_http_error(exc) from exc


@app.delete("/api/runtime/session/{session_id}", status_code=204)
def delete_runtime_session(session_id: str):
    try:
        runtime_sessions.close(session_id)
        return Response(status_code=204)
    except Exception as exc:
        raise _runtime_http_error(exc) from exc


@app.post("/api/runtime/session/{session_id}/preflight")
def preflight_runtime_session(session_id: str):
    """Run the read-only Qdrant Cloud connectivity/schema preflight."""

    try:
        session = runtime_sessions.get(session_id)
        return qdrant_preflight(session.validated_setup())
    except Exception as exc:
        raise _runtime_http_error(exc) from exc


@app.post("/api/processing/jobs", status_code=201)
async def create_job(video: UploadFile = File(...), configuration: str = Form("{}")):
    try:
        config = json.loads(configuration)
        if not isinstance(config, dict):
            raise ValueError("Job configuration must be a JSON object")
        if config.get("profile_id") == "api-gemini-free-v1":
            session_id = config.get("runtime_session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                raise ValueError("API-based indexing requires an active runtime session")
            # Fail before storing the upload if the opaque session expired.
            session = runtime_sessions.get(session_id)
            if session.profile.id != config.get("profile_id"):
                raise ValueError("Runtime session profile does not match the indexing job")
            config = _normalize_api_job_configuration(config, session)
        data = await video.read()
        job = manager.create(video.filename or "", data, config)
        return job.public()
    except (ValueError, VideoProbeError, RuntimeSessionNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/processing/jobs/{job_id}")
def get_job(job_id: str):
    return job_or_404(job_id).public()


@app.post("/api/processing/jobs/{job_id}/start")
def start_job(job_id: str):
    try:
        return manager.start(job_id).public()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/processing/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return manager.cancel(job_id).public()


@app.get("/api/processing/jobs/{job_id}/events")
def events(job_id: str):
    job = job_or_404(job_id)

    def stream():
        sent = 0
        while True:
            while sent < len(job.events):
                yield f"data: {json.dumps(job.events[sent])}\n\n"
                sent += 1
            if job.status in {
                "complete",
                "completed_with_errors",
                "partial",
                "failed",
                "cancelled",
            }:
                break
            import time

            time.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/processing/jobs/{job_id}/activity")
def activity(job_id: str, limit: int = 400):
    """Return the browser-safe diagnostic timeline without a full job payload."""
    job = job_or_404(job_id)
    bounded_limit = max(1, min(limit, 400))
    return {"activity": sanitize(job.activity[-bounded_limit:])}


@app.get("/api/processing/jobs/{job_id}/windows")
def windows(job_id: str):
    return {"windows": job_or_404(job_id).windows}


@app.get("/api/processing/jobs/{job_id}/windows/{window_index}")
def window(job_id: str, window_index: int):
    job = job_or_404(job_id)
    try:
        return next(x for x in job.windows if x["index"] == window_index)
    except StopIteration:
        raise HTTPException(404, "Window not found")


@app.post("/api/processing/jobs/{job_id}/windows/{window_index}/evaluation")
def evaluation(job_id: str, window_index: int, label: dict):
    job = job_or_404(job_id)
    job.evaluations[str(window_index)] = sanitize(label)
    (job.directory / "evaluation.json").write_text(
        json.dumps(job.evaluations, indent=2), encoding="utf-8"
    )
    return {"saved": True}


@app.get("/api/processing/jobs/{job_id}/video")
def video(job_id: str, request: Request):
    job = job_or_404(job_id)
    return media_response(job.video_path, request)


@app.get("/api/processing/jobs/{job_id}/frames/{window_index}")
def frames(job_id: str, window_index: int):
    row = window(job_id, window_index)
    return {"window_index": window_index, "frames": row.get("frames", [])}


@app.get("/api/processing/jobs/{job_id}/exports/{export_type}")
def export(job_id: str, export_type: str):
    allowed = {
        "report": "processing_report.json",
        "windows": "window_debug.jsonl",
        "selector": "selector_trace.csv",
        "transcript": "transcript.json",
        "vlm": "vlm_outputs.json",
        "errors": "errors.json",
        "config": "redacted_configuration.json",
        "activity": "activity.json",
        "evaluation": "../evaluation.json",
    }
    if export_type not in allowed:
        raise HTTPException(404, "Export not found")
    job = job_or_404(job_id)
    path = (job.directory / "exports" / allowed[export_type]).resolve()
    if job.directory not in path.parents or not path.is_file():
        raise HTTPException(404, "Export unavailable")
    return FileResponse(path, filename=path.name)


# --- Persistent indexed-library read model ---------------------------------


def _library_runtime(
    *, runtime_session_id: str | None = None, profile_id: str | None = None
) -> tuple[Settings, dict[str, int], tuple[str, ...]]:
    """Resolve a library/query view without ever returning cloud credentials."""

    resolved_profile_id = profile_id or "self-hosted-v1"
    profile = get_profile(resolved_profile_id)
    expected = {vector.name: vector.dimensions for vector in profile.vectors}
    if profile.qdrant_target == "local":
        base = Settings.from_env()
        return replace(base, collection_name=profile.collection_name), expected, ()
    if not runtime_session_id:
        raise HTTPException(400, "This API-based library requires the active runtime session")
    runtime = runtime_sessions.get_runtime_config(runtime_session_id)
    if runtime.get("runtime_profile_id") != profile.id:
        raise HTTPException(400, "Runtime session profile does not match the selected library")
    vector_store_target = str(runtime.get("vector_store_target") or "cloud")
    settings = replace(
        Settings.from_env(),
        qdrant_url=str(runtime["qdrant_url"]),
        qdrant_api_key=(
            str(runtime.get("qdrant_api_key") or "")
            if vector_store_target == "cloud"
            else None
        ),
        qdrant_timeout_seconds=float(runtime.get("qdrant_timeout_seconds", 10)),
        collection_name=profile.collection_name,
    )
    return settings, expected, tuple(
        value for key, value in runtime.items() if "key" in key.lower() and isinstance(value, str)
    )


def _redact_library_health(health: dict, secrets: tuple[str, ...]) -> dict:
    return redact_secrets(health, secrets)


def _library_http_error(
    operation: str,
    error: Exception,
    secrets: tuple[str, ...] = (),
) -> HTTPException:
    """Return the useful, redacted reason that the Library read failed."""

    if isinstance(error, LibraryReadError):
        detail = str(error)
    else:
        detail = (
            f"Library {operation.replace('_', ' ')} failed "
            f"({type(error).__name__}): {error}. "
            "Review Library diagnostics and retry."
        )
    safe_detail = str(redact_secrets(detail, secrets))
    logger.warning("Library %s failed: %s", operation, safe_detail)
    return HTTPException(503, safe_detail)


@app.get("/api/diagnostics/library")
def library_diagnostics(limit: int = 50):
    """Safe, persistent diagnostics for Library reads after indexing completes."""

    return {"diagnostics": list_library_diagnostics(limit=max(1, min(limit, 500)))}


@app.get("/api/index/health")
def index_health(
    runtime_session_id: str | None = None, profile_id: str | None = None
):
    secrets: tuple[str, ...] = ()
    try:
        settings, expected, secrets = _library_runtime(
            runtime_session_id=runtime_session_id, profile_id=profile_id
        )
        return _redact_library_health(
            collection_health(settings, expected_vector_dims=expected), secrets
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - return a safe connection diagnosis
        raise _library_http_error("collection_health", exc, secrets) from exc


@app.get("/api/index/videos")
def indexed_videos(
    limit: int = 500,
    runtime_session_id: str | None = None,
    profile_id: str | None = None,
):
    secrets: tuple[str, ...] = ()
    try:
        settings, _expected, secrets = _library_runtime(
            runtime_session_id=runtime_session_id, profile_id=profile_id
        )
        return {"videos": list_videos(settings=settings, limit=limit)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _library_http_error("indexed_videos", exc, secrets) from exc


@app.get("/api/index/windows")
def indexed_windows(
    video_id: str | None = None,
    limit: int = 100,
    vectors: bool = False,
    runtime_session_id: str | None = None,
    profile_id: str | None = None,
):
    secrets: tuple[str, ...] = ()
    try:
        settings, _expected, secrets = _library_runtime(
            runtime_session_id=runtime_session_id, profile_id=profile_id
        )
        return {
            "windows": list_windows(
                settings=settings, video_id=video_id, limit=limit, include_vectors=vectors
            )
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _library_http_error("indexed_windows", exc, secrets) from exc


@app.get("/api/index/windows/{window_id}")
def indexed_window(
    window_id: str,
    vectors: bool = True,
    runtime_session_id: str | None = None,
    profile_id: str | None = None,
):
    secrets: tuple[str, ...] = ()
    try:
        settings, _expected, secrets = _library_runtime(
            runtime_session_id=runtime_session_id, profile_id=profile_id
        )
        record = get_window(window_id, settings=settings, include_vectors=vectors)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _library_http_error("indexed_window", exc, secrets) from exc
    if record is None:
        raise HTTPException(404, "Indexed window not found")
    return record


@app.get("/api/index/media/{window_id}")
def indexed_media(
    window_id: str,
    request: Request,
    runtime_session_id: str | None = None,
    profile_id: str | None = None,
):
    secrets: tuple[str, ...] = ()
    try:
        settings, _expected, secrets = _library_runtime(
            runtime_session_id=runtime_session_id, profile_id=profile_id
        )
        path = media_path_for_window(window_id, settings=settings)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _library_http_error("indexed_media", exc, secrets) from exc
    if path is None:
        raise HTTPException(404, "Indexed media is unavailable")
    return media_response(path, request)


# --- Query API wrappers -----------------------------------------------------
# Kept in the same FastAPI process as indexing, but lazy model loading stays
# inside query_api so opening the upload UI never triggers query-model work.


@app.post("/api/query/search", response_model=SearchResponse)
def query_search(request: SearchRequest):
    return query_api.search(request)


@app.post("/api/query/verify", response_model=VerifyResponse)
def query_verify(request: VerifyRequest):
    return query_api.verify(request)


@app.get("/api/query/health")
def query_health():
    return query_api.health()
