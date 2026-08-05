"""Unit coverage for real-frame verification and verification-aware ranking.

No video decoder, OpenAI key, Cosmos key, or network call is required here.
Provider boundaries are mocked so these tests lock down our safety contract.
"""
from query_retrieval import api, verification
from query_retrieval.models import (
    SearchResultItem,
    VerificationOptions,
    VerificationResult,
)


def _candidate(**overrides) -> SearchResultItem:
    defaults = {
        "video_id": "video_a",
        "window_id": "video_a_window_0001",
        "start": 10.0,
        "end": 20.0,
        "transcript": "a loud bang is heard",
        "caption": "a person approaches a red car",
        "score": 0.5,
        "matched_modalities": ["visual", "audio"],
        "source_path": "processing_jobs/example/example.mp4",
    }
    defaults.update(overrides)
    return SearchResultItem(**defaults)


def test_openai_frame_verification_refines_relative_time(monkeypatch):
    candidate = _candidate()
    options = VerificationOptions(provider="openai", api_key="test-key", max_frames=4)
    monkeypatch.setattr(
        verification,
        "_sample_frames",
        lambda _candidate, _count: ([10.0, 12.5, 15.0, 17.5], ["frame"] * 4),
    )
    monkeypatch.setattr(
        verification,
        "_openai_vision_verify",
        lambda _prompt, _frames, _options: {
            "match": True,
            "confidence": 0.91,
            "satisfied_conditions": ["person approaches a red car"],
            "missing_conditions": [],
            "contradictions": [],
            "evidence": "frames show the person walking to the red car",
            "event_start_relative": 2.25,
            "event_end_relative": 5.75,
        },
    )

    result = verification.verify_candidate(
        candidate, "person approaches a red car", ["person approaches a red car"], options
    )

    assert result.state == "verified"
    assert result.provider == "openai"
    assert result.event_start_relative == 2.25
    assert result.event_end_relative == 5.75
    assert result.frame_timestamps == [10.0, 12.5, 15.0, 17.5]


def test_partial_vision_match_is_rejected_even_if_provider_says_match(monkeypatch):
    options = VerificationOptions(provider="cosmos", api_key="test-key")
    monkeypatch.setattr(verification, "_sample_frames", lambda *_: ([10.0, 15.0], ["frame", "frame"]))
    monkeypatch.setattr(
        verification,
        "_cosmos_vision_verify",
        lambda *_: {
            "match": True,
            "confidence": 0.95,
            "satisfied_conditions": ["a person is present"],
            "missing_conditions": ["a bag is stolen"],
            "contradictions": [],
            "evidence": "person is visible but no bag action can be established",
            "event_start_relative": None,
            "event_end_relative": None,
        },
    )

    result = verification.verify_candidate(
        _candidate(), "person steals a bag", ["a person is present", "a bag is stolen"], options
    )

    assert result.state == "rejected"
    assert result.match is False
    assert result.reason == "partial match rejected"


def test_vision_provider_failure_never_becomes_a_match(monkeypatch):
    options = VerificationOptions(provider="cosmos", api_key="test-key")
    monkeypatch.setattr(
        verification,
        "_vision_result",
        lambda *_: (_ for _ in ()).throw(TimeoutError("provider timed out")),
    )

    result = verification.verify_candidate(_candidate(), "anything", [], options)

    assert result.state == "verification_unavailable"
    assert result.match is None
    assert "Cosmos" not in result.reason  # no key/value leaks into errors


def test_verification_key_is_excluded_from_model_serialisation():
    options = VerificationOptions(provider="openai", api_key="secret-do-not-return")
    assert "api_key" not in options.model_dump()
    assert "secret-do-not-return" not in repr(options)


def test_verification_defaults_to_seven_candidates_and_temporal_refinement():
    options = VerificationOptions()

    assert options.top_n == 7
    assert options.enable_temporal_localization is True
    assert options.temporal_target_seconds == 5.0


def test_dense_sampler_uses_bounded_time_bins_without_decoding_video(monkeypatch):
    candidate = _candidate(start=100.0, end=120.0)
    observed: list[float] = []

    def _capture(_candidate, timestamps):
        observed.extend(timestamps)
        return timestamps, ["frame"] * len(timestamps)

    monkeypatch.setattr(verification, "_sample_frames_at_timestamps", _capture)

    timestamps, frames = verification._dense_sample_frames(
        candidate, 0.0, 20.0, target_seconds=5.0, max_frames=12
    )

    # Four five-second bins with two ordered samples per bin; this is dense
    # enough for the VLM to choose a short moment while staying bounded.
    assert timestamps == observed
    assert len(timestamps) == len(frames) == 8
    assert timestamps == [101.25, 103.75, 106.25, 108.75, 111.25, 113.75, 116.25, 118.75]


def test_verified_broad_candidate_gets_second_pass_temporal_localisation(monkeypatch):
    candidate = _candidate(start=10.0, end=30.0)
    options = VerificationOptions(provider="openai", api_key="test-key", max_frames=4)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        verification,
        "_sample_frames",
        lambda *_: ([10.0, 15.0, 20.0, 25.0], ["broad"] * 4),
    )
    monkeypatch.setattr(
        verification,
        "_openai_vision_verify",
        lambda *_: {
            "match": True,
            "confidence": 0.88,
            "satisfied_conditions": ["person reaches the car"],
            "missing_conditions": [],
            "contradictions": [],
            "evidence": "the action is somewhere in this broad region",
            "event_start_relative": 0.0,
            "event_end_relative": 20.0,
        },
    )

    def _dense(_candidate, focus_start, focus_end, target_seconds, max_frames):
        calls.append(("dense", (focus_start, focus_end, target_seconds, max_frames)))
        return [12.5, 15.0, 17.5, 20.0], ["dense"] * 4

    def _localize(_prompt, _frames, passed_options):
        calls.append(("provider", passed_options.provider))
        return {
            "match": True,
            "confidence": 0.82,
            "evidence": "the person reaches the car between the middle samples",
            "event_start_relative": 6.0,
            "event_end_relative": 9.5,
        }

    monkeypatch.setattr(verification, "_dense_sample_frames", _dense)
    monkeypatch.setattr(verification, "_temporal_vision_localize", _localize)

    result = verification.verify_candidate(
        candidate, "person reaches the car", ["person reaches the car"], options
    )

    assert result.state == "verified"
    assert result.localization_state == "localized"
    assert result.event_start_relative == 6.0
    assert result.event_end_relative == 9.5
    assert result.localization_frame_timestamps == [12.5, 15.0, 17.5, 20.0]
    assert calls == [
        ("dense", (0.0, 20.0, 5.0, 12)),
        ("provider", "openai"),
    ]


def test_failed_temporal_localisation_keeps_first_pass_verified_result(monkeypatch):
    candidate = _candidate(start=10.0, end=30.0)
    options = VerificationOptions(provider="cosmos", api_key="test-key")
    monkeypatch.setattr(verification, "_sample_frames", lambda *_: ([10.0, 20.0], ["frame", "frame"]))
    monkeypatch.setattr(
        verification,
        "_cosmos_vision_verify",
        lambda *_: {
            "match": True,
            "confidence": 0.9,
            "satisfied_conditions": [],
            "missing_conditions": [],
            "contradictions": [],
            "evidence": "broad match",
            "event_start_relative": 0.0,
            "event_end_relative": 20.0,
        },
    )
    monkeypatch.setattr(
        verification,
        "_dense_sample_frames",
        lambda *_: ([12.5, 17.5, 22.5, 27.5], ["dense"] * 4),
    )
    monkeypatch.setattr(
        verification,
        "_temporal_vision_localize",
        lambda *_: {
            "match": True,
            "confidence": 0.8,
            "evidence": "over-wide response",
            "event_start_relative": 0.0,
            "event_end_relative": 12.0,
        },
    )

    result = verification.verify_candidate(candidate, "anything", [], options)

    assert result.state == "verified"
    assert result.localization_state == "localization_unavailable"
    assert "bounded localisation contract" in result.localization_reason
    assert result.event_start_relative == 0.0
    assert result.event_end_relative == 20.0


def test_verified_candidates_rerank_and_refine_absolute_time(monkeypatch):
    high_retrieval = _candidate(window_id="high", score=0.9, start=0.0, end=10.0)
    verified = _candidate(window_id="verified", score=0.5, start=30.0, end=40.0)
    options = VerificationOptions(provider="openai", api_key="test-key", top_n=2)

    def _verdict(candidate, *_args):
        if candidate.window_id == "high":
            return VerificationResult(
                candidate_id="high", state="rejected", match=False, confidence=0.99
            )
        return VerificationResult(
            candidate_id="verified",
            state="verified",
            match=True,
            confidence=0.8,
            event_start_relative=1.5,
            event_end_relative=4.5,
        )

    monkeypatch.setattr(api, "verify_candidate", _verdict)
    ranked = api._apply_verification_and_rerank(
        [high_retrieval, verified], "test", ["condition"], options
    )

    assert [item.window_id for item in ranked] == ["verified", "high"]
    refined = ranked[0]
    assert refined.refined_start == 31.5
    assert refined.refined_end == 34.5
    assert refined.final_score is not None


def test_zero_weight_modalities_are_not_searched():
    vectors = {modality: [0.0] for modality in ("visual", "audio", "speech", "caption")}
    assert api._eligible_modalities(
        vectors, {"visual": 0.7, "audio": 0.0, "speech": 0.0, "caption": 0.3}
    ) == ["visual", "caption"]
