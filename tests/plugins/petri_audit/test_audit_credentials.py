"""ANTHROPIC_API_KEY injection into the audit subprocess + opus-4-8 default.

A sub-agent worker that calls run_audit (the seed-gen pilot's petri_audit tool
call) does not load ~/.geode/.env, so the inspect subprocess inherited an env
WITHOUT ANTHROPIC_API_KEY → inspect aborted in ~2s with "Could not resolve
authentication method" and every dim zero-filled. PR-PETRI-AUDIT-DEFAULT-OPUS-CREDS
resolves the key from the GEODE credential source and injects it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from plugins.petri_audit.runner import _resolve_anthropic_api_key, run_audit


def test_resolve_anthropic_api_key_prefers_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.config

    monkeypatch.setattr(
        core.config.settings, "anthropic_api_key", "sk-from-settings", raising=False
    )
    assert _resolve_anthropic_api_key() == "sk-from-settings"


def test_resolve_anthropic_api_key_falls_to_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.config

    monkeypatch.setattr(core.config.settings, "anthropic_api_key", "", raising=False)
    with patch("dotenv.dotenv_values", return_value={"ANTHROPIC_API_KEY": "sk-from-dotenv"}):
        assert _resolve_anthropic_api_key() == "sk-from-dotenv"


def test_resolve_anthropic_api_key_none_when_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.config

    monkeypatch.setattr(core.config.settings, "anthropic_api_key", "", raising=False)
    with patch("dotenv.dotenv_values", return_value={}):
        assert _resolve_anthropic_api_key() is None


def test_run_audit_injects_anthropic_key_into_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ANTHROPIC_API_KEY is absent from the env, run_audit resolves it and
    passes it through to the inspect subprocess so the auditor/judge can auth."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        captured["env"] = kwargs.get("env")
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    with (
        patch("plugins.petri_audit.runner._resolve_anthropic_api_key", return_value="sk-injected"),
        patch("plugins.petri_audit.runner.subprocess.run", side_effect=_fake_run),
        patch("plugins.petri_audit.runner.shutil.which", return_value="/usr/bin/inspect"),
    ):
        run_audit(
            judge="claude-opus-4-8",
            auditor="claude-opus-4-8",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=2,
            dry_run=False,
            yes=True,
            auto_archive=False,
        )
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["ANTHROPIC_API_KEY"] == "sk-injected"


def test_run_audit_keeps_existing_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """An already-present ANTHROPIC_API_KEY is NOT overwritten by the resolver."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-already-here")
    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        captured["env"] = kwargs.get("env")
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    # The resolver must NOT even be consulted when the key is already present.
    with (
        patch(
            "plugins.petri_audit.runner._resolve_anthropic_api_key",
            side_effect=AssertionError("resolver should not run when key present"),
        ),
        patch("plugins.petri_audit.runner.subprocess.run", side_effect=_fake_run),
        patch("plugins.petri_audit.runner.shutil.which", return_value="/usr/bin/inspect"),
    ):
        run_audit(
            judge="claude-opus-4-8",
            auditor="claude-opus-4-8",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=2,
            dry_run=False,
            yes=True,
            auto_archive=False,
        )
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["ANTHROPIC_API_KEY"] == "sk-already-here"


def test_resolve_anthropic_api_key_rejects_oauth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """An OAuth-shaped token (sk-ant-oat…) mis-stored under ANTHROPIC_API_KEY is
    NOT injected — api_key path only (Anthropic TOS forbids OAuth batch use)."""
    import core.config

    monkeypatch.setattr(
        core.config.settings, "anthropic_api_key", "sk-ant-oat01-deadbeef", raising=False
    )
    # settings holds an OAuth token → rejected; dotenv empty → None overall.
    with patch("dotenv.dotenv_values", return_value={}):
        assert _resolve_anthropic_api_key() is None


def test_anthropic_auditor_judge_default_to_api_key_payg() -> None:
    """An anthropic auditor/judge with no per-role source override defaults to
    the api_key (PAYG) path, NOT the claude-cli OAuth route (which refuses the
    adversarial auditor role). openai/codex roles are unaffected (separate test
    coverage in test_oauth_judge)."""
    from plugins.petri_audit.runner import run_audit

    with patch("plugins.petri_audit.user_overrides.read_role_override", return_value={}):
        report = run_audit(
            judge="claude-opus-4-8",
            auditor="claude-opus-4-8",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=2,
            dry_run=True,
        )
    joined = " ".join(report.command)
    assert "auditor=anthropic/claude-opus-4-8" in joined
    assert "judge=anthropic/claude-opus-4-8" in joined
    assert "claude-cli/" not in joined  # PAYG api_key path, not OAuth


def test_explicit_source_override_wins_over_payg_default() -> None:
    """An explicit per-role source override is still honored over the api_key
    default (the default only fills when no override is set)."""
    from plugins.petri_audit.runner import run_audit

    def _override(role: str) -> dict[str, str]:
        return {"source": "claude-cli"} if role in ("auditor", "judge") else {}

    with patch("plugins.petri_audit.user_overrides.read_role_override", side_effect=_override):
        report = run_audit(
            judge="claude-opus-4-8",
            auditor="claude-opus-4-8",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=2,
            dry_run=True,
        )
    joined = " ".join(report.command)
    assert "auditor=claude-cli/claude-opus-4-8" in joined
