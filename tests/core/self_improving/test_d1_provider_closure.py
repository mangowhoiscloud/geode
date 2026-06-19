"""D1 provider closure tests — closure now enforced at *resolution*, not type.

PR-CRED-SOURCE-CENTRALIZE (2026-05-29) reversed the original type-level
exclusion: ``api_key`` was removed from the ``Source`` Literal so the config
*rejected* it. That caused the credential-source fragmentation (``api_key`` in
some enums, not others) and blocked an operator who explicitly opts into PAYG.

The D1 *intent* — a subscription-only run must not **silently** fall through to
PAYG — is unchanged, but it is now enforced at **resolution** time:
``resolve_credential_source(fallback_to_payg=False)`` filters ``api_key`` out of
``auto`` expansion. ``api_key`` is a valid :class:`CredentialSource` member, so
the config accepts an *explicit* ``source = "api_key"`` (the deliberate opt-in)
while ``auto`` still never silently bills the API key. See
``test_credential_source_centralized.py`` for the resolution-gate + enum-drift
invariants.

Remaining wiring (unchanged):
- ``PetriRoleConfig.source`` / ``AutoresearchConfig.source`` default
  ``claude-cli`` (subscription-first).
"""

from __future__ import annotations

from core.config.credential_source import CredentialSource
from core.config.self_improving import (
    AutoresearchConfig,
    PetriRoleConfig,
)

# ---------------------------------------------------------------------------
# 1. Source literal — api_key reject
# ---------------------------------------------------------------------------


def test_petri_role_source_accepts_api_key() -> None:
    """PetriRoleConfig now ACCEPTS ``source = "api_key"`` (centralized enum).

    PR-CRED-SOURCE-CENTRALIZE: ``api_key`` is a valid ``CredentialSource``
    member, so an operator can explicitly opt into PAYG for an audit role. The
    silent-fallback closure moved to resolution (``fallback_to_payg`` gate),
    asserted in ``test_credential_source_centralized.py``.
    """
    p = PetriRoleConfig(source="api_key")
    assert p.source == CredentialSource.API_KEY
    assert p.source == "api_key"  # StrEnum compares equal to its wire string


def test_autoresearch_source_accepts_api_key() -> None:
    """AutoresearchConfig likewise accepts an explicit ``source = "api_key"``."""
    a = AutoresearchConfig(source="api_key")
    assert a.source == CredentialSource.API_KEY


def test_petri_role_source_accepts_claude_cli() -> None:
    """``source = "claude-cli"`` 수락 (subscription default)."""
    p = PetriRoleConfig(source="claude-cli")
    assert p.source == "claude-cli"


def test_petri_role_source_accepts_openai_codex() -> None:
    """``source = "openai-codex"`` 수락 (ChatGPT OAuth)."""
    p = PetriRoleConfig(source="openai-codex")
    assert p.source == "openai-codex"


def test_petri_role_source_accepts_auto() -> None:
    """``source = "auto"`` 수락 (manifest cascade — subscription-first
    but fallback_to_payg=False 가 default 라 PAYG 까지 안 감)."""
    p = PetriRoleConfig(source="auto")
    assert p.source == "auto"


# ---------------------------------------------------------------------------
# 2. Defaults — subscription-first
# ---------------------------------------------------------------------------


def test_petri_role_default_source_claude_cli() -> None:
    """PetriRoleConfig 의 source default 가 ``claude-cli`` (subscription-first).

    PR-SIL-5THEME C6 후 default 변경. ``auto`` 는 manifest cascade 가
    silent PAYG fallback 가능 → 명시 default 로 leak 차단.
    """
    p = PetriRoleConfig()
    assert p.source == "claude-cli"


def test_autoresearch_config_default_source_claude_cli() -> None:
    """AutoresearchConfig 의 source default 도 ``claude-cli``."""
    a = AutoresearchConfig()
    assert a.source == "claude-cli"


# ---------------------------------------------------------------------------
# 3. Backend matrix — 4 cases (api_key reject + 3 valid)
# ---------------------------------------------------------------------------


def test_backend_matrix_all_sources_accepted_petri_role() -> None:
    """4-source matrix: all four canonical sources (incl. ``api_key``) accept.

    Post-centralization the config no longer type-rejects ``api_key``; every
    ``CredentialSource`` member is a valid config value.
    """
    for source in CredentialSource:
        cfg = PetriRoleConfig(source=source)
        assert cfg.source == source


def test_backend_matrix_all_sources_accepted_autoresearch() -> None:
    """AutoresearchConfig accepts every canonical source too."""
    for source in CredentialSource:
        cfg = AutoresearchConfig(source=source)
        assert cfg.source == source
