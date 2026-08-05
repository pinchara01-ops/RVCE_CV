from pathlib import Path
from typing import Protocol

from .model_cache import model_load_kwargs
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

            load_kwargs = model_load_kwargs(self.model_name)
            self._processor = XCLIPProcessor.from_pretrained(
                self.model_name, **load_kwargs
            )
            self._model = (
                XCLIPModel.from_pretrained(self.model_name, **load_kwargs)
                .to(self.device)
                .eval()
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
        # XCLIPProcessor treats the temporal frame list as an image batch.
        # In transformers 4.57, the legacy `videos=` argument is accepted but
        # silently returns an empty BatchEncoding.
        inputs = self._processor(images=frames, return_tensors="pt")
        pixel_values = inputs.get("pixel_values_videos")
        if pixel_values is None:
            pixel_values = inputs.get("pixel_values")
        if pixel_values is None:
            raise ValueError("X-CLIP processor did not return video pixel values")
        pixel_values = pixel_values.to(self.device)
        with torch.inference_mode():
            batch_size, num_frames, channels, height, width = pixel_values.shape
            flattened = pixel_values.reshape(-1, channels, height, width)
            vision = self._model.vision_model(pixel_values=flattened, return_dict=True)
            frame_embeddings = self._model.visual_projection(vision.pooler_output)
            temporal_input = frame_embeddings.view(batch_size, num_frames, -1)
            temporal = self._model.mit(temporal_input, return_dict=True)
            vector = (
                torch.nn.functional.normalize(temporal.pooler_output[0], dim=0)
                .cpu()
                .float()
                .tolist()
            )
        if len(vector) != 512 or not np.isfinite(vector).all():
            raise ValueError("invalid X-CLIP vector")
        return vector
