"""PR-SIL-5THEME C6 — D1 provider B/C closure tests.

operator decision (durable memory ``project_payg_exclusion_decision.md``,
2026-05-23) 으로 autoresearch / Petri audit 의 provider 선택지에서 PAYG
(``api_key``) 영구 exclude. 잔존 옵션 = claude-cli / openai-codex / auto.

C6 의 3 wiring:
1. ``Source`` literal 에서 ``api_key`` 제거 → Pydantic 가 reject (silent
   leak 차단)
2. ``PetriRoleConfig.source`` + ``AutoresearchConfig.source`` default
   ``auto → claude-cli`` (subscription-first 명시)
3. ``autoresearch/prepare.py`` 의 ``check_subscription_cli_for_source``
   pre-flight — binary 부재 시 actionable error
"""

from __future__ import annotations

import pytest
from autoresearch.prepare import check_subscription_cli_for_source
from core.config.self_improving_loop import (
    AutoresearchConfig,
    PetriRoleConfig,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# 1. Source literal — api_key reject
# ---------------------------------------------------------------------------


def test_petri_role_source_api_key_rejected() -> None:
    """PetriRoleConfig 에 ``source = "api_key"`` 설정 시 Pydantic 가 reject —
    PAYG 가 audit role 선택지에서 영구 제거됐다는 invariant.

    operator 가 config.toml 에 ``[self_improving_loop.petri.target]
    source = "api_key"`` 명시 → ValidationError + 어느 값이 invalid 인지
    명시되는 Pydantic 메시지로 surface.
    """
    with pytest.raises(ValidationError) as exc_info:
        PetriRoleConfig(source="api_key")  # type: ignore[arg-type]
    msg = str(exc_info.value)
    assert "source" in msg
    assert "api_key" in msg


def test_autoresearch_source_api_key_rejected() -> None:
    """AutoresearchConfig 도 동일 — ``source = "api_key"`` Pydantic reject."""
    with pytest.raises(ValidationError) as exc_info:
        AutoresearchConfig(source="api_key")  # type: ignore[arg-type]
    msg = str(exc_info.value)
    assert "source" in msg
    assert "api_key" in msg


def test_petri_role_source_accepts_claude_cli() -> None:
    """``source = "claude-cli"`` 수락 (subscription default)."""
    p = PetriRoleConfig(source="claude-cli")
    assert p.source == "claude-cli"


def test_petri_role_source_accepts_openai_codex() -> None:
    """``source = "openai-codex"`` 수락 (ChatGPT Plus OAuth)."""
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
    import autoresearch.prepare as prepare_module

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
    import autoresearch.prepare as prepare_module

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
    import autoresearch.prepare as prepare_module

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


def test_backend_matrix_api_key_rejected_petri_role() -> None:
    """4-backend matrix: api_key 만 reject, 다른 3 (claude-cli / openai-codex /
    auto) 는 accept."""
    # Reject
    with pytest.raises(ValidationError):
        PetriRoleConfig(source="api_key")  # type: ignore[arg-type]
    # Accept (3 valid sources)
    for source in ("claude-cli", "openai-codex", "auto"):
        cfg = PetriRoleConfig(source=source)  # type: ignore[arg-type]
        assert cfg.source == source


def test_backend_matrix_api_key_rejected_autoresearch() -> None:
    """AutoresearchConfig 도 같은 matrix."""
    with pytest.raises(ValidationError):
        AutoresearchConfig(source="api_key")  # type: ignore[arg-type]
    for source in ("claude-cli", "openai-codex", "auto"):
        cfg = AutoresearchConfig(source=source)  # type: ignore[arg-type]
        assert cfg.source == source
