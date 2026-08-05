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
