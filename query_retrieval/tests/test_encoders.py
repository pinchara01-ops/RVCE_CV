"""Unit tests for encoders.py.

We mock the model *loaders* (_load_xclip / _load_clap / _load_bge_m3), not
just their forward pass - real X-CLIP/CLAP/BGE-M3 weights are multi-GB
downloads, far too slow/heavy for a default `pytest` run on every save.
Mocking at the loader boundary still exercises the real wrapper logic we
own (singleton caching, tensor->list conversion, dispatch, per-modality
failure isolation) without ever touching the network or a real model.
"""
import math
from unittest.mock import MagicMock, patch

import pytest

from query_retrieval import config, encoders


class _FakeTextModel:
    """Stands in for XCLIPModel/ClapModel: get_text_features returns a
    deterministic non-zero tensor of the requested dim."""

    def __init__(self, dim: int):
        self.dim = dim

    def get_text_features(self, **kwargs):
        import torch

        batch = 1
        return torch.arange(1, self.dim + 1, dtype=torch.float32).unsqueeze(0).expand(batch, -1) / self.dim

    def to(self, device):
        return self

    def eval(self):
        return self


class _FakeBatchEncoding(dict):
    def to(self, device):
        return self


class _FakeTokenizer:
    def __call__(self, texts, **kwargs):
        import torch

        return _FakeBatchEncoding(input_ids=torch.zeros((len(texts), 4), dtype=torch.long))


class _FakeSentenceTransformer:
    def __init__(self, dim: int):
        self.dim = dim

    def encode(self, text, normalize_embeddings=True):
        import numpy as np

        return np.arange(1, self.dim + 1, dtype=np.float32) / self.dim


@pytest.fixture(autouse=True)
def clear_model_cache():
    encoders._model_cache.clear()
    yield
    encoders._model_cache.clear()


def _dims():
    return {m: config.VECTOR_CONFIG[m]["dim"] for m in config.VECTOR_NAMES}


def _assert_valid_vector(vec: list[float], dim: int):
    assert isinstance(vec, list)
    assert len(vec) == dim
    assert all(isinstance(x, float) for x in vec)
    assert not all(x == 0.0 for x in vec)
    assert not any(math.isnan(x) for x in vec)


def test_encode_visual_text_shape():
    dim = _dims()["visual"]
    with patch.object(encoders, "_load_xclip", return_value=(_FakeTextModel(dim), _FakeTokenizer())):
        vec = encoders.encode_visual_text("person in a red jacket")
    _assert_valid_vector(vec, dim)


def test_encode_audio_text_shape():
    dim = _dims()["audio"]
    with patch.object(encoders, "_load_clap", return_value=(_FakeTextModel(dim), _FakeTokenizer())):
        vec = encoders.encode_audio_text("loud crash sound")
    _assert_valid_vector(vec, dim)


def test_encode_speech_text_shape():
    dim = _dims()["speech"]
    with patch.object(encoders, "_load_bge_m3", return_value=(_FakeSentenceTransformer(dim), None)):
        vec = encoders.encode_speech_text("someone says thank you")
    _assert_valid_vector(vec, dim)


def test_encode_caption_text_shape():
    dim = _dims()["caption"]
    with patch.object(encoders, "_load_bge_m3", return_value=(_FakeSentenceTransformer(dim), None)):
        vec = encoders.encode_caption_text("a birthday celebration")
    _assert_valid_vector(vec, dim)


def test_speech_and_caption_share_one_model_load():
    dim = _dims()["speech"]
    fake_loader = MagicMock(return_value=(_FakeSentenceTransformer(dim), None))
    with patch.object(encoders, "_load_bge_m3", fake_loader):
        encoders.encode_speech_text("hello")
        encoders.encode_caption_text("hello")
    fake_loader.assert_called_once()  # second call hits the singleton cache


def test_encode_query_only_encodes_nonzero_weight_modalities():
    dims = _dims()
    with patch.object(encoders, "_load_xclip", return_value=(_FakeTextModel(dims["visual"]), _FakeTokenizer())), \
         patch.object(encoders, "_load_clap") as mock_clap_loader, \
         patch.object(encoders, "_load_bge_m3") as mock_bge_loader:
        weights = {"visual": 1.0, "audio": 0.0, "speech": 0.0, "caption": 0.0}
        result = encoders.encode_query("person in a red jacket", weights)

    assert set(result.keys()) == {"visual"}
    mock_clap_loader.assert_not_called()
    mock_bge_loader.assert_not_called()


def test_encode_query_partial_failure_drops_only_failing_modality():
    dims = _dims()

    def _broken_loader():
        raise RuntimeError("simulated OOM")

    with patch.object(encoders, "_load_xclip", return_value=(_FakeTextModel(dims["visual"]), _FakeTokenizer())), \
         patch.object(encoders, "_load_clap", side_effect=_broken_loader):
        weights = {"visual": 0.5, "audio": 0.5, "speech": 0.0, "caption": 0.0}
        result = encoders.encode_query("man shouting in a blue shirt", weights)

    assert "visual" in result
    assert "audio" not in result
    _assert_valid_vector(result["visual"], dims["visual"])


def test_encode_query_empty_weights_encodes_nothing():
    result = encoders.encode_query("anything", {"visual": 0.0, "audio": 0.0, "speech": 0.0, "caption": 0.0})
    assert result == {}


def test_warmup_loads_all_three_models_once():
    dims = _dims()
    with patch.object(encoders, "_load_xclip", return_value=(_FakeTextModel(dims["visual"]), _FakeTokenizer())) as m1, \
         patch.object(encoders, "_load_clap", return_value=(_FakeTextModel(dims["audio"]), _FakeTokenizer())) as m2, \
         patch.object(encoders, "_load_bge_m3", return_value=(_FakeSentenceTransformer(dims["speech"]), None)) as m3:
        encoders.warmup()

    m1.assert_called_once()
    m2.assert_called_once()
    m3.assert_called_once()
