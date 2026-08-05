from __future__ import annotations

import base64
from io import BytesIO

import pytest

from query_retrieval.qwen3_vl_backend import (
    DEFAULT_QWEN3_VL_RERANKER_MODEL,
    Qwen3VLRerankerConfig,
    _candidate_document_text,
    create_qwen3_vl_reranker_backend,
)
from query_retrieval.reranking import CrossEncoderInput


def _frame(colour: str) -> str:
    image = pytest.importorskip("PIL.Image").new("RGB", (12, 8), colour)
    encoded = BytesIO()
    image.save(encoded, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")


def _evidence() -> CrossEncoderInput:
    return CrossEncoderInput(
        query="person takes a bag from a car",
        candidate_id="private-window-id",
        candidate_start=10.0,
        candidate_end=30.0,
        frame_timestamps=(12.5, 25.0),
        frames=(_frame("red"), _frame("blue")),
        transcript="a door shuts",
        caption="a person stands beside a parked car",
    )


def test_qwen_backend_loads_only_in_factory_and_scores_raw_candidate_evidence():
    calls = []

    class FakeCrossEncoder:
        def predict(self, pairs, *, prompt):
            calls.append((pairs, prompt))
            return [0.875]

    backend = create_qwen3_vl_reranker_backend(
        Qwen3VLRerankerConfig(device="cpu"),
        cross_encoder_factory=lambda model, device: (
            calls.append((model, device)) or FakeCrossEncoder()
        ),
    )

    assert calls == [(DEFAULT_QWEN3_VL_RERANKER_MODEL, "cpu")]
    assert backend(_evidence()) == 0.875
    pairs, prompt = calls[1]
    query, document = pairs[0]
    assert query == "person takes a bag from a car"
    assert prompt
    assert "door shuts" in document["text"]
    assert "parked car" in document["text"]
    assert "private-window-id" not in document["text"]
    assert "score" not in document["text"].lower()
    assert document["image"].mode == "RGB"
    assert document["image"].width > 0


def test_qwen_backend_falls_back_when_old_cross_encoder_has_no_prompt_argument():
    calls = []

    class OlderCrossEncoder:
        def predict(self, pairs):
            calls.append(pairs)
            return [0.4]

    backend = create_qwen3_vl_reranker_backend(
        cross_encoder_factory=lambda _model, _device: OlderCrossEncoder()
    )

    assert backend(_evidence()) == 0.4
    assert len(calls) == 1


def test_qwen_backend_rejects_invalid_frame_data_without_leaking_payload():
    evidence = CrossEncoderInput(
        query="q",
        candidate_id="id",
        candidate_start=0.0,
        candidate_end=1.0,
        frame_timestamps=(0.0,),
        frames=("not-a-data-url",),
        transcript="",
        caption="",
    )
    backend = create_qwen3_vl_reranker_backend(
        cross_encoder_factory=lambda _model, _device: object()
    )
    with pytest.raises(ValueError, match="base64 image data URLs"):
        backend(evidence)


def test_qwen_config_requires_non_empty_model_and_prompt():
    with pytest.raises(ValueError, match="model"):
        Qwen3VLRerankerConfig(model=" ")
    with pytest.raises(ValueError, match="approved"):
        Qwen3VLRerankerConfig(model="Qwen/Qwen3-VL-Reranker-8B")
    with pytest.raises(ValueError, match="prompt"):
        Qwen3VLRerankerConfig(prompt=" ")


def test_candidate_document_omits_retrieval_ids_and_scores():
    text = _candidate_document_text(_evidence())
    assert "private-window-id" not in text
    assert "RRF" not in text
