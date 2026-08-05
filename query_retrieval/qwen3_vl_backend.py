"""Lazy local backend for the bounded Qwen3-VL reranking stage.

The first retrieval stage operates on four named vector fields.  This module
does something intentionally different: it gives Qwen3-VL-Reranker only the
raw user query and the evidence for *one already-fused candidate*.  It never
receives an RRF score, a vector similarity, a modality rank, or a collection
handle.

The model is optional and loaded only when a caller explicitly enables the
local Qwen reranker.  That makes API-based indexing usable without a local
model download, while still allowing a hybrid run to use the RTX GPU for the
precision stage.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from query_retrieval.reranking import (
    CrossEncoderInput,
    CrossEncoderRunner,
    RerankerUnavailable,
)


DEFAULT_QWEN3_VL_RERANKER_MODEL = "Qwen/Qwen3-VL-Reranker-2B"
# ``CrossEncoder(..., trust_remote_code=True)`` is required by the published
# Qwen integration.  Do not turn the browser's model selector into a generic
# remote-code loader: the profile currently supports this reviewed, laptop-
# sized model only.  Adding another version must be an explicit code/profile
# change with its own memory and dependency review.
SUPPORTED_QWEN3_VL_RERANKER_MODELS = frozenset({DEFAULT_QWEN3_VL_RERANKER_MODEL})
DEFAULT_QWEN3_VL_RERANKER_PROMPT = (
    "Retrieve surveillance-video evidence relevant to the user's query. "
    "Use the supplied chronological frames, transcript, and caption."
)


@dataclass(frozen=True)
class Qwen3VLRerankerConfig:
    """Explicit local Qwen backend settings.

    The 2B reranker is the laptop-oriented choice.  The 8B release should be
    selected only on a machine with materially more available VRAM; this
    backend deliberately does not silently upgrade to it.
    """

    model: str = DEFAULT_QWEN3_VL_RERANKER_MODEL
    device: str | None = None
    prompt: str = DEFAULT_QWEN3_VL_RERANKER_PROMPT

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Qwen reranker model must not be empty")
        if self.model not in SUPPORTED_QWEN3_VL_RERANKER_MODELS:
            raise ValueError(
                "Qwen reranker model is not an approved local model for this profile"
            )
        if not self.prompt.strip():
            raise ValueError("Qwen reranker prompt must not be empty")


CrossEncoderFactory = Callable[[str, str], Any]


def create_qwen3_vl_reranker_backend(
    config: Qwen3VLRerankerConfig | None = None,
    *,
    cross_encoder_factory: CrossEncoderFactory | None = None,
) -> CrossEncoderRunner:
    """Load the local Qwen cross-encoder and return its score callable.

    This function is meant to be passed as
    :class:`~query_retrieval.reranking.Qwen3VLRerankerAdapter`'s
    ``backend_factory``.  Therefore no optional model dependency is imported
    until reranking actually begins.  ``cross_encoder_factory`` is injectable
    for a deterministic unit test or an alternate local serving runtime.
    """

    settings = config or Qwen3VLRerankerConfig()
    device = settings.device or _default_device()
    factory = cross_encoder_factory or _load_cross_encoder
    try:
        cross_encoder = factory(settings.model, device)
    except RerankerUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - optional model failures are safe
        raise RerankerUnavailable(
            "Qwen3-VL-Reranker-2B could not be initialized on this machine"
        ) from exc

    def score(evidence: CrossEncoderInput) -> float:
        document = {
            "text": _candidate_document_text(evidence),
            # A chronological contact sheet keeps one candidate bounded while
            # giving the image-capable cross-encoder all sampled visual proof.
            "image": _contact_sheet(evidence.frames),
        }
        try:
            raw_scores = cross_encoder.predict(
                [(evidence.query, document)], prompt=settings.prompt
            )
        except TypeError:
            # Older sentence-transformers releases may not expose ``prompt``.
            raw_scores = cross_encoder.predict([(evidence.query, document)])
        return _first_numeric_score(raw_scores)

    return score


def _load_cross_encoder(model: str, device: str) -> Any:
    """Import Sentence Transformers only for the actual local rerank call."""

    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise RerankerUnavailable(
            "Local Qwen reranking requires sentence-transformers"
        ) from exc
    try:
        return CrossEncoder(model, device=device, trust_remote_code=True)
    except TypeError:
        # The Qwen model card's standard CrossEncoder route works on versions
        # that do not accept the explicit Transformers forwarding argument.
        return CrossEncoder(model, device=device)


def _default_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # pragma: no cover - torch is an optional runtime seam
        return "cpu"


def _candidate_document_text(evidence: CrossEncoderInput) -> str:
    """Create score-free textual candidate evidence for Qwen.

    The RRF candidate id and temporal bounds are intentionally not included as
    ranking input.  The cross-encoder gets only the user query (separately),
    chronological frame timestamps, transcript, and caption.
    """

    transcript = evidence.transcript.strip() or "(no transcript available)"
    caption = evidence.caption.strip() or "(no generated caption available)"
    frame_times = ", ".join(f"{value:.2f}s" for value in evidence.frame_timestamps)
    return (
        "Chronological sampled-frame timestamps: "
        f"{frame_times or '(not available)'}\n"
        f"Transcript: {transcript}\n"
        f"Generated caption: {caption}"
    )


def _contact_sheet(frames: tuple[str, ...]) -> Any:
    """Decode bounded JPEG/PNG data URLs into one chronological RGB sheet."""

    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - Pillow is a project dep
        raise RerankerUnavailable("Local Qwen reranking requires Pillow") from exc

    decoded = [_decode_data_url(frame, Image) for frame in frames]
    if not decoded:
        raise ValueError("Qwen reranker received no visual frames")
    target_width = min(512, max(image.width for image in decoded))
    target_height = min(320, max(image.height for image in decoded))
    rows = 2 if len(decoded) > 1 else 1
    columns = (len(decoded) + rows - 1) // rows
    sheet = Image.new("RGB", (columns * target_width, rows * target_height), "black")
    for index, image in enumerate(decoded):
        tile = ImageOps.contain(image, (target_width, target_height), method=Image.Resampling.LANCZOS)
        left = (index % columns) * target_width + (target_width - tile.width) // 2
        top = (index // columns) * target_height + (target_height - tile.height) // 2
        sheet.paste(tile, (left, top))
    return sheet


def _decode_data_url(value: str, image_module: Any) -> Any:
    prefix, separator, payload = value.partition(",")
    if not separator or not prefix.startswith("data:image/") or ";base64" not in prefix:
        raise ValueError("Qwen reranker frames must be base64 image data URLs")
    try:
        decoded = base64.b64decode(payload, validate=True)
        with image_module.open(BytesIO(decoded)) as image:
            return image.convert("RGB").copy()
    except Exception as exc:  # noqa: BLE001 - data URLs come from local sampler
        raise ValueError("could not decode a reranker frame") from exc


def _first_numeric_score(values: Any) -> float:
    """Normalize common CrossEncoder score return shapes to one raw float."""

    if isinstance(values, (float, int)) and not isinstance(values, bool):
        return float(values)
    try:
        first = values[0]
    except (TypeError, KeyError, IndexError) as exc:
        raise ValueError("Qwen reranker returned no score") from exc
    try:
        # Torch/numpy scalar values deliberately use their public ``item``
        # protocol before falling back to Python's float conversion.
        scalar = first.item() if hasattr(first, "item") else first
        return float(scalar)
    except (TypeError, ValueError) as exc:
        raise ValueError("Qwen reranker returned a non-numeric score") from exc
