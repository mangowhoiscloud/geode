"""CLI memory action handler — extracted from cli/__init__.py for SRP.

Handles memory-related slash commands: rule CRUD, memory search, memory save.
"""

from __future__ import annotations

import logging
from typing import Any

from rich.console import Console

from core.hooks.system import HookEvent

log = logging.getLogger(__name__)
console = Console()


def handle_memory_action(
    intent: Any,
    user_text: str,
    is_offline: bool,
    *,
    fire_hook: Any = None,
) -> None:
    """Handle memory-related actions (P0-A + P1-B).

    Accepts either an object with an `args` dict attribute, or a plain dict.

    Args:
        intent: Routing intent with args dict or a plain dict.
        user_text: Original user input text.
        is_offline: Whether running in offline mode.
        fire_hook: Callable(event, data) to fire hook events.
    """
    args = intent if isinstance(intent, dict) else intent.args

    # Determine sub-action from tool routing
    rule_action = args.get("rule_action")
    query = args.get("query")
    key = args.get("key")
    content = args.get("content")

    if rule_action:
        _handle_rule_action(rule_action, args, content, fire_hook)
    elif query:
        _handle_memory_search(query, args)
    elif key and content:
        _handle_memory_save(key, content, fire_hook)
    else:
        console.print()
        console.print("  [muted]Memory command not recognized. Try:[/muted]")
        console.print("  [muted]  '이전 분석 결과 검색해' — search memory[/muted]")
        console.print("  [muted]  '규칙 목록 보여줘' — list rules[/muted]")
        console.print("  [muted]  '이 결과 기억해' — save to memory[/muted]")
        console.print()


def _handle_rule_action(
    rule_action: str,
    args: dict[str, Any],
    content: str | None,
    fire_hook: Any,
) -> None:
    from core.memory.project import ProjectMemory

    mem = ProjectMemory()
    if rule_action == "list":
        rules = mem.list_rules()
        console.print()
        console.print("  [header]Active Analysis Rules[/header]")
        if not rules:
            console.print("  [muted]No rules found.[/muted]")
        for r in rules:
            paths_str = ", ".join(r.get("paths", []))
            console.print(f"  - [value]{r['name']}[/value] ({paths_str})")
            if r.get("preview"):
                console.print(f"    [muted]{r['preview'][:80]}...[/muted]")
        console.print()
    elif rule_action == "create":
        name = args.get("name", "")
        paths = args.get("paths", [])
        rule_content = content or ""
        if not name:
            console.print("  [warning]Rule name is required.[/warning]")
            return
        ok = mem.create_rule(name, paths, rule_content)
        if ok:
            console.print(f"  [success]Rule '{name}' created.[/success]")
            if fire_hook:
                fire_hook(HookEvent.RULE_CREATED, {"name": name, "paths": paths})
        else:
            console.print(
                f"  [warning]Failed to create rule '{name}' (may already exist).[/warning]"
            )
        console.print()
    elif rule_action == "update":
        name = args.get("name", "")
        rule_content = content or ""
        if not name:
            console.print("  [warning]Rule name is required.[/warning]")
            return
        ok = mem.update_rule(name, rule_content)
        if ok:
            console.print(f"  [success]Rule '{name}' updated.[/success]")
            if fire_hook:
                fire_hook(HookEvent.RULE_UPDATED, {"name": name})
        else:
            console.print(f"  [warning]Failed to update rule '{name}'.[/warning]")
        console.print()
    elif rule_action == "delete":
        name = args.get("name", "")
        if not name:
            console.print("  [warning]Rule name is required.[/warning]")
            return
        ok = mem.delete_rule(name)
        if ok:
            console.print(f"  [success]Rule '{name}' deleted.[/success]")
            if fire_hook:
                fire_hook(HookEvent.RULE_DELETED, {"name": name})
        else:
            console.print(f"  [warning]Rule '{name}' not found.[/warning]")
        console.print()


def _handle_memory_search(query: str, args: dict[str, Any]) -> None:
    from core.tools.memory_tools import MemorySearchTool

    search_tool = MemorySearchTool()
    tier = args.get("tier", "all")
    search_result = search_tool.execute(query=query, tier=tier)
    matches = search_result.get("result", {}).get("matches", [])
    console.print()
    console.print(f"  [header]Memory Search: '{query}'[/header]")
    if not matches:
        console.print("  [muted]No matches found.[/muted]")
    for m in matches:
        tier_label = m.get("tier", "?")
        source = m.get("source", m.get("session_id", ""))
        console.print(f"  - [{tier_label}] {source}")
        if "matching_lines" in m:
            for line in m["matching_lines"][:3]:
                console.print(f"    [muted]{line}[/muted]")
        if "preview" in m:
            console.print(f"    [muted]{m['preview'][:80]}...[/muted]")
    console.print()


def _handle_memory_save(key: str, content: str, fire_hook: Any) -> None:
    from core.tools.memory_tools import MemorySaveTool

    save_tool = MemorySaveTool()
    save_result = save_tool.execute(
        session_id=key,
        data={"content": content},
        persistent=True,
    )
    saved = save_result.get("result", {}).get("saved", False)
    if saved:
        console.print(f"  [success]Saved to memory: '{key}'[/success]")
        if fire_hook:
            fire_hook(HookEvent.MEMORY_SAVED, {"key": key})
    else:
        console.print("  [warning]Failed to save to memory.[/warning]")
    console.print()
