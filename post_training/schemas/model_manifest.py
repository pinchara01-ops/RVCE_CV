"""Pydantic model for a model-registry entry.

Fields match post-training/README.md section 9 ("Future engineering required
in this repository"), item 1: "Model registry: a manifest per artifact
containing base model, revision, adapter, SHA-256, vector dimension,
tokenizer/processor revision, training data manifest, evaluation report,
licence, and creation date."
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ModelManifest(BaseModel):
    """One versioned, deployable model/adapter artifact."""

    base_model: str = Field(min_length=1, description="e.g. 'BAAI/bge-m3'.")
    revision: str = Field(min_length=1, description="Base model commit/tag/revision.")
    adapter_path: str | None = Field(
        default=None, description="Path/URI to adapter weights, or None for a full checkpoint."
    )
    sha256: str = Field(description="SHA-256 of the artifact file, as 64 lowercase hex chars.")
    vector_dim: int = Field(gt=0, description="Output embedding dimension.")
    tokenizer_revision: str = Field(min_length=1, description="Tokenizer/processor revision.")
    training_data_manifest_ref: str = Field(
        min_length=1, description="Reference to the immutable training-data manifest used."
    )
    eval_report_ref: str = Field(
        min_length=1, description="Reference to the frozen baseline/candidate eval report."
    )
    licence: str = Field(min_length=1)
    created_at: datetime

    @field_validator("sha256")
    @classmethod
    def _check_sha256(cls, value: str) -> str:
        if not _SHA256_RE.match(value):
            raise ValueError("sha256 must be exactly 64 hex characters")
        return value.lower()
