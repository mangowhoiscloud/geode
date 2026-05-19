"""Unit tests for ``core.cli.cmd_config`` (PR-ε1).

Covers the ``geode config migrate-petri-toml`` Typer subcommand:
- dry-run path renders the [self_improving_loop.petri.*] snippets to
  stdout and never mutates the destination
- ``--yes`` path appends the snippets to ``~/.geode/config.toml``
- destination-overlap guard refuses re-writes when sections already exist
- broken TOML in destination → refuses with actionable message + exit=2
- empty plan (no legacy file) → exits 0 silently with "nothing to migrate"

The migration-helper itself (``migration_plan_from_petri_toml``) is
covered separately in ``tests/plugins/petri_audit/test_user_overrides.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.cli.cmd_config import _render_petri_sections, app
from typer.testing import CliRunner

runner = CliRunner()


# ── _render_petri_sections (pure unit) ──────────────────────────────────


def test_render_empty_plan_yields_empty_string() -> None:
    assert _render_petri_sections({}) == ""


def test_render_single_role_emits_section_with_model_and_source() -> None:
    rendered = _render_petri_sections(
        {"auditor": {"model": "claude-sonnet-4-6", "source": "claude-cli"}}
    )
    assert "[self_improving_loop.petri.auditor]" in rendered
    assert 'model = "claude-sonnet-4-6"' in rendered
    assert 'source = "claude-cli"' in rendered


def test_render_preserves_role_insertion_order() -> None:
    plan = {
        "judge": {"model": "claude-opus-4-7"},
        "auditor": {"model": "claude-sonnet-4-6"},
        "target": {"source": "openai-codex"},
    }
    rendered = _render_petri_sections(plan)
    j_idx = rendered.index("[self_improving_loop.petri.judge]")
    a_idx = rendered.index("[self_improving_loop.petri.auditor]")
    t_idx = rendered.index("[self_improving_loop.petri.target]")
    assert j_idx < a_idx < t_idx


# ── geode config migrate-petri-toml dry-run ─────────────────────────────


def _stub_plan(monkeypatch: pytest.MonkeyPatch, plan: dict[str, dict[str, str]]) -> None:
    """Replace migration_plan_from_petri_toml to avoid touching the host's
    real ~/.geode/petri.toml."""
    import plugins.petri_audit.user_overrides as uo

    monkeypatch.setattr(uo, "migration_plan_from_petri_toml", lambda: plan)


def test_migrate_dry_run_prints_preview_and_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths

    target = tmp_path / "config.toml"
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(
        monkeypatch,
        {"auditor": {"model": "claude-opus-4-7", "source": "claude-cli"}},
    )
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "Re-run with --yes" in result.output
    assert "[self_improving_loop.petri.auditor]" in result.output
    assert not target.exists(), "dry-run must not create destination"


def test_migrate_yes_appends_to_config_when_destination_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths

    target = tmp_path / "config.toml"
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(
        monkeypatch,
        {
            "auditor": {"model": "claude-opus-4-7", "source": "claude-cli"},
            "judge": {"model": "claude-sonnet-4-6"},
        },
    )
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 0, result.output
    assert "Appended 2 role(s)" in result.output
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert "[self_improving_loop.petri.auditor]" in content
    assert "[self_improving_loop.petri.judge]" in content
    assert 'model = "claude-opus-4-7"' in content


def test_migrate_yes_preserves_existing_unrelated_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths

    target = tmp_path / "config.toml"
    target.write_text('[mcp.servers.calendar]\ncommand = "npx"\n', encoding="utf-8")
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(
        monkeypatch,
        {"target": {"model": "geode/gpt-5.5", "source": "openai-codex"}},
    )
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 0, result.output
    content = target.read_text(encoding="utf-8")
    # Existing content stays intact + new section appended.
    assert "[mcp.servers.calendar]" in content
    assert "[self_improving_loop.petri.target]" in content


def test_migrate_yes_refuses_when_destination_already_has_overlapping_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths

    target = tmp_path / "config.toml"
    target.write_text(
        '[self_improving_loop.petri.auditor]\nmodel = "old-model"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(
        monkeypatch,
        {"auditor": {"model": "claude-opus-4-7"}},
    )
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 1, result.output
    assert "auditor" in result.output
    assert "Refusing to append" in result.output
    # Destination MUST NOT be modified — guard against partial double-write.
    assert target.read_text(encoding="utf-8") == (
        '[self_improving_loop.petri.auditor]\nmodel = "old-model"\n'
    )


def test_migrate_yes_refuses_when_destination_has_broken_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths

    target = tmp_path / "config.toml"
    target.write_text("[broken_toml = unclosed", encoding="utf-8")
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(monkeypatch, {"auditor": {"model": "x"}})
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 2, result.output
    assert "not valid TOML" in result.output


def test_migrate_empty_plan_exits_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.paths

    target = tmp_path / "config.toml"
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(monkeypatch, {})
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "nothing to migrate" in result.output.lower()
    assert not target.exists()


# ── TOML escape correctness (Codex CRITICAL #1) ─────────────────────────


def test_render_escapes_embedded_double_quote() -> None:
    """A value with an embedded double-quote must serialize as escaped
    (\\") so the resulting TOML is parseable."""
    import tomllib

    rendered = _render_petri_sections(
        {"target": {"model": 'gpt-5.5 "tactical"', "source": "openai-codex"}}
    )
    parsed = tomllib.loads(rendered)
    assert parsed["self_improving_loop"]["petri"]["target"]["model"] == 'gpt-5.5 "tactical"'


def test_render_escapes_backslash() -> None:
    """A value with a literal backslash must serialize as ``\\\\`` so it
    round-trips through tomllib."""
    import tomllib

    rendered = _render_petri_sections({"auditor": {"source": "claude\\backslash"}})
    parsed = tomllib.loads(rendered)
    assert parsed["self_improving_loop"]["petri"]["auditor"]["source"] == "claude\\backslash"


def test_render_escapes_control_characters() -> None:
    """Control characters in a value must serialize as ``\\uXXXX``."""
    import tomllib

    rendered = _render_petri_sections({"x": {"model": "a\x01b"}})
    parsed = tomllib.loads(rendered)
    assert parsed["self_improving_loop"]["petri"]["x"]["model"] == "a\x01b"


def test_yes_migration_with_embedded_quotes_writes_valid_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: an override with embedded quotes survives the round-trip
    through ``--yes`` and the destination is valid TOML."""
    import tomllib

    import core.paths

    target = tmp_path / "config.toml"
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(
        monkeypatch,
        {"target": {"model": 'gpt-5.5 "tactical"', "source": "openai-codex"}},
    )
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(target.read_text(encoding="utf-8"))
    assert parsed["self_improving_loop"]["petri"]["target"]["model"] == 'gpt-5.5 "tactical"'


# ── atomic write / failure rollback (Codex CRITICAL #2) ─────────────────


def test_yes_atomic_write_rollback_preserves_existing_config_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``atomic_write_text`` raises mid-flight, the destination must
    keep its original contents — atomic_io's tmp+rename pattern means we
    never see a partial file even on simulated disk-full."""
    import core.paths

    from core.cli import cmd_config

    target = tmp_path / "config.toml"
    original = '[mcp.servers.calendar]\ncommand = "npx"\n'
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(monkeypatch, {"target": {"model": "geode/gpt-5.5"}})

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated disk full")

    monkeypatch.setattr(cmd_config, "atomic_write_text", _raise)
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code != 0
    assert target.read_text(encoding="utf-8") == original


def test_yes_accepts_source_only_legacy_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy ``[petri.judge] source = "claude-cli"`` (no model field)
    must migrate cleanly — the new schema's ``PetriRoleConfig.model``
    is optional so partial overrides parity-match the legacy semantics."""
    import tomllib

    import core.paths

    target = tmp_path / "config.toml"
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(monkeypatch, {"judge": {"source": "claude-cli"}})
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(target.read_text(encoding="utf-8"))
    assert parsed["self_improving_loop"]["petri"]["judge"]["source"] == "claude-cli"
    assert "model" not in parsed["self_improving_loop"]["petri"]["judge"]


def test_yes_schema_validation_blocks_invalid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy override with a syntactically valid but
    schema-invalid value (e.g. ``source = "bogus"``) must NOT land in
    ~/.geode/config.toml. The post-render pydantic validation refuses
    the write and the destination stays at its prior content
    (Codex HIGH — schema check, not just TOML syntax)."""
    import core.paths

    target = tmp_path / "config.toml"
    original = '[mcp.servers.calendar]\ncommand = "npx"\n'
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    # `source = "bogus"` is not in the Literal["claude-cli", "openai-codex",
    # "api_key", "auto"] union → pydantic rejects.
    _stub_plan(
        monkeypatch,
        {"auditor": {"model": "claude-opus-4-7", "source": "bogus"}},
    )
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 3, result.output
    assert "schema validation" in result.output
    # Destination untouched.
    assert target.read_text(encoding="utf-8") == original


def test_yes_post_render_validation_blocks_corrupt_combined_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the rendered plan would produce invalid combined TOML, the
    destination must NOT be written. Force the case by stubbing the
    renderer to return a known-bad snippet."""
    import core.paths

    from core.cli import cmd_config

    target = tmp_path / "config.toml"
    original = '[mcp.servers.calendar]\ncommand = "npx"\n'
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(core.paths, "GLOBAL_CONFIG_TOML", target)
    _stub_plan(monkeypatch, {"target": {"model": "x"}})
    monkeypatch.setattr(
        cmd_config,
        "_render_petri_sections",
        lambda plan: "[self_improving_loop.petri.target]\nmodel = unbalanced\n",
    )
    result = runner.invoke(app, ["--yes"])
    assert result.exit_code == 3, result.output
    assert "refusing to write" in result.output
    assert target.read_text(encoding="utf-8") == original
