from pathlib import Path
from typing import Protocol
from .models import TranscriptSegment


class Transcriber(Protocol):
    def transcribe(
        self, video_path: Path, has_audio: bool
    ) -> list[TranscriptSegment]: ...


class FasterWhisperTranscriber:
    def __init__(self, model_name="small", device="cpu"):
        self.model_name, self.device, self._model = model_name, device, None

    def transcribe(self, video_path, has_audio):
        if not has_audio:
            return []
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type="float16" if self.device == "cuda" else "int8",
            )
        segments, _ = self._model.transcribe(str(video_path))
        return [
            TranscriptSegment(start=x.start, end=x.end, text=x.text) for x in segments
        ]
