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


class ActionTiming(BaseModel):
    action: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)


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


class RunStatus(str, Enum):
    complete = "complete"
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
