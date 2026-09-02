"""Composable provider profile, credential route, and transport catalogue.

``ProviderSpec`` remains the compatibility view consumed by ``Plan`` and the
login UI. Its payload is now three immutable records so model semantics,
account selection, and wire transport can vary independently without a new
provider enum branch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class AdapterBillingType(str, Enum):  # noqa: UP042 — older serialisers require str+Enum
    """How an adapter call is billed."""

    API = "api"
    SUBSCRIPTION = "subscription"
    METERED_API = "metered_api"
    SUBSCRIPTION_INCLUDED = "subscription_included"
    SUBSCRIPTION_OVERAGE = "subscription_overage"
    CREDITS = "credits"
    FIXED = "fixed"
    UNKNOWN = "unknown"


SOURCE_PAYG = "payg"
SOURCE_SUBSCRIPTION = "subscription"
SOURCE_ADAPTER = "adapter"
SOURCE_AUTO = "auto"
CONCRETE_SOURCES: frozenset[str] = frozenset({SOURCE_PAYG, SOURCE_SUBSCRIPTION, SOURCE_ADAPTER})

AuthType = Literal["bearer", "x-api-key", "oauth_external", "aws-sdk", "adapter"]
_AUTH_TYPES = frozenset({"bearer", "x-api-key", "oauth_external", "aws-sdk", "adapter"})


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Provider/model identity and the routing-manifest default it owns."""

    id: str
    provider: str
    display_name: str
    default_model_key: str

    def __post_init__(self) -> None:
        for field_name in ("id", "provider", "display_name", "default_model_key"):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )

    def default_model(self) -> str:
        """Resolve the current default without copying mutable routing state."""
        from core.config.routing_manifest import load_routing_manifest

        return load_routing_manifest().get_default(self.default_model_key) or ""


@dataclass(frozen=True, slots=True)
class CredentialRoute:
    """Non-secret credential source and account-selection declaration."""

    source: str
    account_provider: str
    selector: str
    auth_type: AuthType
    billing_type: AdapterBillingType
    settings_field: str = ""
    settings_values: tuple[str, ...] = ()
    auto_select: bool = False
    default: bool = False
    quota_policy: str = "adapter-owned"

    def __post_init__(self) -> None:
        source = _require_text(self.source, "credential route source")
        if source not in CONCRETE_SOURCES:
            raise ValueError(f"credential route source {source!r} is not a concrete value")
        object.__setattr__(self, "source", source)
        auth_type = _require_text(self.auth_type, "credential route auth_type")
        if auth_type not in _AUTH_TYPES:
            raise ValueError(f"credential route auth_type {auth_type!r} is not supported")
        object.__setattr__(self, "auth_type", auth_type)
        if not isinstance(self.billing_type, AdapterBillingType):
            raise TypeError("credential route billing_type must be an AdapterBillingType")
        for field_name in ("account_provider", "selector", "quota_policy"):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )
        if not isinstance(self.settings_field, str):
            raise TypeError("credential route settings_field must be a string")
        object.__setattr__(self, "settings_field", self.settings_field.strip())
        raw_settings_values: object = self.settings_values
        if isinstance(raw_settings_values, (str, bytes)):
            raise TypeError("credential route settings_values must be an iterable of strings")
        values = tuple(
            dict.fromkeys(
                _require_text(value, "credential route settings value").lower()
                for value in self.settings_values
            )
        )
        object.__setattr__(self, "settings_values", values)


@dataclass(frozen=True, slots=True)
class TransportSpec:
    """LLM wire/API shape and non-secret endpoint policy."""

    id: str
    api: str
    default_base_url: str
    native_capabilities: frozenset[str] = frozenset()
    retry_policy: str = "agentic-loop"
    extra_headers_factory: Callable[[str], dict[str, str]] | None = field(
        default=None,
        hash=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        for field_name in ("id", "api", "retry_policy"):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )
        raw_capabilities: object = self.native_capabilities
        if isinstance(raw_capabilities, (str, bytes)):
            raise TypeError("transport native_capabilities must be an iterable of strings")
        capabilities = frozenset(
            _require_text(capability, "native capability")
            for capability in self.native_capabilities
        )
        object.__setattr__(self, "native_capabilities", capabilities)
        if self.extra_headers_factory is not None and not callable(self.extra_headers_factory):
            raise TypeError("transport extra_headers_factory must be callable")


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Compatibility composition of one profile, credential route, and transport."""

    profile: ProviderProfile
    credential: CredentialRoute
    transport: TransportSpec

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ProviderProfile):
            raise TypeError("provider spec profile must be a ProviderProfile")
        if not isinstance(self.credential, CredentialRoute):
            raise TypeError("provider spec credential must be a CredentialRoute")
        if not isinstance(self.transport, TransportSpec):
            raise TypeError("provider spec transport must be a TransportSpec")

    @property
    def id(self) -> str:
        return self.profile.id

    @property
    def display_name(self) -> str:
        return self.profile.display_name

    @property
    def default_base_url(self) -> str:
        return self.transport.default_base_url

    @property
    def auth_type(self) -> AuthType:
        return self.credential.auth_type

    @property
    def extra_headers_factory(self) -> Callable[[str], dict[str, str]] | None:
        return self.transport.extra_headers_factory


def _codex_extra_headers(_access_token: str) -> dict[str, str]:
    """Static Codex backend headers; account identity remains token-derived."""
    return {
        "User-Agent": "codex_cli_rs/0.0.0 (GEODE)",
        "originator": "codex_cli_rs",
    }


def _openrouter_extra_headers(_api_key: str) -> dict[str, str]:
    """Documented app attribution plus bounded router-decision evidence."""
    return {
        "HTTP-Referer": "https://mangowhoiscloud.github.io/geode/",
        "X-OpenRouter-Title": "GEODE",
        "X-OpenRouter-Metadata": "enabled",
    }


_COMMON_NATIVE = frozenset({"streaming", "web_search", "text_completion"})

PROVIDER_VARIANTS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        profile=ProviderProfile("anthropic", "anthropic", "Anthropic", "anthropic"),
        credential=CredentialRoute(
            source=SOURCE_PAYG,
            account_provider="anthropic",
            selector="settings",
            auth_type="x-api-key",
            billing_type=AdapterBillingType.API,
            settings_field="anthropic_credential_source",
            settings_values=("api_key",),
            default=True,
            quota_policy="provider-owned",
        ),
        transport=TransportSpec(
            id="anthropic-messages",
            api="anthropic-messages",
            default_base_url="https://api.anthropic.com",
            native_capabilities=_COMMON_NATIVE | {"computer_use"},
        ),
    ),
    "openai": ProviderSpec(
        profile=ProviderProfile("openai", "openai", "OpenAI", "openai"),
        credential=CredentialRoute(
            source=SOURCE_PAYG,
            account_provider="openai",
            selector="settings",
            auth_type="bearer",
            billing_type=AdapterBillingType.API,
            settings_field="openai_credential_source",
            settings_values=("api_key",),
            default=True,
            quota_policy="provider-owned",
        ),
        transport=TransportSpec(
            id="openai-platform-responses",
            api="openai-responses",
            default_base_url="https://api.openai.com/v1",
            native_capabilities=_COMMON_NATIVE | {"computer_use"},
        ),
    ),
    "openai-codex": ProviderSpec(
        profile=ProviderProfile(
            "openai-codex",
            "openai",
            "OpenAI (ChatGPT subscription)",
            "codex",
        ),
        credential=CredentialRoute(
            source=SOURCE_SUBSCRIPTION,
            account_provider="openai-codex",
            selector="codex-oauth",
            auth_type="oauth_external",
            billing_type=AdapterBillingType.SUBSCRIPTION,
            settings_field="openai_credential_source",
            settings_values=("oauth", "openai-codex"),
            auto_select=True,
            quota_policy="codex-usage",
        ),
        transport=TransportSpec(
            id="openai-codex-responses",
            api="openai-responses",
            default_base_url="https://chatgpt.com/backend-api/codex",
            native_capabilities=_COMMON_NATIVE,
            extra_headers_factory=_codex_extra_headers,
        ),
    ),
    "openrouter": ProviderSpec(
        profile=ProviderProfile("openrouter", "openrouter", "OpenRouter", "openrouter"),
        credential=CredentialRoute(
            source=SOURCE_PAYG,
            account_provider="openrouter",
            selector="settings",
            auth_type="bearer",
            billing_type=AdapterBillingType.CREDITS,
            default=True,
            quota_policy="provider-owned",
        ),
        transport=TransportSpec(
            id="openrouter-chat-completions",
            api="openai-chat-completions",
            default_base_url="https://openrouter.ai/api/v1",
            extra_headers_factory=_openrouter_extra_headers,
        ),
    ),
    "glm": ProviderSpec(
        profile=ProviderProfile("glm", "glm", "GLM (PAYG)", "glm"),
        credential=CredentialRoute(
            source=SOURCE_PAYG,
            account_provider="glm",
            selector="settings",
            auth_type="bearer",
            billing_type=AdapterBillingType.API,
            default=True,
            quota_policy="provider-owned",
        ),
        transport=TransportSpec(
            id="glm-payg-chat-completions",
            api="openai-chat-completions",
            default_base_url="https://api.z.ai/api/paas/v4",
            native_capabilities=_COMMON_NATIVE,
        ),
    ),
    "glm-coding": ProviderSpec(
        profile=ProviderProfile("glm-coding", "glm", "GLM Coding Plan", "glm"),
        credential=CredentialRoute(
            source=SOURCE_SUBSCRIPTION,
            account_provider="glm-coding",
            selector="profile-store",
            auth_type="bearer",
            billing_type=AdapterBillingType.SUBSCRIPTION,
            quota_policy="plan-registry",
        ),
        transport=TransportSpec(
            id="glm-coding-chat-completions",
            api="openai-chat-completions",
            default_base_url="https://api.z.ai/api/coding/paas/v4",
            native_capabilities=_COMMON_NATIVE,
        ),
    ),
}


def get_provider_spec(provider: str) -> ProviderSpec | None:
    """Look up one provider variant by compatibility ID."""
    return PROVIDER_VARIANTS.get(provider)


def list_provider_ids() -> list[str]:
    """Return provider variant IDs in deterministic declaration order."""
    return list(PROVIDER_VARIANTS)


def provider_specs_for(provider: str) -> tuple[ProviderSpec, ...]:
    """Return every built-in route serving one canonical model provider."""
    return tuple(spec for spec in PROVIDER_VARIANTS.values() if spec.profile.provider == provider)


PROVIDER_EQUIVALENCE: dict[str, list[str]] = {
    "openai": ["openai-codex", "openai"],
    "openai-codex": ["openai-codex", "openai"],
    "glm": ["glm-coding", "glm"],
    "glm-coding": ["glm-coding", "glm"],
    "anthropic": ["anthropic"],
}


def equivalent_providers(provider: str) -> list[str]:
    """Return preferred-first variants that share a model family."""
    return PROVIDER_EQUIVALENCE.get(provider, [provider])


__all__ = [
    "CONCRETE_SOURCES",
    "PROVIDER_EQUIVALENCE",
    "PROVIDER_VARIANTS",
    "SOURCE_ADAPTER",
    "SOURCE_AUTO",
    "SOURCE_PAYG",
    "SOURCE_SUBSCRIPTION",
    "AdapterBillingType",
    "CredentialRoute",
    "ProviderProfile",
    "ProviderSpec",
    "TransportSpec",
    "equivalent_providers",
    "get_provider_spec",
    "list_provider_ids",
    "provider_specs_for",
]
