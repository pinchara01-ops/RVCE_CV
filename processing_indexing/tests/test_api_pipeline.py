from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from processing_indexing.api_pipeline import (
    ApiGeminiProcessingPipeline,
    ApiPipelineError,
    ApiPipelineSettings,
    ApiWindowRecord,
    FfmpegMediaPreparer,
    api_contract_from_runtime_profile,
    make_profile_qdrant_sink,
)
from processing_indexing.gemini_embeddings import (
    GEMINI_EMBEDDING_DIMENSIONS,
    GeminiEmbedding2Adapter,
)
from processing_indexing.gemini_runtime import (
    GeminiCallAttempt,
    GeminiCallDiagnostics,
    GeminiQuotaError,
    GoogleGenAIRuntime,
    call_with_retry,
)
from processing_indexing.gemini_transcription import (
    GeminiFlashLiteCaptioner,
    GeminiFlashLiteQueryDecomposer,
    GeminiFlashLiteTranscriber,
    GeminiMediaClip,
)
from processing_indexing.models import VideoWindow


def _diagnostics(model: str, operation: str) -> GeminiCallDiagnostics:
    return GeminiCallDiagnostics(
        model=model,
        operation=operation,
        attempts=[GeminiCallAttempt(attempt=1, status="succeeded")],
    )


class FakeGeminiRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        operation = kwargs["operation_name"]
        if operation == "transcription":
            start = 1.0 if "00000" in kwargs["media_path"].name else 0.5
            return (
                {
                    "segments": [
                        {
                            "start_seconds": start,
                            "end_seconds": start + 1,
                            "text": "person speaking",
                        }
                    ]
                },
                _diagnostics(kwargs["model"], operation),
            )
        if operation == "caption":
            return (
                {
                    "caption": "A person walks past a parked car.",
                    "confidence": 0.8,
                    "evidence": ["person", "parked car"],
                },
                _diagnostics(kwargs["model"], operation),
            )
        if operation == "query_decomposition":
            return (
                {
                    "expanded_query": "find a person walking near a car",
                    "visual_query": "person walking near parked car",
                    "audio_query": "footsteps or car sounds",
                    "transcript_query": "person walking",
                    "caption_query": "person walking beside a parked car",
                },
                _diagnostics(kwargs["model"], operation),
            )
        raise AssertionError(f"unexpected operation: {operation}")


class FakeEmbeddingTransport:
    def __init__(self) -> None:
        self.modalities: list[str] = []

    def embed(self, content, *, model, dimensions):
        assert model == "gemini-embedding-2"
        self.modalities.append(content.modality)
        values = {
            "visual": 0.1,
            "audio": 0.2,
            "transcript": 0.3,
            "caption": 0.4,
        }
        return [values[content.modality]] * dimensions


@dataclass
class FakeMediaSession:
    root: Path
    has_audio: bool
    cleaned: bool = False

    def _clip(self, name: str, *, kind: str, start: float, end: float) -> GeminiMediaClip:
        suffix = ".mp4" if kind == "video" else ".mp3"
        path = self.root / f"{name}{suffix}"
        path.write_bytes(b"prepared media")
        return GeminiMediaClip(
            path=path,
            mime_type="video/mp4" if kind == "video" else "audio/mpeg",
            start_seconds=start,
            end_seconds=end,
            kind=kind,
        )

    def prepare_video_window(self, window):
        return self._clip(
            f"window-{window.index:05d}",
            kind="video",
            start=window.start,
            end=window.end,
        )

    def prepare_audio_window(self, window):
        assert self.has_audio
        return self._clip(
            f"audio-{window.index:05d}",
            kind="audio",
            start=window.start,
            end=window.end,
        )

    def prepare_transcription_chunks(self, *, duration_seconds, chunk_seconds):
        chunks = []
        index = 0
        start = 0.0
        while start < duration_seconds:
            end = min(duration_seconds, start + chunk_seconds)
            chunks.append(
                self._clip(
                    f"transcript-{index:05d}", kind="audio", start=start, end=end
                )
            )
            index += 1
            start = end
        return chunks

    def cleanup(self):
        self.cleaned = True


class FakeMediaPreparer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.session: FakeMediaSession | None = None

    def begin(self, _source_path, *, video_id, has_audio):
        self.session = FakeMediaSession(self.root / video_id[:8], has_audio)
        self.session.root.mkdir(parents=True)
        return self.session


def test_api_pipeline_emits_separate_records_and_cleans_prepared_files(tmp_path):
    source = tmp_path / "input.webm"
    source.write_bytes(b"source")
    runtime = FakeGeminiRuntime()
    transport = FakeEmbeddingTransport()
    events = []
    saved = []
    preparer = FakeMediaPreparer(tmp_path)
    adapter = GeminiEmbedding2Adapter(transport)
    pipeline = ApiGeminiProcessingPipeline(
        media_preparer=preparer,
        embeddings=adapter,
        transcriber=GeminiFlashLiteTranscriber(runtime),
        captioner=GeminiFlashLiteCaptioner(runtime),
        record_sink=lambda records, profile: saved.append((list(records), profile)),
        settings=ApiPipelineSettings(transcription_chunk_seconds=30),
        progress_callback=events.append,
    )

    report = pipeline.process_video(
        source, video_id="video-123", duration_seconds=45, has_audio=True
    )

    assert report.total_windows == 4  # 0-20, 10-30, 20-40, 30-45
    assert report.indexed_windows == 4
    assert report.transcript_segments == 2
    assert report.direct_caption_windows == 2  # first + last, bounded by 40%
    assert report.inherited_caption_windows == 2
    assert len(saved) == 1
    assert saved[0][1].profile_id == "api-gemini-free-v1"
    record = report.records[0]
    assert record.payload["embedding_profile"] == "api-gemini-free-v1"
    assert record.payload["source_path"] == str(source.resolve())
    assert set(record.vectors) == {"visual", "audio", "transcript", "caption"}
    assert all(len(vector) == GEMINI_EMBEDDING_DIMENSIONS for vector in record.vectors.values())
    assert "caption" in transport.modalities
    assert preparer.session is not None and preparer.session.cleaned
    assert events[-1].stage == "complete"


def test_api_pipeline_skips_transcription_and_audio_vectors_for_silent_video(tmp_path):
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"source")
    runtime = FakeGeminiRuntime()
    pipeline = ApiGeminiProcessingPipeline(
        media_preparer=FakeMediaPreparer(tmp_path),
        embeddings=GeminiEmbedding2Adapter(FakeEmbeddingTransport()),
        transcriber=GeminiFlashLiteTranscriber(runtime),
        captioner=GeminiFlashLiteCaptioner(runtime),
    )

    report = pipeline.process_video(
        source, video_id="silent", duration_seconds=20, has_audio=False
    )

    assert report.transcript_segments == 0
    assert all("audio" not in record.vectors for record in report.records)
    assert all("transcript" not in record.vectors for record in report.records)
    assert not [call for call in runtime.calls if call["operation_name"] == "transcription"]


def test_structured_transcription_offsets_chunks_and_query_decomposition(tmp_path):
    first = tmp_path / "chunk-00000.mp3"
    second = tmp_path / "chunk-00001.mp3"
    first.write_bytes(b"audio")
    second.write_bytes(b"audio")
    runtime = FakeGeminiRuntime()
    transcriber = GeminiFlashLiteTranscriber(runtime)
    result = transcriber.transcribe_chunks(
        [
            GeminiMediaClip(first, "audio/mpeg", 0, 10, "audio"),
            GeminiMediaClip(second, "audio/mpeg", 10, 20, "audio"),
        ]
    )

    assert [(item.start, item.end) for item in result.segments] == [
        (1.0, 2.0),
        (10.5, 11.5),
    ]
    plan = GeminiFlashLiteQueryDecomposer(runtime).decompose("Find a person near a car")
    assert plan.by_modality()["visual"] == "person walking near parked car"
    assert set(plan.by_modality()) == {"visual", "audio", "transcript", "caption"}


def test_google_runtime_is_lazy_retries_quota_and_redacts_credentials(tmp_path):
    media = tmp_path / "clip.mp3"
    media.write_bytes(b"audio")
    state = {"loader": 0, "calls": 0, "deleted": None}

    class FakeTypes:
        class UploadFileConfig:
            def __init__(self, *, mime_type):
                self.mime_type = mime_type

        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    class QuotaFailure(Exception):
        status_code = 429

        def __str__(self):
            return "quota exceeded for AIzaSuperSecretKey123456789"

    class Files:
        def upload(self, **_kwargs):
            return type("Upload", (), {"name": "files/test"})()

        def delete(self, *, name):
            state["deleted"] = name

    class Models:
        def generate_content(self, **_kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                raise QuotaFailure()
            return type("Response", (), {"text": '{"ok": true}'})()

    class Client:
        models = Models()
        files = Files()

    class FakeGenAI:
        @staticmethod
        def Client(*, api_key):
            assert api_key == "AIzaSuperSecretKey123456789"
            return Client()

    def loader():
        state["loader"] += 1
        return FakeGenAI, FakeTypes

    runtime = GoogleGenAIRuntime(
        api_key="AIzaSuperSecretKey123456789",
        sdk_loader=loader,
        sleep=lambda _delay: None,
    )
    assert state["loader"] == 0
    response, diagnostics = runtime.generate_json(
        model="gemini-test",
        prompt="return test JSON",
        media_path=media,
        media_mime_type="audio/mpeg",
    )

    assert response == {"ok": True}
    assert state["loader"] == 1
    assert state["deleted"] == "files/test"
    assert diagnostics.attempts[0].status == "retrying"
    assert "AIzaSuperSecretKey123456789" not in str(diagnostics.as_dict())


def test_retry_stops_after_bounded_quota_attempts_without_secret_leak():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise GeminiQuotaError("Bearer super-secret-token")

    with pytest.raises(GeminiQuotaError) as raised:
        call_with_retry(
            operation,
            model="gemini-test",
            operation_name="test",
            sleep=lambda _delay: None,
        )

    assert calls == 3
    assert "super-secret-token" not in str(raised.value)


def test_ffmpeg_preparer_converts_webm_and_splits_non_overlapping_audio(tmp_path):
    source = tmp_path / "dashcam.webm"
    source.write_bytes(b"webm")
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"converted")
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    preparer = FfmpegMediaPreparer(work_root=tmp_path / "prepared", runner=runner)
    session = preparer.begin(source, video_id="a-video", has_audio=True)
    window = VideoWindow(
        video_id="a-video", window_id="a-window", index=0, start=0, end=20
    )
    video = session.prepare_video_window(window)
    audio = session.prepare_audio_window(window)
    chunks = session.prepare_transcription_chunks(duration_seconds=241, chunk_seconds=120)

    assert video.path.suffix == ".mp4"
    assert audio.path.suffix == ".mp3"
    assert [(chunk.start_seconds, chunk.end_seconds) for chunk in chunks] == [
        (0, 120),
        (120, 240),
        (240, 241),
    ]
    assert any("libx264" in command for command in commands)
    assert all(str(source) in command for command in commands)
    work_dir = session.work_dir
    session.cleanup()
    assert not work_dir.exists()


def test_profile_adapter_and_qdrant_sink_upsert_records_with_batch_progress():
    contract = api_contract_from_runtime_profile(
        {
            "id": "api-gemini-free-v1",
            "mode": "api-based",
            "execution_mode": "api_based",
            "collection_name": "video_windows_api_gemini_free_v1",
            "vector_schema": {
                name: {"dimensions": 1536} for name in ("visual", "audio", "transcript", "caption")
            },
        }
    )
    state = {"created": None, "payload_indexes": [], "points": [], "factory": None}

    class FakeQdrant:
        def collection_exists(self, _name):
            return False

        def create_collection(self, **kwargs):
            state["created"] = kwargs

        def create_payload_index(self, **kwargs):
            state["payload_indexes"].append(kwargs)

        def upsert(self, **kwargs):
            state["points"].extend(kwargs["points"])

    def factory(**kwargs):
        state["factory"] = kwargs
        return FakeQdrant()

    updates = []
    sink = make_profile_qdrant_sink(
        qdrant_url="https://example.cloud.qdrant.io",
        qdrant_api_key="qdrant-secret",
        profile=contract,
        batch_size=2,
        client_factory=factory,
        on_progress=lambda done, total: updates.append((done, total)),
    )
    records = [
        ApiWindowRecord(
            payload={"window_id": f"window-{index}", **contract.metadata()},
            vectors={"visual": [0.1] * 1536},
        )
        for index in range(3)
    ]

    sink(records, contract)

    assert state["created"]["collection_name"] == contract.collection_name
    assert {item["field_name"] for item in state["payload_indexes"]} == {"video_id", "window_id"}
    assert len(state["points"]) == 3
    assert updates == [(2, 3), (3, 3)]
    assert state["factory"]["url"] == "https://example.cloud.qdrant.io"


def test_qdrant_sink_rejects_record_metadata_from_another_embedding_profile():
    contract = api_contract_from_runtime_profile(
        {
            "id": "api-gemini-free-v1",
            "mode": "api_based",
            "collection_name": "video_windows_api_gemini_free_v1",
            "vector_schema": {
                name: {"dimensions": 1536}
                for name in ("visual", "audio", "transcript", "caption")
            },
        }
    )
    sink = make_profile_qdrant_sink(
        qdrant_url="https://example.cloud.qdrant.io",
        qdrant_api_key="qdrant-secret",
        profile=contract,
        client_factory=lambda **_kwargs: object(),
    )

    with pytest.raises(ApiPipelineError, match="metadata"):
        sink(
            [
                ApiWindowRecord(
                    payload={
                        "window_id": "window-0",
                        **contract.metadata(),
                        "embedding_model": "other-embedding-model",
                    },
                    vectors={"visual": [0.1] * 1536},
                )
            ],
            contract,
        )


def test_qdrant_sink_does_not_echo_its_api_key_when_client_fails():
    contract = api_contract_from_runtime_profile(
        {
            "id": "api-gemini-free-v1",
            "mode": "api_based",
            "collection_name": "video_windows_api_gemini_free_v1",
            "vector_schema": {
                name: {"dimensions": 1536} for name in ("visual", "audio", "transcript", "caption")
            },
        }
    )

    class FailingClient:
        def collection_exists(self, _name):
            raise RuntimeError("connection rejected Bearer qdrant-test-secret")

    sink = make_profile_qdrant_sink(
        qdrant_url="https://example.cloud.qdrant.io",
        qdrant_api_key="qdrant-test-secret",
        profile=contract,
        client_factory=lambda **_kwargs: FailingClient(),
    )
    record = ApiWindowRecord(
        payload={"window_id": "window-0", **contract.metadata()},
        vectors={"visual": [0.1] * 1536},
    )

    with pytest.raises(ApiPipelineError) as raised:
        sink([record], contract)

    assert "qdrant-test-secret" not in str(raised.value)
