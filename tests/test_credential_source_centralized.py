"""Drift invariants for the centralized credential-source enum.

PR-CRED-SOURCE-CENTRALIZE (2026-05-29). The credential-source value set used to
be spelled four different ways with inconsistent membership; these tests pin
every (previously-fragmented) site to the single canonical
:class:`core.config.credential_source.CredentialSource` so the fragmentation
cannot silently come back.
"""

from __future__ import annotations

from typing import get_args

import pytest
from core.config.credential_source import (
    DISABLE_SENTINEL,
    LEGACY_OAUTH_ALIAS,
    CredentialSource,
)
from pydantic import ValidationError


def test_canonical_membership_is_stable() -> None:
    """The canonical enum is exactly these four sources. A change here is a
    deliberate, reviewed event — not an accidental per-module divergence."""
    assert {s.value for s in CredentialSource} == {
        "auto",
        "api_key",
        "claude-cli",
        "openai-codex",
    }


def test_self_improving_loop_source_alias_is_canonical() -> None:
    """``self_improving_loop.Source`` is a re-export of the canonical enum,
    not a second Literal."""
    from core.config.self_improving_loop import Source

    assert Source is CredentialSource


def test_config_source_fields_use_canonical_enum() -> None:
    """Every ``source`` field on the loop config models is typed as the
    canonical enum (previously: two different Literals)."""
    from core.config.self_improving_loop import (
        AutoresearchConfig,
        MutatorConfig,
        PetriRoleConfig,
    )

    for model in (PetriRoleConfig, AutoresearchConfig, MutatorConfig):
        assert model.model_fields["source"].annotation is CredentialSource, model.__name__


def test_auth_coverage_source_is_concrete_subset() -> None:
    """``auth_coverage.Source`` is exactly the *concrete* (non-AUTO) members of
    the canonical enum — pinned so it can't drift (it stays a Literal because an
    auth path is never the AUTO resolver mode)."""
    from plugins.seed_generation.auth_coverage import Source as AuthPathSource

    concrete = {s.value for s in CredentialSource if s is not CredentialSource.AUTO}
    assert set(get_args(AuthPathSource)) == concrete


def test_petri_constants_sourced_from_canonical_enum() -> None:
    """The petri magic constants derive from the canonical enum (no drift)."""
    from plugins.petri_audit.credential_source import PAYG_SOURCE
    from plugins.petri_audit.manifest import AUTO_SOURCE

    assert AUTO_SOURCE == CredentialSource.AUTO.value == "auto"
    assert PAYG_SOURCE == CredentialSource.API_KEY.value == "api_key"


def test_settings_credential_source_validates_against_canonical() -> None:
    """``settings.{provider}_credential_source`` accepts the canonical members
    plus the legacy ``oauth`` alias / ``none`` sentinel, and rejects anything
    else — validated against the single SoT rather than a bare ``str``."""
    from core.config._settings import Settings

    accepted = {s.value for s in CredentialSource} | {LEGACY_OAUTH_ALIAS, DISABLE_SENTINEL}
    for value in accepted:
        s = Settings(anthropic_credential_source=value, openai_credential_source=value)
        assert s.anthropic_credential_source == value

    with pytest.raises(ValidationError):
        Settings(anthropic_credential_source="not-a-real-source")
