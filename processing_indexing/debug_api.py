from __future__ import annotations
import json
import re
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from .debug_jobs import JobManager, sanitize
from .preflight import model_statuses
from .config import Settings

app = FastAPI(title="Processing Debug API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = JobManager()


def job_or_404(job_id):
    try:
        return manager.get(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found")


@app.get("/api/processing/preflight")
def preflight():
    return {"models": [x.model_dump() for x in model_statuses(Settings.from_env())]}


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
            if job.status in {"complete", "failed", "cancelled"}:
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
    size = job.video_path.stat().st_size
    header = request.headers.get("range")
    if not header:
        return FileResponse(job.video_path)
    match = re.match(r"bytes=(\d*)-(\d*)", header)
    if not match:
        raise HTTPException(416, "Invalid range")
    start = int(match.group(1) or 0)
    end = min(int(match.group(2) or size - 1), size - 1)
    if start > end or start >= size:
        raise HTTPException(416, "Range outside file")
    with job.video_path.open("rb") as stream:
        stream.seek(start)
        data = stream.read(end - start + 1)
    return Response(
        data,
        status_code=206,
        media_type="video/mp4",
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
        },
    )


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
