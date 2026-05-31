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
- ``core/self_improving/prepare.py`` ``check_subscription_cli_for_source`` pre-flight.
"""

from __future__ import annotations

import pytest
from core.config.credential_source import CredentialSource
from core.config.self_improving_loop import (
    AutoresearchConfig,
    PetriRoleConfig,
)
from core.self_improving.prepare import check_subscription_cli_for_source

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
# 3. check_subscription_cli_for_source — pre-flight
# ---------------------------------------------------------------------------


def test_preflight_claude_cli_missing_binary_returns_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``claude`` binary 가 PATH 에 없으면 actionable error 메시지 반환."""
    monkeypatch.delenv("GEODE_CLAUDE_CLI_BIN", raising=False)
    # shutil.which("claude") 가 None 반환하도록 mock
    import core.self_improving.prepare as prepare_module

    monkeypatch.setattr(prepare_module.shutil, "which", lambda _: None)

    ok, msg = check_subscription_cli_for_source("claude-cli")
    assert not ok
    assert "claude-cli source selected" in msg
    assert "GEODE_CLAUDE_CLI_BIN" in msg


def test_preflight_codex_cli_missing_binary_returns_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``codex`` binary 부재 시 actionable error."""
    monkeypatch.delenv("GEODE_CODEX_CLI_BIN", raising=False)
    import core.self_improving.prepare as prepare_module

    monkeypatch.setattr(prepare_module.shutil, "which", lambda _: None)

    ok, msg = check_subscription_cli_for_source("openai-codex")
    assert not ok
    assert "openai-codex source selected" in msg
    assert "GEODE_CODEX_CLI_BIN" in msg


def test_preflight_claude_cli_env_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GEODE_CLAUDE_CLI_BIN env override 가 shutil.which 보다 우선."""
    monkeypatch.setenv("GEODE_CLAUDE_CLI_BIN", "/custom/path/claude")
    import core.self_improving.prepare as prepare_module

    # shutil.which 가 다른 값을 반환해도 env override 가 이김
    monkeypatch.setattr(prepare_module.shutil, "which", lambda _: "/usr/local/bin/claude")

    ok, msg = check_subscription_cli_for_source("claude-cli")
    assert ok
    assert "/custom/path/claude" in msg


def test_preflight_auto_source_skips_binary_check() -> None:
    """``source="auto"`` → cascade 가 fallback path 책임 → pre-flight skip."""
    ok, msg = check_subscription_cli_for_source("auto")
    assert ok
    assert "auto source" in msg
    assert "cascade" in msg


def test_preflight_unknown_source_graceful_skip() -> None:
    """Unknown source (e.g. legacy api_key) → graceful skip without error."""
    ok, msg = check_subscription_cli_for_source("api_key")
    assert ok
    assert "api_key" in msg


# ---------------------------------------------------------------------------
# 4. Backend matrix — 4 cases (api_key reject + 3 valid)
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
