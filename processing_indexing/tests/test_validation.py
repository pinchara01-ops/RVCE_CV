import math
import pytest
from processing_indexing.models import WindowVectors, VLMDescription
from processing_indexing.qdrant_store import deterministic_point_id


def vectors(**changes):
    data = {
        "visual": [0.0] * 512,
        "audio": [0.0] * 512,
        "speech": [0.0] * 1024,
        "caption": [0.0] * 1024,
    }
    data.update(changes)
    return data


def test_vectors_accept_contract():
    assert WindowVectors(**vectors()).speech == [0.0] * 1024


def test_wrong_dimension_rejected():
    with pytest.raises(ValueError, match="visual vector"):
        WindowVectors(**vectors(visual=[0.0]))


def test_nonfinite_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        WindowVectors(**vectors(audio=[math.nan] * 512))


def test_vlm_json_and_caption_normalization():
    value = VLMDescription.model_validate_json(
        '{"actions":["person waves"],"visible_text":["EXIT"],"scene_context":"hall"}'
    )
    assert value.caption() == "person waves. EXIT. hall"


def test_invalid_vlm_json():
    with pytest.raises(ValueError):
        VLMDescription.model_validate_json("not json")


def test_point_id_is_deterministic():
    assert deterministic_point_id("a_window_0000") == deterministic_point_id(
        "a_window_0000"
    )
