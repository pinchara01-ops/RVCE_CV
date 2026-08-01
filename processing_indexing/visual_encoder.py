from pathlib import Path
from typing import Protocol
from .models import VideoWindow


class VisualEncoder(Protocol):
    def encode(self, video_path: Path, window: VideoWindow) -> list[float]: ...


class XClipVisualEncoder:
    def __init__(
        self, model_name="microsoft/xclip-base-patch32", device="cpu", frames=8
    ):
        self.model_name, self.device, self.frames, self._model, self._processor = (
            model_name,
            device,
            frames,
            None,
            None,
        )

    def encode(self, video_path, window):
        import cv2
        import numpy as np
        import torch

        if self._model is None:
            from transformers import XCLIPModel, XCLIPProcessor

            self._processor = XCLIPProcessor.from_pretrained(self.model_name)
            self._model = (
                XCLIPModel.from_pretrained(self.model_name).to(self.device).eval()
            )
        cap = cv2.VideoCapture(str(video_path))
        frames = []
        for timestamp in np.linspace(
            window.start, window.end, self.frames, endpoint=False
        ):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = cap.read()
            if not ok:
                cap.release()
                raise RuntimeError(f"Could not decode frame at {timestamp}s")
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        cap.release()
        inputs = {
            k: v.to(self.device)
            for k, v in self._processor(videos=[frames], return_tensors="pt").items()
        }
        with torch.inference_mode():
            vector = (
                torch.nn.functional.normalize(
                    self._model.get_video_features(**inputs)[0], dim=0
                )
                .cpu()
                .float()
                .tolist()
            )
        if len(vector) != 512 or not np.isfinite(vector).all():
            raise ValueError("invalid X-CLIP vector")
        return vector
