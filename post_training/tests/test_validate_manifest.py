"""Tests for post_training/data/validate_manifest.py.

All examples below are SYNTHETIC/FAKE — no real footage, no real video IDs.
They exist only to exercise the cross-field validation rules.
"""
from __future__ import annotations

from post_training.data.validate_manifest import validate_eval_set, validate_example
from post_training.schemas.eval_example import (
    EvalExample,
    EvalLabels,
    EvalQuery,
    EvalSet,
    EvalWindow,
)

# FAKE: passes every rule — event inside window, reason not needed (relevant),
# language/script set.
FAKE_PASSING_EXAMPLE = EvalExample(
    example_id="fake-pass-0001",
    source_video_id="fake-video-001",
    split_group="dev",
    window=EvalWindow(start_s=0.0, end_s=30.0),
    queries=[EvalQuery(text="fake red car query", language="en", script="Latn")],
    labels=EvalLabels(
        relevant=True,
        event_start_s=5.0,
        event_end_s=10.0,
        observed_actions=["fake car enters frame"],
        confidence=0.9,
    ),
)

# FAKE: event window extends past the labeled window -> WARNING, still a pass.
FAKE_EVENT_OUTSIDE_WINDOW = EvalExample(
    example_id="fake-warn-outside-window",
    source_video_id="fake-video-002",
    split_group="dev",
    window=EvalWindow(start_s=10.0, end_s=20.0),
    queries=[EvalQuery(text="fake event spilling past window", language="en", script="Latn")],
    labels=EvalLabels(
        relevant=True,
        event_start_s=18.0,
        event_end_s=25.0,  # 25 > window.end_s(20) -> warning, not error
        observed_actions=["fake event"],
        confidence=0.5,
    ),
)

# FAKE: relevant=false with no reason -> ERROR.
FAKE_MISSING_REASON = EvalExample(
    example_id="fake-fail-missing-reason",
    source_video_id="fake-video-003",
    split_group="dev",
    window=EvalWindow(start_s=0.0, end_s=10.0),
    queries=[EvalQuery(text="fake negative query", language="en", script="Latn")],
    labels=EvalLabels(
        relevant=False,
        event_start_s=1.0,
        event_end_s=2.0,
        observed_actions=[],
        confidence=0.3,
        reason=None,
    ),
)

# FAKE: relevant=false WITH a reason -> passes.
FAKE_NEGATIVE_WITH_REASON = EvalExample(
    example_id="fake-pass-negative-with-reason",
    source_video_id="fake-video-004",
    split_group="test",
    window=EvalWindow(start_s=0.0, end_s=10.0),
    queries=[EvalQuery(text="fake near-miss query", language="en", script="Latn")],
    labels=EvalLabels(
        relevant=False,
        event_start_s=1.0,
        event_end_s=2.0,
        observed_actions=[],
        confidence=0.3,
        reason="temporal near miss",
    ),
)

# FAKE: blank language on one query -> ERROR.
FAKE_BLANK_LANGUAGE = EvalExample(
    example_id="fake-fail-blank-language",
    source_video_id="fake-video-005",
    split_group="dev",
    window=EvalWindow(start_s=0.0, end_s=10.0),
    queries=[EvalQuery(text="fake query", language="  ", script="Latn")],
    labels=EvalLabels(
        relevant=True,
        event_start_s=1.0,
        event_end_s=2.0,
        observed_actions=[],
        confidence=0.4,
    ),
)


def test_passing_example_has_no_issues():
    issues = validate_example(FAKE_PASSING_EXAMPLE)
    assert issues == []


def test_event_outside_window_is_warning_not_error():
    issues = validate_example(FAKE_EVENT_OUTSIDE_WINDOW)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert "outside window" in issues[0].message


def test_relevant_false_without_reason_is_error():
    issues = validate_example(FAKE_MISSING_REASON)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 1
    assert "reason" in errors[0].message


def test_relevant_false_with_reason_passes():
    issues = validate_example(FAKE_NEGATIVE_WITH_REASON)
    assert issues == []


def test_blank_language_is_error():
    issues = validate_example(FAKE_BLANK_LANGUAGE)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 1
    assert "language" in errors[0].message


def test_validate_eval_set_reports_per_example():
    eval_set = EvalSet(
        examples=[
            FAKE_PASSING_EXAMPLE,
            FAKE_MISSING_REASON,
        ]
    )
    report = validate_eval_set(eval_set)
    assert report[FAKE_PASSING_EXAMPLE.example_id] == []
    assert any(i.severity == "error" for i in report[FAKE_MISSING_REASON.example_id])
