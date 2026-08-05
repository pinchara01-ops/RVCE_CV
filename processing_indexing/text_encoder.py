import math
from typing import Protocol

from .model_cache import model_load_kwargs

EMPTY_TEXT_SENTINEL = "[NO SPEECH]"


class TextEncoder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class BgeM3TextEncoder:
    def __init__(self, model_name="BAAI/bge-m3", device="cpu"):
        self.model_name, self.device, self._model = model_name, device, None

    def encode(self, texts):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                **model_load_kwargs(self.model_name),
            )
        result = [
            x.tolist()
            for x in self._model.encode(
                [x.strip() or EMPTY_TEXT_SENTINEL for x in texts],
                normalize_embeddings=True,
            )
        ]
        if any(len(x) != 1024 or not all(math.isfinite(v) for v in x) for x in result):
            raise ValueError("invalid BGE-M3 vector")
        return result
