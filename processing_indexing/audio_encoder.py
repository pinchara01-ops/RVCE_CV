from pathlib import Path
from typing import Protocol
from .models import VideoWindow

SILENT_AUDIO_VECTOR = [0.0] * 512


class AudioEncoder(Protocol):
    def encode(
        self, video_path: Path, window: VideoWindow, has_audio: bool
    ) -> list[float]: ...


class ClapAudioEncoder:
    """Silent/missing audio uses a deterministic zero sentinel while payload has_audio is false."""

    def __init__(self, model_name="laion/clap-htsat-unfused", device="cpu"):
        self.model_name, self.device, self._model, self._processor = (
            model_name,
            device,
            None,
            None,
        )

    def encode(self, video_path, window, has_audio):
        if not has_audio:
            return SILENT_AUDIO_VECTOR.copy()
        import librosa
        import numpy as np
        import torch

        audio, _ = librosa.load(
            str(video_path),
            sr=48000,
            mono=True,
            offset=window.start,
            duration=window.end - window.start,
        )
        if audio.size == 0 or float(np.max(np.abs(audio))) < 1e-8:
            return SILENT_AUDIO_VECTOR.copy()
        if self._model is None:
            from transformers import ClapAudioModelWithProjection, AutoProcessor

            self._processor = AutoProcessor.from_pretrained(self.model_name)
            self._model = (
                ClapAudioModelWithProjection.from_pretrained(
                    self.model_name, use_safetensors=True
                )
                .to(self.device)
                .eval()
            )
        inputs = {
            k: v.to(self.device)
            for k, v in self._processor(
                audios=audio, sampling_rate=48000, return_tensors="pt"
            ).items()
        }
        with torch.inference_mode():
            vector = (
                torch.nn.functional.normalize(
                    self._model(**inputs).audio_embeds[0], dim=0
                )
                .cpu()
                .float()
                .tolist()
            )
        if len(vector) != 512 or not np.isfinite(vector).all():
            raise ValueError("invalid CLAP vector")
        return vector
