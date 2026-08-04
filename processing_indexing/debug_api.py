from __future__ import annotations
import json
import mimetypes
import re
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from .debug_jobs import JobManager, sanitize
from .preflight import model_statuses
from .config import Settings
from .library import collection_health, get_window, list_videos, list_windows, media_path_for_window
from query_retrieval import api as query_api
from query_retrieval.models import SearchRequest, SearchResponse, VerifyRequest, VerifyResponse

app = FastAPI(title="Processing Debug API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3017",
        "http://127.0.0.1:3017",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = JobManager()


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


@app.post("/api/processing/jobs", status_code=201)
async def create_job(video: UploadFile = File(...), configuration: str = Form("{}")):
    try:
        config = json.loads(configuration)
        data = await video.read()
        job = manager.create(video.filename or "", data, config)
        return job.public()
    except (ValueError, json.JSONDecodeError) as exc:
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


@app.get("/api/index/health")
def index_health():
    return collection_health()


@app.get("/api/index/videos")
def indexed_videos(limit: int = 500):
    try:
        return {"videos": list_videos(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not read indexed videos: {exc}") from exc


@app.get("/api/index/windows")
def indexed_windows(video_id: str | None = None, limit: int = 100, vectors: bool = False):
    try:
        return {
            "windows": list_windows(
                video_id=video_id, limit=limit, include_vectors=vectors
            )
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not read indexed windows: {exc}") from exc


@app.get("/api/index/windows/{window_id}")
def indexed_window(window_id: str, vectors: bool = True):
    try:
        record = get_window(window_id, include_vectors=vectors)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not read indexed window: {exc}") from exc
    if record is None:
        raise HTTPException(404, "Indexed window not found")
    return record


@app.get("/api/index/media/{window_id}")
def indexed_media(window_id: str, request: Request):
    try:
        path = media_path_for_window(window_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not resolve indexed media: {exc}") from exc
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
