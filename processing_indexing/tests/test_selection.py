import math
import pytest

from processing_indexing.config import Settings
from processing_indexing.selection import (
    SelectionInput,
    effective_weights,
    select_vlm_windows,
)


def unit(angle=0.0, size=512):
    values = [0.0] * size
    values[0], values[1] = math.cos(angle), math.sin(angle)
    return values


def entry(visual=0.0, audio=0.0, speech=0.0, has_audio=True, has_speech=True):
    return SelectionInput(
        unit(visual), unit(audio), unit(speech, 1024), has_audio, has_speech
    )


def reasons(inputs, settings=Settings()):
    return [decision.reasons for decision in select_vlm_windows(inputs, settings)]


def test_first_and_last_are_always_selected():
    decisions = select_vlm_windows([entry()] * 4, Settings(vlm_max_gap_windows=10))
    assert decisions[0].reasons == ["first_window"]
    assert decisions[-1].reasons == ["last_window"]


@pytest.mark.parametrize(
    "changed,reason",
    [
        (entry(visual=1.0), "visual_threshold"),
        (entry(audio=1.0), "audio_threshold"),
        (entry(speech=1.0), "speech_threshold"),
    ],
)
def test_individual_modality_hard_triggers(changed, reason):
    assert (
        reason
        in reasons([entry(), changed], Settings(vlm_combined_change_threshold=2))[1]
    )


def test_strong_individual_change_survives_low_weight():
    settings = Settings(
        vlm_change_weight_visual=0.001,
        vlm_change_weight_audio=0.999,
        vlm_change_weight_speech=0,
        vlm_combined_change_threshold=2,
    )
    assert "visual_threshold" in reasons([entry(), entry(visual=1)], settings)[1]


def test_speech_start_and_end_trigger_without_sentinel_distance():
    inputs = [entry(has_speech=False), entry(has_speech=True), entry(has_speech=False)]
    decisions = select_vlm_windows(inputs, Settings(vlm_max_gap_windows=10))
    assert "speech_started" in decisions[1].reasons
    assert "speech_ended" in decisions[2].reasons
    assert decisions[1].change_from_previous["speech"] is None
    assert decisions[1].effective_weights["speech"] == 0


def test_combined_weighted_trigger():
    settings = Settings(
        vlm_visual_change_threshold=2,
        vlm_audio_change_threshold=2,
        vlm_speech_change_threshold=2,
        vlm_combined_change_threshold=0.05,
    )
    assert (
        "combined_threshold"
        in reasons([entry(), entry(visual=0.5, audio=0.5, speech=0.5)], settings)[1]
    )


def test_weights_normalize_across_available_modalities():
    weights = effective_weights(Settings(), has_audio=False, has_speech=True)
    assert weights["audio"] == 0
    assert weights["visual"] + weights["speech"] == pytest.approx(1)
    weights = effective_weights(Settings(), has_audio=True, has_speech=False)
    assert weights["speech"] == 0 and sum(weights.values()) == pytest.approx(1)


def test_periodic_max_gap_refresh():
    decisions = select_vlm_windows([entry()] * 8, Settings(vlm_max_gap_windows=3))
    assert [d.index for d in decisions if "max_gap" in d.reasons] == [3, 6]


def test_three_window_gap_is_three_strides_or_fifteen_seconds_by_default():
    decisions = select_vlm_windows([entry()] * 7, Settings(vlm_max_gap_windows=3))
    selected_starts = [
        decision.index * 5 for decision in decisions if decision.selected
    ]
    assert selected_starts[:3] == [0, 15, 30]


def test_last_vlm_comparison_detects_gradual_change():
    settings = Settings(
        vlm_visual_change_threshold=0.12,
        vlm_audio_change_threshold=2,
        vlm_speech_change_threshold=2,
        vlm_combined_change_threshold=2,
        vlm_max_gap_windows=10,
    )
    inputs = [
        entry(visual=angle, has_audio=False, has_speech=False)
        for angle in (0, 0.2, 0.4, 0.6)
    ]
    decisions = select_vlm_windows(inputs, settings)
    assert decisions[2].change_from_previous["visual"] < 0.12
    assert decisions[2].change_from_last_vlm["visual"] < 0.12
    assert "visual_threshold" in decisions[3].reasons


def test_previous_and_last_vlm_changes_are_both_preserved():
    decisions = select_vlm_windows(
        [entry(visual=0), entry(visual=0.2), entry(visual=0.5)],
        Settings(vlm_max_gap_windows=10),
    )
    assert (
        decisions[2].change_from_previous["visual"]
        != decisions[2].change_from_last_vlm["visual"]
    )


def test_selection_is_deterministic_and_ratio_caps_combined_only_candidates():
    settings = Settings(
        vlm_visual_change_threshold=2,
        vlm_audio_change_threshold=2,
        vlm_speech_change_threshold=2,
        vlm_combined_change_threshold=0.001,
        vlm_max_gap_windows=99,
        vlm_max_selected_ratio=0.5,
    )
    inputs = [entry(visual=i * 0.1, audio=i * 0.1, speech=i * 0.1) for i in range(6)]
    first = select_vlm_windows(inputs, settings)
    second = select_vlm_windows(inputs, settings)
    assert [(d.selected, d.reasons) for d in first] == [
        (d.selected, d.reasons) for d in second
    ]
    assert sum(d.selected for d in first) <= 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"vlm_change_weight_visual": -1},
        {"vlm_max_gap_windows": 0},
        {"vlm_max_selected_ratio": 1.1},
        {"vlm_visual_change_threshold": 2.1},
    ],
)
def test_invalid_selection_configuration(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
