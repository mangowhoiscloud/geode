"""Canonical credential-source enum — single source of truth.

PR-CRED-SOURCE-CENTRALIZE (2026-05-29). The LLM credential-source value set
was previously defined four different ways, with *inconsistent membership*:

- the self-improving config source type — ``{claude-cli, openai-codex, auto}``
  (no ``api_key``)
- the mutator-config ``source`` Literal — ``{auto, api_key, claude-cli, openai-codex}``
  (with ``api_key``)
- ``geode_product.seed_generation.auth_coverage.Source`` — ``{claude-cli, openai-codex,
  api_key}`` (no ``auto``)
- ``settings.{anthropic,openai}_credential_source`` — bare ``str``

plus the petri magic constants ``AUTO_SOURCE = "auto"`` / ``PAYG_SOURCE =
"api_key"``. A change in one place silently diverged from the others (e.g.
``api_key`` accepted by the mutator config but rejected by the autoresearch
config), which is exactly the fragmentation this module removes: every
credential-source field now references :class:`CredentialSource`.

``StrEnum`` so members compare equal to their wire string
(``CredentialSource.AUTO == "auto"``) — existing string comparisons and TOML
config values keep working, while pydantic gains centralized validation.

PAYG safety
-----------
``API_KEY`` is a **valid member everywhere**. Preventing a subscription-only
run from silently falling through to PAYG is enforced at *resolution* time by
``[self_improving_loop] fallback_to_payg`` /
``geode_product.petri_audit.credential_source.resolve_credential_source(fallback_to_payg=…)``
— **not** by narrowing this enum. This moves ``project_payg_exclusion_decision``
from a type-level exclusion to a runtime gate (the gate is the real safety
boundary; the type-level narrowing only caused the fragmentation above and
blocked an operator who explicitly opts into PAYG).
"""

from __future__ import annotations

from enum import StrEnum


class CredentialSource(StrEnum):
    """The concrete credential sources a provider call can be routed through."""

    #: Resolver picks per the manifest ``allowed`` order (OAuth-first), gated
    #: by ``fallback_to_payg`` for the PAYG (``api_key``) entry.
    AUTO = "auto"
    #: Pay-as-you-go API key (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``).
    API_KEY = "api_key"
    #: Retired input sentinel kept only so existing TOML can load and emit a
    #: migration error before dispatch. It is never an executable source.
    LEGACY_CLAUDE_CLI = "claude-cli"
    #: OpenAI OAuth via the ChatGPT subscription backend.
    OPENAI_CODEX = "openai-codex"


#: Legacy provider-agnostic OAuth alias. Historically some ``.env`` /
#: ``config.toml`` files set ``*_credential_source = "oauth"``; the resolver
#: maps it to OpenAI Codex OAuth or Anthropic's retired sentinel. Not a
#: :class:`CredentialSource` member because it is an input alias.
LEGACY_OAUTH_ALIAS = "oauth"

CLAUDE_CLI_RETIRED_MESSAGE = (
    "Anthropic Claude CLI integration is retired; GEODE will not invoke the "
    "`claude` binary. Select source='api_key' and configure ANTHROPIC_API_KEY."
)

#: Disable sentinel accepted by ``settings.{provider}_credential_source``.
DISABLE_SENTINEL = "none"


__all__ = [
    "CLAUDE_CLI_RETIRED_MESSAGE",
    "DISABLE_SENTINEL",
    "LEGACY_OAUTH_ALIAS",
    "CredentialSource",
]
