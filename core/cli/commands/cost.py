"""``/cost`` slash command — LLM cost dashboard.

Hosts ``cmd_cost`` plus the ``_budget_bar`` / ``_get_cost_budget`` /
``_set_cost_budget`` helpers. Extracted from the monolithic
``core/cli/commands.py`` (Tier 3 #9) — every function body is preserved
byte-identical from the legacy module.

Tests that monkeypatch ``core.cli.commands._set_cost_budget`` /
``core.cli.commands._get_cost_budget`` reach the call sites here through
the deferred ``import core.cli.commands as _pkg`` lookup, mirroring the
pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def cmd_cost(args: str) -> None:
    """Handle /cost command — LLM cost dashboard.

    /cost              → session + monthly summary
    /cost daily        → today's breakdown
    /cost recent       → last 10 LLM calls
    /cost budget <amt> → set monthly budget ceiling (USD)
    """
    from datetime import date

    from core.cli import commands as _pkg
    from core.llm.token_tracker import get_tracker
    from core.llm.usage_store import get_usage_store

    sub = args.strip().lower() if args else ""
    store = get_usage_store()
    tracker = get_tracker()
    acc = tracker.accumulator

    # --- session summary (always shown unless subcommand) ---
    if not sub or sub == "session":
        _pkg.console.print()
        _pkg.console.print("  [header]Cost Dashboard[/header]")

        # Session
        if acc.calls:
            _pkg.console.print()
            _pkg.console.print("  [label]Session[/label]")
            _pkg.console.print(f"    Calls: {len(acc.calls)}")
            _pkg.console.print(
                f"    Tokens: {acc.total_input_tokens:,} in / {acc.total_output_tokens:,} out"
            )
            _pkg.console.print(f"    Cost: [warning]${acc.total_cost_usd:.4f}[/warning]")
        else:
            _pkg.console.print()
            _pkg.console.print("  [label]Session[/label]  [muted]no calls yet[/muted]")

        # Monthly
        summary = store.get_monthly_summary()
        today = date.today()
        _pkg.console.print()
        _pkg.console.print(f"  [label]Month ({today.year}-{today.month:02d})[/label]")
        _pkg.console.print(f"    Calls: {summary['total_calls']}")
        _pkg.console.print(f"    Cost: [warning]${summary['total_cost']:.2f}[/warning]")

        if summary["by_model"]:
            for model, stats in sorted(summary["by_model"].items(), key=lambda x: -x[1]["cost"]):
                _pkg.console.print(
                    f"      {model}: ${stats['cost']:.2f} ({int(stats['calls'])} calls)"
                )

        # Budget
        budget = _pkg._get_cost_budget()
        if budget > 0:
            pct = summary["total_cost"] / budget * 100
            bar = _pkg._budget_bar(pct)
            _pkg.console.print()
            cost = summary["total_cost"]
            _pkg.console.print(f"  [label]Budget[/label]  ${cost:.2f} / ${budget:.2f}  {bar}")
        _pkg.console.print()
        return

    # --- daily ---
    if sub in {"daily", "today"}:
        daily = store.get_daily_summary()
        _pkg.console.print()
        _pkg.console.print(f"  [header]Daily Cost — {daily['date']}[/header]")
        _pkg.console.print(f"    Calls: {daily['total_calls']}")
        _pkg.console.print(f"    Cost: [warning]${daily['total_cost']:.4f}[/warning]")
        if daily["by_model"]:
            for model, stats in sorted(daily["by_model"].items(), key=lambda x: -x[1]["cost"]):
                _pkg.console.print(
                    f"      {model}: ${stats['cost']:.4f} ({int(stats['calls'])} calls)"
                )
        _pkg.console.print()
        return

    # --- recent ---
    if sub == "recent":
        records = store.get_recent_records(10)
        if not records:
            _pkg.console.print("  [muted]No recent records.[/muted]")
            _pkg.console.print()
            return

        from datetime import datetime

        _pkg.console.print()
        _pkg.console.print("  [header]Recent LLM Calls (last 10)[/header]")
        for rec in records:
            ts = datetime.fromtimestamp(rec.ts).strftime("%H:%M:%S")
            _pkg.console.print(
                f"    {ts}  {rec.model:<30s}  "
                f"{rec.input_tokens:>6,}in {rec.output_tokens:>6,}out  "
                f"${rec.cost_usd:.4f}"
            )
        _pkg.console.print()
        return

    # --- budget ---
    if sub.startswith("budget"):
        rest = sub[6:].strip()
        if not rest:
            budget = _pkg._get_cost_budget()
            if budget > 0:
                _pkg.console.print(f"  [label]Monthly budget:[/label] ${budget:.2f}")
            else:
                _pkg.console.print("  [muted]No budget set.[/muted]")
            _pkg.console.print("  [muted]Usage: /cost budget <amount>[/muted]")
            _pkg.console.print()
            return

        try:
            amount = float(rest)
        except ValueError:
            _pkg.console.print(f"  [warning]Invalid amount: {rest}[/warning]")
            _pkg.console.print()
            return

        _pkg._set_cost_budget(amount)
        _pkg.console.print(f"  [success]Monthly budget set: ${amount:.2f}[/success]")
        _pkg.console.print()
        return

    _pkg.console.print("  [warning]Usage: /cost [daily|recent|budget <amount>][/warning]")
    _pkg.console.print()


def _budget_bar(pct: float) -> str:
    """Render a budget progress bar."""
    filled = int(min(pct, 100) / 5)
    empty = 20 - filled
    if pct >= 90:
        style = "error"
    elif pct >= 70:
        style = "warning"
    else:
        style = "success"
    bar = "█" * filled + "░" * empty
    return f"[{style}]{bar}[/{style}] {pct:.0f}%"


def _get_cost_budget() -> float:
    """Read monthly budget from .geode/config.toml or env."""
    import os

    env_val = os.environ.get("GEODE_MONTHLY_BUDGET", "")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass

    config_path = Path(".geode") / "config.toml"
    if config_path.exists():
        import tomllib

        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            return float(data.get("cost", {}).get("monthly_budget", 0))
        except (OSError, ValueError, KeyError):
            return 0.0
    return 0.0


def _set_cost_budget(amount: float) -> None:
    """Write monthly budget to .geode/config.toml."""
    config_path = Path(".geode") / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    found_section = False
    found_key = False

    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        in_cost_section = False
        for line in raw.splitlines():
            if line.strip() == "[cost]":
                in_cost_section = True
                found_section = True
                lines.append(line)
                continue
            if in_cost_section and line.strip().startswith("monthly_budget"):
                lines.append(f"monthly_budget = {amount}")
                found_key = True
                in_cost_section = False
                continue
            if in_cost_section and line.strip().startswith("["):
                # New section — insert before it
                if not found_key:
                    lines.append(f"monthly_budget = {amount}")
                    found_key = True
                in_cost_section = False
            lines.append(line)

        if found_section and not found_key:
            lines.append(f"monthly_budget = {amount}")
    else:
        lines = []

    if not found_section:
        if lines:
            lines.append("")
        lines.append("[cost]")
        lines.append(f"monthly_budget = {amount}")

    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
