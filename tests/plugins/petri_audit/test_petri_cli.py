"""Unit tests for the /petri slash command (P1-F).

The interactive TerminalMenu picker (``_picker_for_role``) requires a TTY
and is exercised only via smoke + non-TTY fallback here. The sub-command
sub-commands (status / model / source / reset) cover the bulk of the
behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plugins.petri_audit.cli import cmd_petri
from plugins.petri_audit.manifest import clear_manifest_cache

from plugins.petri_audit import credential_source as cs
from plugins.petri_audit import user_overrides as uo


@pytest.fixture(autouse=True)
def _petri_toml(tmp_path: Path, monkeypatch):
    """Redirect petri.toml + clear all stateful caches."""
    target = tmp_path / "petri.toml"
    monkeypatch.setenv("GEODE_PETRI_TOML", str(target))
    clear_manifest_cache()
    cs.clear_suppressions()
    yield target
    cs.clear_suppressions()
    clear_manifest_cache()


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPUAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch):
    monkeypatch.setattr(cs, "_settings_source", lambda family: None)


@pytest.fixture(autouse=True)
def _stub_oauth(monkeypatch):
    from plugins.petri_audit.adapters import claude_cli_backend, openai_codex_oauth

    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: False)
    monkeypatch.setattr(openai_codex_oauth, "is_available", lambda: False)


@pytest.fixture
def captured(monkeypatch):
    """Capture every console.print call for assertion."""
    from core.cli import commands as _pkg

    lines: list[str] = []

    class _StubConsole:
        def print(self, *args, **kwargs):
            lines.append(" ".join(str(a) for a in args))

        def input(self, prompt: str = "") -> str:
            lines.append(f"<input>{prompt}")
            return "y"

    monkeypatch.setattr(_pkg, "console", _StubConsole())
    return lines


# ── Status (/petri with no args) ────────────────────────────────────────────


def test_status_lists_three_roles(captured, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cmd_petri("")
    joined = "\n".join(captured)
    assert "auditor" in joined
    assert "target" in joined
    assert "judge" in joined
    assert "Petri bindings" in joined


def test_status_marks_missing_env(captured):
    # No env vars set → resolver raises → status shows 'unresolved' + missing env.
    cmd_petri("")
    joined = "\n".join(captured)
    assert "unresolved" in joined
    assert "Missing env" in joined
    assert "ANTHROPIC_API_KEY" in joined


def test_status_target_geode_prefix(captured, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cmd_petri("")
    joined = "\n".join(captured)
    assert "geode/" in joined  # target row uses geode prefix


# ── /petri model ───────────────────────────────────────────────────────────


def test_set_model_updates_override(captured, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cmd_petri("model auditor claude-opus-4-7")
    assert uo.read_role_override("auditor") == {"model": "claude-opus-4-7"}
    joined = "\n".join(captured)
    assert "claude-opus-4-7" in joined


def test_set_model_rejects_disallowed(captured):
    cmd_petri("model auditor glm-4-6")  # auditor doesn't allow GLM
    joined = "\n".join(captured)
    assert "not in allowed" in joined
    assert uo.read_role_override("auditor") == {}


def test_set_model_normalised_match(captured, monkeypatch):
    """Hyphens / case-insensitive match works (mirrors /model behaviour)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cmd_petri("model auditor CLAUDEOPUS47")  # normalised → claude-opus-4-7
    assert uo.read_role_override("auditor").get("model") == "claude-opus-4-7"


def test_set_model_family_change_resets_source(captured, monkeypatch):
    """Switching family (claude- → gpt-) erases the now-incompatible source."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    # Initial — claude family + claude-cli source.
    uo.save_role_override("auditor", model="claude-opus-4-7", source="claude-cli")
    cmd_petri("model auditor gpt-5.5")
    out = uo.read_role_override("auditor")
    assert out.get("model") == "gpt-5.5"
    assert "source" not in out  # erased


def test_set_model_unknown_role(captured):
    cmd_petri("model imposter claude-opus-4-7")
    joined = "\n".join(captured)
    assert "Unknown petri role" in joined


def test_set_model_missing_args(captured):
    cmd_petri("model auditor")  # missing model name
    joined = "\n".join(captured)
    assert "Usage" in joined


# ── /petri source ──────────────────────────────────────────────────────────


def test_set_source_updates_override(captured, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cmd_petri("source auditor api_key")
    assert uo.read_role_override("auditor") == {"source": "api_key"}


def test_set_source_rejects_invalid(captured):
    cmd_petri("source auditor imposter")
    joined = "\n".join(captured)
    assert "not allowed for family" in joined
    assert uo.read_role_override("auditor") == {}


def test_set_source_family_aware(captured):
    """A source belonging to a different family is rejected.
    auditor's default model is claude-* (family=anthropic) → openai-codex
    is not allowed for that family."""
    cmd_petri("source auditor openai-codex")
    joined = "\n".join(captured)
    assert "not allowed for family" in joined


def test_set_source_auto(captured):
    """'auto' is always a valid source for any family that lists it."""
    cmd_petri("source auditor auto")
    assert uo.read_role_override("auditor").get("source") == "auto"


# ── /petri reset ───────────────────────────────────────────────────────────


def test_reset_single_role(captured, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    uo.save_role_override("auditor", model="claude-opus-4-7")
    cmd_petri("reset auditor")
    assert uo.read_role_override("auditor") == {}


def test_reset_all_with_confirmation(captured):
    """'/petri reset' wipes after y confirmation (stub_console returns 'y')."""
    uo.save_role_override("auditor", model="claude-opus-4-7")
    uo.save_role_override("judge", source="api_key")
    cmd_petri("reset")
    assert uo.load_user_overrides() == {}


def test_reset_all_cancelled(captured, monkeypatch):
    """A 'no' answer at the confirmation prompt leaves overrides intact."""
    from core.cli import commands as _pkg

    class _DenyConsole:
        def print(self, *args, **kwargs):
            captured.append(" ".join(str(a) for a in args))

        def input(self, prompt: str = "") -> str:
            return "n"

    monkeypatch.setattr(_pkg, "console", _DenyConsole())

    uo.save_role_override("auditor", model="claude-opus-4-7")
    cmd_petri("reset")
    assert uo.read_role_override("auditor").get("model") == "claude-opus-4-7"


def test_reset_unknown_role(captured):
    cmd_petri("reset imposter")
    joined = "\n".join(captured)
    assert "Unknown petri role" in joined


# ── Interactive picker non-TTY fallback ────────────────────────────────────


def test_picker_non_tty_falls_back_to_status(captured, monkeypatch):
    """/petri auditor in a non-tty pipe shows status + usage hint instead
    of raising on TerminalMenu init."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    cmd_petri("auditor")
    joined = "\n".join(captured)
    assert "Petri bindings" in joined
    assert "Usage" in joined


def test_picker_unknown_role(captured):
    cmd_petri("imposter")
    joined = "\n".join(captured)
    assert "Unknown petri role" in joined


# ── Command map registration ───────────────────────────────────────────────


def test_command_map_contains_petri():
    from core.cli.commands._state import COMMAND_MAP

    assert COMMAND_MAP["/petri"] == "petri"


def test_resolve_action_petri():
    from core.cli.commands import resolve_action

    assert resolve_action("/petri") == "petri"
