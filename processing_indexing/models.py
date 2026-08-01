from pydantic import BaseModel, Field, model_validator


class VideoWindow(BaseModel):
    video_id: str
    window_id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    transcript: str = ""
    caption: str = ""
    has_audio: bool = False
    vlm_processed: bool = False
    source_path: str

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
