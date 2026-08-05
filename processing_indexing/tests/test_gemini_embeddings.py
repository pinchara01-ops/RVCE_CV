from pathlib import Path

import pytest

from processing_indexing.gemini_embeddings import (
    GEMINI_EMBEDDING_DIMENSIONS,
    GeminiEmbedding2Adapter,
    GeminiEmbeddingInputError,
    GeminiEmbeddingProfile,
    GeminiEmbeddingResponseError,
    GoogleGenAIEmbeddingClient,
    normalize_audio_input,
    normalize_transcript_input,
    normalize_video_input,
)


def _vector(
    value: float = 0.25, *, dimensions: int = GEMINI_EMBEDDING_DIMENSIONS
) -> list[float]:
    return [value] * dimensions


def _media_file(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"media")
    return path


def test_normalizes_supported_video_and_audio_inputs(tmp_path):
    video = normalize_video_input(
        _media_file(tmp_path, "clip.MP4"), duration_seconds=120
    )
    audio = normalize_audio_input(
        _media_file(tmp_path, "clip.wav"), duration_seconds=180
    )

    assert video.mime_type == "video/mp4"
    assert video.duration_seconds == 120
    assert audio.mime_type == "audio/wav"
    assert audio.duration_seconds == 180


@pytest.mark.parametrize(
    ("normalizer", "filename", "duration"),
    [
        (normalize_video_input, "clip.webm", 10),
        (normalize_video_input, "clip.mp4", 120.01),
        (normalize_audio_input, "clip.flac", 10),
        (normalize_audio_input, "clip.mp3", 180.01),
    ],
)
def test_rejects_unsupported_or_overlong_media(
    tmp_path, normalizer, filename, duration
):
    with pytest.raises(GeminiEmbeddingInputError):
        normalizer(_media_file(tmp_path, filename), duration_seconds=duration)


def test_transcript_is_trimmed_and_empty_text_is_rejected():
    assert normalize_transcript_input("  person runs away  ").text == "person runs away"
    with pytest.raises(GeminiEmbeddingInputError):
        normalize_transcript_input(" \n ")


def test_adapter_preserves_separate_unified_vectors(tmp_path):
    class FakeTransport:
        def __init__(self):
            self.requests = []

        def embed(self, content, *, model, dimensions):
            self.requests.append((content, model, dimensions))
            return _vector(float(len(self.requests)), dimensions=dimensions)

    transport = FakeTransport()
    adapter = GeminiEmbedding2Adapter(transport)
    embeddings = adapter.embed_window(
        video=normalize_video_input(
            _media_file(tmp_path, "clip.mp4"), duration_seconds=20
        ),
        audio=normalize_audio_input(
            _media_file(tmp_path, "clip.mp3"), duration_seconds=20
        ),
        transcript=normalize_transcript_input("car horn then a crash"),
    )

    assert [request[0].modality for request in transport.requests] == [
        "visual",
        "audio",
        "transcript",
    ]
    assert all(request[1] == "gemini-embedding-2" for request in transport.requests)
    assert all(request[2] == 1536 for request in transport.requests)
    assert embeddings.visual[0] == 1.0
    assert embeddings.audio is not None and embeddings.audio[0] == 2.0
    assert embeddings.transcript is not None and embeddings.transcript[0] == 3.0
    assert set(embeddings.as_named_vectors()) == {"visual", "audio", "transcript"}
    assert all(len(vector) == 1536 for vector in embeddings.as_named_vectors().values())


def test_adapter_allows_per_modality_dimensions_for_an_isolated_schema(tmp_path):
    class FakeTransport:
        def embed(self, _content, *, model, dimensions):
            assert model == "gemini-embedding-2"
            return _vector(value=float(dimensions), dimensions=dimensions)

    adapter = GeminiEmbedding2Adapter(FakeTransport())
    embeddings = adapter.embed_window(
        video=normalize_video_input(
            _media_file(tmp_path, "clip.mp4"), duration_seconds=20
        ),
        audio=normalize_audio_input(
            _media_file(tmp_path, "clip.mp3"), duration_seconds=20
        ),
        transcript=normalize_transcript_input("car horn then a crash"),
        caption=normalize_transcript_input("a car collides with a barrier"),
        dimensions_by_modality={
            "visual": 512,
            "audio": 512,
            "transcript": 1024,
            "caption": 1024,
        },
    )

    assert {
        name: len(vector) for name, vector in embeddings.as_named_vectors().items()
    } == {
        "visual": 512,
        "audio": 512,
        "transcript": 1024,
        "caption": 1024,
    }


@pytest.mark.parametrize("dimensions", [127, 3073])
def test_adapter_rejects_gemini_dimensions_outside_supported_range(
    tmp_path, dimensions
):
    class FakeTransport:
        def embed(self, *_args, **_kwargs):
            return _vector()

    adapter = GeminiEmbedding2Adapter(FakeTransport())
    video = normalize_video_input(
        _media_file(tmp_path, "clip.mov"), duration_seconds=10
    )
    with pytest.raises(ValueError, match="between 128 and 3072"):
        adapter.embed_visual(video, dimensions=dimensions)


def test_adapter_rejects_wrong_sized_provider_response(tmp_path):
    class BadTransport:
        def embed(self, *_args, **_kwargs):
            return [0.0]

    adapter = GeminiEmbedding2Adapter(BadTransport())
    video = normalize_video_input(
        _media_file(tmp_path, "clip.mov"), duration_seconds=10
    )
    with pytest.raises(GeminiEmbeddingResponseError, match="1536"):
        adapter.embed_visual(video)


def test_profile_allows_any_supported_shared_embedding_dimension():
    assert GeminiEmbeddingProfile(dimensions=768).dimensions == 768


def test_google_transport_is_lazy_and_mockable_without_google_sdk(tmp_path):
    calls = {"loader": 0, "factory": 0, "request": None}

    class FakeTypes:
        class EmbedContentConfig:
            def __init__(self, *, output_dimensionality):
                self.output_dimensionality = output_dimensionality

        class Part:
            @staticmethod
            def from_bytes(*, data, mime_type):
                return {"data": data, "mime_type": mime_type}

        class Content:
            def __init__(self, *, parts):
                self.parts = parts

    class FakeModels:
        def embed_content(self, **kwargs):
            calls["request"] = kwargs
            return type(
                "Response",
                (),
                {"embeddings": [type("Embedding", (), {"values": _vector()})()]},
            )()

    class FakeClient:
        models = FakeModels()

    class FakeGenAI:
        @staticmethod
        def Client(*, api_key):
            calls["factory"] += 1
            assert api_key == "test-key"
            return FakeClient()

    def fake_loader():
        calls["loader"] += 1
        return FakeGenAI, FakeTypes

    transport = GoogleGenAIEmbeddingClient(api_key="test-key", sdk_loader=fake_loader)
    assert calls["loader"] == 0
    adapter = GeminiEmbedding2Adapter(transport)
    video = normalize_video_input(
        _media_file(tmp_path, "clip.mp4"), duration_seconds=10
    )

    assert len(adapter.embed_visual(video)) == 1536
    assert calls["loader"] == 1
    assert calls["factory"] == 1
    assert calls["request"]["model"] == "gemini-embedding-2"
    assert calls["request"]["config"].output_dimensionality == 1536
    assert calls["request"]["contents"].parts[0]["mime_type"] == "video/mp4"


def test_google_transport_accepts_an_injected_sdk_client_without_importing(tmp_path):
    class FakeTypes:
        class EmbedContentConfig:
            def __init__(self, *, output_dimensionality):
                self.output_dimensionality = output_dimensionality

        class Part:
            @staticmethod
            def from_bytes(*, data, mime_type):
                return {"data": data, "mime_type": mime_type}

        class Content:
            def __init__(self, *, parts):
                self.parts = parts

    class FakeModels:
        def embed_content(self, **_kwargs):
            return {"embeddings": [{"values": _vector(dimensions=512)}]}

    class FakeClient:
        models = FakeModels()

    def unexpected_loader():
        raise AssertionError("the injected client must not import the SDK")

    transport = GoogleGenAIEmbeddingClient(
        client=FakeClient(),
        types_module=FakeTypes,
        sdk_loader=unexpected_loader,
    )
    adapter = GeminiEmbedding2Adapter(transport)
    video = normalize_video_input(
        _media_file(tmp_path, "clip.mp4"), duration_seconds=10
    )

    assert len(adapter.embed_visual(video, dimensions=512)) == 512
