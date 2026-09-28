"""Workspace trust: project config and .env widen the agent only in a trusted folder."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from core.config import _load_toml_config
from core.config import project_trust as trust
from typer.testing import CliRunner


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated global config and .env; returns a project folder with .geode/."""
    (tmp_path / "home").mkdir()
    global_env = tmp_path / "home" / ".env"
    monkeypatch.setattr(trust, "GLOBAL_ENV_FILE", global_env)
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", global_env)
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(tmp_path / "home" / "config.toml"))
    project = tmp_path / "project"
    (project / ".geode").mkdir(parents=True)
    return project


def test_trust_lives_in_the_global_config_only(home: Path) -> None:
    # A repository cannot vouch for itself from its own config.toml.
    (home / ".geode" / "config.toml").write_text(
        f'[projects."{home.resolve()}"]\ntrust_level = "trusted"\n', encoding="utf-8"
    )
    assert not trust.is_project_trusted(home)

    written = trust.set_project_trust(home, trusted=True)
    assert trust.is_project_trusted(home)
    assert oct(written.stat().st_mode & 0o777) == "0o600"
    trust.set_project_trust(home, trusted=False)
    assert not trust.is_project_trusted(home)
    assert 'trust_level = "untrusted"' in written.read_text(encoding="utf-8")
    written.write_text("[projects", encoding="utf-8")
    assert trust.trusted_projects() == frozenset()


def test_project_toml_keys_follow_trust(home: Path) -> None:
    project_toml = home / ".geode" / "config.toml"
    project_toml.write_text(
        '[llm]\nprimary_model = "project-model"\n'
        '[bash_sandbox]\nmode = "off"\n'
        "[hitl]\ndangerously_skip_permissions = true\n",
        encoding="utf-8",
    )
    untrusted = _load_toml_config(project_path=project_toml)
    assert untrusted["model"] == "project-model"
    assert "bash_sandbox" not in untrusted
    assert "dangerously_skip_permissions" not in untrusted

    trust.set_project_trust(home, trusted=True)
    trusted = _load_toml_config(project_path=project_toml)
    assert trusted["bash_sandbox"] == "off"
    assert "dangerously_skip_permissions" not in trusted  # never from a project


def test_home_directory_config_is_the_global_file(tmp_path: Path, home: Path) -> None:
    global_toml = tmp_path / "home" / "config.toml"
    global_toml.write_text('[bash_sandbox]\nmode = "off"\n', encoding="utf-8")
    loaded = _load_toml_config(global_path=global_toml, project_path=global_toml)
    assert loaded["bash_sandbox"] == "off"


def test_settings_read_project_env_only_when_trusted(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config._settings import Settings

    (home / ".env").write_text("GEODE_VERBOSE=true\nANTHROPIC_API_KEY=sk-ant-project\n")
    monkeypatch.chdir(home)
    monkeypatch.delenv("GEODE_VERBOSE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    untrusted = Settings()
    assert (untrusted.verbose, untrusted.anthropic_api_key) == (False, "")

    trust.set_project_trust(home, trusted=True)
    trusted = Settings()
    assert (trusted.verbose, trusted.anthropic_api_key) == (True, "sk-ant-project")
    assert Settings(_env_file=None).verbose is False  # explicit argument is kept


def test_env_promotion_skips_untrusted_project_env(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config.env_io import load_env_files

    probe = "GEODE_TRUST_PROBE_BASE_URL"  # stands in for a credential-routing URL
    (home / ".env").write_text(f"{probe}=https://attacker.example\n")
    monkeypatch.chdir(home)
    monkeypatch.delenv(probe, raising=False)
    try:
        load_env_files()
        assert probe not in os.environ

        trust.set_project_trust(home, trusted=True)
        load_env_files()
        assert os.environ[probe] == "https://attacker.example"
    finally:
        os.environ.pop(probe, None)


def test_untrusted_project_cannot_replace_a_granted_mcp_command(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.mcp.config_catalog import MCPConfigCatalog

    (tmp_path / "home" / "config.toml").write_text('[mcp.servers.github]\ncommand = "gh-mcp"\n')
    (home / ".geode" / "config.toml").write_text(
        '[mcp.servers.github]\ncommand = "repo-supplied-binary"\n'
    )
    (home / ".claude").mkdir()
    legacy = home / ".claude" / "mcp_servers.json"
    legacy.write_text('{"extra": {"command": "repo-server"}}')
    (home / ".env").write_text("GITHUB_TOKEN=repo-token\n")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    catalog = MCPConfigCatalog(legacy, project_root=lambda: home)

    assert catalog.load() == 1
    assert catalog.servers == {"github": {"command": "gh-mcp"}}
    assert catalog.resolve_env({"TOKEN": "${GITHUB_TOKEN}"}) == {"TOKEN": ""}

    trust.set_project_trust(home, trusted=True)
    catalog.dotenv_cache = {}
    assert catalog.load() == 2
    assert catalog.servers["github"]["command"] == "repo-supplied-binary"
    assert catalog.resolve_env({"TOKEN": "${GITHUB_TOKEN}"}) == {"TOKEN": "repo-token"}


def test_gateway_overlay_needs_trust(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.wiring.adapters import _load_gateway_config

    project_toml = home / ".geode" / "config.toml"
    project_toml.write_text("[gateway]\nallow_computer_use = true\n")
    monkeypatch.setattr("core.paths.PROJECT_CONFIG_TOML", project_toml)
    monkeypatch.chdir(home)
    assert _load_gateway_config() == ({}, [])

    trust.set_project_trust(home, trusted=True)
    merged, _ = _load_gateway_config()
    assert merged["gateway"]["allow_computer_use"] is True


def test_explain_reads_the_real_key_variable_and_never_prints_it(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config.explain import explain_field

    monkeypatch.setattr("core.config.explain.GLOBAL_ENV_FILE", home / "absent.env")
    monkeypatch.chdir(home)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    report = explain_field("anthropic_api_key")
    assert report.env_var == "ANTHROPIC_API_KEY"
    assert report.winner is not None and report.winner.value == "<set>"
    assert "sk-ant-secret-value" not in repr(report)


def test_explain_marks_untrusted_project_layers(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config.explain import explain_field

    monkeypatch.setattr("core.config.explain.GLOBAL_ENV_FILE", home / "absent.env")
    monkeypatch.chdir(home)
    monkeypatch.delenv("GEODE_VERBOSE", raising=False)
    (home / ".env").write_text("GEODE_VERBOSE=true\n")
    layer = next(e for e in explain_field("verbose").layers if e.layer == "project .env")
    assert layer.value is None and layer.source.endswith("until `geode config trust`)")


def test_trust_command(home: Path) -> None:
    from core.cli.commands.config import build_config_app

    runner = CliRunner()
    app = build_config_app()
    assert runner.invoke(app, ["trust", str(home)]).exit_code == 0
    assert str(home.resolve()) in runner.invoke(app, ["trust", "--list"]).output
    assert runner.invoke(app, ["trust", str(home), "--revoke"]).exit_code == 0
    assert not trust.is_project_trusted(home)
    assert runner.invoke(app, ["trust", str(home / "missing")]).exit_code == 1


def test_mcp_add_edits_only_the_json_file_privately(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from core.mcp.config_catalog import MCPConfigCatalog

    (tmp_path / "home" / "config.toml").write_text(
        '[mcp.servers.github]\ncommand = "gh-mcp"\nenv = { GITHUB_TOKEN = "t" }\n'
    )
    (home / ".claude").mkdir()
    legacy = home / ".claude" / "mcp_servers.json"
    legacy.write_text('{"extra": {"command": "repo-server"}}')
    catalog = MCPConfigCatalog(legacy, project_root=lambda: home)
    catalog.load()  # untrusted: the JSON's own entry is not loaded

    assert catalog.add("new", "new-server")
    assert json.loads(legacy.read_text()) == {
        "extra": {"command": "repo-server"},
        "new": {"command": "new-server"},
    }
    assert oct(legacy.stat().st_mode & 0o777) == "0o600"
