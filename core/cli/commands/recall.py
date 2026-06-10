"""``/recall`` REPL slash command — operator surface for the memory-recall pool.

D-3 decision ③ (2026-06-10) — OL-C3 shipped the *writer*
(``core/memory/recall_writer.write_recall_entry``) as a pure utility whose
docstring promised "operator calls ``write_recall_entry(...)`` via CLI /
REPL slash", but no slash existed. The M4.4.1 *reader*
(``core/self_improving/loop/inject/memory_recall.py``, injected through
``in_context_wiring``) has been live the whole time, so the pool's only
write path was hand-editing ``~/.geode/memory/recall/*.md``. This module
closes that loop.

Sub-actions:

  /recall                       list (default)
  /recall list                  dense table — name / type / description
  /recall show <name>           print one entry verbatim
  /recall save <name> [--type t] [--desc "..."] [--body "..."] [--overwrite]
                                write one entry; missing --desc/--body are
                                prompted interactively when a TTY is attached

Read-write parity: ``list`` / ``show`` resolve the pool directory through
the same env override (``$GEODE_MEMORY_RECALL_DIR``) the reader and writer
share, and ``list`` parses entries with the reader's own parser
(``load_memory_entries``) — one frontmatter schema, one parser.
"""

from __future__ import annotations

import shlex
import sys

from core.ui.console import console

__all__ = ["cmd_recall"]

_VALID_TYPES_HINT = "user / feedback / project / reference"


def cmd_recall(args: str) -> None:
    """Dispatch the ``/recall`` sub-action. Empty args → ``list``."""
    try:
        parts = shlex.split(args) if args else []
    except ValueError as exc:
        console.print(f"  [warning]argument parse failed: {exc}[/warning]")
        return
    action = parts[0] if parts else "list"

    if action == "list":
        _cmd_list()
        return
    if action == "show":
        _cmd_show(parts[1:])
        return
    if action == "save":
        _cmd_save(parts[1:])
        return

    console.print()
    console.print(f"  [warning]Unknown action: /recall {action}[/warning]")
    console.print("  [muted]Available: list / show <name> / save <name> [flags][/muted]")
    console.print()


def _cmd_list() -> None:
    """Render the recall pool as a dense table (reader's parser = one schema)."""
    from core.memory.recall_writer import resolve_recall_dir
    from core.self_improving.loop.inject.memory_recall import load_memory_entries

    entries = load_memory_entries()
    console.print()
    console.print("  [header]Memory recall pool[/header]")
    console.print(f"  [muted]{resolve_recall_dir()}[/muted]")
    console.print()
    if not entries:
        console.print("    [muted]no entries — /recall save <name> writes the first one[/muted]")
        console.print()
        return
    name_width = max(len(e.name) for e in entries)
    type_width = max((len(e.type) for e in entries if e.type), default=4)
    for entry in sorted(entries, key=lambda e: e.name):
        type_label = entry.type or "-"
        console.print(
            f"    {entry.name:<{name_width}}  [muted]{type_label:<{type_width}}[/muted]  "
            f"{_clip(entry.description, 80)}"
        )
    console.print()
    console.print(f"  [muted]{len(entries)} entries · /recall show <name> for full body[/muted]")
    console.print()


def _cmd_show(opts: list[str]) -> None:
    """Print one entry's file verbatim (frontmatter + body)."""
    from core.memory.recall_writer import resolve_recall_dir

    if not opts:
        console.print("  [warning]show: needs an entry name — /recall show <name>[/warning]")
        return
    name = opts[0]
    file_path = resolve_recall_dir() / f"{name}.md"
    if not file_path.is_file():
        console.print()
        console.print(f"  [warning]no entry named {name!r}[/warning] [muted]({file_path})[/muted]")
        console.print("  [muted]/recall list shows available names[/muted]")
        console.print()
        return
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        console.print(f"  [warning]read failed:[/warning] {exc}")
        return
    console.print()
    console.print(f"  [muted]{file_path}[/muted]")
    console.print()
    console.print(content)


def _cmd_save(opts: list[str]) -> None:
    """Write one entry via ``write_recall_entry``.

    Positional ``<name>`` is required. ``--desc`` / ``--body`` fall back
    to interactive prompts on a TTY; without a TTY they are required flags
    so scripted callers fail loudly instead of writing empty fields.
    """
    from core.memory.recall_writer import (
        RECALL_TYPE_FEEDBACK,
        VALID_RECALL_TYPES,
        write_recall_entry,
    )

    name = ""
    type_label = RECALL_TYPE_FEEDBACK
    description = ""
    body = ""
    overwrite = False
    i = 0
    while i < len(opts):
        tok = opts[i]
        if tok == "--overwrite":
            overwrite = True
        elif tok in {"--type", "--desc", "--body"}:
            if i + 1 >= len(opts):
                console.print(f"  [warning]{tok} requires a value[/warning]")
                return
            value = opts[i + 1]
            if tok == "--type":
                type_label = value
            elif tok == "--desc":
                description = value
            else:
                body = value
            i += 1
        elif tok.startswith("--"):
            console.print(f"  [warning]unknown flag: {tok!r}[/warning]")
            return
        elif not name:
            name = tok
        else:
            console.print(f"  [warning]unexpected extra argument: {tok!r}[/warning]")
            return
        i += 1

    if not name:
        console.print(
            "  [warning]save: needs a name — "
            '/recall save <name> [--type t] [--desc "..."] [--body "..."][/warning]'
        )
        return
    if type_label not in VALID_RECALL_TYPES:
        console.print(
            f"  [warning]invalid type: {type_label!r} (valid: {_VALID_TYPES_HINT})[/warning]"
        )
        return

    if not description:
        prompted_desc = _prompt_field("description (one line)", flag="--desc")
        if prompted_desc is None:
            return
        description = prompted_desc
    if not body:
        prompted_body = _prompt_field("body", flag="--body")
        if prompted_body is None:
            return
        body = prompted_body
    if not description or not body:
        console.print("  [warning]save: description and body must be non-empty[/warning]")
        return

    written_path = write_recall_entry(
        name=name,
        description=description,
        body=body,
        type_label=type_label,
        overwrite=overwrite,
    )
    console.print()
    if written_path is None:
        console.print(
            f"  [warning]not written[/warning] — entry {name!r} already exists "
            "(re-run with --overwrite) or the write failed (see log)"
        )
    else:
        console.print(f"  [success]saved[/success]  {written_path}")
        console.print(f"    type {type_label} · injected by memory-recall on keyword match")
    console.print()


def _prompt_field(label: str, *, flag: str) -> str | None:
    """Interactive fallback for a missing field. ``None`` = abort."""
    if not sys.stdin.isatty():
        console.print(f"  [warning]save: {flag} is required without a TTY[/warning]")
        return None
    try:
        return str(console.input(f"  {label}: ")).strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        console.print("  [muted]aborted[/muted]")
        return None


def _clip(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"
