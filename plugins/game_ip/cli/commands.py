"""Game-IP slash commands and help text fragments.

Step 4 (domain-free-core) relocated the IP-specific halves of
``core/cli/commands.py`` into this plugin module so ``core/cli/commands.py``
no longer reaches into ``plugins.game_ip.fixtures``. The slashes are
re-merged into the generic ``COMMAND_MAP`` registry at bootstrap via
``GameIPDomain.register_slash_commands`` (see
``core/cli/commands.py:install_domain_commands``).
"""

from __future__ import annotations

from typing import Any as _Any

from core.ui.console import console

# ---------------------------------------------------------------------------
# Game-IP slash command entries (merged into core's COMMAND_MAP at bootstrap)
# ---------------------------------------------------------------------------

GAME_IP_SLASHES: dict[str, str] = {
    "/list": "list",
    "/analyze": "analyze",
    "/a": "analyze",
    "/run": "run",
    "/r": "run",
    "/search": "search",
    "/s": "search",
    "/generate": "generate",
    "/gen": "generate",
    "/report": "report",
    "/rpt": "report",
    "/batch": "batch",
    "/b": "batch",
    "/compare": "compare",
}


# ---------------------------------------------------------------------------
# Game-IP help fragment (rendered after the generic /help body)
# ---------------------------------------------------------------------------


def render_help_fragment() -> None:
    """Render the IP-specific block of ``/help``.

    Called from ``core.cli.commands.show_help`` via the optional
    ``DomainPort.render_help_fragment`` hook (when present); kept as a
    standalone function so the plugin owns its own copy.
    """
    console.print("  [label]/analyze[/label] <IP name>  — Analyze an IP (dry-run)")
    console.print("  [label]/run[/label] <IP name>      — Analyze with real LLM")
    console.print("  [label]/search[/label] <query>     — Search IPs by keyword")
    console.print("  [label]/list[/label]               — Show available IPs")
    console.print("  [label]/generate[/label] [count]   — Generate synthetic demo data")
    console.print("  [label]/report[/label] <IP> [fmt]  — Generate report (md/html/json)")
    console.print("  [label]/batch[/label] <IP1> <IP2>  — Batch analyze multiple IPs")
    console.print("  [label]/compare[/label] <A> <B>    — Compare two IPs")


# ---------------------------------------------------------------------------
# Game-IP slash command implementations
# ---------------------------------------------------------------------------


def cmd_list() -> None:
    """List available IP fixtures."""
    from plugins.game_ip.fixtures import FIXTURE_MAP as _FIXTURE_MAP

    console.print()
    console.print("  [header]Available IPs[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"    [value]{name.title()}[/value]")
    console.print()


def cmd_generate(args: str) -> None:
    """Handle /generate command — create synthetic demo data.

    /generate         → generate 5 IPs
    /generate 10      → generate 10 IPs
    /generate 3 mecha → generate 3 IPs of specific genre
    """
    from plugins.game_ip.fixtures.generator import GENRE_PARAMS, generate_batch

    parts = args.strip().split() if args.strip() else []

    count = 5
    genre = None

    if len(parts) >= 1 and parts[0].isdigit():
        count = int(parts[0])
        count = max(1, min(20, count))
    if len(parts) >= 2:
        genre = parts[1].lower()
        if genre not in GENRE_PARAMS:
            console.print(f"  [warning]Unknown genre: {genre}[/warning]")
            console.print(f"  [muted]Available: {', '.join(GENRE_PARAMS.keys())}[/muted]")
            console.print()
            return

    ips = generate_batch(count, genre=genre, seed=42)

    console.print()
    console.print(f"  [header]Generated {len(ips)} Synthetic IPs[/header]")
    for ip in ips:
        tier = ip.data["expected_results"]["tier"]
        score = ip.data["expected_results"]["final_score"]
        tier_style = {"S": "tier_s", "A": "tier_a", "B": "tier_b", "C": "tier_c"}.get(tier, "bold")
        console.print(
            f"    [{tier_style}]{tier}[/{tier_style}] {score:5.1f}  "
            f"[value]{ip.ip_name:<20}[/value] {ip.genre} / {ip.media_type}"
        )
    console.print()


def cmd_batch(
    args: str,
    *,
    run_fn: _Any = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> list[_Any]:
    """Handle /batch command — analyze multiple IPs in sequence.

    /batch Balatro Hades Celeste
    /batch Balatro,Hades,Celeste
    """
    if not args.strip():
        console.print("  [warning]Usage: /batch <IP1> <IP2> ... or <IP1>,<IP2>,...[/warning]")
        return []

    # Parse IP names (comma or space separated)
    raw = args.strip()
    if "," in raw:
        ip_names = [n.strip() for n in raw.split(",") if n.strip()]
    else:
        ip_names = [n.strip() for n in raw.split() if n.strip()]

    if not ip_names:
        console.print("  [warning]No IP names provided.[/warning]")
        return []

    console.print()
    console.print(f"  [header]Batch Analysis — {len(ip_names)} IPs[/header]")
    mode = "[muted]dry-run[/muted]" if dry_run else "[success]live[/success]"
    console.print(f"  Mode: {mode}")
    console.print()

    results: list[_Any] = []
    for i, ip_name in enumerate(ip_names, 1):
        console.print(f"  [{i}/{len(ip_names)}] [value]{ip_name}[/value]")
        if run_fn is not None:
            try:
                with console.status(
                    f"  [cyan]Analyzing {ip_name}...[/cyan]",
                    spinner="dots",
                    spinner_style="cyan",
                ):
                    result = run_fn(ip_name, dry_run=dry_run, verbose=verbose)
                results.append(result)
            except Exception as exc:
                console.show_cursor(True)
                console.print(f"  [error]Failed: {exc}[/error]")
                results.append(None)
        else:
            results.append(None)

    console.print()
    console.print(f"  [success]Batch complete: {len(results)}/{len(ip_names)} processed[/success]")
    console.print()
    return results
