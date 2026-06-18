"""CLI subcommand: ``geode config`` — config inspection + migration helpers.

Phase ε1 of the 2026-05-19 self-improving-loop config consolidation plan
(`docs/plans/2026-05-19-self-improving-loop-config-consolidation.md`).
Wires the existing :func:`plugins.petri_audit.user_overrides.migration_plan_from_petri_toml`
read-only helper into a Typer command so operators can move per-role
overrides from the legacy ``~/.geode/petri.toml`` into the new
``[self_improving_loop.petri.*]`` sections of ``~/.geode/config.toml``.

Default mode is dry-run — the command prints the TOML snippets the
operator should append, and never mutates either file. Passing
``--yes`` writes the snippets to ``~/.geode/config.toml`` automatically
(after refusing if the file already contains overlapping sections so a
re-run does not double-write).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import typer
from rich.console import Console

from core.config.toml_edit import toml_escape
from core.memory.atomic_write import atomic_write_text

app = typer.Typer(
    name="config",
    help="GEODE config inspection + migration helpers.",
    no_args_is_help=True,
    add_completion=False,
)

_console = Console()


def _render_petri_sections(plan: dict[str, dict[str, str]]) -> str:
    """Render ``plan`` as ``[self_improving_loop.autoresearch.<role>]`` TOML blocks.

    Each block carries ``model`` / ``source`` lines for the role. Empty
    plan yields an empty string. Roles iterate in dict insertion order so
    the operator's existing ``~/.geode/petri.toml`` ordering is preserved.

    Step J-b.1 (2026-05-23) — destination relocated from
    ``[self_improving_loop.petri.<role>]`` (executor namespace) to
    ``[self_improving_loop.autoresearch.<role>]`` (control namespace).
    autoresearch is the upper layer that owns model selection;
    petri_audit is the executor that reads.
    """
    if not plan:
        return ""
    lines: list[str] = []
    for role, override in plan.items():
        lines.append(f"[self_improving_loop.autoresearch.{role}]")
        for key, value in override.items():
            lines.append(f'{key} = "{toml_escape(value)}"')
        lines.append("")
    return "\n".join(lines)


def _config_already_has_petri_section(path: Path) -> list[str]:
    """Return role names whose ``[self_improving_loop.autoresearch.<role>]``
    section is already present in ``path``. Empty list when ``path`` is
    absent or no overlapping sections exist.

    Step J-b.1 — checks the new namespace + the legacy
    ``[self_improving_loop.petri.<role>]`` namespace so a re-run of
    ``migrate-petri-toml`` does not double-write either layout.
    """
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        # Operator's config is broken — refuse to write rather than corrupt
        # further. Surfaced as a separate guard message by the caller.
        raise
    sip = raw.get("self_improving_loop")
    if not isinstance(sip, dict):
        return []
    overlap: set[str] = set()
    autoresearch = sip.get("autoresearch")
    if isinstance(autoresearch, dict):
        for role_name in ("target", "judge", "auditor"):
            if isinstance(autoresearch.get(role_name), dict):
                overlap.add(role_name)
    legacy_petri = sip.get("petri")
    if isinstance(legacy_petri, dict):
        overlap.update(legacy_petri.keys())
    return sorted(overlap)


@app.command("migrate-petri-toml")
def migrate_petri_toml(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=(
            "Append the migration plan to ~/.geode/config.toml. "
            "Without this flag the command prints the snippets and exits "
            "(dry-run preview)."
        ),
    ),
) -> None:
    """Move petri.* sections from ~/.geode/petri.toml into
    ``[self_improving_loop.autoresearch.<role>]`` sections of
    ``~/.geode/config.toml`` (control-layer SoT, Step J-b.1).

    Dry-run by default — prints the TOML snippets the operator should
    append. With --yes, the snippets are appended to
    ~/.geode/config.toml (creating it if absent). The legacy file
    is left intact in both modes so the operator can roll back; deleting
    it is the operator's call after verifying the new path resolves.

    Refuses --yes when the destination already contains overlapping
    role sections (either the new ``autoresearch.<role>`` namespace or
    the legacy ``petri.<role>`` namespace) — prevents accidental
    double-write on re-run.
    """
    from plugins.petri_audit.user_overrides import migration_plan_from_petri_toml

    from core.paths import GLOBAL_CONFIG_TOML

    plan = migration_plan_from_petri_toml()
    if not plan:
        _console.print("[muted]No entries in ~/.geode/petri.toml — nothing to migrate.[/muted]")
        raise typer.Exit(code=0)

    rendered = _render_petri_sections(plan)

    if not yes:
        _console.print(
            "# Migration plan from ~/.geode/petri.toml → "
            "~/.geode/config.toml [self_improving_loop.autoresearch.<role>]"
        )
        _console.print("# Re-run with --yes to append automatically.")
        _console.print("")
        _console.print(rendered, markup=False, highlight=False)
        raise typer.Exit(code=0)

    target = GLOBAL_CONFIG_TOML
    try:
        existing_roles = _config_already_has_petri_section(target)
    except tomllib.TOMLDecodeError as exc:
        _console.print(
            f"{target} is not valid TOML ({exc}); refusing to append. "
            "Fix the file by hand and re-run.",
            markup=False,
            style="red",
        )
        raise typer.Exit(code=2) from exc

    overlap = sorted(set(existing_roles) & set(plan.keys()))
    if overlap:
        # markup=False so literal ``[self_improving_loop.autoresearch.X]``
        # is not interpreted by rich as a (missing) style tag and stripped.
        _console.print(
            f"{target} already has [self_improving_loop.autoresearch.{{{','.join(overlap)}}}] "
            "(or legacy [petri.<role>]) section(s). Refusing to append — "
            "remove the existing entries first "
            "or apply the migration plan manually.",
            markup=False,
            style="red",
        )
        raise typer.Exit(code=1)

    existing_text = target.read_text(encoding="utf-8") if target.is_file() else ""
    if existing_text and not existing_text.endswith("\n"):
        existing_text += "\n"
    new_content = (
        existing_text
        + "\n# Migrated from ~/.geode/petri.toml (PR-ε1, "
        + "self-improving-loop config consolidation)\n"
        + rendered
        + "\n"
    )
    # Final validation — the rendered content must (1) parse cleanly when
    # combined with the existing config, and (2) pass pydantic schema
    # validation. The schema check catches the case where a legacy
    # ``petri.toml`` entry is syntactically valid TOML but semantically
    # invalid for ``SelfImprovingLoopConfig`` (e.g. unknown ``source``
    # value), which would atomically land a poisoned config that breaks
    # every later ``load_self_improving_loop_config()`` consumer.
    try:
        parsed = tomllib.loads(new_content)
    except tomllib.TOMLDecodeError as exc:
        _console.print(
            f"rendered migration would corrupt {target} ({exc}); refusing to write. "
            "This is a bug in the migrator — please report it.",
            markup=False,
            style="red",
        )
        raise typer.Exit(code=3) from exc
    sip_section = parsed.get("self_improving_loop")
    if isinstance(sip_section, dict):
        try:
            from core.config.self_improving import SelfImprovingLoopConfig

            SelfImprovingLoopConfig.model_validate(sip_section)
        except Exception as exc:
            _console.print(
                f"migrated [self_improving_loop] section fails schema validation "
                f"({exc}); refusing to write. Fix the legacy petri.toml entries "
                "(unknown source / model / extra field) before re-running.",
                markup=False,
                style="red",
            )
            raise typer.Exit(code=3) from exc
    # Atomic write via tmp+rename — prevents partial-write corruption on
    # interruption (KeyboardInterrupt, kill, power loss) so the operator
    # always sees either the old config intact or the new config in full.
    atomic_write_text(target, new_content)
    _console.print(f"[green]Appended {len(plan)} role(s) to {target}.[/green]")
    _console.print(
        "[muted]Legacy ~/.geode/petri.toml is unchanged — verify the new path "
        "via `geode audit` smoke, then delete the legacy file manually.[/muted]"
    )


@app.command(name="explain")
def explain(
    key: str = typer.Argument("model", help="Settings field to explain (default: model)"),
) -> None:
    """Show every config layer's candidate for KEY and which one wins.

    C-1 of the config-unification sprint — the answer to "I changed the
    config but the model didn't move": the winning layer and everything
    it masks, with file paths.
    """
    from core.config.explain import explain_field

    try:
        report = explain_field(key)
    except Exception as exc:
        typer.echo(f"explain failed for {key!r}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("")
    typer.echo(
        f"  {report.field_name}  (env var {report.env_var}"
        + (f", toml key {report.toml_key}" if report.toml_key else "")
        + ")"
    )
    typer.echo(f"  effective: {report.effective!r}")
    typer.echo("")
    typer.echo(f"  {'layer':22} {'value':28} source")
    for entry in report.layers:
        marker = "  WINNER" if entry.is_winner else ("  masked" if entry.is_masked else "")
        value = "-" if entry.value is None else repr(entry.value)
        typer.echo(f"  {entry.layer:22} {value:28} {entry.source}{marker}")
    masked = report.masked_layers
    typer.echo("")
    if masked:
        winner_layer = report.winner.layer if report.winner else "?"
        typer.echo(
            f"  {len(masked)} layer(s) masked by {winner_layer}."
            " Edit the WINNER layer (or remove its line) to change the effective value."
        )
    else:
        typer.echo("  no masking - single layer set.")
    typer.echo("")
