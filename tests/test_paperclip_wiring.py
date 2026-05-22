"""Paperclip wiring invariants — claude-cli / openai-codex source dispatch.

Pins:
- ``invoke_claude_cli`` / ``invoke_codex_cli`` run the right binary with
  the right argv shape and return stdout text. Missing binary raises
  ``CliInvocationError`` with an actionable message.
- ``_default_llm_call`` dispatches to claude-cli / codex-cli when
  ``MutatorConfig.source`` is paperclip; legacy "api_key" / "auto"
  paths are unaffected.
- ``_splice_section`` updates an existing TOML section in place, appends
  a fresh section when missing, and replaces a single key while
  preserving the rest of the section.
- ``_cmd_source_set`` rejects invalid sources / unknown keys without
  touching the config file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# cli_subprocess ------------------------------------------------------------


def test_invoke_claude_cli_argv_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """``claude --print --output-format text --append-system-prompt <SYS> <USER>``."""
    from core.self_improving_loop import cli_subprocess

    monkeypatch.setattr(cli_subprocess.shutil, "which", lambda b: f"/usr/local/bin/{b}")
    captured: dict[str, list[str]] = {}

    def _fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        return subprocess.CompletedProcess(
            argv, returncode=0, stdout="raw mutator JSON\n", stderr=""
        )

    monkeypatch.setattr(cli_subprocess.subprocess, "run", _fake_run)
    out = cli_subprocess.invoke_claude_cli(system_prompt="SYS", user_prompt="USR")
    assert out == "raw mutator JSON"
    assert captured["argv"][0] == "/usr/local/bin/claude"
    assert "--print" in captured["argv"]
    assert "--output-format" in captured["argv"]
    assert "--append-system-prompt" in captured["argv"]
    sys_idx = captured["argv"].index("--append-system-prompt")
    assert captured["argv"][sys_idx + 1] == "SYS"
    assert captured["argv"][-1] == "USR"


def test_invoke_codex_cli_argv_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """``codex exec --skip-git-repo-check <COMBINED system+user>``."""
    from core.self_improving_loop import cli_subprocess

    monkeypatch.setattr(cli_subprocess.shutil, "which", lambda b: f"/usr/local/bin/{b}")
    captured: dict[str, list[str]] = {}

    def _fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, returncode=0, stdout="ok ", stderr="")

    monkeypatch.setattr(cli_subprocess.subprocess, "run", _fake_run)
    out = cli_subprocess.invoke_codex_cli(system_prompt="SYS", user_prompt="USR")
    assert out == "ok"
    assert captured["argv"][0].endswith("/codex")
    assert captured["argv"][1] == "exec"
    assert "--skip-git-repo-check" in captured["argv"]
    combined = captured["argv"][-1]
    assert "System: SYS" in combined
    assert "User: USR" in combined


def test_invoke_claude_cli_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing binary → CliInvocationError with actionable install hint."""
    from core.self_improving_loop import cli_subprocess

    monkeypatch.setattr(cli_subprocess.shutil, "which", lambda b: None)
    monkeypatch.delenv(cli_subprocess.CLAUDE_CLI_BIN_ENV, raising=False)
    with pytest.raises(cli_subprocess.CliInvocationError, match="not found on \\$PATH"):
        cli_subprocess.invoke_claude_cli(system_prompt="s", user_prompt="u")


def test_binary_env_override_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``GEODE_CLAUDE_CLI_BIN`` overrides PATH lookup."""
    from core.self_improving_loop import cli_subprocess

    bin_path = tmp_path / "custom_claude"
    bin_path.write_text("#!/bin/sh\n")
    bin_path.chmod(0o755)
    monkeypatch.setenv(cli_subprocess.CLAUDE_CLI_BIN_ENV, str(bin_path))
    monkeypatch.setattr(cli_subprocess.shutil, "which", lambda b: None)
    captured: dict[str, list[str]] = {}

    def _fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli_subprocess.subprocess, "run", _fake_run)
    cli_subprocess.invoke_claude_cli(system_prompt="s", user_prompt="u")
    assert captured["argv"][0] == str(bin_path)


def test_invoke_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-zero exit → CliInvocationError carrying stderr clip."""
    from core.self_improving_loop import cli_subprocess

    monkeypatch.setattr(cli_subprocess.shutil, "which", lambda b: f"/bin/{b}")

    def _fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, returncode=2, stdout="", stderr="auth failed")

    monkeypatch.setattr(cli_subprocess.subprocess, "run", _fake_run)
    with pytest.raises(cli_subprocess.CliInvocationError, match="auth failed"):
        cli_subprocess.invoke_claude_cli(system_prompt="s", user_prompt="u")


def test_invoke_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``subprocess.TimeoutExpired`` → ``CliInvocationError`` with timeout hint."""
    from core.self_improving_loop import cli_subprocess

    monkeypatch.setattr(cli_subprocess.shutil, "which", lambda b: f"/bin/{b}")

    def _fake_run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=argv, timeout=180)

    monkeypatch.setattr(cli_subprocess.subprocess, "run", _fake_run)
    with pytest.raises(cli_subprocess.CliInvocationError, match="timed out"):
        cli_subprocess.invoke_claude_cli(system_prompt="s", user_prompt="u")


# runner dispatch -----------------------------------------------------------


def test_default_llm_call_dispatches_to_claude_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """source=claude-cli skips the API path entirely."""
    from core.self_improving_loop import runner

    cfg_mock = MagicMock()
    cfg_mock.mutator.default_model = "claude-opus-4-7"
    cfg_mock.mutator.source = "claude-cli"
    cfg_mock.mutator.max_tokens = 1024
    monkeypatch.setattr(
        "core.config.self_improving_loop.load_self_improving_loop_config",
        lambda: cfg_mock,
    )
    monkeypatch.setattr("core.config._resolve_provider", lambda m: "anthropic")
    monkeypatch.setattr("core.llm.adapters.resolve_agentic_adapter", lambda p: MagicMock())

    invoked = {"called": False, "system": "", "user": ""}

    def _fake_invoke(*, system_prompt: str, user_prompt: str) -> str:
        invoked["called"] = True
        invoked["system"] = system_prompt
        invoked["user"] = user_prompt
        return "from claude-cli"

    monkeypatch.setattr("core.self_improving_loop.cli_subprocess.invoke_claude_cli", _fake_invoke)
    result = runner._default_llm_call("SYS", "USR")
    assert result == "from claude-cli"
    assert invoked["called"] is True
    assert invoked["system"] == "SYS"
    assert invoked["user"] == "USR"


def test_default_llm_call_dispatches_to_codex_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """source=openai-codex skips the API path entirely."""
    from core.self_improving_loop import runner

    cfg_mock = MagicMock()
    cfg_mock.mutator.default_model = "gpt-5-codex"
    cfg_mock.mutator.source = "openai-codex"
    cfg_mock.mutator.max_tokens = 1024
    monkeypatch.setattr(
        "core.config.self_improving_loop.load_self_improving_loop_config",
        lambda: cfg_mock,
    )
    monkeypatch.setattr("core.config._resolve_provider", lambda m: "openai-codex")
    monkeypatch.setattr("core.llm.adapters.resolve_agentic_adapter", lambda p: MagicMock())

    def _fake_invoke(*, system_prompt: str, user_prompt: str) -> str:
        return "from codex-cli"

    monkeypatch.setattr("core.self_improving_loop.cli_subprocess.invoke_codex_cli", _fake_invoke)
    result = runner._default_llm_call("SYS", "USR")
    assert result == "from codex-cli"


def test_default_llm_call_api_key_path_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """source=api_key still routes through call_with_failover (no subprocess)."""
    from core.self_improving_loop import runner

    cfg_mock = MagicMock()
    cfg_mock.mutator.default_model = "claude-opus-4-7"
    cfg_mock.mutator.source = "api_key"
    cfg_mock.mutator.max_tokens = 1024
    monkeypatch.setattr(
        "core.config.self_improving_loop.load_self_improving_loop_config",
        lambda: cfg_mock,
    )
    monkeypatch.setattr("core.config._resolve_provider", lambda m: "anthropic")

    adapter = MagicMock()
    adapter.last_error = None
    monkeypatch.setattr("core.llm.adapters.resolve_agentic_adapter", lambda p: adapter)

    text_block = MagicMock()
    text_block.text = "from api"
    api_response = MagicMock()
    api_response.content = [text_block]

    async def _fake_failover(models: list[str], do_call: object) -> tuple[object, str]:
        return (api_response, models[0])

    monkeypatch.setattr("core.llm.router.call_with_failover", _fake_failover)

    claude_called = {"hit": False}

    def _explode_if_called(**_kw: object) -> str:
        claude_called["hit"] = True
        return "should never reach claude-cli"

    monkeypatch.setattr(
        "core.self_improving_loop.cli_subprocess.invoke_claude_cli", _explode_if_called
    )
    monkeypatch.setattr(
        "core.self_improving_loop.cli_subprocess.invoke_codex_cli", _explode_if_called
    )

    result = runner._default_llm_call("SYS", "USR")
    assert result == "from api"
    assert claude_called["hit"] is False


# TOML splicer --------------------------------------------------------------


def test_splice_section_appends_when_missing() -> None:
    from core.cli.commands.self_improving import _splice_section

    out = _splice_section(
        "[other]\nfoo = 1\n",
        "self_improving_loop.mutator",
        {"source": "claude-cli"},
    )
    assert "[self_improving_loop.mutator]" in out
    assert 'source = "claude-cli"' in out
    assert "[other]" in out  # preserved


def test_splice_section_replaces_existing_key() -> None:
    from core.cli.commands.self_improving import _splice_section

    src = '[self_improving_loop.mutator]\nsource = "api_key"\nmax_tokens = 1024\n'
    out = _splice_section(src, "self_improving_loop.mutator", {"source": "claude-cli"})
    assert 'source = "claude-cli"' in out
    assert 'source = "api_key"' not in out
    assert "max_tokens = 1024" in out  # untouched neighbor preserved


def test_splice_section_inserts_new_key_in_existing_section() -> None:
    from core.cli.commands.self_improving import _splice_section

    src = "[self_improving_loop.mutator]\nmax_tokens = 1024\n"
    out = _splice_section(src, "self_improving_loop.mutator", {"default_model": "claude-opus-4-7"})
    assert 'default_model = "claude-opus-4-7"' in out
    assert "max_tokens = 1024" in out


def test_splice_section_does_not_clobber_sibling_section() -> None:
    """Updating mutator must not touch ``[self_improving_loop.petri.auditor]``."""
    from core.cli.commands.self_improving import _splice_section

    src = (
        "[self_improving_loop.mutator]\n"
        'source = "api_key"\n'
        "\n"
        "[self_improving_loop.petri.auditor]\n"
        'source = "api_key"\n'
        'model = "claude-opus-4-7"\n'
    )
    out = _splice_section(src, "self_improving_loop.mutator", {"source": "claude-cli"})
    assert 'source = "claude-cli"' in out
    # Petri section untouched:
    assert "[self_improving_loop.petri.auditor]" in out
    assert out.count('source = "api_key"') == 1  # petri still has api_key
    assert 'model = "claude-opus-4-7"' in out


def test_splice_section_escapes_special_chars() -> None:
    from core.cli.commands.self_improving import _splice_section

    out = _splice_section("", "x", {"k": 'has " quote and \\ backslash'})
    assert 'k = "has \\" quote and \\\\ backslash"' in out


# source set --------------------------------------------------------------


def test_cmd_source_set_rejects_invalid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bad source value → no file written."""
    from core.cli.commands import self_improving

    fake_toml = tmp_path / "config.toml"
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    # Single-SoT (2026-05-22) — writer now resolves through
    # ``core.config.self_improving_loop._resolve_config_path`` which
    # reads the module-local import; patch that symbol too so the test
    # honors fake_toml regardless of which side calls in first.
    monkeypatch.setattr("core.config.self_improving_loop.GLOBAL_CONFIG_TOML", fake_toml)
    with patch.object(self_improving, "console") as cmock:
        self_improving._cmd_source_set(["source=bogus"])
    assert not fake_toml.exists()
    # Warning emitted, no success line
    printed = " ".join(str(call) for call in cmock.print.call_args_list)
    assert "invalid source" in printed


def test_cmd_source_set_persists_valid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """source=claude-cli writes the line to ~/.geode/config.toml."""
    from core.cli.commands import self_improving

    fake_toml = tmp_path / "config.toml"
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    # See sibling test for rationale on patching both symbols.
    monkeypatch.setattr("core.config.self_improving_loop.GLOBAL_CONFIG_TOML", fake_toml)
    self_improving._cmd_source_set(["source=claude-cli"])
    text = fake_toml.read_text(encoding="utf-8")
    assert "[self_improving_loop.mutator]" in text
    assert 'source = "claude-cli"' in text


def test_valid_sources_constant_matches_config_enum() -> None:
    """``_VALID_SOURCES`` must stay in sync with ``MutatorConfig.source`` Literal."""
    from core.cli.commands.self_improving import _VALID_SOURCES

    assert set(_VALID_SOURCES) == {"auto", "api_key", "claude-cli", "openai-codex"}


def test_persist_full_config_uses_plural_roles_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed-generation writes MUST land under ``...seed_generation.roles.<X>`` (plural).

    Pre-fix the writer used singular ``role.<X>`` which falls outside
    ``SeedGenerationConfig`` schema's ``extra="forbid"`` allowlist —
    next config load raises ``ValidationError``. Codex MCP catch on
    PR-PAPERCLIP.
    """
    from core.cli.commands import self_improving
    from core.config.self_improving_loop import load_self_improving_loop_config

    fake_toml = tmp_path / "config.toml"
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    monkeypatch.setattr("core.config.self_improving_loop.GLOBAL_CONFIG_TOML", fake_toml)
    self_improving._persist_full_config(
        mutator={},
        petri={},
        seed_generation={"miner": {"model": "claude-haiku-4-5", "source": "claude-cli"}},
    )
    text = fake_toml.read_text(encoding="utf-8")
    assert "[self_improving_loop.seed_generation.roles.miner]" in text
    assert "[self_improving_loop.seed_generation.role.miner]" not in text  # singular forbidden
    # Round-trip: the loader must accept what the writer produced.
    cfg = load_self_improving_loop_config()
    assert "miner" in cfg.seed_generation.roles
    assert cfg.seed_generation.roles["miner"].source == "claude-cli"
