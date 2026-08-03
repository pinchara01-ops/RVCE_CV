from __future__ import annotations
from dataclasses import dataclass, field, replace
from pathlib import Path
import csv
import io
import json
import os
import threading
import time
import uuid
from .config import Settings
from .preflight import model_statuses
from .probe import probe_video, stable_video_id
from .models import VLMDescription

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
SECRET_KEYS = {"openai_api_key", "api_key", "qdrant_api_key", "authorization"}


def sanitize(value):
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if k.lower() in SECRET_KEYS or "key" in k.lower()
                else sanitize(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def safe_filename(name: str) -> str:
    clean = Path(name).name
    if clean != name or Path(clean).suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Unsafe or unsupported video filename")
    return clean


@dataclass
class Job:
    id: str
    directory: Path
    video_path: Path
    config: dict
    metadata: dict
    status: str = "created"
    stage: str = "validated"
    progress: float = 0.0
    current_window: int = 0
    total_windows: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel_requested: bool = False
    windows: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    report: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    evaluations: dict[str, dict] = field(default_factory=dict)

    def public(self):
        return sanitize(
            {
                "job_id": self.id,
                "status": self.status,
                "stage": self.stage,
                "progress": self.progress,
                "current_window": self.current_window,
                "total_windows": self.total_windows,
                "elapsed_seconds": (self.finished_at or time.time())
                - (self.started_at or self.created_at),
                "configuration": self.config,
                "metadata": self.metadata,
                "summary": self.report,
                "errors": self.errors,
                "model_status": [
                    x.model_dump()
                    for x in model_statuses(
                        Settings.from_env(), self.config.get("vlm_mode")
                    )
                ],
            }
        )


class JobManager:
    def __init__(self, root: Path | None = None):
        self.root = (
            root or Path(os.getenv("PROCESSING_JOBS_DIR", "processing_jobs"))
        ).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._active: str | None = None

    def create(self, filename: str, data: bytes, config: dict) -> Job:
        name = safe_filename(filename)
        job_id = uuid.uuid4().hex
        directory = self.root / job_id
        directory.mkdir()
        path = (directory / name).resolve()
        if directory not in path.parents:
            raise ValueError("Unsafe upload path")
        path.write_bytes(data)
        metadata = probe_video(path).model_dump()
        video_id = stable_video_id(path)
        metadata["video_id"] = video_id
        job = Job(job_id, directory, path, sanitize(config), metadata)
        self.jobs[job_id] = job
        self._event(job, "created")
        return job

    def get(self, job_id: str) -> Job:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise KeyError("Job not found")

    def _event(self, job: Job, event: str, **details):
        job.events.append(
            {
                "sequence": len(job.events),
                "event": event,
                "timestamp": time.time(),
                **sanitize(details),
            }
        )

    def start(self, job_id: str):
        job = self.get(job_id)
        with self._lock:
            if self._active and self._active != job_id:
                raise RuntimeError("Another processing job is active")
            if job.status not in {"created", "cancelled", "failed"}:
                raise RuntimeError("Job cannot be started")
            self._active = job_id
            job.status = "queued"
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def cancel(self, job_id: str):
        job = self.get(job_id)
        job.cancel_requested = True
        self._event(job, "cancel_requested")
        return job

    def _run(self, job: Job):
        try:
            job.status = "running"
            job.started_at = time.time()
            job.stage = "configuration"
            self._event(job, "started")
            settings = self._settings(job)
            mode = job.config.get("vlm_mode", "selection_only")
            if mode not in {"selection_only", "mock", "openai"}:
                raise ValueError("Unsupported VLM mode")
            if mode == "mock" and job.config.get("index_qdrant"):
                collection = str(job.config.get("collection_name", ""))
                if not (
                    collection.startswith("debug_") or collection.startswith("mock_")
                ):
                    raise ValueError(
                        "Mock results require a debug_ or mock_ Qdrant collection"
                    )
            self._execute_pipeline(job, settings, mode)
            if job.cancel_requested:
                job.status = "cancelled"
                job.stage = "cancelled"
                self._event(job, "cancelled")
                return
            job.stage = "complete"
            job.status = "complete"
            job.progress = 1.0
            job.finished_at = time.time()
            self._write_artifacts(job)
            self._event(job, "complete")
        except Exception as exc:
            job.status = "failed"
            job.stage = "failed"
            job.finished_at = time.time()
            job.errors.append({"message": str(exc)})
            self._event(job, "failed", message=str(exc))
        finally:
            with self._lock:
                if self._active == job.id:
                    self._active = None

    def _settings(self, job):
        base = Settings.from_env()
        c = job.config
        return replace(
            base,
            window_seconds=float(c.get("window_seconds", 10)),
            stride_seconds=float(c.get("stride_seconds", 5)),
            device=str(c.get("device", "cpu")),
            collection_name=str(c.get("collection_name", "video_windows")),
            vlm_visual_change_threshold=float(
                c.get("visual_threshold", base.vlm_visual_change_threshold)
            ),
            vlm_audio_change_threshold=float(
                c.get("audio_threshold", base.vlm_audio_change_threshold)
            ),
            vlm_speech_change_threshold=float(
                c.get("speech_threshold", base.vlm_speech_change_threshold)
            ),
            vlm_combined_change_threshold=float(
                c.get("combined_threshold", base.vlm_combined_change_threshold)
            ),
            vlm_change_weight_visual=float(
                c.get("visual_weight", base.vlm_change_weight_visual)
            ),
            vlm_change_weight_audio=float(
                c.get("audio_weight", base.vlm_change_weight_audio)
            ),
            vlm_change_weight_speech=float(
                c.get("speech_weight", base.vlm_change_weight_speech)
            ),
            openai_vlm_max_frames=int(
                c.get("openai_max_frames", base.openai_vlm_max_frames)
            ),
            max_windows=(
                int(c["max_windows"]) if int(c.get("max_windows", 0)) > 0 else None
            ),
        )

    def _execute_pipeline(self, job, settings, mode):
        from .audio_encoder import ClapAudioEncoder
        from .pipeline import ProcessingPipeline
        from .qdrant_store import QdrantStore, deterministic_point_id
        from .text_encoder import BgeM3TextEncoder
        from .transcription import FasterWhisperTranscriber
        from .visual_encoder import XClipVisualEncoder
        from .vlm import OpenAIVisionProvider

        class Cancelled(RuntimeError):
            pass

        def check():
            if job.cancel_requested:
                raise Cancelled("Cancellation requested")

        class Guard:
            def __init__(self, inner):
                self.inner = inner

            def encode(self, *args):
                check()
                return self.inner.encode(*args)

        class GuardTranscriber:
            def __init__(self, inner):
                self.inner = inner

            def transcribe(self, *args):
                check()
                job.stage = "transcription"
                return self.inner.transcribe(*args)

        class MemoryStore:
            def __init__(self):
                self.records = []

            def ensure_collection(self):
                pass

            def upsert(self, items):
                check()
                self.records.extend(items)

        class TeeStore:
            def __init__(self, debug_store, index_store):
                self.debug_store = debug_store
                self.index_store = index_store

            def ensure_collection(self):
                self.index_store.ensure_collection()

            def existing_window_ids(self, video_id):
                return self.index_store.existing_window_ids(video_id)

            def upsert(self, items):
                self.debug_store.upsert(items)
                self.index_store.upsert(items)

        class DebugVLM:
            def describe(self, path, window):
                check()
                job.stage = "mock_vlm"
                return VLMDescription(
                    scene_context=f"Deterministic debug context for window {window.index}",
                    confidence=1,
                )

        class SelectionVLM:
            def describe(self, path, window):
                check()
                return VLMDescription(confidence=1)

        transcriber = GuardTranscriber(
            FasterWhisperTranscriber(settings.whisper_model, settings.device)
        )
        visual = Guard(XClipVisualEncoder(device=settings.device))
        audio = Guard(ClapAudioEncoder(device=settings.device))
        text = Guard(BgeM3TextEncoder(device=settings.device))
        if mode == "openai":
            inner = OpenAIVisionProvider(
                settings.openai_api_key,
                settings.openai_vlm_model,
                settings.openai_vlm_timeout_seconds,
                settings.openai_vlm_retries,
                settings.openai_vlm_image_detail,
                settings.openai_vlm_max_frames,
            )

            class OpenAIGuard:
                def describe(self, *args):
                    check()
                    job.stage = "openai_vlm"
                    result = inner.describe(*args)
                    window = args[1]
                    openai_debug[window.index] = {
                        "request": inner.last_sanitized_request,
                        "response": inner.last_sanitized_response,
                        "usage": inner.last_usage,
                    }
                    return result

            openai_debug = {}
            vlm = OpenAIGuard()
        elif mode == "mock":
            vlm = DebugVLM()
        else:
            vlm = SelectionVLM()
        memory = MemoryStore()
        store = memory
        if job.config.get("index_qdrant"):
            from qdrant_client import QdrantClient

            index_store = QdrantStore(
                QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key),
                settings.collection_name,
                settings.batch_size,
            )
            store = TeeStore(memory, index_store)
        job.stage = "model_processing"
        report = ProcessingPipeline(
            transcriber, visual, audio, text, vlm, store, settings
        ).process_video(job.video_path)
        records = memory.records
        job.total_windows = report.total_windows
        for payload, vectors in records:
            diagnostics = {
                name: _vector_summary(getattr(vectors, name))
                for name in ("visual", "audio", "speech", "caption")
            }
            provenance = (
                "direct"
                if payload.caption_direct
                else "inherited"
                if payload.caption_inherited
                else "unavailable"
            )
            job.windows.append(
                {
                    "index": int(payload.window_id.rsplit("_", 1)[1]),
                    "window_id": payload.window_id,
                    "start": payload.start,
                    "end": payload.end,
                    "transcript": payload.transcript,
                    "change_scores": payload.change_scores,
                    "selected": bool(payload.selection_reasons),
                    "selection_reasons": payload.selection_reasons,
                    "vlm_call_state": "succeeded"
                    if payload.vlm_processed
                    else "skipped",
                    "caption": payload.caption,
                    "provenance": provenance,
                    "confidence": payload.caption_confidence,
                    "indexed": bool(job.config.get("index_qdrant")),
                    "point_id": deterministic_point_id(payload.window_id),
                    "vectors": diagnostics,
                    "cache": {"pipeline": "newly_computed"},
                    "openai": openai_debug.get(int(payload.window_id.rsplit("_", 1)[1]))
                    if mode == "openai"
                    else None,
                    "errors": [],
                }
            )
        job.report = report.model_dump(mode="json")
        job.report.update(
            {
                "actual_openai_calls": report.successful_vlm_windows
                + report.failed_vlm_windows
                if mode == "openai"
                else 0,
                "provider_mode": mode,
                "qdrant_inserted": report.successfully_indexed_windows
                if job.config.get("index_qdrant")
                else 0,
                "qdrant_updated": 0,
            }
        )

    def _write_artifacts(self, job):
        exports = job.directory / "exports"
        exports.mkdir(exist_ok=True)
        (exports / "processing_report.json").write_text(
            json.dumps(sanitize(job.report), indent=2), encoding="utf-8"
        )
        (exports / "window_debug.jsonl").write_text(
            "\n".join(json.dumps(sanitize(x)) for x in job.windows), encoding="utf-8"
        )
        transcript = [
            {
                "index": x["index"],
                "start": x["start"],
                "end": x["end"],
                "transcript": x["transcript"],
            }
            for x in job.windows
        ]
        vlm = [
            {
                "index": x["index"],
                "caption": x["caption"],
                "provenance": x["provenance"],
                "confidence": x["confidence"],
            }
            for x in job.windows
        ]
        (exports / "transcript.json").write_text(
            json.dumps(transcript, indent=2), encoding="utf-8"
        )
        (exports / "vlm_outputs.json").write_text(
            json.dumps(vlm, indent=2), encoding="utf-8"
        )
        (exports / "errors.json").write_text(
            json.dumps(sanitize(job.errors), indent=2), encoding="utf-8"
        )
        (exports / "redacted_configuration.json").write_text(
            json.dumps(sanitize(job.config), indent=2), encoding="utf-8"
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["index", "start", "end", "selected", "selection_reasons"],
        )
        writer.writeheader()
        for row in job.windows:
            writer.writerow({k: row[k] for k in writer.fieldnames})
        (exports / "selector_trace.csv").write_text(output.getvalue(), encoding="utf-8")
        (job.directory / "evaluation.json").write_text(
            json.dumps(job.evaluations, indent=2), encoding="utf-8"
        )


def _vector_summary(vector):
    import math

    return {
        "shape": [len(vector)],
        "norm": math.sqrt(sum(x * x for x in vector)),
        "min": min(vector),
        "max": max(vector),
        "finite": all(math.isfinite(x) for x in vector),
    }
