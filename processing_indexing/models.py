from enum import Enum
import math
from pydantic import BaseModel, Field, field_validator, model_validator

VECTOR_DIMS = {"visual": 512, "audio": 512, "speech": 1024, "caption": 1024}


class VideoMetadata(BaseModel):
    duration: float = Field(gt=0)
    has_video: bool
    has_audio: bool
    fps: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    codec: str
    container: str


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end <= self.start:
            raise ValueError("segment end must be after start")
        return self


class VideoWindow(BaseModel):
    video_id: str
    window_id: str
    index: int = Field(default=0, ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class WindowVectors(BaseModel):
    visual: list[float]
    audio: list[float]
    speech: list[float]
    caption: list[float]

    @field_validator("visual", "audio", "speech", "caption")
    @classmethod
    def finite(cls, value):
        if not all(math.isfinite(x) for x in value):
            raise ValueError("embedding contains non-finite values")
        return value

    @model_validator(mode="after")
    def dimensions(self):
        for name, size in VECTOR_DIMS.items():
            if len(getattr(self, name)) != size:
                raise ValueError(f"{name} vector must have {size} dimensions")
        return self


class WindowPayload(BaseModel):
    video_id: str
    window_id: str
    start: float
    end: float
    transcript: str
    caption: str
    has_audio: bool
    vlm_processed: bool
    source_path: str
    caption_direct: bool = False
    caption_inherited: bool = False
    caption_available: bool = False
    caption_source_window_id: str | None = None
    caption_source_distance: int = 0
    caption_confidence: float = Field(default=0.0, ge=0, le=1)
    selection_reasons: list[str] = []
    change_scores: dict[str, float] = {}
    change_from_previous: dict[str, float | None] = {}
    change_from_last_vlm: dict[str, float | None] = {}
    vlm_call_state: str = "unavailable"


class ActionTiming(BaseModel):
    action: str
    # Provider outputs are normalized against the selected window after parsing.
    start_seconds: float
    end_seconds: float


class VLMDescription(BaseModel):
    people_and_clothing: list[str] = []
    objects_and_colours: list[str] = []
    actions: list[str] = []
    object_action_relationships: list[str] = []
    spatial_relationships: list[str] = []
    visible_text: list[str] = []
    scene_context: str = ""
    action_timing: list[ActionTiming] = []
    uncertainty: list[str] = []
    confidence: float = Field(default=0.0, ge=0, le=1)

    def caption(self):
        groups = [
            self.people_and_clothing,
            self.objects_and_colours,
            self.actions,
            self.object_action_relationships,
            self.spatial_relationships,
            self.visible_text,
        ]
        parts = [x.strip() for group in groups for x in group if x.strip()]
        if self.scene_context.strip():
            parts.append(self.scene_context.strip())
        parts += [
            f"{x.action} from {x.start_seconds:g}s to {x.end_seconds:g}s"
            for x in self.action_timing
        ]
        parts += [f"Uncertain: {x.strip()}" for x in self.uncertainty if x.strip()]
        return ". ".join(parts)

    def context_caption(self):
        groups = [
            self.people_and_clothing,
            self.objects_and_colours,
            self.spatial_relationships,
            self.visible_text,
        ]
        parts = [x.strip() for group in groups for x in group if x.strip()]
        if self.scene_context.strip():
            parts.append(self.scene_context.strip())
        parts += [f"Uncertain: {x.strip()}" for x in self.uncertainty if x.strip()]
        return ". ".join(parts)


class RunStatus(str, Enum):
    complete = "complete"
    completed_with_errors = "completed_with_errors"
    partial = "partial"
    failed = "failed"


class ProcessingReport(BaseModel):
    video_id: str
    duration: float
    total_windows: int
    successfully_indexed_windows: int
    failed_windows: int
    vlm_successes: int
    vlm_failures: int
    elapsed_seconds: float
    errors: dict[str, str] = {}
    status: RunStatus
    selected_vlm_windows: int = 0
    successful_vlm_windows: int = 0
    failed_vlm_windows: int = 0
    skipped_vlm_windows: int = 0
    direct_caption_windows: int = 0
    inherited_caption_windows: int = 0
    unavailable_caption_windows: int = 0
    selected_ratio: float = 0.0
    estimated_calls_saved: int = 0
    selection_count_by_reason: dict[str, int] = {}
    average_change: dict[str, float] = {}
    selection_config: dict[str, float | int | bool] = {}
    stage_durations: dict[str, float] = {}
    stage_timing_semantics: str = (
        "accumulated wall-clock seconds per stage; batched or overlapping work may "
        "make stage sums differ from total elapsed time"
    )
