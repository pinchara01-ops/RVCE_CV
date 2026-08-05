"""Tests for post_training/data/check_split_leakage.py.

All video/example IDs below are SYNTHETIC/FAKE — no real footage.
"""
from __future__ import annotations

from post_training.data.check_split_leakage import find_leakage
from post_training.schemas.eval_example import (
    EvalExample,
    EvalLabels,
    EvalQuery,
    EvalSet,
    EvalWindow,
)


def _fake_example(example_id: str, video_id: str, split_group: str, start_s: float = 0.0) -> EvalExample:
    return EvalExample(
        example_id=example_id,
        source_video_id=video_id,
        split_group=split_group,
        window=EvalWindow(start_s=start_s, end_s=start_s + 10.0),
        queries=[EvalQuery(text="fake query", language="en", script="Latn")],
        labels=EvalLabels(
            relevant=True,
            event_start_s=start_s + 1.0,
            event_end_s=start_s + 2.0,
            observed_actions=[],
            confidence=0.5,
        ),
    )


def test_no_leakage_when_each_video_has_one_split():
    eval_set = EvalSet(
        examples=[
            _fake_example("fake-0001", "fake-video-A", "dev"),
            _fake_example("fake-0002", "fake-video-A", "dev", start_s=20.0),
            _fake_example("fake-0003", "fake-video-B", "test"),
        ]
    )
    assert find_leakage(eval_set) == {}


def test_leakage_detected_when_video_spans_two_splits():
    eval_set = EvalSet(
        examples=[
            _fake_example("fake-0001", "fake-video-A", "dev"),
            _fake_example("fake-0002", "fake-video-A", "test", start_s=20.0),
            _fake_example("fake-0003", "fake-video-B", "test"),
        ]
    )
    offenders = find_leakage(eval_set)
    assert set(offenders) == {"fake-video-A"}
    assert offenders["fake-video-A"] == {"dev", "test"}
