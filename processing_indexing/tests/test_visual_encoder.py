from processing_indexing.visual_encoder import XClipVisualEncoder


def test_xclip_processor_video_key_is_mapped_to_model_pixel_values(monkeypatch):
    import cv2
    import numpy as np
    import torch

    class Capture:
        def set(self, *_):
            pass

        def read(self):
            return True, np.zeros((4, 4, 3), dtype=np.uint8)

        def release(self):
            pass

    class Processor:
        def __call__(self, **kwargs):
            assert "images" in kwargs and "videos" not in kwargs
            return {"pixel_values": torch.ones((1, 8, 3, 4, 4))}

    class Model:
        def __init__(self):
            self.vision_model = self.Vision()
            self.mit = self.Temporal()

        class Vision:
            def __call__(self, pixel_values, return_dict):
                assert return_dict and pixel_values.shape == (8, 3, 4, 4)
                return type("Output", (), {"pooler_output": torch.ones((8, 512))})()

        class Temporal:
            def __call__(self, values, return_dict):
                assert return_dict and values.shape == (1, 8, 512)
                return type("Output", (), {"pooler_output": torch.ones((1, 512))})()

        def visual_projection(self, values):
            return values

    monkeypatch.setattr(cv2, "VideoCapture", lambda *_: Capture())
    encoder = XClipVisualEncoder(frames=8)
    encoder._processor = Processor()
    encoder._model = Model()
    window = type("Window", (), {"start": 0.0, "end": 10.0})()
    assert len(encoder.encode("video.mp4", window)) == 512
