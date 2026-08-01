import uuid
import time
from .models import VECTOR_DIMS, WindowPayload, WindowVectors


class CollectionSchemaError(RuntimeError):
    pass


def deterministic_point_id(window_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "video-window:" + window_id))


class QdrantStore:
    def __init__(
        self, client, collection_name="video_windows", batch_size=8, retries=2
    ):
        self.client, self.collection_name, self.batch_size, self.retries = (
            client,
            collection_name,
            batch_size,
            retries,
        )

    def ensure_collection(self):
        from qdrant_client.models import Distance, VectorParams

        expected = {
            k: VectorParams(size=v, distance=Distance.COSINE)
            for k, v in VECTOR_DIMS.items()
        }
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(self.collection_name, vectors_config=expected)
            return
        actual = self.client.get_collection(self.collection_name).config.params.vectors
        errors = []
        if set(actual) != set(expected):
            errors.append(
                f"vector names: expected {sorted(expected)}, got {sorted(actual)}"
            )
        for name, size in VECTOR_DIMS.items():
            if name in actual and actual[name].size != size:
                errors.append(
                    f"{name} dimension: expected {size}, got {actual[name].size}"
                )
            if (
                name in actual
                and str(actual[name].distance).lower().split(".")[-1] != "cosine"
            ):
                errors.append(f"{name} distance must be Cosine")
        if errors:
            raise CollectionSchemaError("; ".join(errors))

    def upsert(self, items: list[tuple[WindowPayload, WindowVectors]]):
        from qdrant_client.models import PointStruct

        for offset in range(0, len(items), self.batch_size):
            points = [
                PointStruct(
                    id=deterministic_point_id(p.window_id),
                    vector=v.model_dump(),
                    payload=p.model_dump(),
                )
                for p, v in items[offset : offset + self.batch_size]
            ]
            for attempt in range(self.retries + 1):
                try:
                    self.client.upsert(
                        collection_name=self.collection_name, points=points, wait=True
                    )
                    break
                except Exception:
                    if attempt == self.retries:
                        raise
                    time.sleep(2**attempt)
