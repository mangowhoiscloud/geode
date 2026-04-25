"""Provider Variant Registry — endpoint + auth-type per provider variant.

Hermes-style ProviderConfig: each variant binds (id, default base URL,
auth header convention, optional extra headers factory). Used by Plan to
resolve runtime endpoints and by AuthProfile validation to ensure a
credential's provider matches a registered variant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

AuthType = Literal["bearer", "x-api-key", "oauth_external", "aws-sdk"]


@dataclass(frozen=True)
class ProviderSpec:
    """Static metadata for a provider variant."""

    id: str  # canonical provider variant ID, e.g. "openai-codex"
    display_name: str
    default_base_url: str
    auth_type: AuthType = "bearer"
    # Optional callable: (access_token: str) -> dict[str, str]
    # Used by openai-codex for Cloudflare/account headers.
    extra_headers_factory: Callable[[str], dict[str, str]] | None = field(
        default=None, hash=False, compare=False
    )


def _codex_extra_headers(_access_token: str) -> dict[str, str]:
    """Cloudflare bypass headers for chatgpt.com/backend-api/codex.

    Mirrors Hermes agent/auxiliary_client.py:_codex_cloudflare_headers.
    The ChatGPT-Account-ID claim extraction is handled by the codex
    provider module itself (it already parses the JWT for the account_id
    field), so we keep this factory header-only.
    """
    return {
        "User-Agent": "codex_cli_rs/0.0.0 (GEODE)",
        "originator": "codex_cli_rs",
    }


PROVIDER_VARIANTS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        id="anthropic",
        display_name="Anthropic",
        default_base_url="https://api.anthropic.com",
        auth_type="x-api-key",
    ),
    "openai": ProviderSpec(
        id="openai",
        display_name="OpenAI",
        default_base_url="https://api.openai.com/v1",
        auth_type="bearer",
    ),
    "openai-codex": ProviderSpec(
        id="openai-codex",
        display_name="OpenAI Codex (Plus)",
        default_base_url="https://chatgpt.com/backend-api/codex",
        auth_type="oauth_external",
        extra_headers_factory=_codex_extra_headers,
    ),
    "glm": ProviderSpec(
        id="glm",
        display_name="GLM (PAYG)",
        default_base_url="https://api.z.ai/api/paas/v4",
        auth_type="bearer",
    ),
    "glm-coding": ProviderSpec(
        id="glm-coding",
        display_name="GLM Coding Plan",
        default_base_url="https://api.z.ai/api/coding/paas/v4",
        auth_type="bearer",
    ),
}


def get_provider_spec(provider: str) -> ProviderSpec | None:
    """Look up the ProviderSpec for a provider variant ID."""
    return PROVIDER_VARIANTS.get(provider)


def list_provider_ids() -> list[str]:
    """Return all registered provider variant IDs."""
    return list(PROVIDER_VARIANTS.keys())
