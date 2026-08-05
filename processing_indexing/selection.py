from __future__ import annotations
from dataclasses import dataclass, field
import math
from .config import Settings


@dataclass(frozen=True)
class SelectionInput:
    visual: list[float]
    audio: list[float]
    speech: list[float]
    has_audio: bool
    has_speech: bool


@dataclass
class SelectionDecision:
    index: int
    selected: bool
    reasons: list[str] = field(default_factory=list)
    change_from_previous: dict[str, float | None] = field(default_factory=dict)
    change_from_last_vlm: dict[str, float | None] = field(default_factory=dict)
    change_scores: dict[str, float] = field(default_factory=dict)
    effective_weights: dict[str, float] = field(default_factory=dict)


def cosine_distance(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(v * v for v in left))
    right_norm = math.sqrt(sum(v * v for v in right))
    if left_norm == 0 and right_norm == 0:
        return 0.0
    if left_norm == 0 or right_norm == 0:
        raise ValueError("cosine distance is undefined for one zero vector")
    return max(0.0, min(2.0, 1.0 - dot / (left_norm * right_norm)))


def effective_weights(
    settings: Settings, has_audio: bool, has_speech: bool
) -> dict[str, float]:
    raw = {
        "visual": settings.vlm_change_weight_visual,
        "audio": settings.vlm_change_weight_audio if has_audio else 0.0,
        "speech": settings.vlm_change_weight_speech if has_speech else 0.0,
    }
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("available modality weights must have a positive sum")
    return {name: value / total for name, value in raw.items()}


def _changes(
    current: SelectionInput, reference: SelectionInput
) -> dict[str, float | None]:
    return {
        "visual": cosine_distance(current.visual, reference.visual),
        "audio": cosine_distance(current.audio, reference.audio)
        if current.has_audio and reference.has_audio
        else None,
        "speech": cosine_distance(current.speech, reference.speech)
        if current.has_speech and reference.has_speech
        else None,
    }


def select_vlm_windows(
    inputs: list[SelectionInput], settings: Settings
) -> list[SelectionDecision]:
    if not inputs:
        return []
    if not settings.vlm_selection_enabled:
        return [
            SelectionDecision(
                i,
                True,
                ["selection_disabled"],
                change_scores={
                    "visual": 0.0,
                    "audio": 0.0,
                    "speech": 0.0,
                    "combined": 0.0,
                },
            )
            for i in range(len(inputs))
        ]
    decisions = []
    last_selected = 0
    selected_count = 0
    selection_budget = max(2, math.ceil(len(inputs) * settings.vlm_max_selected_ratio))
    for index, current in enumerate(inputs):
        empty = {name: None for name in ("visual", "audio", "speech")}
        previous = _changes(current, inputs[index - 1]) if index else empty
        since_vlm = _changes(current, inputs[last_selected]) if index else empty.copy()
        scores = {
            name: max(v for v in (previous[name], since_vlm[name]) if v is not None)
            if previous[name] is not None or since_vlm[name] is not None
            else 0.0
            for name in ("visual", "audio", "speech")
        }
        weights = effective_weights(
            settings,
            previous["audio"] is not None or since_vlm["audio"] is not None,
            previous["speech"] is not None or since_vlm["speech"] is not None,
        )
        scores["combined"] = sum(weights[name] * scores[name] for name in weights)
        reasons = []
        if index == 0:
            reasons.append("first_window")
        if index == len(inputs) - 1:
            reasons.append("last_window")
        if index and scores["visual"] >= settings.vlm_visual_change_threshold:
            reasons.append("visual_threshold")
        if index and scores["audio"] >= settings.vlm_audio_change_threshold:
            reasons.append("audio_threshold")
        if index and scores["speech"] >= settings.vlm_speech_change_threshold:
            reasons.append("speech_threshold")
        if index and scores["combined"] >= settings.vlm_combined_change_threshold:
            reasons.append("combined_threshold")
        if index and current.has_speech and not inputs[index - 1].has_speech:
            reasons.append("speech_started")
        if index and not current.has_speech and inputs[index - 1].has_speech:
            reasons.append("speech_ended")
        if index and index - last_selected >= settings.vlm_max_gap_windows:
            reasons.append("max_gap")
        selected = bool(reasons)
        if reasons == ["combined_threshold"] and selected_count >= selection_budget - 1:
            reasons = []
            selected = False
        decisions.append(
            SelectionDecision(
                index, selected, reasons, previous, since_vlm, scores, weights
            )
        )
        if selected:
            last_selected = index
            selected_count += 1
    return decisions


def is_strong_boundary(decision: SelectionDecision, settings: Settings) -> bool:
    return any(
        reason in decision.reasons
        for reason in (
            "visual_threshold",
            "audio_threshold",
            "speech_threshold",
            "combined_threshold",
            "speech_started",
            "speech_ended",
        )
    )
