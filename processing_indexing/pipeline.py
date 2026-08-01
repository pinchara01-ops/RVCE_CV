"""Pipeline orchestration boundaries.

Implementation order:
probe -> transcribe full video -> generate overlapping windows -> encode each
modality -> caption every window with the VLM -> validate -> idempotent upsert.
Do not hide model or indexing failures behind generated dummy data.
"""

from pathlib import Path


class ProcessingPipeline:
    def process_video(self, video_path: Path) -> dict:
        raise NotImplementedError("Implement according to PROCESSING_INDEXING_SPEC.md")
