"""Runtime-profile contracts for local and API-based processing.

The existing processing pipeline has a fixed local vector schema.  API-based
runs need a different schema (four Gemini 1536-D vectors), and putting both
schemas in one Qdrant collection would silently corrupt search.  This module
is the small, dependency-free source of truth for those contracts.

It deliberately contains *no* application credentials and does not contact
external services.  ``runtime_sessions`` owns credentials, while this module
only validates the public configuration that says which providers will be
used.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from types import MappingProxyType
from typing import Any, Sequence
from urllib.parse import urlparse

REDACTED = "[REDACTED]"


class RuntimeProfileError(ValueError):
    """Raised when a requested runtime profile or its setup is invalid."""


class ProviderConfigurationError(RuntimeProfileError):
    """Raised when selected stage providers cannot run with the supplied keys."""


@dataclass(frozen=True)
class VectorField:
    """One named Qdrant vector and its immutable compatibility contract."""

    name: str
    dimensions: int
    distance: str = "Cosine"

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("Vector names must contain letters, digits, or underscores")
        if self.dimensions < 1:
            raise ValueError("Vector dimensions must be positive")
        if self.distance.lower() != "cosine":
            raise ValueError("This application currently requires cosine vector distance")

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dimensions": self.dimensions,
            "distance": self.distance,
        }


@dataclass(frozen=True)
class ProviderOption:
    """A selectable provider/model pair for one runtime stage."""

    provider: str
    model: str
    label: str
    credential_name: str | None = None
    cost_label: str = "Included in this profile"

    def public(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "label": self.label,
            "credential_required": self.credential_name is not None,
            "cost_label": self.cost_label,
        }


_SELF_HOSTED_STAGE_OPTIONS = MappingProxyType(
    {
        "transcription": (
            ProviderOption("local", "faster-whisper-small", "Local Whisper"),
        ),
        "media_embedding": (
            ProviderOption("local", "xclip-base-patch32 + clap-htsat-unfused", "Local X-CLIP + CLAP"),
        ),
        "text_embedding": (
            ProviderOption("local", "BAAI/bge-m3", "Local BGE-M3"),
        ),
        "caption": (
            ProviderOption("none", "selection_only", "Selection only (no caption VLM)"),
            ProviderOption(
                "local_qwen",
                "Qwen/Qwen2.5-VL-3B-Instruct",
                "Local Qwen2.5-VL-3B captioner (on-demand, laptop default)",
                cost_label="Local GPU or CPU, model download on first use; CUDA recommended",
            ),
        ),
        "verification": (
            ProviderOption("none", "disabled", "Disabled (evidence is optional at search time)"),
        ),
        "query_decomposition": (
            ProviderOption("local", "local query model", "Local query model"),
        ),
        "reranker": (
            ProviderOption("none", "disabled", "Disabled (RRF recall only)"),
            ProviderOption(
                "local_qwen",
                "Qwen/Qwen3-VL-Reranker-2B",
                "Qwen3-VL-Reranker-2B (local, on-demand)",
                cost_label="Local GPU or CPU, model download on first use",
            ),
        ),
    }
)

_API_GEMINI_STAGE_OPTIONS = MappingProxyType(
    {
        "transcription": (
            ProviderOption(
                "gemini",
                "gemini-3.5-flash-lite",
                "Gemini 3.5 Flash-Lite",
                "gemini_api_key",
                "Free tier default (subject to quota)",
            ),
        ),
        "media_embedding": (
            ProviderOption(
                "gemini",
                "gemini-embedding-2",
                "Gemini Embedding 2",
                "gemini_api_key",
                "Free tier default (subject to quota)",
            ),
        ),
        "text_embedding": (
            ProviderOption(
                "gemini",
                "gemini-embedding-2",
                "Gemini Embedding 2",
                "gemini_api_key",
                "Free tier default (subject to quota)",
            ),
        ),
        "caption": (
            ProviderOption(
                "gemini",
                "gemini-3.5-flash-lite",
                "Gemini 3.5 Flash-Lite",
                "gemini_api_key",
                "Free tier default (subject to quota)",
            ),
            ProviderOption(
                "openai",
                "gpt-4.1-mini",
                "OpenAI GPT-4.1 mini",
                "openai_api_key",
                "Paid / API credits required",
            ),
            ProviderOption(
                "cosmos",
                "nvidia/cosmos3-nano-reasoner",
                "NVIDIA Cosmos Reasoner",
                "nvidia_api_key",
                "Paid / NVIDIA API credits required",
            ),
        ),
        "verification": (
            ProviderOption(
                "gemini",
                "gemini-3.5-flash-lite",
                "Gemini 3.5 Flash-Lite",
                "gemini_api_key",
                "Free tier default (subject to quota)",
            ),
            ProviderOption(
                "openai",
                "gpt-4.1-mini",
                "OpenAI GPT-4.1 mini",
                "openai_api_key",
                "Paid / API credits required",
            ),
            ProviderOption(
                "cosmos",
                "nvidia/cosmos3-nano-reasoner",
                "NVIDIA Cosmos Reasoner",
                "nvidia_api_key",
                "Paid / NVIDIA API credits required",
            ),
        ),
        "query_decomposition": (
            ProviderOption(
                "gemini",
                "gemini-3.5-flash-lite",
                "Gemini 3.5 Flash-Lite",
                "gemini_api_key",
                "Gemini API tier",
            ),
        ),
        # This is deliberately a local model even in an API-based index: Qwen
        # does not have a free hosted reranker endpoint here.  It is optional
        # and runs only on the bounded RRF candidate set, never the library.
        "reranker": (
            ProviderOption("none", "disabled", "Disabled (RRF recall only)"),
            ProviderOption(
                "local_qwen",
                "Qwen/Qwen3-VL-Reranker-2B",
                "Qwen3-VL-Reranker-2B (local, on-demand)",
                cost_label="Local GPU or CPU, model download on first use",
            ),
        ),
    }
)


@dataclass(frozen=True)
class RuntimeProfile:
    """The complete, immutable vector and provider contract for one run mode."""

    id: str
    label: str
    mode: str
    description: str
    collection_name: str
    vectors: tuple[VectorField, ...]
    defaults: Mapping[str, Any]
    stage_options: Mapping[str, tuple[ProviderOption, ...]]
    qdrant_target: str
    requires_cloud_consent: bool = False
    free_default: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"self_hosted", "api_based"}:
            raise ValueError("Runtime profile mode must be self_hosted or api_based")
        if self.qdrant_target not in {"local", "cloud"}:
            raise ValueError("Runtime profile Qdrant target must be local or cloud")
        names = [item.name for item in self.vectors]
        if len(names) != len(set(names)):
            raise ValueError("Runtime profile vector names must be unique")
        if not self.collection_name.replace("_", "").isalnum():
            raise ValueError("Collection name must contain letters, digits, or underscores")

    @property
    def vector_schema(self) -> dict[str, dict[str, Any]]:
        return {item.name: item.public() for item in self.vectors}

    def option_for(self, stage: str, provider: str) -> ProviderOption:
        for option in self.stage_options.get(stage, ()):
            if option.provider == provider:
                return option
        valid = [option.provider for option in self.stage_options.get(stage, ())]
        if not valid:
            raise ProviderConfigurationError(f"Unknown provider stage '{stage}'")
        raise ProviderConfigurationError(
            f"Provider '{provider}' is unavailable for {stage}; choose one of {', '.join(valid)}"
        )

    def public(self) -> dict[str, Any]:
        defaults = _public_copy(self.defaults)
        defaults["models"] = {
            stage: self.option_for(stage, provider).model
            for stage, provider in defaults["providers"].items()
        }
        return {
            "id": self.id,
            "label": self.label,
            # The hyphenated values match the wording shown in the UI.  Keep
            # the underscore form separately for backend integration code.
            "mode": self.mode.replace("_", "-"),
            "execution_mode": self.mode,
            "description": self.description,
            "collection_name": self.collection_name,
            "vector_schema": self.vector_schema,
            "defaults": defaults,
            "provider_options": {
                stage: [option.public() for option in options]
                for stage, options in self.stage_options.items()
            },
            "qdrant_target": self.qdrant_target,
            "requires_cloud_consent": self.requires_cloud_consent,
            "free_default": self.free_default,
            "stage_aliases": dict(_STAGE_ALIASES),
        }


SELF_HOSTED_V1 = RuntimeProfile(
    id="self-hosted-v1",
    label="Self-hosted",
    mode="self_hosted",
    description="Existing local CPU models with a local Qdrant instance.",
    collection_name="video_windows",
    vectors=(
        VectorField("visual", 512),
        VectorField("audio", 512),
        VectorField("speech", 1024),
        VectorField("caption", 1024),
    ),
    defaults=MappingProxyType(
        {
            "window_seconds": 10.0,
            "stride_seconds": 5.0,
            "qdrant_url": "http://localhost:6333",
            "providers": {
                "transcription": "local",
                "media_embedding": "local",
                "text_embedding": "local",
                "caption": "none",
                "verification": "none",
                "query_decomposition": "local",
                # Keep the expensive local cross-encoder opt-in. Selecting a
                # self-hosted profile alone must not download or allocate a
                # Qwen model on the next search.
                "reranker": "none",
            },
        }
    ),
    stage_options=_SELF_HOSTED_STAGE_OPTIONS,
    qdrant_target="local",
)

API_GEMINI_FREE_V1 = RuntimeProfile(
    id="api-gemini-free-v1",
    label="API-based (Gemini free default)",
    mode="api_based",
    description=(
        "Managed Qdrant Cloud with Gemini Embedding 2 and Gemini Flash-Lite. "
        "Video is sent to the selected API providers."
    ),
    collection_name="video_windows_api_gemini_free_v1",
    vectors=(
        VectorField("visual", 1536),
        VectorField("audio", 1536),
        VectorField("transcript", 1536),
        VectorField("caption", 1536),
    ),
    defaults=MappingProxyType(
        {
            "window_seconds": 20.0,
            "stride_seconds": 10.0,
            "providers": {
                "transcription": "gemini",
                "media_embedding": "gemini",
                "text_embedding": "gemini",
                "caption": "gemini",
                "verification": "gemini",
                "query_decomposition": "gemini",
                "reranker": "none",
            },
        }
    ),
    stage_options=_API_GEMINI_STAGE_OPTIONS,
    qdrant_target="cloud",
    requires_cloud_consent=True,
)


_PROFILES = MappingProxyType(
    {
        SELF_HOSTED_V1.id: SELF_HOSTED_V1,
        API_GEMINI_FREE_V1.id: API_GEMINI_FREE_V1,
    }
)

# ``decomposition`` is the short UI label.  Keep the longer internal name so
# indexing/query workers read a self-explanatory configuration key.
_STAGE_ALIASES = MappingProxyType({"decomposition": "query_decomposition"})

_CONFIGURATION_KEYS = frozenset(
    {
        "qdrant_url",
        "qdrant_timeout_seconds",
        "window_seconds",
        "stride_seconds",
        "providers",
        "models",
        "consent_cloud_video",
    }
)
_CREDENTIAL_KEYS = frozenset(
    {
        "gemini_api_key",
        "openai_api_key",
        "nvidia_api_key",
        "qdrant_api_key",
    }
)


@dataclass(frozen=True)
class ValidatedRuntimeSetup:
    """Normalized public config plus private credentials for one session."""

    profile: RuntimeProfile
    configuration: Mapping[str, Any]
    credentials: Mapping[str, str]


def all_profiles() -> tuple[RuntimeProfile, ...]:
    """Return profiles in the order they should appear in the UI."""

    return tuple(_PROFILES.values())


def list_profiles_public() -> list[dict[str, Any]]:
    return [profile.public() for profile in all_profiles()]


def get_profile(profile_id: str) -> RuntimeProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise RuntimeProfileError(f"Unknown runtime profile '{profile_id}'") from exc


def credential_keys() -> frozenset[str]:
    """Credential names accepted by the session layer (never their values)."""

    return _CREDENTIAL_KEYS


def validate_runtime_setup(
    profile_id: str,
    configuration: Mapping[str, Any] | None = None,
    credentials: Mapping[str, Any] | None = None,
) -> ValidatedRuntimeSetup:
    """Validate and normalize a user-selected runtime setup.

    The function intentionally rejects unknown keys.  That prevents an API key
    accidentally supplied in a public configuration field from getting copied
    into a job payload, diagnostic export, or response.
    """

    profile = get_profile(profile_id)
    raw_config = _mapping_or_error(configuration, "configuration")
    raw_credentials = _mapping_or_error(credentials, "credentials")
    unknown_config = sorted(set(raw_config) - _CONFIGURATION_KEYS)
    unknown_credentials = sorted(set(raw_credentials) - _CREDENTIAL_KEYS)
    if unknown_config:
        raise RuntimeProfileError(
            f"Unsupported runtime configuration field(s): {', '.join(unknown_config)}"
        )
    if unknown_credentials:
        raise RuntimeProfileError(
            f"Unsupported credential field(s): {', '.join(unknown_credentials)}"
        )

    normalized_credentials = _normalize_credentials(raw_credentials)
    normalized = _default_configuration(profile)
    normalized.update(
        {
            key: raw_config[key]
            for key in raw_config
            if key not in {"providers", "models", "consent_cloud_video"}
        }
    )
    normalized["providers"] = _normalize_providers(profile, raw_config.get("providers"))
    normalized["models"] = _normalize_models(
        profile,
        normalized["providers"],
        raw_config.get("models"),
    )

    normalized["window_seconds"] = _positive_number(
        normalized["window_seconds"], "window_seconds"
    )
    normalized["stride_seconds"] = _positive_number(
        normalized["stride_seconds"], "stride_seconds"
    )
    if normalized["stride_seconds"] > normalized["window_seconds"]:
        raise RuntimeProfileError("stride_seconds must not exceed window_seconds")
    normalized["qdrant_timeout_seconds"] = _positive_number(
        normalized.get("qdrant_timeout_seconds", 10.0), "qdrant_timeout_seconds"
    )

    if profile.qdrant_target == "cloud":
        normalized["qdrant_url"] = _normalize_qdrant_cloud_url(
            normalized.get("qdrant_url")
        )
        if raw_config.get("consent_cloud_video") is not True:
            raise RuntimeProfileError(
                "consent_cloud_video must be true before API-based processing can upload video"
            )
        normalized["consent_cloud_video"] = True
        # Keep only credentials selected by this concrete run configuration.
        # This is intentionally done after validation: an API-key field that
        # was needed by a previous provider selection must not linger in an
        # updated in-memory session after the UI switches that stage back to
        # Gemini.  It reduces the secret footprint without weakening the
        # required-key check below.
        required_credentials = _require_credentials(
            profile, normalized["providers"], normalized_credentials
        )
        normalized_credentials = {
            name: value
            for name, value in normalized_credentials.items()
            if name in required_credentials
        }
    else:
        if raw_credentials:
            raise RuntimeProfileError(
                "Self-hosted mode does not accept cloud API credentials in a runtime session"
            )
        normalized["qdrant_url"] = _normalize_local_qdrant_url(
            normalized.get("qdrant_url")
        )
        normalized["consent_cloud_video"] = False

    return ValidatedRuntimeSetup(
        profile=profile,
        configuration=MappingProxyType(_public_copy(normalized)),
        credentials=MappingProxyType(normalized_credentials),
    )


def redact_secrets(value: Any, secrets: tuple[str, ...] | list[str] = ()) -> Any:
    """Recursively redact secret-shaped fields and literal secret values.

    It is used before API responses and exception text leave this process.  The
    literal replacement is important because third-party client errors can
    include a request URL or header value in their diagnostic text.
    """

    secret_values = tuple(item for item in secrets if item)
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED
            if _looks_secret_name(str(key))
            else redact_secrets(item, secret_values)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_secrets(item, secret_values) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secret_values:
            redacted = redacted.replace(secret, REDACTED)
        return redacted
    return value


def redact_validation_errors(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return FastAPI/Pydantic validation details without credential values.

    Pydantic's stock 422 response includes the rejected ``input`` value.  A
    length/type error on a credential field would therefore echo the API key
    straight back to the browser, despite that field being excluded from
    normal response serialisation.  Keep useful field-level errors, but
    replace inputs located under a secret-shaped name and redact nested secret
    mappings everywhere else.
    """

    safe_errors: list[dict[str, Any]] = []
    for error in errors:
        safe = redact_secrets(dict(error))
        location = error.get("loc", ())
        if isinstance(location, (list, tuple)) and any(
            _looks_secret_name(str(part)) for part in location
        ):
            safe["input"] = REDACTED
        safe_errors.append(safe)
    return safe_errors


def qdrant_preflight(
    setup: ValidatedRuntimeSetup,
    *,
    client_factory: Any | None = None,
) -> dict[str, Any]:
    """Perform a read-only Qdrant connection and schema compatibility test.

    The function never creates, changes, or deletes a collection.  A missing
    collection is a successful connection result: the first index job is the
    operation that creates the profile-specific collection.  ``client_factory``
    is injectable so API tests never need a live Cloud cluster.
    """

    profile = setup.profile
    expected_schema = profile.vector_schema
    timeout_seconds = float(setup.configuration.get("qdrant_timeout_seconds", 10.0))
    diagnostics: list[dict[str, Any]] = [
        {
            "stage": "profile_contract",
            "status": "passed",
            "message": (
                f"Using profile {profile.id} with compatible collection "
                f"{profile.collection_name}."
            ),
        }
    ]
    result: dict[str, Any] = {
        "profile_id": profile.id,
        "collection_name": profile.collection_name,
        "expected_schema": expected_schema,
        "reachable": False,
        "collection_exists": False,
        "schema_valid": False,
        "schema_errors": [],
        "points_count": 0,
        "warning": None,
        "timeout_seconds": timeout_seconds,
        "diagnostics": diagnostics,
    }
    if profile.qdrant_target != "cloud":
        result.update(
            {
                "reachable": True,
                "schema_valid": True,
                "warning": "This self-hosted profile uses the local Qdrant setting; no cloud preflight was run.",
            }
        )
        diagnostics.append(
            {
                "stage": "qdrant_cloud_connection",
                "status": "skipped",
                "message": "Cloud connectivity is not required for the self-hosted profile.",
            }
        )
        return result

    secrets = tuple(setup.credentials.values())
    started_at = perf_counter()
    try:
        if client_factory is None:
            from qdrant_client import QdrantClient

            client_factory = QdrantClient
        client = client_factory(
            url=str(setup.configuration["qdrant_url"]),
            api_key=setup.credentials["qdrant_api_key"],
            timeout=timeout_seconds,
        )
        exists = bool(client.collection_exists(profile.collection_name))
        elapsed_ms = round((perf_counter() - started_at) * 1000)
        result["reachable"] = True
        result["collection_exists"] = exists
        diagnostics.append(
            {
                "stage": "qdrant_cloud_connection",
                "status": "passed",
                "message": "Qdrant Cloud accepted the authenticated collection lookup.",
                "elapsed_ms": elapsed_ms,
            }
        )
        if not exists:
            result.update(
                {
                    "schema_valid": True,
                    "warning": "Qdrant Cloud is reachable. The profile collection will be created by the first index run.",
                }
            )
            diagnostics.append(
                {
                    "stage": "collection_schema",
                    "status": "warning",
                    "message": "The compatible collection does not exist yet; the first index run will create it.",
                    "next_action": "Start indexing when you are ready. No manual collection setup is needed.",
                }
            )
            return result

        collection = client.get_collection(profile.collection_name)
        result["points_count"] = getattr(collection, "points_count", 0) or 0
        actual_vectors = getattr(
            getattr(getattr(collection, "config", None), "params", None),
            "vectors",
            None,
        )
        schema_errors = qdrant_schema_errors(expected_schema, actual_vectors)
        result["schema_errors"] = schema_errors
        result["schema_valid"] = not schema_errors
        if schema_errors:
            result["warning"] = (
                "The existing collection is incompatible with this runtime profile. "
                "Choose the profile collection shown above; do not mix vector schemas."
            )
            diagnostics.append(
                {
                    "stage": "collection_schema",
                    "status": "failed",
                    "message": "The existing collection does not match this embedding profile.",
                    "next_action": "Use the profile collection shown above or reindex into a compatible collection.",
                }
            )
        else:
            diagnostics.append(
                {
                    "stage": "collection_schema",
                    "status": "passed",
                    "message": "The existing collection matches the selected embedding profile.",
                }
            )
        return result
    except Exception as exc:  # noqa: BLE001 - UI needs a non-secret diagnostic
        safe_error = str(redact_secrets(str(exc), secrets))
        result["error_type"] = type(exc).__name__
        result["error"] = safe_error
        diagnostics.append(
            {
                "stage": "qdrant_cloud_connection",
                "status": "failed",
                "message": safe_error or "Qdrant Cloud did not complete the collection lookup.",
                "elapsed_ms": round((perf_counter() - started_at) * 1000),
                "next_action": _qdrant_preflight_next_action(exc, timeout_seconds),
            }
        )
        return result


def _qdrant_preflight_next_action(exc: Exception, timeout_seconds: float) -> str:
    """Return a safe, actionable next step for a Cloud preflight failure."""

    description = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timed out" in description or "timeout" in description:
        return (
            f"The lookup did not finish within {timeout_seconds:g} seconds. Check the Cloud endpoint, "
            "college network/Wi-Fi/proxy/firewall access, then retry."
        )
    if any(token in description for token in ("401", "403", "unauthorized", "forbidden", "api key", "authentication")):
        return "Check that the Qdrant Cloud API key is current and belongs to this cluster, then retry."
    if any(token in description for token in ("dns", "getaddrinfo", "name resolution", "connection refused", "network")):
        return "Check the exact Cloud endpoint and network access, then retry from a network that permits HTTPS to Qdrant Cloud."
    return "Check the Qdrant Cloud endpoint, API key, and network access, then retry."


def qdrant_schema_errors(
    expected_schema: Mapping[str, Mapping[str, Any]], actual_vectors: Any
) -> list[str]:
    """Compare a Qdrant collection's named-vector schema with a profile.

    Qdrant returns a mapping of ``VectorParams`` for named vectors.  The small
    duck-typed reader also makes this function easy to test without importing
    qdrant-client or opening a database connection.
    """

    if not isinstance(actual_vectors, Mapping):
        return ["The collection has one unnamed vector; this profile requires named vectors."]
    errors: list[str] = []
    expected_names = set(expected_schema)
    actual_names = set(actual_vectors)
    missing = sorted(expected_names - actual_names)
    unexpected = sorted(actual_names - expected_names)
    if missing:
        errors.append(f"Missing vector(s): {', '.join(missing)}")
    if unexpected:
        errors.append(f"Unexpected vector(s): {', '.join(unexpected)}")
    for name in sorted(expected_names & actual_names):
        actual = actual_vectors[name]
        actual_size = _qdrant_value(actual, "size")
        expected_size = expected_schema[name]["dimensions"]
        if actual_size != expected_size:
            errors.append(
                f"{name} dimension: expected {expected_size}, got {actual_size}"
            )
        actual_distance = _qdrant_value(actual, "distance")
        normalized_distance = str(actual_distance).lower().split(".")[-1]
        if normalized_distance != str(expected_schema[name]["distance"]).lower():
            errors.append(
                f"{name} distance: expected {expected_schema[name]['distance']}, got {actual_distance}"
            )
    return errors


def _qdrant_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _default_configuration(profile: RuntimeProfile) -> dict[str, Any]:
    result = _public_copy(profile.defaults)
    result.setdefault("qdrant_timeout_seconds", 10.0)
    result["models"] = {
        stage: profile.option_for(stage, provider).model
        for stage, provider in result["providers"].items()
    }
    return result


def _normalize_providers(
    profile: RuntimeProfile, raw_providers: Any | None
) -> dict[str, str]:
    providers = _public_copy(profile.defaults["providers"])
    if raw_providers is None:
        return providers
    if not isinstance(raw_providers, Mapping):
        raise ProviderConfigurationError("providers must be an object keyed by processing stage")
    resolved_providers = _normalize_stage_aliases(raw_providers, "providers")
    unknown_stages = sorted(set(resolved_providers) - set(profile.stage_options))
    if unknown_stages:
        raise ProviderConfigurationError(
            f"Unsupported provider stage(s): {', '.join(unknown_stages)}"
        )
    for stage, provider in resolved_providers.items():
        if not isinstance(provider, str) or not provider.strip():
            raise ProviderConfigurationError(f"Provider for {stage} must be a non-empty string")
        providers[stage] = profile.option_for(stage, provider.strip().lower()).provider
    return providers


def _normalize_models(
    profile: RuntimeProfile,
    providers: Mapping[str, str],
    raw_models: Any | None,
) -> dict[str, str]:
    """Validate per-stage model selectors against the selected provider.

    A model selection is intentionally not an arbitrary string: allowing that
    would let one profile use an unknown embedding model while still writing to
    the profile's fixed Qdrant collection.  The UI receives every allowed
    provider/model pair from :meth:`RuntimeProfile.public`.
    """

    models = {
        stage: profile.option_for(stage, provider).model
        for stage, provider in providers.items()
    }
    if raw_models is None:
        return models
    if not isinstance(raw_models, Mapping):
        raise ProviderConfigurationError("models must be an object keyed by processing stage")
    resolved_models = _normalize_stage_aliases(raw_models, "models")
    unknown_stages = sorted(set(resolved_models) - set(profile.stage_options))
    if unknown_stages:
        raise ProviderConfigurationError(
            f"Unsupported model stage(s): {', '.join(unknown_stages)}"
        )
    for stage, model in resolved_models.items():
        if not isinstance(model, str) or not model.strip():
            raise ProviderConfigurationError(f"Model for {stage} must be a non-empty string")
        expected = profile.option_for(stage, providers[stage]).model
        if model.strip() != expected:
            raise ProviderConfigurationError(
                f"Model for {stage} must be '{expected}' when provider is {providers[stage]}"
            )
        models[stage] = expected
    return models


def _normalize_stage_aliases(
    values: Mapping[str, Any],
    field_name: str,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_stage, value in values.items():
        if not isinstance(raw_stage, str):
            raise ProviderConfigurationError(f"{field_name} stage names must be strings")
        stage = _STAGE_ALIASES.get(raw_stage.strip(), raw_stage.strip())
        if not stage:
            raise ProviderConfigurationError(f"{field_name} stage names must not be empty")
        if stage in normalized:
            raise ProviderConfigurationError(
                f"{field_name} includes duplicate stage '{stage}'"
            )
        normalized[stage] = value
    return normalized


def _require_credentials(
    profile: RuntimeProfile, providers: Mapping[str, str], credentials: Mapping[str, str]
) -> set[str]:
    required = {"qdrant_api_key"}
    for stage, provider in providers.items():
        option = profile.option_for(stage, provider)
        if option.credential_name:
            required.add(option.credential_name)
    missing = sorted(name for name in required if not credentials.get(name))
    if missing:
        raise ProviderConfigurationError(
            f"Missing required credential(s): {', '.join(missing)}"
        )
    return required


def _normalize_credentials(raw_credentials: Mapping[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in raw_credentials.items():
        if not isinstance(value, str):
            raise ProviderConfigurationError(f"Credential '{name}' must be a string")
        stripped = value.strip()
        if not stripped:
            raise ProviderConfigurationError(f"Credential '{name}' must not be empty")
        normalized[str(name)] = stripped
    return normalized


def _normalize_qdrant_cloud_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeProfileError("qdrant_url is required for the API-based profile")
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname.endswith(".cloud.qdrant.io"):
        raise RuntimeProfileError(
            "API-based mode requires an HTTPS Qdrant Cloud URL ending in .cloud.qdrant.io"
        )
    # A Qdrant Cloud API key belongs in the separate, session-private
    # credential field.  Besides being unsupported by Qdrant Cloud setup, URL
    # userinfo would make a secret-shaped value look like ordinary public
    # configuration and could therefore be reflected by a browser-safe
    # session response.  Reject it before the URL is stored anywhere.
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeProfileError(
            "qdrant_url must not include credentials; enter the Qdrant API key separately"
        )
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise RuntimeProfileError("qdrant_url must be a Qdrant Cloud base URL without a path")
    return url


def _normalize_local_qdrant_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeProfileError("qdrant_url must be a non-empty local URL")
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeProfileError(
            "Self-hosted mode requires a localhost Qdrant URL; use API-based mode for Qdrant Cloud"
        )
    return url


def _positive_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise RuntimeProfileError(f"{field_name} must be a positive number")
    return float(value)


def _mapping_or_error(value: Mapping[str, Any] | None, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RuntimeProfileError(f"{name} must be an object")
    return value


def _looks_secret_name(name: str) -> bool:
    lowered = name.lower()
    return any(
        token in lowered
        for token in ("api_key", "apikey", "secret", "token", "authorization", "password")
    )


def _public_copy(value: Any) -> Any:
    """Copy mappings/lists so callers cannot mutate profile defaults."""

    if isinstance(value, Mapping):
        return {str(key): _public_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_public_copy(item) for item in value]
    if isinstance(value, list):
        return [_public_copy(item) for item in value]
    return value
