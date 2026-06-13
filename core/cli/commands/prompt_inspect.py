"""``geode prompt`` — assembled-system-prompt inspection (PR-PROMPT-DUMP).

Operator entry point for the prompt-refactor sprint's P0: dump the REAL
assembled system prompt per (model, surface) cell with structure summary
and token figures, into ``~/.geode/diagnostics/prompt-dump/<ts>/``.
"""

from __future__ import annotations

import typer

prompt_app = typer.Typer(name="prompt", help="Assembled system prompt inspection")


@prompt_app.command(name="dump")
def prompt_dump(
    model: list[str] = typer.Option(  # noqa: B008 — typer option factory
        None, "--model", "-m", help="Model id(s); default = each provider's primary"
    ),
    surface: list[str] = typer.Option(  # noqa: B008
        None, "--surface", "-s", help="Surface(s); default = all 6 known surfaces"
    ),
    measure: bool = typer.Option(
        False,
        "--measure",
        help="Real token count via Anthropic count_tokens (free endpoint; "
        "single-ruler across models). Falls back to chars//4 estimate.",
    ),
) -> None:
    """Dump assembled system prompts for a (model, surface) matrix."""
    from core.agent.prompt_dump import DUMP_SURFACES, dump_matrix
    from core.config import ANTHROPIC_PRIMARY, GLM_PRIMARY, OPENAI_PRIMARY

    models = tuple(model) if model else (ANTHROPIC_PRIMARY, OPENAI_PRIMARY, GLM_PRIMARY)
    surfaces = tuple(surface) if surface else DUMP_SURFACES

    rows = dump_matrix(models, surfaces, measure=measure)

    token_label = "tokens" if measure else "~tokens(est)"
    typer.echo(f"{'model':<22} {'surface':<11} {'chars':>7} {token_label:>13}  dup-tags")
    for row in rows:
        dup_field = ",".join(row.duplicate_tags) if row.duplicate_tags else "-"
        typer.echo(
            f"{row.model:<22} {row.surface:<11} {row.chars:>7} {row.est_tokens:>13}  {dup_field}"
        )
    typer.echo(f"\n{len(rows)} cells -> {rows[0].path.parent}")
    any_dup = sorted({t for row in rows for t in row.duplicate_tags})
    if any_dup:
        typer.echo(f"WARNING: duplicate section tags detected: {', '.join(any_dup)}")
