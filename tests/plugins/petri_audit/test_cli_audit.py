"""Typer + slash entry-point tests for petri_audit (no [audit] extra needed).

Both surfaces are thin adapters over ``runner.run_audit``; tests assert
that ``--dry-run`` flows through and the rendered output mentions the
constructed command + cost estimate.
"""

from __future__ import annotations

import pytest
from core.cli import app
from plugins.petri_audit.cli_audit import _build_slash_parser, cmd_audit_slash
from typer.testing import CliRunner

runner = CliRunner()


def test_typer_audit_dry_run_prints_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "plugins.petri_audit.adapters.claude_cli_backend.is_available", lambda: True
    )
    result = runner.invoke(
        app,
        [
            "audit",
            "--judge",
            "claude-haiku-4-5-20251001",
            "--auditor",
            "claude-sonnet-4-6",
            "--target",
            "claude-opus-4-7",
            "--seeds",
            "1",
            "--max-turns",
            "3",
            "--tags",
            "sycophancy",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Petri audit" in result.output
    assert "inspect eval inspect_petri/audit" in result.output
    # CSA-3 flip — was claude-code/, now claude-cli/.
    assert (
        "judge=anthropic/claude-haiku-4-5-20251001" in result.output
    )  # PAYG default (anthropic judge)
    assert "target=geode/claude-opus-4-7" in result.output
    assert "seed_instructions=tags:sycophancy" in result.output
    assert "dry-run" in result.output.lower()


def test_typer_audit_default_is_dry_run() -> None:
    """A bare ``geode audit`` invocation must NOT spend — default dry_run=True."""
    result = runner.invoke(app, ["audit"])
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower()


def test_slash_parser_parses_short_and_long_flags() -> None:
    parser = _build_slash_parser()
    ns = parser.parse_args(
        [
            "-j",
            "gpt-5.4-mini",
            "-a",
            "claude-sonnet-4-6",
            "-t",
            "claude-opus-4-7",
            "-s",
            "2",
            "-m",
            "4",
            "--tags",
            "self_preservation",
            "--no-cache",
            "--dry-run",
            "-y",
        ]
    )
    assert ns.judge == "gpt-5.4-mini"
    assert ns.auditor == "claude-sonnet-4-6"
    assert ns.target == "claude-opus-4-7"
    assert ns.seeds == 2
    assert ns.max_turns == 4
    assert ns.tags == "self_preservation"
    assert ns.dim_set == "subset"  # default — pruned 22-dim set
    assert ns.cache is False
    assert ns.dry_run is True
    assert ns.yes is True


def test_slash_parser_judge_auditor_target_default_to_none_for_petri_role_lookup() -> None:
    """SoT-flip (2026-05-22) — when ``--judge`` / ``--auditor`` /
    ``--target`` are omitted, the slash parser must leave them ``None``
    so the runner can defer to ``[self_improving_loop.petri.<role>].model``
    via the binding registry. Prior to this PR the parser hardcoded
    ``"claude-haiku-4-5-20251001"`` (judge) and ``"claude-opus-4-7"``
    (auditor) defaults — argv-level pin that silently bypassed the
    operator's role config (PR-G3-style reader-assumption drift).
    Pinning ``None`` here forces a future cost/quality default-tweak
    to either route through ``[petri.<role>]`` or break this test."""
    parser = _build_slash_parser()
    ns = parser.parse_args([])
    assert ns.judge is None
    assert ns.auditor is None
    assert ns.target is None


def test_slash_parser_accepts_dim_set_override() -> None:
    """``--dim-set full`` opts back into inspect-petri's 36-dim default."""
    parser = _build_slash_parser()
    ns = parser.parse_args(["--dim-set", "full"])
    assert ns.dim_set == "full"


def test_slash_parser_accepts_seed_select_id_form() -> None:
    """``--seed-select id:a,b,c,d`` parses cleanly so N7' can pin 4
    seeds per operational axis without tag-set hacking."""
    parser = _build_slash_parser()
    ns = parser.parse_args(
        [
            "--seed-select",
            "id:helpful_only_model_harmful_task,broken_tool_error_handling",
        ]
    )
    assert ns.seed_select == ("id:helpful_only_model_harmful_task,broken_tool_error_handling")


def test_slash_handler_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_audit_slash(
        "--judge claude-haiku-4-5-20251001 --target claude-opus-4-7 --seeds 1 --max-turns 2 --dry-run"
    )
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Petri audit" in out
    assert "inspect eval inspect_petri/audit" in out


def test_slash_handler_invalid_args_does_not_raise(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # argparse normally calls sys.exit on a bad flag; the slash handler
    # intercepts so the REPL stays alive.
    cmd_audit_slash("--mystery flag")
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "invalid /audit arguments" in out


def test_slash_handler_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_audit_slash("--help")
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "/audit" in out
    assert "--judge" in out
