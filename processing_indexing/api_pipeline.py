"""API-based Gemini indexing primitives, independent from the local pipeline.

This module is intentionally not wired into ``ProcessingPipeline``.  That
keeps the existing self-hosted CPU route unchanged while giving the job/API
layer a concrete, testable API-based path to invoke after it has selected a
profile and holds credentials in memory.

The pipeline emits records with public ``payload`` and ``vectors`` mappings;
the surrounding application supplies the profile-aware Qdrant Cloud sink.
No API key is read from the environment, written into a record, or included in
an event.
"""

from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .gemini_embeddings import (
    DEFAULT_GEMINI_EMBEDDING_PROFILE,
    GeminiEmbedding2Adapter,
    GeminiEmbeddingProfile,
    GoogleGenAIEmbeddingClient,
    normalize_audio_input,
    normalize_transcript_input,
    normalize_video_input,
)
from .gemini_runtime import (
    GeminiCallDiagnostics,
    GeminiInputError,
    GeminiJsonRuntime,
    GoogleGenAIRuntime,
    redact_mapping,
    redact_text,
)
from .gemini_transcription import (
    GEMINI_FLASH_LITE_MODEL,
    GeminiCaptionResult,
    GeminiFlashLiteCaptioner,
    GeminiFlashLiteQueryDecomposer,
    GeminiFlashLiteTranscriber,
    GeminiMediaClip,
    GeminiQueryPlan,
    GeminiTranscriptionResult,
)
from .models import TranscriptSegment, VideoWindow
from .probe import probe_video, stable_video_id
from .windowing import generate_windows, transcript_for_window

API_GEMINI_FREE_PROFILE_ID = "api-gemini-free-v1"
API_GEMINI_FREE_COLLECTION = "video_windows_api_gemini_free_v1"
API_VECTOR_FIELDS = ("visual", "audio", "transcript", "caption")


class MediaPreparationError(RuntimeError):
    """A local ffmpeg conversion/extraction failure safe for UI diagnostics."""


class ApiPipelineError(RuntimeError):
    """An API indexing orchestration failure safe for job diagnostics."""


@dataclass(frozen=True)
class ApiEmbeddingProfileContract:
    """Immutable collection contract; fields cannot be mixed across profiles."""

    profile_id: str = API_GEMINI_FREE_PROFILE_ID
    collection_name: str = API_GEMINI_FREE_COLLECTION
    provider: str = "gemini"
    embedding_model: str = DEFAULT_GEMINI_EMBEDDING_PROFILE.model
    dimensions: int = DEFAULT_GEMINI_EMBEDDING_PROFILE.dimensions
    vector_fields: tuple[str, ...] = API_VECTOR_FIELDS

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.collection_name.strip():
            raise ValueError("API embedding profile needs an id and collection name")
        if set(self.vector_fields) != set(API_VECTOR_FIELDS):
            raise ValueError(
                "API embedding profile must expose visual, audio, transcript, and caption"
            )
        if self.dimensions < 128 or self.dimensions > 3072:
            raise ValueError("API Gemini dimensions must be between 128 and 3072")

    @property
    def vector_dimensions(self) -> dict[str, int]:
        return {field: self.dimensions for field in self.vector_fields}

    def metadata(self) -> dict[str, Any]:
        return {
            "embedding_profile": self.profile_id,
            "embedding_provider": self.provider,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.dimensions,
            "vector_fields": list(self.vector_fields),
        }


DEFAULT_API_GEMINI_PROFILE = ApiEmbeddingProfileContract()


@dataclass(frozen=True)
class ApiPipelineSettings:
    """Defaults deliberately match the API demo contract: 20s / 10s windows."""

    window_seconds: float = 20.0
    stride_seconds: float = 10.0
    transcription_chunk_seconds: float = 120.0
    caption_change_threshold: float = 0.14
    caption_max_gap_windows: int = 3
    caption_max_selected_ratio: float = 0.40
    caption_context_neighbours: int = 1
    profile: ApiEmbeddingProfileContract = DEFAULT_API_GEMINI_PROFILE

    def __post_init__(self) -> None:
        if self.window_seconds <= 0 or self.stride_seconds <= 0:
            raise ValueError("window_seconds and stride_seconds must be positive")
        if self.stride_seconds > self.window_seconds:
            raise ValueError("stride_seconds cannot exceed window_seconds")
        if self.transcription_chunk_seconds <= 0:
            raise ValueError("transcription_chunk_seconds must be positive")
        if not 0 <= self.caption_change_threshold <= 2:
            raise ValueError("caption_change_threshold must be in 0..2")
        if self.caption_max_gap_windows < 1:
            raise ValueError("caption_max_gap_windows must be at least one")
        if not 0 < self.caption_max_selected_ratio <= 1:
            raise ValueError("caption_max_selected_ratio must be within (0, 1]")
        if self.caption_context_neighbours < 0:
            raise ValueError("caption_context_neighbours cannot be negative")


@dataclass(frozen=True)
class ApiPipelineEvent:
    """Safe progress/activity payload for the existing live diagnostics UI."""

    stage: str
    status: str
    progress: float
    message: str
    current_window: int = 0
    total_windows: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "progress": min(1.0, max(0.0, self.progress)),
            "message": redact_text(self.message),
            "current_window": self.current_window,
            "total_windows": self.total_windows,
            "details": redact_mapping(dict(self.details)),
        }


@dataclass(frozen=True)
class ApiWindowRecord:
    """Profile-compatible record emitted to a caller-supplied Qdrant Cloud sink."""

    payload: Mapping[str, Any]
    vectors: Mapping[str, list[float]]

    def __post_init__(self) -> None:
        missing = {"visual"} - set(self.vectors)
        if missing:
            raise ValueError("API records require a visual vector")
        unexpected = set(self.vectors) - set(API_VECTOR_FIELDS)
        if unexpected:
            raise ValueError(f"unknown API vector fields: {sorted(unexpected)}")
        if any(not values for values in self.vectors.values()):
            raise ValueError("API vectors must not be empty")

    def as_qdrant_item(self) -> tuple[Mapping[str, Any], Mapping[str, list[float]]]:
        """Convenience iterator shape for simple profile-aware store adapters."""

        return self.payload, self.vectors


@dataclass(frozen=True)
class ApiIndexingReport:
    video_id: str
    duration_seconds: float
    total_windows: int
    indexed_windows: int
    failed_windows: int
    selected_caption_windows: int
    direct_caption_windows: int
    inherited_caption_windows: int
    transcript_segments: int
    elapsed_seconds: float
    profile: ApiEmbeddingProfileContract
    errors: Mapping[str, str]
    records: tuple[ApiWindowRecord, ...]
    provider_calls: Mapping[str, int]


@dataclass
class _PreparedWindow:
    window: VideoWindow
    visual_clip: GeminiMediaClip
    audio_clip: GeminiMediaClip | None
    transcript: str
    visual: list[float]
    audio: list[float] | None
    transcript_vector: list[float] | None


class ApiMediaSession(Protocol):
    """Job-scoped local media preparation; files must be removed by ``cleanup``."""

    def prepare_video_window(self, window: VideoWindow) -> GeminiMediaClip: ...

    def prepare_audio_window(self, window: VideoWindow) -> GeminiMediaClip: ...

    def prepare_transcription_chunks(
        self, *, duration_seconds: float, chunk_seconds: float
    ) -> Sequence[GeminiMediaClip]: ...

    def cleanup(self) -> None: ...


class ApiMediaPreparer(Protocol):
    def begin(self, source_path: Path, *, video_id: str, has_audio: bool) -> ApiMediaSession: ...


class ApiRecordSink(Protocol):
    """Minimal Qdrant integration point owned by the app/profile layer.

    ``records`` contain only payload/vector data and ``profile`` contains the
    public immutable vector contract.  The callable must never put credentials
    in either argument, event logs, or exceptions returned to the browser.
    """

    def __call__(
        self,
        records: Sequence[ApiWindowRecord],
        profile: ApiEmbeddingProfileContract,
    ) -> None: ...


def api_contract_from_runtime_profile(profile: Any) -> ApiEmbeddingProfileContract:
    """Adapt a runtime-profile object or public mapping to this pipeline's contract.

    The function is deliberately duck-typed rather than importing
    ``runtime_profiles``.  This prevents a circular dependency and allows
    tests or a future API service to provide the serialised profile returned to
    the browser.  Only the four named 1536-D API fields are accepted.
    """

    profile_id = _profile_value(profile, "id")
    collection_name = _profile_value(profile, "collection_name")
    # RuntimeProfile objects expose ``api_based`` while their browser-safe
    # public representation uses ``api-based`` plus ``execution_mode``.  The
    # explicit execution field wins when both are supplied.
    execution_mode = _profile_value(profile, "execution_mode", required=False)
    mode = execution_mode or _profile_value(profile, "mode", required=False)
    normalized_mode = str(mode).replace("-", "_") if mode is not None else None
    if normalized_mode is not None and normalized_mode != "api_based":
        raise ValueError("only an api_based runtime profile can use the API pipeline")
    vector_schema = _runtime_vector_schema(profile)
    if set(vector_schema) != set(API_VECTOR_FIELDS):
        raise ValueError(
            "API runtime profile must contain visual, audio, transcript, and caption vectors"
        )
    dimensions = {
        int(_vector_value(vector, "dimensions")) for vector in vector_schema.values()
    }
    if len(dimensions) != 1:
        raise ValueError("API runtime profile vectors must share one embedding dimension")
    return ApiEmbeddingProfileContract(
        profile_id=str(profile_id),
        collection_name=str(collection_name),
        dimensions=dimensions.pop(),
        vector_fields=tuple(vector_schema),
    )


class _ProfileQdrantSink:
    """Lazy, credential-private adapter from :class:`ApiWindowRecord` to Qdrant."""

    def __init__(
        self,
        *,
        qdrant_url: str,
        qdrant_api_key: str,
        profile: ApiEmbeddingProfileContract,
        timeout_seconds: float,
        batch_size: int,
        retries: int,
        client_factory: Callable[..., Any] | None,
        on_progress: Callable[[int, int], None] | None,
    ) -> None:
        if not qdrant_url.strip():
            raise ValueError("Qdrant URL is required for API-based indexing")
        if not qdrant_api_key.strip():
            raise ValueError("Qdrant API key is required for API-based indexing")
        if timeout_seconds <= 0:
            raise ValueError("Qdrant timeout must be positive")
        if batch_size < 1:
            raise ValueError("Qdrant batch size must be positive")
        self._qdrant_url = qdrant_url.rstrip("/")
        self._qdrant_api_key = qdrant_api_key
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        self.retries = retries
        self._client_factory = client_factory
        self._on_progress = on_progress
        self._store: Any | None = None

    def __call__(
        self,
        records: Sequence[ApiWindowRecord],
        profile: ApiEmbeddingProfileContract,
    ) -> None:
        if profile != self.profile:
            raise ApiPipelineError(
                "record profile does not match the Qdrant Cloud sink profile"
            )
        try:
            _validate_record_profile_metadata(records, profile)
            store = self._store_instance()
            store.ensure_collection()
            total = len(records)
            for offset in range(0, total, self.batch_size):
                batch = records[offset : offset + self.batch_size]
                # Import here so a local-only install never needs the cloud-store
                # path merely to import the processing module.
                from .profile_qdrant_store import ProfileWindowRecord

                store.upsert(
                    [
                        ProfileWindowRecord(payload=record.payload, vectors=record.vectors)
                        for record in batch
                    ]
                )
                self._emit_progress(min(total, offset + len(batch)), total)
        except Exception as exc:
            safe_error = redact_text(str(exc).replace(self._qdrant_api_key, "[REDACTED]"))
            raise ApiPipelineError(f"Qdrant Cloud write failed: {safe_error}") from exc

    def _store_instance(self) -> Any:
        if self._store is None:
            from .profile_qdrant_store import NamedVectorSchema, ProfiledQdrantStore

            client_factory = self._client_factory
            if client_factory is None:
                from qdrant_client import QdrantClient

                client_factory = QdrantClient
            # The API key remains only in this closure/client object.  It is
            # never attached to a record, profile, progress event, or error.
            client = client_factory(
                url=self._qdrant_url,
                api_key=self._qdrant_api_key,
                timeout=self.timeout_seconds,
            )
            self._store = ProfiledQdrantStore(
                client,
                collection_name=self.profile.collection_name,
                vector_schema=[
                    NamedVectorSchema(name=name, dimensions=self.profile.dimensions)
                    for name in self.profile.vector_fields
                ],
                batch_size=self.batch_size,
                retries=self.retries,
            )
        return self._store

    def _emit_progress(self, current: int, total: int) -> None:
        if self._on_progress is None:
            return
        try:
            self._on_progress(current, total)
        except Exception:  # noqa: BLE001 - a UI update cannot fail Qdrant writes
            return


def make_profile_qdrant_sink(
    *,
    qdrant_url: str,
    qdrant_api_key: str,
    profile: ApiEmbeddingProfileContract | Any,
    timeout_seconds: float = 10.0,
    batch_size: int = 8,
    retries: int = 2,
    client_factory: Callable[..., Any] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> ApiRecordSink:
    """Create a lazy Qdrant Cloud sink for one runtime-profile/session.

    ``on_progress(done, total)`` fires after every successful upsert batch so
    ``JobManager`` can add per-window qdrant progress events.  Neither it nor
    this function receives a serialisable credential-bearing configuration.
    """

    contract = (
        profile
        if isinstance(profile, ApiEmbeddingProfileContract)
        else api_contract_from_runtime_profile(profile)
    )
    return _ProfileQdrantSink(
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        profile=contract,
        timeout_seconds=timeout_seconds,
        batch_size=batch_size,
        retries=retries,
        client_factory=client_factory,
        on_progress=on_progress,
    )


def _validate_record_profile_metadata(
    records: Sequence[ApiWindowRecord], profile: ApiEmbeddingProfileContract
) -> None:
    """Reject a point whose payload does not declare this exact contract.

    Named-vector dimensions protect the collection schema, but dimensions
    alone cannot distinguish two embedding providers that happen to use the
    same size.  Every cloud point must therefore carry the active profile's
    provider/model/dimension metadata before it can be persisted.
    """

    expected = profile.metadata()
    for record in records:
        for name, value in expected.items():
            if record.payload.get(name) != value:
                raise ApiPipelineError(
                    "Qdrant Cloud record metadata does not match the active embedding profile"
                )


class FfmpegMediaPreparer:
    """Prepare Gemini-compatible MP4/MP3 clips without touching source media.

    Every job gets a new subdirectory under ``work_root``.  It is safe to use
    for WebM or longer videos because every window is individually transcoded
    to a 20-second MP4 and audio is independently extracted into bounded MP3
    chunks.  The caller must call the returned session's ``cleanup``.
    """

    def __init__(
        self,
        work_root: str | Path | None = None,
        *,
        ffmpeg_binary: str = "ffmpeg",
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.work_root = Path(work_root or tempfile.gettempdir()).expanduser().resolve()
        self.ffmpeg_binary = ffmpeg_binary
        self._runner = runner

    def begin(self, source_path: Path, *, video_id: str, has_audio: bool) -> _FfmpegMediaSession:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise MediaPreparationError(f"source video does not exist: {source}")
        self.work_root.mkdir(parents=True, exist_ok=True)
        safe_id = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:12]
        work_dir = Path(
            tempfile.mkdtemp(prefix=f"gemini-media-{safe_id}-", dir=self.work_root)
        ).resolve()
        return _FfmpegMediaSession(
            source_path=source,
            has_audio=has_audio,
            work_dir=work_dir,
            work_root=self.work_root,
            ffmpeg_binary=self.ffmpeg_binary,
            runner=self._runner,
        )


class _FfmpegMediaSession:
    def __init__(
        self,
        *,
        source_path: Path,
        has_audio: bool,
        work_dir: Path,
        work_root: Path,
        ffmpeg_binary: str,
        runner: Callable[..., Any],
    ) -> None:
        self.source_path = source_path
        self.has_audio = has_audio
        self.work_dir = work_dir
        self.work_root = work_root
        self.ffmpeg_binary = ffmpeg_binary
        self._runner = runner
        self._closed = False

    def prepare_video_window(self, window: VideoWindow) -> GeminiMediaClip:
        output = self.work_dir / f"window-{window.index:05d}.mp4"
        self._ffmpeg(
            [
                "-ss",
                _seconds(window.start),
                "-i",
                str(self.source_path),
                "-t",
                _seconds(window.end - window.start),
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-n",
                str(output),
            ]
        )
        return GeminiMediaClip(
            path=output,
            mime_type="video/mp4",
            start_seconds=window.start,
            end_seconds=window.end,
            kind="video",
        )

    def prepare_audio_window(self, window: VideoWindow) -> GeminiMediaClip:
        if not self.has_audio:
            raise MediaPreparationError("source video does not have an audio stream")
        output = self.work_dir / f"window-{window.index:05d}.mp3"
        self._ffmpeg(
            [
                "-ss",
                _seconds(window.start),
                "-i",
                str(self.source_path),
                "-t",
                _seconds(window.end - window.start),
                "-map",
                "0:a:0",
                "-vn",
                "-c:a",
                "libmp3lame",
                "-n",
                str(output),
            ]
        )
        return GeminiMediaClip(
            path=output,
            mime_type="audio/mpeg",
            start_seconds=window.start,
            end_seconds=window.end,
            kind="audio",
        )

    def prepare_transcription_chunks(
        self, *, duration_seconds: float, chunk_seconds: float
    ) -> Sequence[GeminiMediaClip]:
        if not self.has_audio:
            return ()
        if duration_seconds <= 0 or chunk_seconds <= 0:
            raise ValueError("audio chunk duration values must be positive")
        clips: list[GeminiMediaClip] = []
        index = 0
        start = 0.0
        while start < duration_seconds:
            end = min(duration_seconds, start + chunk_seconds)
            output = self.work_dir / f"transcript-{index:05d}.mp3"
            self._ffmpeg(
                [
                    "-ss",
                    _seconds(start),
                    "-i",
                    str(self.source_path),
                    "-t",
                    _seconds(end - start),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-n",
                    str(output),
                ]
            )
            clips.append(
                GeminiMediaClip(
                    path=output,
                    mime_type="audio/mpeg",
                    start_seconds=start,
                    end_seconds=end,
                    kind="audio",
                )
            )
            start = end
            index += 1
        return tuple(clips)

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.work_dir.relative_to(self.work_root)
        except ValueError as exc:  # should be impossible unless state was mutated
            raise MediaPreparationError("refusing to delete media outside the temp root") from exc
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def _ffmpeg(self, arguments: Sequence[str]) -> None:
        if self._closed:
            raise MediaPreparationError("media preparation session is already closed")
        try:
            result = self._runner(
                [self.ffmpeg_binary, "-hide_banner", "-loglevel", "error", *arguments],
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
        except FileNotFoundError as exc:
            raise MediaPreparationError("ffmpeg is required for API media preparation") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaPreparationError("ffmpeg timed out while preparing media") from exc
        if getattr(result, "returncode", 0) != 0:
            stderr = redact_text(getattr(result, "stderr", "ffmpeg failed"))
            raise MediaPreparationError(f"ffmpeg failed to prepare media: {stderr}")


class GeminiApiQueryEncoder:
    """Create compatible text query vectors per field for a Gemini API profile."""

    def __init__(self, embedding_adapter: GeminiEmbedding2Adapter) -> None:
        self.embedding_adapter = embedding_adapter

    def encode(self, plan: GeminiQueryPlan) -> dict[str, list[float]]:
        # Gemini Embedding 2 is a shared multimodal space.  A text query is
        # still generated separately for every field so retrieval can rank-fuse
        # fields rather than incorrectly adding/averaging raw vectors.
        return {
            field: self.embedding_adapter.embed_transcript(
                normalize_transcript_input(text)
            )
            for field, text in plan.by_modality().items()
        }


class ApiGeminiProcessingPipeline:
    """Twenty-second/ten-second API indexing orchestration.

    This pipeline does not know Qdrant credentials or implementation details.
    After processing it passes safe records to ``record_sink(records, profile)``.
    The app layer can connect that sink to local Qdrant or Qdrant Cloud.
    """

    def __init__(
        self,
        *,
        media_preparer: ApiMediaPreparer,
        embeddings: GeminiEmbedding2Adapter,
        transcriber: GeminiFlashLiteTranscriber,
        captioner: GeminiFlashLiteCaptioner,
        record_sink: ApiRecordSink | None = None,
        settings: ApiPipelineSettings | None = None,
        progress_callback: Callable[[ApiPipelineEvent], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.media_preparer = media_preparer
        self.embeddings = embeddings
        self.transcriber = transcriber
        self.captioner = captioner
        self.record_sink = record_sink
        self.settings = settings or ApiPipelineSettings()
        self.progress_callback = progress_callback
        self.clock = clock

        if embeddings.profile.model != self.settings.profile.embedding_model:
            raise ValueError("embedding adapter model must match API profile")
        if embeddings.profile.dimensions != self.settings.profile.dimensions:
            raise ValueError("embedding adapter dimensions must match API profile")

    def process_video(
        self,
        video_path: str | Path,
        *,
        video_id: str | None = None,
        duration_seconds: float | None = None,
        has_audio: bool | None = None,
    ) -> ApiIndexingReport:
        """Process a source file without persisting credentials or raw uploads."""

        started = self.clock()
        path = Path(video_path).expanduser().resolve()
        if not path.is_file():
            raise ApiPipelineError(f"video is not a readable file: {path}")
        self._emit("validation", "running", 0.02, "Validating video and API profile")
        if duration_seconds is None or has_audio is None:
            metadata = probe_video(path)
            duration_seconds = metadata.duration
            has_audio = metadata.has_audio
        if duration_seconds <= 0:
            raise ApiPipelineError("video duration must be positive")
        resolved_video_id = video_id or stable_video_id(path)
        windows = generate_windows(
            resolved_video_id,
            duration_seconds,
            self.settings.window_seconds,
            self.settings.stride_seconds,
        )
        self._emit(
            "windowing",
            "complete",
            0.08,
            f"Created {len(windows)} API windows",
            total_windows=len(windows),
            details={
                "window_seconds": self.settings.window_seconds,
                "stride_seconds": self.settings.stride_seconds,
                "embedding_profile": self.settings.profile.profile_id,
            },
        )

        session = self.media_preparer.begin(path, video_id=resolved_video_id, has_audio=has_audio)
        errors: dict[str, str] = {}
        diagnostics: list[GeminiCallDiagnostics] = []
        try:
            transcript_result = self._transcribe(
                session,
                duration_seconds=duration_seconds,
                has_audio=has_audio,
                total_windows=len(windows),
            )
            diagnostics.extend(transcript_result.diagnostics)
            prepared = self._embed_windows(
                session,
                path=path,
                windows=windows,
                transcript_segments=transcript_result.segments,
                has_audio=has_audio,
                errors=errors,
            )
            caption_results, selected = self._caption_selected_windows(
                prepared,
                total_windows=len(windows),
                errors=errors,
            )
            diagnostics.extend(
                result.diagnostics for result in caption_results.values()
            )
            records, direct, inherited = self._build_records(
                prepared,
                caption_results=caption_results,
                selected=selected,
                source_path=path,
                errors=errors,
            )
            if self.record_sink is not None and records:
                self._emit(
                    "qdrant_upsert",
                    "running",
                    0.94,
                    "Writing API-profile records to the configured vector store",
                    current_window=len(records),
                    total_windows=len(windows),
                    details={"collection": self.settings.profile.collection_name},
                )
                self.record_sink(records, self.settings.profile)
            self._emit(
                "complete",
                "complete",
                1.0,
                "API indexing completed",
                current_window=len(records),
                total_windows=len(windows),
                details={"records": len(records), "failed_windows": len(errors)},
            )
            return ApiIndexingReport(
                video_id=resolved_video_id,
                duration_seconds=duration_seconds,
                total_windows=len(windows),
                indexed_windows=len(records),
                failed_windows=len(errors),
                selected_caption_windows=len(selected),
                direct_caption_windows=direct,
                inherited_caption_windows=inherited,
                transcript_segments=len(transcript_result.segments),
                elapsed_seconds=self.clock() - started,
                profile=self.settings.profile,
                errors=dict(errors),
                records=tuple(records),
                provider_calls=_call_counts(diagnostics),
            )
        except Exception as exc:
            self._emit(
                "failed",
                "failed",
                1.0,
                "API indexing stopped with an error",
                total_windows=len(windows),
                details={"error": redact_text(exc)},
            )
            raise
        finally:
            session.cleanup()

    def _transcribe(
        self,
        session: ApiMediaSession,
        *,
        duration_seconds: float,
        has_audio: bool,
        total_windows: int,
    ) -> GeminiTranscriptionResult:
        if not has_audio:
            self._emit(
                "transcription",
                "skipped",
                0.12,
                "Video has no audio stream; transcription skipped",
                total_windows=total_windows,
            )
            return GeminiTranscriptionResult((), (), self.transcriber.model, 0)
        chunks = session.prepare_transcription_chunks(
            duration_seconds=duration_seconds,
            chunk_seconds=self.settings.transcription_chunk_seconds,
        )
        self._emit(
            "transcription",
            "running",
            0.12,
            f"Transcribing {len(chunks)} non-overlapping audio chunks",
            total_windows=total_windows,
        )

        def progress(current: int, total: int) -> None:
            self._emit(
                "transcription",
                "running",
                0.12 + 0.16 * current / max(total, 1),
                f"Transcribed audio chunk {current}/{total}",
                total_windows=total_windows,
                details={"audio_chunks_complete": current, "audio_chunks_total": total},
            )

        return self.transcriber.transcribe_chunks(chunks, progress_callback=progress)

    def _embed_windows(
        self,
        session: ApiMediaSession,
        *,
        path: Path,
        windows: Sequence[VideoWindow],
        transcript_segments: Sequence[TranscriptSegment],
        has_audio: bool,
        errors: dict[str, str],
    ) -> list[_PreparedWindow]:
        prepared: list[_PreparedWindow] = []
        total = len(windows)
        for current, window in enumerate(windows, start=1):
            self._emit(
                "embedding_windows",
                "running",
                0.30 + 0.32 * (current - 1) / max(total, 1),
                f"Generating independent Gemini embeddings for window {current}/{total}",
                current_window=current - 1,
                total_windows=total,
            )
            try:
                visual_clip = session.prepare_video_window(window)
                video_input = normalize_video_input(
                    visual_clip.path,
                    duration_seconds=visual_clip.duration_seconds,
                    mime_type=visual_clip.mime_type,
                    profile=self.embeddings.profile,
                )
                audio_clip = session.prepare_audio_window(window) if has_audio else None
                audio_input = (
                    normalize_audio_input(
                        audio_clip.path,
                        duration_seconds=audio_clip.duration_seconds,
                        mime_type=audio_clip.mime_type,
                        profile=self.embeddings.profile,
                    )
                    if audio_clip is not None
                    else None
                )
                transcript = transcript_for_window(list(transcript_segments), window.start, window.end)
                transcript_input = (
                    normalize_transcript_input(transcript) if transcript.strip() else None
                )
                vectors = self.embeddings.embed_window(
                    video=video_input,
                    audio=audio_input,
                    transcript=transcript_input,
                )
                prepared.append(
                    _PreparedWindow(
                        window=window,
                        visual_clip=visual_clip,
                        audio_clip=audio_clip,
                        transcript=transcript,
                        visual=list(vectors.visual),
                        audio=list(vectors.audio) if vectors.audio is not None else None,
                        transcript_vector=(
                            list(vectors.transcript)
                            if vectors.transcript is not None
                            else None
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one window must not end the job
                errors[window.window_id] = redact_text(exc)
                self._emit(
                    "embedding_windows",
                    "warning",
                    0.30 + 0.32 * current / max(total, 1),
                    f"Window {current}/{total} could not be embedded",
                    current_window=current - 1,
                    total_windows=total,
                    details={"window_id": window.window_id, "error": redact_text(exc)},
                )
        return prepared

    def _caption_selected_windows(
        self,
        prepared: Sequence[_PreparedWindow],
        *,
        total_windows: int,
        errors: dict[str, str],
    ) -> tuple[dict[int, GeminiCaptionResult], set[int]]:
        selected = _select_caption_indexes(prepared, self.settings)
        results: dict[int, GeminiCaptionResult] = {}
        for current, index in enumerate(sorted(selected), start=1):
            item = prepared[index]
            self._emit(
                "captioning_windows",
                "running",
                0.64 + 0.18 * (current - 1) / max(len(selected), 1),
                f"Generating Gemini caption for selected window {current}/{len(selected)}",
                current_window=item.window.index,
                total_windows=total_windows,
            )
            try:
                results[index] = self.captioner.caption_window(item.visual_clip, item.window)
            except Exception as exc:  # noqa: BLE001 - caption failure is recoverable
                errors[f"{item.window.window_id}:caption"] = redact_text(exc)
                self._emit(
                    "captioning_windows",
                    "warning",
                    0.64 + 0.18 * current / max(len(selected), 1),
                    "Selected caption call failed; visual/audio retrieval remains available",
                    current_window=item.window.index,
                    total_windows=total_windows,
                    details={"window_id": item.window.window_id, "error": redact_text(exc)},
                )
        return results, selected

    def _build_records(
        self,
        prepared: Sequence[_PreparedWindow],
        *,
        caption_results: Mapping[int, GeminiCaptionResult],
        selected: set[int],
        source_path: Path,
        errors: dict[str, str],
    ) -> tuple[list[ApiWindowRecord], int, int]:
        records: list[ApiWindowRecord] = []
        direct = 0
        inherited = 0
        for index, item in enumerate(prepared):
            caption_result = caption_results.get(index)
            caption = ""
            caption_source_index: int | None = None
            caption_direct = False
            caption_inherited = False
            confidence = 0.0
            if caption_result is not None:
                caption = caption_result.caption
                caption_source_index = index
                caption_direct = True
                confidence = caption_result.confidence
                direct += 1
            else:
                inherited_result = _nearby_caption(
                    index,
                    caption_results,
                    max_distance=self.settings.caption_context_neighbours,
                )
                if inherited_result is not None:
                    caption_source_index, source = inherited_result
                    caption = source.caption
                    confidence = source.confidence
                    caption_inherited = True
                    inherited += 1

            vectors: dict[str, list[float]] = {"visual": item.visual}
            if item.audio is not None:
                vectors["audio"] = item.audio
            if item.transcript_vector is not None:
                vectors["transcript"] = item.transcript_vector
            if caption:
                try:
                    caption_vector = self.embeddings.embed_caption(
                        normalize_transcript_input(caption)
                    )
                    vectors["caption"] = caption_vector
                except Exception as exc:  # noqa: BLE001 - retain other modalities
                    errors[f"{item.window.window_id}:caption_embedding"] = redact_text(exc)

            payload: dict[str, Any] = {
                "video_id": item.window.video_id,
                "window_id": item.window.window_id,
                "window_index": item.window.index,
                "start": item.window.start,
                "end": item.window.end,
                "transcript": item.transcript,
                "caption": caption,
                "has_audio": item.audio is not None,
                "caption_direct": caption_direct,
                "caption_inherited": caption_inherited,
                "caption_available": bool(caption),
                "caption_source_window_id": (
                    prepared[caption_source_index].window.window_id
                    if caption_source_index is not None
                    else None
                ),
                "caption_confidence": confidence,
                "caption_selected": index in selected,
                "source_path": str(source_path),
                "api_based": True,
                "transcription_model": self.transcriber.model,
                "caption_model": self.captioner.model,
                **self.settings.profile.metadata(),
            }
            records.append(ApiWindowRecord(payload=payload, vectors=vectors))
        return records, direct, inherited

    def _emit(
        self,
        stage: str,
        status: str,
        progress: float,
        message: str,
        *,
        current_window: int = 0,
        total_windows: int = 0,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(
                ApiPipelineEvent(
                    stage=stage,
                    status=status,
                    progress=progress,
                    message=message,
                    current_window=current_window,
                    total_windows=total_windows,
                    details=redact_mapping(dict(details or {})),
                )
            )
        except Exception:  # noqa: BLE001 - diagnostics must never stop processing
            # Observability must not break a billable indexing job.
            return


@dataclass(frozen=True)
class GeminiApiPipelineFactoryConfig:
    """Explicit in-memory setup; intentionally does not read environment variables."""

    gemini_api_key: str = field(repr=False)
    embedding_model: str = DEFAULT_GEMINI_EMBEDDING_PROFILE.model
    embedding_dimensions: int = DEFAULT_GEMINI_EMBEDDING_PROFILE.dimensions
    generation_model: str = GEMINI_FLASH_LITE_MODEL
    profile_id: str = API_GEMINI_FREE_PROFILE_ID
    collection_name: str = API_GEMINI_FREE_COLLECTION

    def __post_init__(self) -> None:
        if not self.gemini_api_key.strip():
            raise GeminiInputError("A Gemini API key is required for API-based mode")


@dataclass(frozen=True)
class GeminiApiPipelineBundle:
    """Factory output also exposes query interfaces for the query service to wire."""

    pipeline: ApiGeminiProcessingPipeline
    query_decomposer: GeminiFlashLiteQueryDecomposer
    query_encoder: GeminiApiQueryEncoder
    profile: ApiEmbeddingProfileContract


def build_gemini_api_pipeline(
    config: GeminiApiPipelineFactoryConfig,
    *,
    record_sink: ApiRecordSink | None = None,
    media_preparer: ApiMediaPreparer | None = None,
    progress_callback: Callable[[ApiPipelineEvent], None] | None = None,
    runtime: GeminiJsonRuntime | None = None,
    embedding_transport: Any | None = None,
    settings: ApiPipelineSettings | None = None,
) -> GeminiApiPipelineBundle:
    """Build the free Gemini API path from caller-provided, session-memory keys."""

    profile = ApiEmbeddingProfileContract(
        profile_id=config.profile_id,
        collection_name=config.collection_name,
        embedding_model=config.embedding_model,
        dimensions=config.embedding_dimensions,
    )
    resolved_settings = settings or ApiPipelineSettings(profile=profile)
    if resolved_settings.profile != profile:
        raise ValueError("provided API pipeline settings must use the factory profile")
    resolved_runtime = runtime or GoogleGenAIRuntime(api_key=config.gemini_api_key)
    transport = embedding_transport or GoogleGenAIEmbeddingClient(
        api_key=config.gemini_api_key
    )
    embeddings = GeminiEmbedding2Adapter(
        transport,
        profile=GeminiEmbeddingProfile(
            model=config.embedding_model,
            dimensions=config.embedding_dimensions,
        ),
    )
    transcriber = GeminiFlashLiteTranscriber(
        resolved_runtime, model=config.generation_model
    )
    captioner = GeminiFlashLiteCaptioner(resolved_runtime, model=config.generation_model)
    pipeline = ApiGeminiProcessingPipeline(
        media_preparer=media_preparer or FfmpegMediaPreparer(),
        embeddings=embeddings,
        transcriber=transcriber,
        captioner=captioner,
        record_sink=record_sink,
        settings=resolved_settings,
        progress_callback=progress_callback,
    )
    return GeminiApiPipelineBundle(
        pipeline=pipeline,
        query_decomposer=GeminiFlashLiteQueryDecomposer(
            resolved_runtime, model=config.generation_model
        ),
        query_encoder=GeminiApiQueryEncoder(embeddings),
        profile=profile,
    )


def _seconds(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _call_counts(diagnostics: Sequence[GeminiCallDiagnostics]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in diagnostics:
        counts[item.operation] = counts.get(item.operation, 0) + len(item.attempts)
    return counts


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 and right_norm == 0:
        return 0.0
    if left_norm == 0 or right_norm == 0:
        return 1.0
    return max(0.0, min(2.0, 1.0 - dot / (left_norm * right_norm)))


def _caption_change(current: _PreparedWindow, previous: _PreparedWindow) -> float:
    scores = [_cosine_distance(current.visual, previous.visual)]
    if current.audio is not None and previous.audio is not None:
        scores.append(_cosine_distance(current.audio, previous.audio))
    if current.transcript_vector is not None and previous.transcript_vector is not None:
        scores.append(_cosine_distance(current.transcript_vector, previous.transcript_vector))
    return sum(scores) / len(scores)


def _select_caption_indexes(
    prepared: Sequence[_PreparedWindow], settings: ApiPipelineSettings
) -> set[int]:
    if not prepared:
        return set()
    candidates: list[tuple[int, float]] = [(0, 2.0)]
    last_selected = 0
    for index in range(1, len(prepared)):
        change = _caption_change(prepared[index], prepared[index - 1])
        if (
            change >= settings.caption_change_threshold
            or index - last_selected >= settings.caption_max_gap_windows
            or index == len(prepared) - 1
        ):
            candidates.append((index, change))
            last_selected = index
    cap = max(1, math.ceil(len(prepared) * settings.caption_max_selected_ratio))
    # Preserve first/last for coverage, then retain the largest evidence changes.
    required = {0, len(prepared) - 1}
    selected = set(required)
    for index, _score in sorted(candidates, key=lambda item: (-item[1], item[0])):
        if len(selected) >= cap:
            break
        selected.add(index)
    return selected


def _nearby_caption(
    index: int,
    results: Mapping[int, GeminiCaptionResult],
    *,
    max_distance: int,
) -> tuple[int, GeminiCaptionResult] | None:
    candidates = [
        (source, result)
        for source, result in results.items()
        if abs(source - index) <= max_distance and result.caption.strip()
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (abs(item[0] - index), item[0]))


def _profile_value(profile: Any, name: str, *, required: bool = True) -> Any:
    value = profile.get(name) if isinstance(profile, Mapping) else getattr(profile, name, None)
    if required and (value is None or (isinstance(value, str) and not value.strip())):
        raise ValueError(f"runtime profile requires {name}")
    return value


def _runtime_vector_schema(profile: Any) -> dict[str, Any]:
    schema = _profile_value(profile, "vector_schema", required=False)
    if isinstance(schema, Mapping):
        return dict(schema)
    vectors = _profile_value(profile, "vectors", required=False)
    if vectors is None:
        raise ValueError("runtime profile requires vector_schema or vectors")
    result: dict[str, Any] = {}
    for vector in vectors:
        name = _vector_value(vector, "name")
        result[str(name)] = vector
    return result


def _vector_value(vector: Any, name: str) -> Any:
    value = vector.get(name) if isinstance(vector, Mapping) else getattr(vector, name, None)
    if value is None:
        raise ValueError(f"runtime profile vector requires {name}")
    return value
