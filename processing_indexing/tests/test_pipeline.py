from types import SimpleNamespace
import pytest
from processing_indexing.models import TranscriptSegment, VLMDescription
from processing_indexing.pipeline import ProcessingPipeline


class Store:
    def __init__(self, fail=False):
        self.points = {}
        self.fail = fail

    def ensure_collection(self):
        pass

    def upsert(self, items):
        if self.fail:
            raise RuntimeError("interrupted")
        for p, v in items:
            self.points[p.window_id] = (p, v)


class Text:
    def encode(self, texts):
        return [[0.0] * 1024 for _ in texts]


class VLM:
    def describe(self, *args):
        return VLMDescription(actions=["waves"], scene_context="room", confidence=1)


def test_pipeline_payload_resume_and_idempotency(tmp_path, monkeypatch):
    path = tmp_path / "v"
    path.write_bytes(b"same")
    meta = SimpleNamespace(duration=10.0, has_audio=False)
    monkeypatch.setattr("processing_indexing.pipeline.probe_video", lambda p: meta)
    store = Store()
    pipeline = ProcessingPipeline(
        SimpleNamespace(
            transcribe=lambda *a: [TranscriptSegment(start=1, end=2, text="hi")]
        ),
        SimpleNamespace(encode=lambda *a: [0.0] * 512),
        SimpleNamespace(encode=lambda *a: [0.0] * 512),
        Text(),
        VLM(),
        store,
    )
    one = pipeline.process_video(path)
    two = pipeline.process_video(path)
    assert (
        one.status == "complete"
        and len(store.points) == 1
        and two.successfully_indexed_windows == 1
    )
    payload = next(iter(store.points.values()))[0]
    assert {
        "video_id",
        "window_id",
        "start",
        "end",
        "transcript",
        "caption",
        "has_audio",
        "vlm_processed",
        "source_path",
    } <= set(payload.model_dump())


def test_partial_failure_report(tmp_path, monkeypatch):
    path = tmp_path / "v"
    path.write_bytes(b"x")
    monkeypatch.setattr(
        "processing_indexing.pipeline.probe_video",
        lambda p: SimpleNamespace(duration=15, has_audio=False),
    )
    visual = SimpleNamespace(
        encode=lambda p, w: (
            (_ for _ in ()).throw(RuntimeError("bad frame"))
            if w.index == 1
            else [0.0] * 512
        )
    )
    report = ProcessingPipeline(
        SimpleNamespace(transcribe=lambda *a: []),
        visual,
        SimpleNamespace(encode=lambda *a: [0.0] * 512),
        Text(),
        VLM(),
        Store(),
    ).process_video(path)
    assert (
        report.status == "partial"
        and report.failed_windows == 1
        and report.successfully_indexed_windows == 1
    )


@pytest.mark.integration
def test_real_stack_opt_in():
    pytest.skip(
        "Set up a real video, cached models, and Qdrant, then replace this opt-in fixture"
    )
