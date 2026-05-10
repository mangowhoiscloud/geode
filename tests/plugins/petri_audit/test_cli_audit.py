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


def test_typer_audit_dry_run_prints_command() -> None:
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
    assert "judge=anthropic/claude-haiku-4-5-20251001" in result.output
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
    assert ns.dim_set == "5axes"  # default — pruned 17-dim set
    assert ns.cache is False
    assert ns.dry_run is True
    assert ns.yes is True


def test_slash_parser_accepts_dim_set_override() -> None:
    """``--dim-set full`` opts back into inspect-petri's 36-dim default."""
    parser = _build_slash_parser()
    ns = parser.parse_args(["--dim-set", "full"])
    assert ns.dim_set == "full"


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
