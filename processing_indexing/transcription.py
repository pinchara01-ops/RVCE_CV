import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .models import TranscriptSegment


logger = logging.getLogger(__name__)


class Transcriber(Protocol):
    def transcribe(
        self,
        video_path: Path,
        has_audio: bool,
        progress_callback: Callable[[float], None] | None = None,
    ) -> list[TranscriptSegment]: ...


class FasterWhisperTranscriber:
    def __init__(self, model_name="small", device="cpu"):
        self.model_name, self.device, self._model = model_name, device, None

    def transcribe(self, video_path, has_audio, progress_callback=None):
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
        transcript = []
        for segment in segments:
            transcript.append(
                TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                )
            )
            if progress_callback is not None:
                # The callback is observability-only.  A bad UI callback must
                # never make an otherwise valid transcription fail.
                try:
                    progress_callback(float(segment.end))
                except Exception:  # noqa: BLE001
                    logger.debug("Whisper progress callback failed", exc_info=True)
        return transcript
