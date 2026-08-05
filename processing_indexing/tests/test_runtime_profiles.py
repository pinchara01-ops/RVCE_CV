from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from processing_indexing.runtime_profiles import (
    API_GEMINI_FREE_V1,
    SELF_HOSTED_V1,
    ProviderConfigurationError,
    RuntimeProfileError,
    list_profiles_public,
    qdrant_preflight,
    redact_secrets,
    validate_runtime_setup,
)
from processing_indexing.runtime_sessions import (
    RuntimeSessionNotFoundError,
    RuntimeSessionStore,
    parse_session_payload,
)


def _api_setup(**configuration_overrides):
    configuration = {
        "qdrant_url": "https://test-cluster.cloud.qdrant.io",
        "consent_cloud_video": True,
        **configuration_overrides,
    }
    return validate_runtime_setup(
        "api-gemini-free-v1",
        configuration,
        {"gemini_api_key": "gemini-secret", "qdrant_api_key": "qdrant-secret"},
    )


def test_profiles_keep_incompatible_vector_schemas_in_separate_collections():
    assert SELF_HOSTED_V1.collection_name == "video_windows"
    assert API_GEMINI_FREE_V1.collection_name == "video_windows_api_gemini_free_v1"
    assert SELF_HOSTED_V1.vector_schema == {
        "visual": {"name": "visual", "dimensions": 512, "distance": "Cosine"},
        "audio": {"name": "audio", "dimensions": 512, "distance": "Cosine"},
        "speech": {"name": "speech", "dimensions": 1024, "distance": "Cosine"},
        "caption": {"name": "caption", "dimensions": 1024, "distance": "Cosine"},
    }
    assert set(API_GEMINI_FREE_V1.vector_schema) == {
        "visual",
        "audio",
        "transcript",
        "caption",
    }
    assert {
        item["dimensions"] for item in API_GEMINI_FREE_V1.vector_schema.values()
    } == {1536}
    api_profile = next(
        item for item in list_profiles_public() if item["id"] == API_GEMINI_FREE_V1.id
    )
    assert api_profile["free_default"] is True
    assert api_profile["mode"] == "api-based"
    assert api_profile["execution_mode"] == "api_based"
    assert "Free tier" in api_profile["provider_options"]["caption"][0]["cost_label"]


def test_api_profile_requires_explicit_consent_qdrant_cloud_and_required_keys():
    with pytest.raises(RuntimeProfileError, match="consent_cloud_video"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            {"qdrant_url": "https://demo.cloud.qdrant.io"},
            {"gemini_api_key": "g", "qdrant_api_key": "q"},
        )
    with pytest.raises(RuntimeProfileError, match="Qdrant Cloud URL"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            {"qdrant_url": "http://localhost:6333", "consent_cloud_video": True},
            {"gemini_api_key": "g", "qdrant_api_key": "q"},
        )
    with pytest.raises(ProviderConfigurationError, match="qdrant_api_key"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            {"qdrant_url": "https://demo.cloud.qdrant.io", "consent_cloud_video": True},
            {"gemini_api_key": "g"},
        )


def test_api_profile_can_use_local_qdrant_without_a_qdrant_cloud_key():
    setup = validate_runtime_setup(
        "api-gemini-free-v1",
        {
            "vector_store_target": "local",
            "qdrant_url": "http://127.0.0.1:6333",
            "consent_cloud_video": True,
        },
        {"gemini_api_key": "gemini-secret"},
    )

    assert setup.configuration["vector_store_target"] == "local"
    assert setup.configuration["qdrant_url"] == "http://127.0.0.1:6333"
    assert "qdrant_api_key" not in setup.credentials

    with pytest.raises(RuntimeProfileError, match="does not use a Qdrant Cloud API key"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            {
                "vector_store_target": "local",
                "qdrant_url": "http://127.0.0.1:6333",
                "consent_cloud_video": True,
            },
            {"gemini_api_key": "g", "qdrant_api_key": "should-not-be-used"},
        )


def test_qdrant_cloud_url_rejects_userinfo_before_a_session_can_be_public():
    with pytest.raises(RuntimeProfileError, match="must not include credentials"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            {
                "qdrant_url": "https://embedded-user:embedded-password@demo.cloud.qdrant.io",
                "consent_cloud_video": True,
            },
            {"gemini_api_key": "gemini-secret", "qdrant_api_key": "qdrant-secret"},
        )

    session = RuntimeSessionStore().create(
        "api-gemini-free-v1",
        {
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "consent_cloud_video": True,
        },
        {"gemini_api_key": "gemini-secret", "qdrant_api_key": "qdrant-secret"},
    )
    public_payload = json.dumps(session.public())
    assert "embedded-user" not in public_payload
    assert "embedded-password" not in public_payload
    assert "gemini-secret" not in public_payload
    assert "qdrant-secret" not in public_payload


def test_advanced_provider_requires_only_its_corresponding_paid_key():
    config = {
        "qdrant_url": "https://demo.cloud.qdrant.io",
        "consent_cloud_video": True,
        "providers": {"caption": "cosmos", "verification": "openai"},
    }
    with pytest.raises(ProviderConfigurationError, match="nvidia_api_key, openai_api_key"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            config,
            {"gemini_api_key": "g", "qdrant_api_key": "q"},
        )
    setup = validate_runtime_setup(
        "api-gemini-free-v1",
        config,
        {
            "gemini_api_key": "g",
            "qdrant_api_key": "q",
            "nvidia_api_key": "n",
            "openai_api_key": "o",
        },
    )
    assert setup.configuration["providers"]["caption"] == "cosmos"
    assert setup.configuration["providers"]["verification"] == "openai"


def test_models_are_strictly_bound_to_supported_providers_and_decomposition_alias():
    with pytest.raises(ProviderConfigurationError, match="unavailable"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            {
                "qdrant_url": "https://demo.cloud.qdrant.io",
                "consent_cloud_video": True,
                "providers": {"decomposition": "openai"},
                "models": {"decomposition": "gpt-4.1-mini"},
            },
            {
                "gemini_api_key": "g",
                "qdrant_api_key": "q",
                "openai_api_key": "o",
            },
        )
    with pytest.raises(ProviderConfigurationError, match="must be 'gemini-embedding-2'"):
        validate_runtime_setup(
            "api-gemini-free-v1",
            {
                "qdrant_url": "https://demo.cloud.qdrant.io",
                "consent_cloud_video": True,
                "models": {"media_embedding": "not-an-allowed-model"},
            },
            {"gemini_api_key": "g", "qdrant_api_key": "q"},
        )


def test_api_profile_allows_optional_local_qwen_reranker_without_a_cloud_key():
    setup = validate_runtime_setup(
        "api-gemini-free-v1",
        {
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "consent_cloud_video": True,
            "providers": {"reranker": "local_qwen"},
            "models": {"reranker": "Qwen/Qwen3-VL-Reranker-2B"},
        },
        {"gemini_api_key": "g", "qdrant_api_key": "q"},
    )
    assert setup.configuration["providers"]["reranker"] == "local_qwen"
    assert setup.configuration["models"]["reranker"] == "Qwen/Qwen3-VL-Reranker-2B"
    public = next(
        item for item in list_profiles_public() if item["id"] == "api-gemini-free-v1"
    )
    assert {choice["provider"] for choice in public["provider_options"]["reranker"]} == {
        "none",
        "local_qwen",
    }


def test_self_hosted_profile_remains_local_and_rejects_cloud_key_leaks():
    setup = validate_runtime_setup("self-hosted-v1")
    assert setup.configuration["qdrant_url"] == "http://localhost:6333"
    assert setup.configuration["providers"]["media_embedding"] == "local"
    with pytest.raises(RuntimeProfileError, match="does not accept cloud API credentials"):
        validate_runtime_setup("self-hosted-v1", credentials={"gemini_api_key": "g"})
    with pytest.raises(ProviderConfigurationError, match="unavailable"):
        validate_runtime_setup(
            "self-hosted-v1", {"providers": {"caption": "gemini"}}
        )


def test_session_keeps_keys_in_memory_only_and_public_payload_is_redacted():
    store = RuntimeSessionStore()
    session = store.create(
        "api-gemini-free-v1",
        {
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "consent_cloud_video": True,
        },
        {"gemini_api_key": "gemini-secret", "qdrant_api_key": "qdrant-secret"},
    )
    public = session.public()
    encoded = json.dumps(public)
    assert session.id != "gemini-secret"
    assert "gemini-secret" not in encoded and "qdrant-secret" not in encoded
    assert public["credentials"]["gemini_api_key"] is True
    assert session.runtime_config()["gemini_api_key"] == "gemini-secret"
    assert session.redacted_runtime_config()["gemini_api_key"] == "[REDACTED]"
    store.close(session.id)
    with pytest.raises(RuntimeSessionNotFoundError):
        store.get(session.id)


def test_session_drops_an_unselected_advanced_key_on_update():
    store = RuntimeSessionStore()
    session = store.create(
        "api-gemini-free-v1",
        {
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "consent_cloud_video": True,
            "providers": {"caption": "openai"},
            "models": {"caption": "gpt-4.1-mini"},
        },
        {
            "gemini_api_key": "gemini-secret",
            "qdrant_api_key": "qdrant-secret",
            "openai_api_key": "openai-secret",
        },
    )
    assert session.public()["credentials"]["openai_api_key"] is True

    # Sessions merge submitted fields.  Even though the old OpenAI value is
    # present during validation, switching the stage back to Gemini must drop
    # an unneeded secret rather than retaining it for the rest of the TTL.
    updated = store.update(
        session.id,
        configuration={
            "providers": {"caption": "gemini"},
            "models": {"caption": "gemini-3.5-flash-lite"},
        },
    )

    assert updated.public()["credentials"]["openai_api_key"] is False
    assert "openai_api_key" not in updated.runtime_config()


def test_session_expires_and_parsers_accept_flat_or_nested_payloads(monkeypatch):
    store = RuntimeSessionStore(ttl=timedelta(microseconds=1))
    session = store.create("self-hosted-v1")
    import processing_indexing.runtime_sessions as sessions_module

    original_now = sessions_module._utcnow
    monkeypatch.setattr(
        sessions_module, "_utcnow", lambda: original_now() + timedelta(seconds=1)
    )
    with pytest.raises(RuntimeSessionNotFoundError):
        store.get(session.id)

    profile_id, config, credentials = parse_session_payload(
        {
            "profile_id": "api-gemini-free-v1",
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "gemini_api_key": "g",
            "credentials": {"qdrant_api_key": "q"},
            "models": {"decomposition": "gemini-3.5-flash-lite"},
        }
    )
    assert profile_id == "api-gemini-free-v1"
    assert config["qdrant_url"].startswith("https://")
    assert credentials == {"gemini_api_key": "g", "qdrant_api_key": "q"}
    assert config["models"]["decomposition"] == "gemini-3.5-flash-lite"


def test_redaction_removes_nested_secret_names_and_literal_values():
    value = redact_secrets(
        {
            "qdrant_api_key": "qdrant-secret",
            "nested": {"authorization": "Bearer gemini-secret"},
            "error": "failed with qdrant-secret",
        },
        ("qdrant-secret", "gemini-secret"),
    )
    encoded = json.dumps(value)
    assert "qdrant-secret" not in encoded
    assert "gemini-secret" not in encoded
    assert value["qdrant_api_key"] == "[REDACTED]"


def test_qdrant_preflight_succeeds_when_collection_is_absent_without_mutation():
    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def collection_exists(self, name):
            assert name == API_GEMINI_FREE_V1.collection_name
            return False

    result = qdrant_preflight(_api_setup(), client_factory=Client)
    assert result["reachable"] is True
    assert result["collection_exists"] is False
    assert result["schema_valid"] is True
    assert "created by the first index run" in result["warning"]
    assert calls[0]["api_key"] == "qdrant-secret"


def test_api_local_qdrant_preflight_does_not_send_a_cloud_key():
    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def collection_exists(self, _name):
            return False

    setup = validate_runtime_setup(
        "api-gemini-free-v1",
        {
            "vector_store_target": "local",
            "qdrant_url": "http://127.0.0.1:6333",
            "consent_cloud_video": True,
        },
        {"gemini_api_key": "gemini-secret"},
    )
    result = qdrant_preflight(setup, client_factory=Client)

    assert result["reachable"] is True
    assert result["vector_store_target"] == "local"
    assert result["diagnostics"][-2]["stage"] == "local_qdrant_connection"
    assert calls[0]["api_key"] is None


def test_qdrant_preflight_reports_schema_mismatch_and_redacts_connection_error():
    class BadClient:
        def __init__(self, **kwargs):
            pass

        def collection_exists(self, _name):
            return True

        def get_collection(self, _name):
            vectors = {
                "visual": SimpleNamespace(size=512, distance="Cosine"),
                "audio": SimpleNamespace(size=1536, distance="Cosine"),
                "transcript": SimpleNamespace(size=1536, distance="Cosine"),
                "caption": SimpleNamespace(size=1536, distance="Cosine"),
            }
            return SimpleNamespace(
                points_count=4,
                config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)),
            )

    mismatch = qdrant_preflight(_api_setup(), client_factory=BadClient)
    assert mismatch["reachable"] is True
    assert mismatch["schema_valid"] is False
    assert "visual dimension" in mismatch["schema_errors"][0]

    class BrokenClient:
        def __init__(self, **kwargs):
            raise ConnectionError("authorization=qdrant-secret")

    failed = qdrant_preflight(_api_setup(), client_factory=BrokenClient)
    assert failed["reachable"] is False
    assert "qdrant-secret" not in failed["error"]


def test_qdrant_preflight_exposes_a_safe_timeout_diagnostic():
    class TimedOutClient:
        def __init__(self, **kwargs):
            pass

        def collection_exists(self, _name):
            raise TimeoutError("timed out while using qdrant-secret")

    result = qdrant_preflight(_api_setup(), client_factory=TimedOutClient)

    assert result["reachable"] is False
    assert result["error_type"] == "TimeoutError"
    assert result["diagnostics"][-1]["stage"] == "qdrant_cloud_connection"
    assert result["diagnostics"][-1]["status"] == "failed"
    assert "timed out" in result["diagnostics"][-1]["message"]
    assert "network" in result["diagnostics"][-1]["next_action"].lower()
    assert "qdrant-secret" not in json.dumps(result)


def test_runtime_endpoints_never_return_flat_or_nested_key_values(monkeypatch):
    pytest.importorskip("qdrant_client")
    from processing_indexing import debug_api

    store = RuntimeSessionStore()
    monkeypatch.setattr(debug_api, "runtime_sessions", store)
    client = TestClient(debug_api.app)
    profiles = client.get("/api/runtime/profiles")
    assert profiles.status_code == 200
    assert {profile["id"] for profile in profiles.json()["profiles"]} == {
        "self-hosted-v1",
        "api-gemini-free-v1",
    }
    response = client.post(
        "/api/runtime/session",
        json={
            "profile_id": "api-gemini-free-v1",
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "gemini_api_key": "gemini-secret",
            "credentials": {"qdrant_api_key": "qdrant-secret"},
            "consent_cloud_video": True,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert "gemini-secret" not in json.dumps(payload)
    assert "qdrant-secret" not in json.dumps(payload)
    assert payload["credentials"]["qdrant_api_key"] is True
    invalid = client.post(
        "/api/runtime/session",
        json={
            "profile_id": "api-gemini-free-v1",
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "gemini_api_key": "do-not-leak-me",
            "consent_cloud_video": True,
        },
    )
    assert invalid.status_code == 400
    assert "do-not-leak-me" not in invalid.text


def test_api_job_configuration_is_allowlisted_and_never_reflects_cloud_values(monkeypatch):
    pytest.importorskip("qdrant_client")
    from processing_indexing import debug_api

    store = RuntimeSessionStore()
    monkeypatch.setattr(debug_api, "runtime_sessions", store)
    captured: dict[str, object] = {}

    def fake_create(filename, data, configuration):
        captured["filename"] = filename
        captured["data"] = data
        captured["configuration"] = dict(configuration)
        return SimpleNamespace(public=lambda: {"configuration": dict(configuration)})

    monkeypatch.setattr(debug_api.manager, "create", fake_create)
    client = TestClient(debug_api.app)
    session_response = client.post(
        "/api/runtime/session",
        json={
            "profile_id": "api-gemini-free-v1",
            "qdrant_url": "https://demo.cloud.qdrant.io",
            "gemini_api_key": "gemini-session-secret",
            "qdrant_api_key": "qdrant-session-secret",
            "consent_cloud_video": True,
        },
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["session_id"]
    base = {
        "profile_id": "api-gemini-free-v1",
        "runtime_session_id": session_id,
        "window_seconds": 20,
        "stride_seconds": 10,
        "max_windows": 0,
        "index_qdrant": True,
    }

    accepted = client.post(
        "/api/processing/jobs",
        files={"video": ("clip.mp4", b"placeholder", "video/mp4")},
        data={"configuration": json.dumps(base)},
    )
    assert accepted.status_code == 201
    assert captured["configuration"] == base
    assert "qdrant_url" not in accepted.text
    assert "gemini-session-secret" not in accepted.text
    assert "qdrant-session-secret" not in accepted.text

    malicious = {
        **base,
        "qdrant_url": "https://embedded-user:embedded-password@demo.cloud.qdrant.io",
        "providers": {"caption": "submitted-provider-secret"},
    }
    rejected = client.post(
        "/api/processing/jobs",
        files={"video": ("clip.mp4", b"placeholder", "video/mp4")},
        data={"configuration": json.dumps(malicious)},
    )
    assert rejected.status_code == 400
    assert "embedded-user" not in rejected.text
    assert "embedded-password" not in rejected.text
    assert "submitted-provider-secret" not in rejected.text

    malformed_tuning = {
        **base,
        "window_seconds": {"api_key": "nested-config-secret"},
    }
    malformed = client.post(
        "/api/processing/jobs",
        files={"video": ("clip.mp4", b"placeholder", "video/mp4")},
        data={"configuration": json.dumps(malformed_tuning)},
    )
    assert malformed.status_code == 400
    assert "nested-config-secret" not in malformed.text


def test_query_validation_does_not_reflect_an_invalid_api_key():
    pytest.importorskip("qdrant_client")
    from processing_indexing import debug_api

    client = TestClient(debug_api.app)
    secret = "do-not-reflect-" + "x" * 5_000
    response = client.post(
        "/api/query/search",
        json={
            "query": "find a red car",
            "verification": {"api_key": secret},
        },
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["detail"][0]["input"] == "[REDACTED]"
