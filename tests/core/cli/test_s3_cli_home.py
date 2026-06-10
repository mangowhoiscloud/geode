"""S-3 CLI structure guards (2026-06-11).

Pins the dual-home fold (``core/cli/cmd_*.py`` → ``core/cli/commands/``)
and the scripts→CLI promotion (``geode seeds assemble`` / ``geode hub
build`` as thin pass-through wrappers).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_cmd_star_modules_are_gone() -> None:
    """No second home — typer command modules live under commands/."""
    leftovers = sorted(p.name for p in (REPO_ROOT / "core" / "cli").glob("cmd_*.py"))
    assert leftovers == [], f"cmd_* dual home regrew: {leftovers}"
    for name in ("adapters", "config", "lifecycle", "schedule", "skill"):
        assert (REPO_ROOT / "core" / "cli" / "commands" / f"{name}.py").is_file(), name


def test_seeds_and_hub_subcommands_registered() -> None:
    from core.cli import app

    registered = {grp.name for grp in app.registered_groups}
    assert {"seeds", "hub"} <= registered


def test_promoted_wrappers_pass_args_verbatim(monkeypatch) -> None:
    """The wrappers forward ctx.args to the script main and exit with its code."""
    import click
    import pytest
    import scripts.assemble_seed_pool as assemble_mod
    import typer
    from core.cli.commands.seed_pool import seeds_assemble

    captured: dict[str, list[str]] = {}

    def _fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(assemble_mod, "main", _fake_main)
    ctx = typer.Context(click.Command("assemble"))
    ctx.args = ["--per-run", "5", "--force"]
    with pytest.raises(click.exceptions.Exit) as excinfo:
        seeds_assemble(ctx)
    assert excinfo.value.exit_code == 0
    assert captured["argv"] == ["--per-run", "5", "--force"]
