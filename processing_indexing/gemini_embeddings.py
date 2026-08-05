"""Small, injectable adapter for Gemini Embedding 2 media embeddings.

This module deliberately does not change the local processing pipeline.  It
defines the cloud-facing boundary that a later processing profile can use:
video, audio, and transcript embeddings remain separate named vectors.  They
default to Gemini Embedding 2's shared 1536-dimensional space, while callers
may opt into another supported dimension for an isolated legacy schema.

The Google SDK is an optional, lazy dependency.  Importing this module (and
running the local-only profile) therefore never requires ``google-genai`` or
an API key.  Tests and callers can inject an ``EmbeddingTransport`` instead.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any, Protocol

GEMINI_EMBEDDING_2_MODEL = "gemini-embedding-2"
GEMINI_EMBEDDING_DIMENSIONS = 1536
GEMINI_MIN_EMBEDDING_DIMENSIONS = 128
GEMINI_MAX_EMBEDDING_DIMENSIONS = 3072
GEMINI_MAX_VIDEO_SECONDS = 120.0
GEMINI_MAX_AUDIO_SECONDS = 180.0

_VIDEO_MIME_BY_EXTENSION = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}
_AUDIO_MIME_BY_EXTENSION = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}
_MIME_ALIASES = {
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
}


class GeminiEmbeddingInputError(ValueError):
    """Raised before a request when a media input is unsupported or unsafe."""


class GeminiEmbeddingResponseError(RuntimeError):
    """Raised when a provider response cannot be used as a Gemini vector."""


class GeminiEmbeddingSDKUnavailableError(RuntimeError):
    """Raised only when a real Google SDK transport is used without its SDK."""


def _validate_dimensions(dimensions: int) -> None:
    if not isinstance(dimensions, int) or isinstance(dimensions, bool):
        raise TypeError("Gemini embedding dimensions must be an integer")
    if (
        not GEMINI_MIN_EMBEDDING_DIMENSIONS
        <= dimensions
        <= GEMINI_MAX_EMBEDDING_DIMENSIONS
    ):
        raise ValueError(
            "Gemini Embedding 2 dimensions must be between "
            f"{GEMINI_MIN_EMBEDDING_DIMENSIONS} and {GEMINI_MAX_EMBEDDING_DIMENSIONS}"
        )


@dataclass(frozen=True)
class GeminiEmbeddingProfile:
    """The fixed Gemini Embedding 2 contract used by the cloud profile."""

    model: str = GEMINI_EMBEDDING_2_MODEL
    # 1536-D is the default shared space.  Gemini Embedding 2 also supports
    # 128..3072 dimensions, which callers may select per modality if a vector
    # store needs to retain an existing named-vector schema.
    dimensions: int = GEMINI_EMBEDDING_DIMENSIONS
    max_video_seconds: float = GEMINI_MAX_VIDEO_SECONDS
    max_audio_seconds: float = GEMINI_MAX_AUDIO_SECONDS

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Gemini embedding model must not be empty")
        _validate_dimensions(self.dimensions)
        if self.max_video_seconds <= 0 or self.max_audio_seconds <= 0:
            raise ValueError("Gemini media duration limits must be positive")


DEFAULT_GEMINI_EMBEDDING_PROFILE = GeminiEmbeddingProfile()


@dataclass(frozen=True)
class GeminiVideoInput:
    """An already-normalized, video-only clip to embed visually.

    Gemini Embedding 2 does not process a video's audio track.  Callers should
    pass an extracted audio clip separately through :class:`GeminiAudioInput`.
    """

    path: Path
    mime_type: str
    duration_seconds: float


@dataclass(frozen=True)
class GeminiAudioInput:
    """An already-normalized audio-only clip to embed acoustically."""

    path: Path
    mime_type: str
    duration_seconds: float


@dataclass(frozen=True)
class GeminiTranscriptInput:
    """A non-empty transcript segment to embed in the same semantic space."""

    text: str


@dataclass(frozen=True)
class GeminiEmbeddingContent:
    """A provider-independent request payload passed to an embedding transport."""

    modality: str
    path: Path | None = None
    mime_type: str | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        media_input = self.path is not None
        text_input = self.text is not None
        if media_input == text_input:
            raise ValueError("embedding content must contain exactly one input type")
        if media_input and not self.mime_type:
            raise ValueError("media embedding content must include a MIME type")


@dataclass(frozen=True)
class GeminiWindowEmbeddings:
    """Independent vectors for one window, with dimensions recorded per field.

    ``audio`` and ``transcript`` are optional because a source video may be
    silent or may not have a usable transcript.  The adapter intentionally
    does not replace missing data with zero vectors: the vector-store policy
    belongs to the pipeline integration layer.

    The default profile places all fields in the same 1536-D space.  A caller
    may intentionally select different valid Gemini dimensions per field to
    match an isolated pre-existing vector schema; it must then generate query
    vectors at each matching field dimension during retrieval.
    """

    visual: tuple[float, ...]
    audio: tuple[float, ...] | None = None
    transcript: tuple[float, ...] | None = None
    caption: tuple[float, ...] | None = None
    dimensions_by_modality: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        dimensions = dict(self.dimensions_by_modality or {})
        default_dimension = GEMINI_EMBEDDING_DIMENSIONS
        _validate_vector(
            self.visual,
            field="visual",
            dimensions=dimensions.get("visual", default_dimension),
        )
        if self.audio is not None:
            _validate_vector(
                self.audio,
                field="audio",
                dimensions=dimensions.get("audio", default_dimension),
            )
        if self.transcript is not None:
            _validate_vector(
                self.transcript,
                field="transcript",
                dimensions=dimensions.get("transcript", default_dimension),
            )
        if self.caption is not None:
            _validate_vector(
                self.caption,
                field="caption",
                dimensions=dimensions.get("caption", default_dimension),
            )

    def as_named_vectors(self) -> dict[str, list[float]]:
        """Return only available named vectors for a future vector-store adapter."""

        vectors = {"visual": list(self.visual)}
        if self.audio is not None:
            vectors["audio"] = list(self.audio)
        if self.transcript is not None:
            vectors["transcript"] = list(self.transcript)
        if self.caption is not None:
            vectors["caption"] = list(self.caption)
        return vectors


class EmbeddingTransport(Protocol):
    """Provider-neutral seam used by :class:`GeminiEmbedding2Adapter`."""

    def embed(
        self,
        content: GeminiEmbeddingContent,
        *,
        model: str,
        dimensions: int,
    ) -> list[float]: ...


def normalize_video_input(
    path: str | Path,
    *,
    duration_seconds: float,
    mime_type: str | None = None,
    profile: GeminiEmbeddingProfile = DEFAULT_GEMINI_EMBEDDING_PROFILE,
) -> GeminiVideoInput:
    """Validate one MP4/MOV visual clip against Gemini Embedding 2's limit.

    This is validation and MIME normalization, not transcoding.  Convert WebM
    and longer clips with the media-preparation stage before calling it.
    """

    normalized_path, normalized_mime = _normalize_media_path(
        path,
        mime_type=mime_type,
        allowed_mimes=set(_VIDEO_MIME_BY_EXTENSION.values()),
        kind="video",
    )
    _validate_duration(
        duration_seconds,
        max_seconds=profile.max_video_seconds,
        kind="video",
    )
    return GeminiVideoInput(
        path=normalized_path,
        mime_type=normalized_mime,
        duration_seconds=float(duration_seconds),
    )


def normalize_audio_input(
    path: str | Path,
    *,
    duration_seconds: float,
    mime_type: str | None = None,
    profile: GeminiEmbeddingProfile = DEFAULT_GEMINI_EMBEDDING_PROFILE,
) -> GeminiAudioInput:
    """Validate one MP3/WAV audio clip against Gemini Embedding 2's limit."""

    normalized_path, normalized_mime = _normalize_media_path(
        path,
        mime_type=mime_type,
        allowed_mimes=set(_AUDIO_MIME_BY_EXTENSION.values()),
        kind="audio",
    )
    _validate_duration(
        duration_seconds,
        max_seconds=profile.max_audio_seconds,
        kind="audio",
    )
    return GeminiAudioInput(
        path=normalized_path,
        mime_type=normalized_mime,
        duration_seconds=float(duration_seconds),
    )


def normalize_transcript_input(text: str) -> GeminiTranscriptInput:
    """Trim a transcript and reject empty text before a billable request."""

    normalized = text.strip()
    if not normalized:
        raise GeminiEmbeddingInputError("transcript text must not be empty")
    return GeminiTranscriptInput(text=normalized)


class GeminiEmbedding2Adapter:
    """Embed media through an injected client while preserving modality fields.

    ``transport`` is deliberately a small interface, so local tests can use a
    fake and a production caller can use :class:`GoogleGenAIEmbeddingClient`.
    """

    def __init__(
        self,
        transport: EmbeddingTransport,
        *,
        profile: GeminiEmbeddingProfile = DEFAULT_GEMINI_EMBEDDING_PROFILE,
    ):
        self._transport = transport
        self.profile = profile

    def embed_visual(
        self, video: GeminiVideoInput, *, dimensions: int | None = None
    ) -> list[float]:
        return self._embed(
            GeminiEmbeddingContent(
                modality="visual", path=video.path, mime_type=video.mime_type
            ),
            dimensions=dimensions,
        )

    def embed_audio(
        self, audio: GeminiAudioInput, *, dimensions: int | None = None
    ) -> list[float]:
        return self._embed(
            GeminiEmbeddingContent(
                modality="audio", path=audio.path, mime_type=audio.mime_type
            ),
            dimensions=dimensions,
        )

    def embed_transcript(
        self, transcript: GeminiTranscriptInput, *, dimensions: int | None = None
    ) -> list[float]:
        return self._embed(
            GeminiEmbeddingContent(modality="transcript", text=transcript.text),
            dimensions=dimensions,
        )

    def embed_caption(
        self, caption: GeminiTranscriptInput, *, dimensions: int | None = None
    ) -> list[float]:
        """Embed a VLM caption separately from its source transcript."""

        return self._embed(
            GeminiEmbeddingContent(modality="caption", text=caption.text),
            dimensions=dimensions,
        )

    def embed_window(
        self,
        *,
        video: GeminiVideoInput,
        audio: GeminiAudioInput | None = None,
        transcript: GeminiTranscriptInput | None = None,
        caption: GeminiTranscriptInput | None = None,
        dimensions_by_modality: Mapping[str, int] | None = None,
    ) -> GeminiWindowEmbeddings:
        """Embed independent fields for one window without fusing them."""

        dimensions = _normalize_dimension_map(
            dimensions_by_modality, default=self.profile.dimensions
        )
        visual = tuple(self.embed_visual(video, dimensions=dimensions["visual"]))
        audio_vector = (
            tuple(self.embed_audio(audio, dimensions=dimensions["audio"]))
            if audio is not None
            else None
        )
        transcript_vector = (
            tuple(
                self.embed_transcript(transcript, dimensions=dimensions["transcript"])
            )
            if transcript is not None
            else None
        )
        caption_vector = (
            tuple(self.embed_caption(caption, dimensions=dimensions["caption"]))
            if caption is not None
            else None
        )
        return GeminiWindowEmbeddings(
            visual=visual,
            audio=audio_vector,
            transcript=transcript_vector,
            caption=caption_vector,
            dimensions_by_modality=dimensions,
        )

    def _embed(
        self, content: GeminiEmbeddingContent, *, dimensions: int | None = None
    ) -> list[float]:
        output_dimensions = (
            self.profile.dimensions if dimensions is None else dimensions
        )
        _validate_dimensions(output_dimensions)
        vector = self._transport.embed(
            content,
            model=self.profile.model,
            dimensions=output_dimensions,
        )
        _validate_vector(
            vector,
            field=f"{content.modality} response",
            dimensions=output_dimensions,
        )
        return [float(value) for value in vector]


class GoogleGenAIEmbeddingClient:
    """Lazy production transport backed by the optional ``google-genai`` SDK.

    ``client``, ``types_module``, and ``sdk_loader`` are injectable to make
    the adapter testable.  The SDK is imported only on the first real ``embed``
    call, not at module import or construction time.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        types_module: Any | None = None,
        sdk_loader: Callable[[], tuple[Any, Any]] | None = None,
    ):
        self._api_key = api_key
        self._client = client
        self._types = types_module
        self._sdk_loader = sdk_loader or _load_google_sdk

    def embed(
        self,
        content: GeminiEmbeddingContent,
        *,
        model: str,
        dimensions: int,
    ) -> list[float]:
        client, types = self._ensure_client_and_types()
        contents = _build_google_content(types, content)
        config = types.EmbedContentConfig(output_dimensionality=dimensions)
        response = client.models.embed_content(
            model=model,
            contents=contents,
            config=config,
        )
        return _extract_embedding_values(response)

    def _ensure_client_and_types(self) -> tuple[Any, Any]:
        if self._client is None or self._types is None:
            genai, types = self._sdk_loader()
            self._types = types
            if self._client is None:
                self._client = (
                    genai.Client(api_key=self._api_key)
                    if self._api_key is not None
                    else genai.Client()
                )
        return self._client, self._types


def _normalize_media_path(
    path: str | Path,
    *,
    mime_type: str | None,
    allowed_mimes: set[str],
    kind: str,
) -> tuple[Path, str]:
    normalized_path = Path(path).expanduser().resolve()
    if not normalized_path.is_file():
        raise GeminiEmbeddingInputError(
            f"{kind} file does not exist: {normalized_path}"
        )

    inferred_mime = _VIDEO_MIME_BY_EXTENSION.get(normalized_path.suffix.lower())
    if inferred_mime is None:
        inferred_mime = _AUDIO_MIME_BY_EXTENSION.get(normalized_path.suffix.lower())
    normalized_mime = _MIME_ALIASES.get(
        (mime_type or inferred_mime or "").lower(),
        (mime_type or inferred_mime or "").lower(),
    )
    if normalized_mime not in allowed_mimes:
        supported = ", ".join(sorted(allowed_mimes))
        raise GeminiEmbeddingInputError(
            f"unsupported Gemini {kind} MIME type {normalized_mime or '(unknown)'}; "
            f"convert it to one of: {supported}"
        )
    return normalized_path, normalized_mime


def _validate_duration(
    duration_seconds: float, *, max_seconds: float, kind: str
) -> None:
    if not isinstance(duration_seconds, Real) or isinstance(duration_seconds, bool):
        raise GeminiEmbeddingInputError(f"{kind} duration must be a number")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise GeminiEmbeddingInputError(
            f"{kind} duration must be a positive finite value"
        )
    if duration_seconds > max_seconds:
        raise GeminiEmbeddingInputError(
            f"Gemini Embedding 2 accepts {kind} clips up to {max_seconds:g} seconds; "
            f"received {duration_seconds:g} seconds"
        )


def _normalize_dimension_map(
    dimensions_by_modality: Mapping[str, int] | None, *, default: int
) -> dict[str, int]:
    supported = {"visual", "audio", "transcript", "caption"}
    overrides = dict(dimensions_by_modality or {})
    unsupported = set(overrides) - supported
    if unsupported:
        raise ValueError(
            f"unsupported Gemini embedding modalities: {', '.join(sorted(unsupported))}"
        )
    dimensions = {modality: overrides.get(modality, default) for modality in supported}
    for value in dimensions.values():
        _validate_dimensions(value)
    return dimensions


def _validate_vector(
    vector: tuple[float, ...] | list[float], *, field: str, dimensions: int
) -> None:
    _validate_dimensions(dimensions)
    if len(vector) != dimensions:
        raise GeminiEmbeddingResponseError(
            f"{field} embedding must have {dimensions} dimensions; "
            f"received {len(vector)}"
        )
    if any(
        not isinstance(value, Real)
        or isinstance(value, bool)
        or not math.isfinite(value)
        for value in vector
    ):
        raise GeminiEmbeddingResponseError(
            f"{field} embedding contains non-finite values"
        )


def _load_google_sdk() -> tuple[Any, Any]:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - depends on local optional install
        raise GeminiEmbeddingSDKUnavailableError(
            "Gemini cloud embeddings require the optional 'google-genai' package. "
            "Install it before enabling the Gemini profile."
        ) from exc
    return genai, types


def _build_google_content(types: Any, content: GeminiEmbeddingContent) -> Any:
    if content.text is not None:
        return content.text
    assert content.path is not None and content.mime_type is not None
    part = types.Part.from_bytes(
        data=content.path.read_bytes(), mime_type=content.mime_type
    )
    return types.Content(parts=[part])


def _extract_embedding_values(response: Any) -> list[float]:
    embeddings = _response_value(response, "embeddings")
    if embeddings:
        values = _response_value(embeddings[0], "values")
    else:
        embedding = _response_value(response, "embedding")
        values = _response_value(embedding, "values") if embedding is not None else None
    if values is None:
        raise GeminiEmbeddingResponseError(
            "Gemini embedding response did not contain values"
        )
    return list(values)


def _response_value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
