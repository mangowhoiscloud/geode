"""``geode reindex`` — rebuild the cross-project search index.

Hermes Phase 1d.2 ships a derived ``~/.geode/search/global.db`` FTS5
index that mirrors every per-project ``sessions.db``'s ``messages``
rows so the ``session_search`` tool can answer ``scope="all"``
queries. The index is intentionally a rebuild-from-source artefact
(no ground truth lives here) — this command does the rebuild.

**When to run**: after any large operator action that adds / drops
sessions (long capture sweep, multi-project migration, manual DB
prune) when you want the next ``session_search(scope="all")`` to
see the new state. The default flow is "run once per session" — the
per-project FTS index inside each ``sessions.db`` stays live via
the Phase 1c triggers.

Output: per-project ``project_id  rows_indexed`` lines + a summary
of total rows + total projects.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

log = logging.getLogger(__name__)


_PROJECTS_ROOT_OPTION = typer.Option(
    None,
    "--projects-root",
    help=(
        "Override the projects directory walked for source sessions DBs. "
        "Defaults to ~/.geode/projects/. Useful for test fixtures."
    ),
)


def reindex(projects_root: Path | None = _PROJECTS_ROOT_OPTION) -> None:
    """Rebuild ``~/.geode/search/global.db`` from every project's sessions.db."""
    from rich.console import Console
    from rich.table import Table

    from core.memory.search_index import SearchIndex

    console = Console()
    console.print("[cyan]Rebuilding cross-project search index...[/cyan]")
    try:
        with SearchIndex() as index:
            stats = index.rebuild(projects_root=projects_root)
    except Exception as exc:  # pragma: no cover — surfaced to operator
        console.print(f"[red]reindex failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not stats:
        console.print(
            "[yellow]No projects found under ~/.geode/projects/[/yellow] — "
            "global.db is empty. Run a session first."
        )
        return

    table = Table(title="Cross-project search index — rebuild summary")
    table.add_column("project_id", style="cyan")
    table.add_column("rows_indexed", justify="right", style="cyan")
    total = 0
    for project_id in sorted(stats):
        rows = stats[project_id]
        total += rows
        table.add_row(project_id, str(rows))
    console.print(table)
    console.print(f"[success]Indexed {total} messages across {len(stats)} projects.[/success]")
