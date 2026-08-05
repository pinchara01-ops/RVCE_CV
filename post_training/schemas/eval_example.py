"""Pydantic schema for hand-labeled post-training evaluation examples.

Isolated from query_retrieval/ and processing_indexing/ on purpose: this
module has no import-time dependency on the existing pipeline, so editing
the eval schema can never touch working retrieval code.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EvalWindow(BaseModel):
    """The video window the example was drawn from."""

    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _check_order(self) -> "EvalWindow":
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")
        return self


class EvalQuery(BaseModel):
    """One natural-language query paired with this example."""

    text: str = Field(min_length=1)
    language: str = Field(default="en", description="BCP-47-ish language code, e.g. 'en', 'hi'.")
    script: str = Field(default="Latn", description="ISO 15924 script code, e.g. 'Latn', 'Deva'.")
    origin: Literal["human", "synthetic", "back_translated"] = "human"


class EvalLabels(BaseModel):
    """Ground truth for scoring retrieval against this example."""

    relevant: bool
    event_start_s: float = Field(ge=0)
    event_end_s: float = Field(ge=0)
    observed_actions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    # README (post-training/README.md, section 5): "relevant=false negatives
    # must have an explicit reason: temporal near miss, similar object,
    # similar activity, language mismatch, silent audio, etc." Optional here
    # at the schema level; post_training/data/validate_manifest.py enforces
    # it as a hard error whenever relevant is False.
    reason: str | None = None

    @model_validator(mode="after")
    def _check_order(self) -> "EvalLabels":
        if self.event_end_s <= self.event_start_s:
            raise ValueError("event_end_s must be greater than event_start_s")
        return self


class EvalMetadata(BaseModel):
    """Slicing metadata for the example's source video/window.

    post-training/README.md section 6 ("Evaluation before training") requires
    reporting every metric by language/script (see EvalQuery), domain,
    daylight/night, and audio availability — not aggregate-only. All fields
    are optional/"unknown"-defaulted since this metadata is frequently not
    known until a human reviews the source video.
    """

    domain: str | None = Field(
        default=None, description="e.g. 'road', 'retail', 'corridor', 'outdoor'."
    )
    day_night: Literal["day", "night", "unknown"] = "unknown"
    has_audio: bool | None = Field(
        default=None, description="None means unknown/not yet reviewed, distinct from False."
    )


class EvalExample(BaseModel):
    """One labeled evaluation example: a video window, its queries, and the
    ground-truth event span queries should retrieve."""

    example_id: str = Field(min_length=1)
    source_video_id: str = Field(min_length=1)
    split_group: Literal["dev", "test"] = "dev"
    window: EvalWindow
    queries: list[EvalQuery] = Field(min_length=1)
    labels: EvalLabels
    metadata: EvalMetadata = Field(default_factory=EvalMetadata)


class EvalSet(BaseModel):
    """Top-level container for post_training/data/eval_set.json."""

    examples: list[EvalExample] = Field(default_factory=list)
