from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .models import VLMDescription
from .preflight import model_statuses
from .probe import probe_video, stable_video_id

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
SECRET_KEYS = {
    "openai_api_key",
    "gemini_api_key",
    "nvidia_api_key",
    "api_key",
    "qdrant_api_key",
    "authorization",
}
MAX_ACTIVITY_ENTRIES = 400


def summarize_openai_usage(openai_debug):
    categories = {
        "successful_captured": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        "failed_captured": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    }
    unknown = 0
    for value in openai_debug.values():
        for attempt in value.get("attempts", []):
            usage = attempt.get("usage")
            if attempt.get("usage_status") != "captured" or usage is None:
                unknown += 1
                continue
            key = (
                "successful_captured"
                if attempt.get("status") == "succeeded"
                else "failed_captured"
            )
            categories[key]["calls"] += 1
            for token_field in ("input_tokens", "output_tokens", "total_tokens"):
                categories[key][token_field] += int(usage.get(token_field, 0))
    minimum = {
        token_field: categories["successful_captured"][token_field]
        + categories["failed_captured"][token_field]
        for token_field in ("input_tokens", "output_tokens", "total_tokens")
    }
    return {
        **categories,
        "calls_with_unknown_usage": unknown,
        "minimum_known_usage": minimum,
    }


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
    # Human-readable, structured diagnostics intended for the processing UI.
    # Unlike ``events`` (which is the transport/SSE stream), these records are
    # retained in the status payload and can be rendered as a timeline.
    activity: list[dict] = field(default_factory=list)
    activity_sequence: int = field(default=0, repr=False)
    # Dynamic model state is separate from preflight cache state.  It lets the
    # UI distinguish "cached locally" from "currently loading" and "ready".
    model_activity: dict[str, dict] = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    evaluations: dict[str, dict] = field(default_factory=dict)
    # A browser-supplied provider key exists only for the active in-memory job
    # run.  ``config`` is deliberately the redacted, user-visible version.
    private_config: dict = field(default_factory=dict, repr=False)

    def runtime_config(self) -> dict:
        """Return non-public execution settings without exposing credentials."""
        return self.private_config or self.config

    def public(self):
        statuses = [
            x.model_dump()
            for x in model_statuses(
                Settings.from_env(), self.config.get("vlm_mode")
            )
        ]
        for status in statuses:
            runtime = self.model_activity.get(status["component"])
            if runtime is None:
                continue
            status["loading_attempted"] = runtime["state"] != "not_attempted"
            status["load_success"] = runtime["state"] == "ready"
            status["message"] = runtime["message"]
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
                "model_status": statuses,
                "activity": self.activity,
                "runtime_models": self.model_activity,
            }
        )


class JobManager:
    def __init__(
        self,
        root: Path | None = None,
        *,
        runtime_config_resolver: Callable[[str], dict] | None = None,
    ):
        self.root = (
            root or Path(os.getenv("PROCESSING_JOBS_DIR", "processing_jobs"))
        ).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._active: str | None = None
        # API-profile credentials live in RuntimeSessionStore, never in an
        # upload request or exported job configuration.  The resolver is
        # injected to avoid a debug_api import cycle.
        self._runtime_config_resolver = runtime_config_resolver

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
        metadata["filename"] = name
        job = Job(
            job_id,
            directory,
            path,
            sanitize(config),
            metadata,
            private_config=dict(config),
        )
        self.jobs[job_id] = job
        self._event(job, "created")
        self._activity(
            job,
            "upload",
            "Upload validated and ready to process",
            filename=name,
            bytes=len(data),
            duration_seconds=metadata.get("duration"),
            container=metadata.get("container"),
            video_codec=metadata.get("codec"),
            has_audio=metadata.get("has_audio"),
            dimensions=[metadata.get("width"), metadata.get("height")],
        )
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

    def _safe_message(self, job: Job, message: object) -> str:
        """Keep browser diagnostics useful without echoing a supplied key."""
        result = str(message)

        def visit(value: object, name: str = ""):
            nonlocal result
            if isinstance(value, dict):
                for key, nested in value.items():
                    visit(nested, str(key))
            elif isinstance(value, (list, tuple)):
                for nested in value:
                    visit(nested, name)
            elif (
                isinstance(value, str)
                and value
                and ("key" in name.lower() or name.lower() == "authorization")
            ):
                result = result.replace(value, "[REDACTED]")

        visit(job.runtime_config())
        return result

    def _activity(
        self,
        job: Job,
        area: str,
        message: object,
        *,
        level: str = "info",
        **details,
    ) -> dict:
        """Append one bounded, UI-safe diagnostic record and publish it over SSE."""
        entry = {
            "sequence": job.activity_sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "area": area,
            "message": self._safe_message(job, message),
        }
        job.activity_sequence += 1
        if details:
            entry["details"] = sanitize(details)
        job.activity.append(entry)
        if len(job.activity) > MAX_ACTIVITY_ENTRIES:
            del job.activity[: len(job.activity) - MAX_ACTIVITY_ENTRIES]
        self._event(job, "activity", activity=entry)
        return entry

    def _model_state(
        self,
        job: Job,
        component: str,
        state: str,
        message: object,
        **details,
    ) -> None:
        record = {
            "state": state,
            "message": self._safe_message(job, message),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if details:
            record["details"] = sanitize(details)
        job.model_activity[component] = record
        self._activity(
            job,
            "model",
            message,
            level="error" if state == "failed" else "info",
            component=component,
            state=state,
            **details,
        )

    def start(self, job_id: str):
        job = self.get(job_id)
        with self._lock:
            if self._active and self._active != job_id:
                raise RuntimeError("Another processing job is active")
            # A job directory is a durable record of one attempt.  Reusing it
            # after cancellation/failure previously mixed old rows with a new
            # run, so the UI now makes every retry a fresh upload/job.
            if job.status != "created":
                raise RuntimeError("Job cannot be started")
            self._active = job_id
            job.status = "queued"
            self._activity(
                job,
                "job",
                "Processing job queued",
                stage="queued",
            )
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def cancel(self, job_id: str):
        job = self.get(job_id)
        job.cancel_requested = True
        self._event(job, "cancel_requested")
        self._activity(
            job,
            "job",
            "Cancellation requested. The current model call will finish safely before the job stops.",
            level="warning",
            stage=job.stage,
        )
        return job

    def _hydrate_api_runtime(self, job: Job) -> None:
        """Attach a private runtime session just before an API job executes.

        The persisted/public job configuration contains only the opaque session
        id.  Credentials are resolved from the in-memory session store at
        execution time and are removed from the job object again in ``finally``.
        """

        profile_id = str(job.config.get("profile_id") or "")
        if profile_id != "api-gemini-free-v1":
            return
        session_id = job.config.get("runtime_session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("API-based indexing requires an active runtime session")
        if self._runtime_config_resolver is None:
            raise RuntimeError("API runtime sessions are not configured in this backend")
        runtime = self._runtime_config_resolver(session_id)
        if runtime.get("runtime_profile_id") != profile_id:
            raise ValueError("Runtime session profile does not match this indexing job")
        # The session config wins for cloud endpoint, provider choices, and
        # collection contract.  User-tunable non-secret settings stay in the
        # job-local mapping.
        job.private_config = {**job.private_config, **runtime}
        self._activity(
            job,
            "runtime",
            "Resolved the API-based session in backend memory",
            profile_id=profile_id,
            collection=runtime.get("collection_name"),
            providers=runtime.get("providers", {}),
        )

    @staticmethod
    def _forget_runtime_credentials(job: Job) -> None:
        """Drop transient key values from the in-memory Job after execution."""

        for name in tuple(job.private_config):
            if "key" in name.lower() or name.lower() == "authorization":
                del job.private_config[name]

    def _run(self, job: Job):
        try:
            job.status = "running"
            job.started_at = time.time()
            job.stage = "configuration"
            self._event(job, "started")
            self._hydrate_api_runtime(job)
            settings = self._settings(job)
            run_config = job.runtime_config()
            mode = run_config.get("vlm_mode", "selection_only")
            self._activity(
                job,
                "job",
                "Processing started",
                stage="configuration",
                device=settings.device,
                vlm_mode=mode,
                index_qdrant=bool(run_config.get("index_qdrant")),
                collection=settings.collection_name,
                window_seconds=settings.window_seconds,
                stride_seconds=settings.stride_seconds,
                max_windows=settings.max_windows,
            )
            if run_config.get("runtime_profile_id") == "api-gemini-free-v1":
                self._execute_api_pipeline(job, settings)
            else:
                if mode not in {"selection_only", "mock", "openai", "cosmos", "local_qwen"}:
                    raise ValueError("Unsupported VLM mode")
                if mode == "mock" and run_config.get("index_qdrant"):
                    collection = settings.collection_name
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
                job.report["status"] = "cancelled"
                job.finished_at = time.time()
                self._activity(job, "job", "Processing cancelled safely")
                self._event(job, "cancelled")
                self._write_artifacts(job)
                return
            pipeline_status = job.report.get("status", "failed")
            if pipeline_status == "failed":
                job.stage = "failed"
                job.status = "failed"
                job.progress = 1.0
                job.finished_at = time.time()
                self._activity(
                    job,
                    "job",
                    "Processing pipeline finished without an indexable result",
                    level="error",
                )
                self._event(job, "failed", message="Processing pipeline failed")
                self._write_artifacts(job)
                return
            job.stage = pipeline_status
            job.status = pipeline_status
            job.progress = 1.0
            job.finished_at = time.time()
            self._activity(
                job,
                "job",
                "Processing finished",
                status=pipeline_status,
                indexed_windows=job.report.get("successfully_indexed_windows"),
                failed_windows=job.report.get("failed_windows"),
            )
            self._event(job, pipeline_status)
            self._write_artifacts(job)
        except Exception as exc:
            if job.cancel_requested:
                job.status = "cancelled"
                job.stage = "cancelled"
                job.finished_at = time.time()
                job.report = {**job.report, "status": "cancelled"}
                self._activity(job, "job", "Processing cancelled safely")
                self._event(job, "cancelled")
                self._write_artifacts(job)
                return
            job.status = "failed"
            job.stage = "failed"
            job.finished_at = time.time()
            safe_error = self._safe_message(job, exc)
            job.errors.append({"message": safe_error})
            job.report = {
                **job.report,
                "status": "failed",
                "errors": job.report.get("errors", {}),
                "stage_durations": job.report.get("stage_durations", {}),
            }
            self._activity(
                job,
                "job",
                "Processing stopped with an error",
                level="error",
                error_type=type(exc).__name__,
                error=safe_error,
            )
            self._event(job, "failed", message=safe_error)
            self._write_artifacts(job)
        finally:
            self._forget_runtime_credentials(job)
            with self._lock:
                if self._active == job.id:
                    self._active = None

    def _settings(self, job):
        base = Settings.from_env()
        c = job.runtime_config()
        return replace(
            base,
            window_seconds=float(c.get("window_seconds", 10)),
            stride_seconds=float(c.get("stride_seconds", 5)),
            device=str(c.get("device", "cpu")),
            qdrant_url=str(c.get("qdrant_url", base.qdrant_url)),
            qdrant_api_key=c.get("qdrant_api_key", base.qdrant_api_key),
            qdrant_timeout_seconds=float(
                c.get("qdrant_timeout_seconds", base.qdrant_timeout_seconds)
            ),
            collection_name=str(c.get("collection_name", base.collection_name)),
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
            vlm_model=str(c.get("local_qwen_model", base.vlm_model)),
            max_windows=(
                int(c["max_windows"]) if int(c.get("max_windows", 0)) > 0 else None
            ),
        )

    def _execute_api_pipeline(self, job: Job, settings: Settings) -> None:
        """Run the credential-private Gemini/Qdrant Cloud indexing profile.

        This path is intentionally separate from ``_execute_pipeline``: it
        must never instantiate Whisper, X-CLIP, CLAP, BGE, or local Qdrant.
        The only stored job configuration is the opaque session id; API keys
        are present only in ``job.private_config`` for this active call.
        """

        from .api_pipeline import (
            ApiPipelineSettings,
            GeminiApiPipelineFactoryConfig,
            api_contract_from_runtime_profile,
            build_gemini_api_pipeline,
            make_profile_qdrant_sink,
        )
        from .runtime_profiles import get_profile

        runtime = job.runtime_config()
        profile = get_profile(str(runtime.get("runtime_profile_id")))
        providers = dict(runtime.get("providers") or {})
        unsupported = {
            stage: provider
            for stage, provider in providers.items()
            if stage in {"transcription", "media_embedding", "text_embedding"}
            and provider != "gemini"
        }
        if unsupported:
            selections = ", ".join(
                f"{stage}={provider}" for stage, provider in sorted(unsupported.items())
            )
            raise ValueError(
                "This API indexing implementation currently executes the Gemini "
                f"profile only; change these stages to Gemini: {selections}"
            )
        gemini_key = runtime.get("gemini_api_key")
        if not isinstance(gemini_key, str) or not gemini_key.strip():
            raise ValueError("The active API session does not contain a Gemini API key")

        models = dict(runtime.get("models") or {})
        embedding_model = str(models.get("media_embedding") or "gemini-embedding-2")
        generation_model = str(models.get("transcription") or "gemini-3.5-flash-lite")
        contract = api_contract_from_runtime_profile(profile)

        def qdrant_progress(done: int, total: int) -> None:
            job.stage = "qdrant_upsert"
            job.current_window = done
            job.total_windows = max(job.total_windows, total)
            self._activity(
                job,
                "qdrant",
                f"Qdrant Cloud confirmed {done}/{total} indexed windows",
                current_window=done,
                total_windows=total,
                collection=contract.collection_name,
            )

        def pipeline_progress(event) -> None:
            job.stage = event.stage
            job.progress = max(job.progress, min(float(event.progress), 0.98))
            job.current_window = int(event.current_window)
            job.total_windows = int(event.total_windows)
            self._activity(
                job,
                "api_pipeline",
                event.message,
                level="warning" if event.status in {"warning", "failed"} else "info",
                stage=event.stage,
                state=event.status,
                overall_progress=round(job.progress, 3),
                current_window=job.current_window,
                total_windows=job.total_windows,
                **dict(event.details),
            )

        sink = None
        if runtime.get("index_qdrant"):
            sink = make_profile_qdrant_sink(
                qdrant_url=str(runtime.get("qdrant_url") or ""),
                qdrant_api_key=str(runtime.get("qdrant_api_key") or ""),
                profile=profile,
                timeout_seconds=settings.qdrant_timeout_seconds,
                batch_size=settings.batch_size,
                on_progress=qdrant_progress,
            )
        self._model_state(
            job,
            "gemini_api",
            "loading",
            "Preparing hosted Gemini embedding, transcription, and caption services",
            embedding_model=embedding_model,
            generation_model=generation_model,
        )
        self._activity(
            job,
            "qdrant",
            "Using the managed Qdrant Cloud profile collection",
            collection=contract.collection_name,
            persistent=bool(sink),
        )
        bundle = build_gemini_api_pipeline(
            GeminiApiPipelineFactoryConfig(
                gemini_api_key=gemini_key,
                embedding_model=embedding_model,
                embedding_dimensions=contract.dimensions,
                generation_model=generation_model,
                profile_id=contract.profile_id,
                collection_name=contract.collection_name,
            ),
            record_sink=sink,
            progress_callback=pipeline_progress,
            settings=ApiPipelineSettings(
                window_seconds=settings.window_seconds,
                stride_seconds=settings.stride_seconds,
                profile=contract,
            ),
        )
        caption_provider = str(providers.get("caption") or "gemini")
        if caption_provider in {"openai", "cosmos"}:
            # Reuse the existing hosted VLM implementations only for the
            # bounded, change-selected caption windows.  Gemini remains the
            # free default; this is an explicit paid/credit override.
            from .gemini_runtime import GeminiCallAttempt, GeminiCallDiagnostics
            from .gemini_transcription import GeminiCaptionResult
            from .vlm import NvidiaCosmosProvider, OpenAIVisionProvider

            caption_model = str(models.get("caption") or "")
            if caption_provider == "openai":
                inner = OpenAIVisionProvider(
                    str(runtime.get("openai_api_key") or ""),
                    caption_model or settings.openai_vlm_model,
                    settings.openai_vlm_timeout_seconds,
                    settings.openai_vlm_retries,
                    settings.openai_vlm_image_detail,
                    settings.openai_vlm_max_frames,
                )
            else:
                inner = NvidiaCosmosProvider(
                    str(runtime.get("nvidia_api_key") or ""),
                    caption_model or "nvidia/cosmos3-nano-reasoner",
                    settings.openai_vlm_timeout_seconds,
                    settings.openai_vlm_retries,
                    8,
                )

            class HostedCaptioner:
                model = caption_model or caption_provider

                def caption_window(self, clip, window):
                    description = inner.describe(clip.path, window)
                    return GeminiCaptionResult(
                        caption=description.caption(),
                        confidence=description.confidence,
                        evidence=tuple(description.actions + description.objects_and_colours),
                        diagnostics=GeminiCallDiagnostics(
                            model=self.model,
                            operation=f"{caption_provider}_caption",
                            attempts=[GeminiCallAttempt(attempt=1, status="succeeded")],
                        ),
                        model=self.model,
                    )

            bundle.pipeline.captioner = HostedCaptioner()
            self._activity(
                job,
                "vlm",
                "Using the selected paid VLM only for bounded caption windows",
                provider=caption_provider,
                model=caption_model,
            )
        report = bundle.pipeline.process_video(
            job.video_path,
            video_id=str(job.metadata.get("video_id") or "") or None,
            duration_seconds=float(job.metadata.get("duration") or 0) or None,
            has_audio=bool(job.metadata.get("has_audio")),
        )
        self._model_state(
            job,
            "gemini_api",
            "ready",
            "Hosted Gemini indexing calls completed",
            provider_calls=dict(report.provider_calls),
        )
        job.total_windows = report.total_windows
        job.current_window = report.indexed_windows
        for record in report.records:
            payload = dict(record.payload)
            vectors = dict(record.vectors)
            window_id = str(payload["window_id"])
            caption = str(payload.get("caption") or "")
            job.windows.append(
                {
                    "index": int(payload.get("window_index", len(job.windows))),
                    "video_id": payload.get("video_id", ""),
                    "window_id": window_id,
                    "start": float(payload.get("start", 0)),
                    "end": float(payload.get("end", 0)),
                    "transcript": payload.get("transcript", ""),
                    "change_scores": {},
                    "selected": bool(payload.get("caption_selected")),
                    "selection_reasons": ["embedding_change"] if payload.get("caption_selected") else [],
                    "vlm_call_state": "direct" if payload.get("caption_direct") else "inherited" if caption else "unavailable",
                    "caption": caption,
                    "has_audio": bool(payload.get("has_audio")),
                    "provenance": "direct" if payload.get("caption_direct") else "inherited" if payload.get("caption_inherited") else "unavailable",
                    "confidence": float(payload.get("caption_confidence") or 0),
                    "indexed": bool(sink),
                    "point_id": None,
                    "stored_payload": {key: value for key, value in payload.items() if key != "source_path"},
                    "vectors": {name: _vector_summary(values) for name, values in vectors.items()},
                    "openai": None,
                    "cosmos": None,
                    "errors": [error for key, error in report.errors.items() if key.startswith(window_id)],
                }
            )
        job.errors.extend(
            {"window_id": window_id, "message": message}
            for window_id, message in report.errors.items()
        )
        job.report = {
            "status": "completed",
            "provider_mode": "api-gemini",
            "embedding_profile": contract.profile_id,
            "collection_name": contract.collection_name,
            "total_windows": report.total_windows,
            "successfully_indexed_windows": report.indexed_windows,
            "failed_windows": report.failed_windows,
            "selected_vlm_windows": report.selected_caption_windows,
            "direct_captions": report.direct_caption_windows,
            "inherited_captions": report.inherited_caption_windows,
            "transcript_segments": report.transcript_segments,
            "elapsed_seconds": report.elapsed_seconds,
            "provider_calls": dict(report.provider_calls),
            "qdrant_inserted": report.indexed_windows if sink else 0,
            "errors": dict(report.errors),
        }

    def _execute_pipeline(self, job, settings, mode):
        from .audio_encoder import ClapAudioEncoder
        from .pipeline import ProcessingPipeline
        from .qdrant_store import QdrantStore, deterministic_point_id
        from .text_encoder import BgeM3TextEncoder
        from .transcription import FasterWhisperTranscriber
        from .visual_encoder import XClipVisualEncoder
        from .vlm import LocalQwenProvider, NvidiaCosmosProvider, OpenAIVisionProvider

        manager = self

        class Cancelled(RuntimeError):
            pass

        def check():
            if job.cancel_requested:
                raise Cancelled("Cancellation requested")

        class Guard:
            def __init__(self, inner, component, checkpoint):
                self.inner = inner
                self.component = component
                self.checkpoint = checkpoint

            def encode(self, *args):
                check()
                first_use = self.component not in job.model_activity
                if first_use:
                    manager._model_state(
                        job,
                        self.component,
                        "loading",
                        f"Loading {self.component} model",
                        checkpoint=self.checkpoint,
                        device=settings.device,
                    )
                try:
                    result = self.inner.encode(*args)
                except Exception as exc:
                    manager._model_state(
                        job,
                        self.component,
                        "failed",
                        f"{self.component} model failed",
                        checkpoint=self.checkpoint,
                        error_type=type(exc).__name__,
                        error=manager._safe_message(job, exc),
                    )
                    raise
                if first_use:
                    manager._model_state(
                        job,
                        self.component,
                        "ready",
                        f"{self.component} model is ready",
                        checkpoint=self.checkpoint,
                        device=settings.device,
                    )
                return result

        class GuardTranscriber:
            def __init__(self, inner):
                self.inner = inner

            def transcribe(self, *args, **kwargs):
                check()
                job.stage = "transcription"
                has_audio = bool(args[1]) if len(args) > 1 else True
                if not has_audio:
                    manager._model_state(
                        job,
                        "whisper",
                        "skipped",
                        "Source has no audio, so Whisper transcription was skipped",
                    )
                    return self.inner.transcribe(*args, **kwargs)

                duration = float(job.metadata.get("duration") or 0)
                last_bucket = -1

                def transcription_progress(processed_seconds: float):
                    nonlocal last_bucket
                    if duration <= 0:
                        return
                    fraction = max(0.0, min(float(processed_seconds) / duration, 1.0))
                    # Whisper owns this first long-running phase.  Treat it as
                    # a visible slice of the overall job rather than leaving
                    # the UI frozen at "window 0" until it returns.
                    job.progress = max(job.progress, 0.10 + 0.08 * fraction)
                    bucket = int(fraction * 20)
                    if bucket <= last_bucket:
                        return
                    last_bucket = bucket
                    manager._activity(
                        job,
                        "transcription",
                        f"Whisper transcription reached {min(bucket * 5, 100)}% of the source video",
                        source_seconds=round(min(float(processed_seconds), duration), 1),
                        duration_seconds=round(duration, 1),
                        fraction=round(fraction, 3),
                    )

                manager._model_state(
                    job,
                    "whisper",
                    "loading",
                    "Loading Whisper and transcribing the full source video",
                    checkpoint=settings.whisper_model,
                    device=settings.device,
                    duration_seconds=duration,
                )
                manager._activity(
                    job,
                    "transcription",
                    "Whisper transcribes the full video before window embedding begins",
                    duration_seconds=duration,
                    note="Long videos can remain on window 0 while this phase is active.",
                )
                try:
                    result = self.inner.transcribe(
                        *args, progress_callback=transcription_progress, **kwargs
                    )
                except Exception as exc:
                    manager._model_state(
                        job,
                        "whisper",
                        "failed",
                        "Whisper transcription failed",
                        checkpoint=settings.whisper_model,
                        error_type=type(exc).__name__,
                        error=manager._safe_message(job, exc),
                    )
                    raise
                check()
                manager._model_state(
                    job,
                    "whisper",
                    "ready",
                    "Whisper transcription complete",
                    checkpoint=settings.whisper_model,
                    segments=len(result),
                )
                manager._activity(
                    job,
                    "transcription",
                    "Transcript is ready; creating searchable video windows next",
                    transcript_segments=len(result),
                )
                return result

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
                check()
                manager._activity(
                    job,
                    "qdrant",
                    "Checking Qdrant collection schema",
                    collection=settings.collection_name,
                )
                try:
                    self.index_store.ensure_collection()
                except Exception as exc:
                    manager._activity(
                        job,
                        "qdrant",
                        "Qdrant collection setup failed",
                        level="error",
                        error_type=type(exc).__name__,
                        error=manager._safe_message(job, exc),
                    )
                    raise
                manager._activity(
                    job,
                    "qdrant",
                    "Qdrant collection is ready",
                    collection=settings.collection_name,
                )

            def existing_window_ids(self, video_id):
                return self.index_store.existing_window_ids(video_id)

            def upsert(self, items):
                check()
                manager._activity(
                    job,
                    "qdrant",
                    "Writing a batch of searchable windows to Qdrant",
                    records=len(items),
                    first_window_id=items[0][0].window_id if items else None,
                )
                self.debug_store.upsert(items)
                try:
                    self.index_store.upsert(items)
                except Exception as exc:
                    manager._activity(
                        job,
                        "qdrant",
                        "Qdrant batch write failed",
                        level="error",
                        records=len(items),
                        error_type=type(exc).__name__,
                        error=manager._safe_message(job, exc),
                    )
                    raise

        class DebugVLM:
            def describe(self, path, window):
                check()
                job.stage = "mock_vlm"
                manager._activity(
                    job,
                    "vlm",
                    "Generating deterministic debug caption",
                    window_index=window.index,
                )
                return VLMDescription(
                    scene_context=f"Deterministic debug context for window {window.index}",
                    confidence=1,
                )

        class SelectionVLM:
            disabled = True

            def describe(self, path, window):
                check()
                return VLMDescription(confidence=1)

        transcriber = GuardTranscriber(
            FasterWhisperTranscriber(settings.whisper_model, settings.device)
        )
        visual = Guard(
            XClipVisualEncoder(device=settings.device),
            "visual",
            "microsoft/xclip-base-patch32",
        )
        audio = Guard(
            ClapAudioEncoder(device=settings.device),
            "audio",
            "laion/clap-htsat-unfused",
        )
        text = Guard(BgeM3TextEncoder(device=settings.device), "text", "BAAI/bge-m3")
        run_config = job.runtime_config()
        openai_debug = {}
        cosmos_debug = {}
        if mode == "openai":
            inner = OpenAIVisionProvider(
                run_config.get("openai_api_key") or settings.openai_api_key,
                run_config.get("openai_model") or settings.openai_vlm_model,
                settings.openai_vlm_timeout_seconds,
                settings.openai_vlm_retries,
                settings.openai_vlm_image_detail,
                int(run_config.get("openai_max_frames", settings.openai_vlm_max_frames)),
            )
            self._model_state(
                job,
                "vlm",
                "not_attempted",
                "OpenAI VLM is configured and will be called only for selected windows",
                provider="openai",
                model=run_config.get("openai_model") or settings.openai_vlm_model,
            )

            class OpenAIGuard:
                def describe(self, *args):
                    check()
                    job.stage = "openai_vlm"
                    window = args[1]
                    manager._model_state(
                        job,
                        "vlm",
                        "loading",
                        "Calling the OpenAI VLM for a selected window",
                        provider="openai",
                        window_index=window.index,
                    )
                    try:
                        result = inner.describe(*args)
                        manager._model_state(
                            job,
                            "vlm",
                            "ready",
                            "OpenAI VLM response received",
                            provider="openai",
                            window_index=window.index,
                        )
                        return result
                    except Exception as exc:
                        manager._model_state(
                            job,
                            "vlm",
                            "failed",
                            "OpenAI VLM request failed",
                            provider="openai",
                            window_index=window.index,
                            error_type=type(exc).__name__,
                            error=manager._safe_message(job, exc),
                        )
                        raise
                    finally:
                        openai_debug[window.index] = {
                            "request": inner.last_sanitized_request,
                            "response": inner.last_sanitized_response,
                            "usage": inner.last_usage,
                            "attempts": list(inner.attempts),
                        }

            vlm = OpenAIGuard()
        elif mode == "cosmos":
            inner = NvidiaCosmosProvider(
                run_config.get("nvidia_api_key"),
                run_config.get("cosmos_model", "nvidia/cosmos3-nano-reasoner"),
                settings.openai_vlm_timeout_seconds,
                settings.openai_vlm_retries,
                int(run_config.get("cosmos_max_frames", 8)),
            )
            self._model_state(
                job,
                "vlm",
                "not_attempted",
                "NVIDIA Cosmos is configured and will be called only for selected windows",
                provider="cosmos",
                model=run_config.get("cosmos_model", "nvidia/cosmos3-nano-reasoner"),
            )

            class CosmosGuard:
                def describe(self, *args):
                    check()
                    job.stage = "cosmos_vlm"
                    window = args[1]
                    manager._model_state(
                        job,
                        "vlm",
                        "loading",
                        "Calling NVIDIA Cosmos for a selected window",
                        provider="cosmos",
                        window_index=window.index,
                    )
                    try:
                        result = inner.describe(*args)
                        manager._model_state(
                            job,
                            "vlm",
                            "ready",
                            "NVIDIA Cosmos response received",
                            provider="cosmos",
                            window_index=window.index,
                        )
                        return result
                    except Exception as exc:
                        manager._model_state(
                            job,
                            "vlm",
                            "failed",
                            "NVIDIA Cosmos request failed",
                            provider="cosmos",
                            window_index=window.index,
                            error_type=type(exc).__name__,
                            error=manager._safe_message(job, exc),
                        )
                        raise
                    finally:
                        cosmos_debug[window.index] = {
                            "request": inner.last_sanitized_request,
                            "response": inner.last_sanitized_response,
                            "usage": inner.last_usage,
                            "attempts": list(inner.attempts),
                        }

            vlm = CosmosGuard()
        elif mode == "local_qwen":
            inner = LocalQwenProvider(
                model_name=run_config.get("local_qwen_model") or settings.vlm_model,
                device=settings.device,
                timeout=settings.vlm_timeout_seconds,
                retries=settings.vlm_retries,
            )
            self._model_state(
                job,
                "vlm",
                "not_attempted",
                "Local Qwen2.5-VL is configured and will load only for selected windows",
                provider="local_qwen",
                model=run_config.get("local_qwen_model") or settings.vlm_model,
                device=settings.device,
            )

            class LocalQwenGuard:
                def describe(self, *args):
                    check()
                    job.stage = "local_qwen_vlm"
                    window = args[1]
                    manager._model_state(
                        job,
                        "vlm",
                        "loading",
                        "Loading or running Local Qwen2.5-VL for a selected window",
                        provider="local_qwen",
                        window_index=window.index,
                        device=settings.device,
                    )
                    try:
                        result = inner.describe(*args)
                        manager._model_state(
                            job,
                            "vlm",
                            "ready",
                            "Local Qwen2.5-VL caption received",
                            provider="local_qwen",
                            window_index=window.index,
                            device=settings.device,
                        )
                        return result
                    except Exception as exc:
                        manager._model_state(
                            job,
                            "vlm",
                            "failed",
                            "Local Qwen2.5-VL failed",
                            provider="local_qwen",
                            window_index=window.index,
                            error_type=type(exc).__name__,
                            error=manager._safe_message(job, exc),
                        )
                        raise

            vlm = LocalQwenGuard()
        elif mode == "mock":
            self._model_state(
                job,
                "vlm",
                "ready",
                "Deterministic debug VLM is ready",
                provider="mock",
            )
            vlm = DebugVLM()
        else:
            self._model_state(
                job,
                "vlm",
                "ready",
                "VLM calls are intentionally skipped in selection-only mode",
                provider="selection_only",
            )
            vlm = SelectionVLM()
        memory = MemoryStore()
        store = memory
        if run_config.get("index_qdrant"):
            from qdrant_client import QdrantClient

            self._activity(
                job,
                "qdrant",
                "Connecting to Qdrant for persistent indexing",
                collection=settings.collection_name,
                timeout_seconds=settings.qdrant_timeout_seconds,
            )
            index_store = QdrantStore(
                QdrantClient(
                    url=settings.qdrant_url,
                    api_key=settings.qdrant_api_key,
                    timeout=settings.qdrant_timeout_seconds,
                ),
                settings.collection_name,
                settings.batch_size,
            )
            store = TeeStore(memory, index_store)
        else:
            self._activity(
                job,
                "qdrant",
                "Qdrant indexing is disabled; results will remain in this job only",
                level="warning",
            )

        last_progress = {"stage": None, "bucket": -1}

        def progress(stage, fraction, current_window, total_windows):
            job.stage = stage
            job.progress = max(job.progress, min(float(fraction), 1.0))
            job.current_window = int(current_window)
            job.total_windows = int(total_windows)
            if stage != last_progress["stage"]:
                last_progress["stage"] = stage
                last_progress["bucket"] = -1
                manager._activity(
                    job,
                    "pipeline",
                    f"Started pipeline stage: {stage.replace('_', ' ')}",
                    stage=stage,
                    overall_progress=round(job.progress, 3),
                    current_window=job.current_window,
                    total_windows=job.total_windows,
                )
                return
            if job.total_windows <= 0:
                return
            bucket = int(20 * job.current_window / job.total_windows)
            if bucket <= last_progress["bucket"]:
                return
            last_progress["bucket"] = bucket
            manager._activity(
                job,
                "pipeline",
                f"{stage.replace('_', ' ')} progress: {min(bucket * 5, 100)}%",
                stage=stage,
                current_window=job.current_window,
                total_windows=job.total_windows,
                overall_progress=round(job.progress, 3),
            )

        job.stage = "model_processing"
        self._activity(job, "pipeline", "Preparing the local indexing pipeline")
        report = ProcessingPipeline(
            transcriber,
            visual,
            audio,
            text,
            vlm,
            store,
            settings,
            progress_callback=progress,
        ).process_video(job.video_path)
        self._activity(
            job,
            "pipeline",
            "Pipeline computation finished; preparing browser inspection data",
            total_windows=report.total_windows,
            selected_vlm_windows=report.selected_vlm_windows,
            indexed_windows=report.successfully_indexed_windows,
            failed_windows=report.failed_windows,
        )
        records = memory.records
        job.total_windows = report.total_windows
        qdrant_errors = {
            window_id
            for window_id, message in report.errors.items()
            if message.startswith("Qdrant upsert failed:")
        }
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
                    "video_id": payload.video_id,
                    "window_id": payload.window_id,
                    "start": payload.start,
                    "end": payload.end,
                    "transcript": payload.transcript,
                    "change_scores": payload.change_scores,
                    "selected": bool(payload.selection_reasons),
                    "selection_reasons": payload.selection_reasons,
                    "vlm_call_state": payload.vlm_call_state,
                    "caption": payload.caption,
                    "has_audio": payload.has_audio,
                    "provenance": provenance,
                    "confidence": payload.caption_confidence,
                    "indexed": bool(run_config.get("index_qdrant"))
                    and payload.window_id not in qdrant_errors,
                    "point_id": deterministic_point_id(payload.window_id),
                    "stored_payload": {
                        key: value
                        for key, value in payload.model_dump().items()
                        if key != "source_path"
                    },
                    "vectors": diagnostics,
                    "cache": {"pipeline": "newly_computed"},
                    "openai": openai_debug.get(int(payload.window_id.rsplit("_", 1)[1]))
                    if mode == "openai"
                    else None,
                    "cosmos": cosmos_debug.get(int(payload.window_id.rsplit("_", 1)[1]))
                    if mode == "cosmos"
                    else None,
                    "errors": (
                        [report.errors[payload.window_id]]
                        if payload.window_id in report.errors
                        else []
                    ),
                }
            )
        job.report = report.model_dump(mode="json")
        job.errors.extend(
            {"window_id": window_id, "message": message}
            for window_id, message in report.errors.items()
        )
        job.report.update(
            {
                "actual_openai_calls": sum(
                    len(value.get("attempts", [])) for value in openai_debug.values()
                )
                if mode == "openai"
                else 0,
                "openai_usage": summarize_openai_usage(openai_debug)
                if mode == "openai"
                else summarize_openai_usage({}),
                "provider_mode": mode,
                "qdrant_inserted": report.successfully_indexed_windows
                if run_config.get("index_qdrant")
                else 0,
                "qdrant_updated": 0,
                "actual_cosmos_calls": sum(
                    len(value.get("attempts", [])) for value in cosmos_debug.values()
                )
                if mode == "cosmos"
                else 0,
                "cosmos_usage": summarize_openai_usage(cosmos_debug)
                if mode == "cosmos"
                else summarize_openai_usage({}),
            }
        )

    def _write_artifacts(self, job):
        export_started = time.perf_counter()
        exports = job.directory / "exports"
        exports.mkdir(exist_ok=True)
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
                "vlm_call_state": x["vlm_call_state"],
                "openai": x.get("openai"),
                "cosmos": x.get("cosmos"),
                "errors": x["errors"],
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
        (exports / "activity.json").write_text(
            json.dumps(sanitize(job.activity), indent=2), encoding="utf-8"
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "index",
                "start",
                "end",
                "selected",
                "selection_reasons",
                "vlm_call_state",
            ],
        )
        writer.writeheader()
        for row in job.windows:
            writer.writerow({k: row[k] for k in writer.fieldnames})
        (exports / "selector_trace.csv").write_text(output.getvalue(), encoding="utf-8")
        (job.directory / "evaluation.json").write_text(
            json.dumps(job.evaluations, indent=2), encoding="utf-8"
        )
        job.report.setdefault("stage_durations", {})["export_generation"] = (
            time.perf_counter() - export_started
        )
        (exports / "processing_report.json").write_text(
            json.dumps(sanitize(job.report), indent=2), encoding="utf-8"
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
