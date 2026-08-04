from types import SimpleNamespace

from processing_indexing.config import Settings
from processing_indexing.models import VLMDescription
from processing_indexing.pipeline import ProcessingPipeline


def vector(size, axis=0):
    result = [0.0] * size
    result[axis] = 1.0
    return result


class Store:
    def __init__(self):
        self.points = {}

    def ensure_collection(self):
        pass

    def upsert(self, records):
        for payload, vectors in records:
            self.points[payload.window_id] = (payload, vectors)


class Text:
    def encode(self, texts):
        return [vector(1024) for _ in texts]


class RecordingVLM:
    def __init__(self, outcomes=None):
        self.calls = []
        self.outcomes = outcomes or {}

    def describe(self, path, window):
        self.calls.append(window.index)
        outcome = self.outcomes.get(window.index)
        if isinstance(outcome, Exception):
            raise outcome
        confidence = 1.0 if outcome is None else outcome
        return VLMDescription(
            people_and_clothing=["person in a blue shirt"],
            objects_and_colours=["red cup"],
            actions=["person lifts cup"],
            spatial_relationships=["cup beside person"],
            scene_context="kitchen",
            confidence=confidence,
        )


def pipeline(tmp_path, monkeypatch, duration=30, vlm=None, visual=None, settings=None):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"real identity input")
    monkeypatch.setattr(
        "processing_indexing.pipeline.probe_video",
        lambda _: SimpleNamespace(duration=duration, has_audio=False),
    )
    store = Store()
    vlm = vlm or RecordingVLM()
    visual = visual or SimpleNamespace(encode=lambda path, window: vector(512))
    processor = ProcessingPipeline(
        SimpleNamespace(transcribe=lambda *args: []),
        visual,
        SimpleNamespace(encode=lambda *args: [0.0] * 512),
        Text(),
        vlm,
        store,
        settings or Settings(vlm_max_gap_windows=10, vlm_min_direct_confidence=0.5),
    )
    return processor.process_video(path), store, vlm


def test_two_pass_pipeline_calls_only_selected_windows_and_preserves_all_points(
    tmp_path, monkeypatch
):
    report, store, vlm = pipeline(tmp_path, monkeypatch)
    assert vlm.calls == [0, 4]
    assert len(store.points) == report.total_windows == 5
    assert report.selected_vlm_windows == 2
    assert report.estimated_calls_saved == 3
    assert report.selected_ratio == 0.4


def test_direct_inherited_and_unavailable_payloads_are_distinct(tmp_path, monkeypatch):
    report, store, _ = pipeline(tmp_path, monkeypatch)
    payloads = [store.points[key][0] for key in sorted(store.points)]
    direct, inherited, unavailable = payloads[0], payloads[1], payloads[2]
    assert (
        direct.vlm_processed and direct.caption_direct and not direct.caption_inherited
    )
    assert (
        inherited.caption_inherited
        and not inherited.caption_direct
        and not inherited.vlm_processed
    )
    assert inherited.caption_source_window_id == direct.window_id
    assert inherited.caption_source_distance == 1
    assert inherited.caption.startswith("Inherited nearby scene context")
    assert "lifts cup" not in inherited.caption
    assert unavailable.caption == "" and not unavailable.caption_available
    assert not unavailable.vlm_processed and not unavailable.caption_inherited
    assert len(store.points[unavailable.window_id][1].caption) == 1024
    assert report.direct_caption_windows == 2
    assert report.inherited_caption_windows == 2
    assert report.unavailable_caption_windows == 1


def test_previous_vlm_failure_selects_next_window_for_recovery(tmp_path, monkeypatch):
    report, store, vlm = pipeline(
        tmp_path, monkeypatch, vlm=RecordingVLM({0: RuntimeError("down")})
    )
    assert vlm.calls[:2] == [0, 1]
    assert (
        "previous_vlm_failure"
        in store.points[sorted(store.points)[1]][0].selection_reasons
    )
    assert report.failed_vlm_windows == 1
    assert report.selected_vlm_windows == 3
    assert report.successful_vlm_windows == 2
    assert report.skipped_vlm_windows == 2
    assert report.estimated_calls_saved == 2
    assert report.selection_count_by_reason["previous_vlm_failure"] == 1
    failed = store.points[sorted(store.points)[0]][0]
    assert failed.vlm_call_state == "failed"
    assert report.status == "completed_with_errors"


def test_low_confidence_selects_next_window_earlier(tmp_path, monkeypatch):
    report, store, vlm = pipeline(tmp_path, monkeypatch, vlm=RecordingVLM({0: 0.2}))
    assert vlm.calls[:2] == [0, 1]
    assert (
        "previous_low_confidence"
        in store.points[sorted(store.points)[1]][0].selection_reasons
    )
    assert report.successful_vlm_windows == 3
    assert report.selected_vlm_windows == 3
    assert report.selection_count_by_reason["previous_low_confidence"] == 1


def test_high_confidence_selected_call_does_not_promote_recovery(tmp_path, monkeypatch):
    report, _, vlm = pipeline(tmp_path, monkeypatch, vlm=RecordingVLM({0: 0.9}))
    assert vlm.calls == [0, 4]
    assert report.selected_vlm_windows == 2


def test_consecutive_failures_advance_once_per_window_and_terminate(
    tmp_path, monkeypatch
):
    failures = {index: RuntimeError(f"failure {index}") for index in range(5)}
    report, _, vlm = pipeline(tmp_path, monkeypatch, vlm=RecordingVLM(failures))
    assert vlm.calls == [0, 1, 2, 3, 4]
    assert report.selected_vlm_windows == 5
    assert report.failed_vlm_windows == 5
    assert report.successful_vlm_windows == 0
    assert report.skipped_vlm_windows == 0
    assert report.status == "completed_with_errors"


def test_last_window_failure_never_promotes_beyond_video(tmp_path, monkeypatch):
    report, _, vlm = pipeline(
        tmp_path, monkeypatch, vlm=RecordingVLM({4: RuntimeError("last failed")})
    )
    assert vlm.calls == [0, 4]
    assert report.selected_vlm_windows == 2
    assert report.failed_vlm_windows == 1


def test_ratio_cap_never_suppresses_recovery_call(tmp_path, monkeypatch):
    settings = Settings(
        vlm_max_gap_windows=99,
        vlm_max_selected_ratio=0.01,
        vlm_min_direct_confidence=0.5,
    )
    report, _, vlm = pipeline(
        tmp_path,
        monkeypatch,
        vlm=RecordingVLM({0: RuntimeError("down")}),
        settings=settings,
    )
    assert vlm.calls == [0, 1, 4]
    assert report.selected_vlm_windows == 3
    assert report.selected_ratio == 0.6


def test_adjacent_overlapping_same_event_is_not_called_twice(tmp_path, monkeypatch):
    changing = SimpleNamespace(
        encode=lambda path, window: vector(512, 1 if window.index >= 1 else 0)
    )
    settings = Settings(vlm_max_gap_windows=10, vlm_min_direct_confidence=0)
    _, _, vlm = pipeline(tmp_path, monkeypatch, visual=changing, settings=settings)
    assert vlm.calls == [0, 1, 4]


def test_no_inheritance_across_detected_boundary(tmp_path, monkeypatch):
    changing = SimpleNamespace(
        encode=lambda path, window: vector(512, 1 if window.index >= 2 else 0)
    )
    vlm = RecordingVLM({0: RuntimeError("down"), 1: RuntimeError("down")})
    _, store, _ = pipeline(
        tmp_path,
        monkeypatch,
        vlm=vlm,
        visual=changing,
        settings=Settings(vlm_max_gap_windows=10, vlm_min_direct_confidence=0),
    )
    second = store.points[sorted(store.points)[1]][0]
    assert second.caption == ""
    assert not second.caption_inherited and not second.caption_available


def test_selection_report_reason_counts_and_change_averages(tmp_path, monkeypatch):
    report, _, _ = pipeline(tmp_path, monkeypatch)
    assert report.selection_count_by_reason == {"first_window": 1, "last_window": 1}
    assert set(report.average_change) == {"visual", "audio", "speech", "combined"}
    assert report.selection_config["visual_threshold"] == 0.12


def test_separate_videos_never_share_inherited_caption_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "processing_indexing.pipeline.probe_video",
        lambda _: SimpleNamespace(duration=20, has_audio=False),
    )
    store = Store()
    processor = ProcessingPipeline(
        SimpleNamespace(transcribe=lambda *args: []),
        SimpleNamespace(encode=lambda *args: vector(512)),
        SimpleNamespace(encode=lambda *args: [0.0] * 512),
        Text(),
        RecordingVLM(),
        store,
        Settings(vlm_max_gap_windows=10, vlm_min_direct_confidence=0.5),
    )
    first = tmp_path / "first.mp4"
    first.write_bytes(b"first video")
    second = tmp_path / "second.mp4"
    second.write_bytes(b"second video")
    reports = [processor.process_video(first), processor.process_video(second)]
    for report in reports:
        payloads = [
            payload
            for payload, _ in store.points.values()
            if payload.video_id == report.video_id
        ]
        for payload in payloads:
            if payload.caption_source_window_id:
                assert payload.caption_source_window_id.startswith(report.video_id)
