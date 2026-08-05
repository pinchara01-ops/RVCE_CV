"""Tests for post_training/schemas/model_manifest.py sha256 validation.

Fields below are SYNTHETIC/FAKE placeholders, not a real model artifact.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from post_training.schemas.model_manifest import ModelManifest

FAKE_VALID_SHA256 = "a" * 64  # syntactically valid hex, not a real digest


def _fake_manifest_kwargs(sha256: str) -> dict:
    return dict(
        base_model="fake-org/fake-base-model",
        revision="fake-rev-1",
        adapter_path="fake/adapter/path",
        sha256=sha256,
        vector_dim=1024,
        tokenizer_revision="fake-tokenizer-rev-1",
        training_data_manifest_ref="fake://manifest/ref",
        eval_report_ref="fake://eval/report",
        licence="fake-licence",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_valid_sha256_is_accepted():
    manifest = ModelManifest(**_fake_manifest_kwargs(FAKE_VALID_SHA256))
    assert manifest.sha256 == FAKE_VALID_SHA256


def test_uppercase_sha256_is_lowercased():
    manifest = ModelManifest(**_fake_manifest_kwargs("A" * 64))
    assert manifest.sha256 == "a" * 64


@pytest.mark.parametrize(
    "bad_sha256",
    [
        "not-a-hash",
        "a" * 63,  # too short
        "a" * 65,  # too long
        "g" * 64,  # non-hex character
        "",
    ],
)
def test_bad_sha256_is_rejected(bad_sha256: str):
    with pytest.raises(ValidationError):
        ModelManifest(**_fake_manifest_kwargs(bad_sha256))
