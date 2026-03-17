"""Batch analysis — run GEODE pipeline on multiple IPs."""

from __future__ import annotations

import logging
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from core.config import settings
from core.fixtures import FIXTURE_MAP

log = logging.getLogger(__name__)
console = Console()

# Per-IP analysis timeout (seconds)
_IP_TIMEOUT_S = 120


def select_ips(
    *,
    top: int = 20,
    genre: str | None = None,
    ips: list[str] | None = None,
) -> list[str]:
    """Select IPs for batch analysis.

    Priority: explicit list > genre filter > all fixtures.
    """
    if ips:
        # Validate provided IPs exist
        valid: list[str] = []
        for ip in ips:
            key = ip.lower().strip()
            if key in FIXTURE_MAP:
                valid.append(ip)
            else:
                log.warning("IP '%s' not found in fixtures, skipping", ip)
        return valid[:top]

    candidates = sorted(FIXTURE_MAP.keys())

    if genre:
        from core.fixtures import load_fixture

        filtered: list[str] = []
        for ip_key in candidates:
            try:
                fixture = load_fixture(ip_key)
                ip_genres = fixture.get("ip_info", {}).get("genre", [])
                if isinstance(ip_genres, list):
                    if any(genre.lower() in g.lower() for g in ip_genres):
                        filtered.append(ip_key)
                elif genre.lower() in str(ip_genres).lower():
                    filtered.append(ip_key)
            except Exception:
                log.debug("Failed to load fixture for genre filter: %s", ip_key)
        candidates = filtered

    return candidates[:top]


def _run_analysis_standalone(ip_name: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Run analysis pipeline for a single IP (no circular import to core.cli).

    This is thread-safe: each call creates its own GeodeRuntime.
    """
    from core.runtime import GeodeRuntime

    key = ip_name.lower().strip()
    if key not in FIXTURE_MAP:
        return {
            "ip_name": ip_name,
            "tier": "ERR",
            "final_score": 0.0,
            "cause": f"Unknown IP: {ip_name}",
            "error": True,
        }

    # Each thread gets its own runtime (thread-safe isolation)
    runtime = GeodeRuntime.create(ip_name)
    graph = runtime.compile_graph()

    initial_state: dict[str, Any] = {
        "ip_name": ip_name,
        "pipeline_mode": "full_pipeline",
        "dry_run": dry_run,
        "verbose": False,
        "analyses": [],
        "evaluations": {},
        "errors": [],
        # Ensemble config injection (L5 nodes read from state, not settings)
        "_ensemble_mode": settings.ensemble_mode,
        "_secondary_analysts": settings.secondary_analysts,
    }

    if not dry_run:
        tool_injection = runtime.get_tool_state_injection(mode="full_pipeline")
        initial_state.update(tool_injection)

    try:
        result = graph.invoke(initial_state, config=runtime.thread_config)  # type: ignore[call-overload]
    finally:
        runtime.shutdown()

    output: dict[str, Any] = {
        "ip_name": ip_name,
        "tier": result.get("tier", "?"),
        "final_score": result.get("final_score", 0.0),
    }

    synthesis = result.get("synthesis")
    if synthesis:
        output["cause"] = synthesis.undervaluation_cause
        output["action"] = synthesis.action_type

    return output


def run_single_analysis(
    ip_name: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run analysis on a single IP and return summary dict."""
    try:
        return _run_analysis_standalone(ip_name, dry_run=dry_run)
    except Exception as exc:
        log.error("Batch analysis failed for %s: %s", ip_name, exc)
        return {
            "ip_name": ip_name,
            "tier": "ERR",
            "final_score": 0.0,
            "cause": str(exc),
            "error": True,
        }


def run_batch(
    *,
    top: int = 20,
    genre: str | None = None,
    ips: list[str] | None = None,
    concurrency: int = 2,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Run batch analysis on multiple IPs."""
    selected = select_ips(top=top, genre=genre, ips=ips)
    if not selected:
        console.print("[yellow]No IPs selected for batch analysis.[/yellow]")
        return []

    console.print(f"\n[bold]Batch Analysis: {len(selected)} IPs[/bold]")

    results: list[dict[str, Any]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Analyzing {len(selected)} IPs...",
            total=len(selected),
        )

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(run_single_analysis, ip, dry_run=dry_run): ip for ip in selected}
            for future in as_completed(futures):
                ip = futures[future]
                try:
                    result = future.result(timeout=_IP_TIMEOUT_S)
                except TimeoutError:
                    log.warning("IP '%s' timed out after %ds", ip, _IP_TIMEOUT_S)
                    result = {
                        "ip_name": ip,
                        "tier": "ERR",
                        "final_score": 0.0,
                        "cause": f"Timeout after {_IP_TIMEOUT_S}s",
                        "error": True,
                    }
                except Exception as exc:
                    log.error("IP '%s' failed: %s", ip, exc)
                    result = {
                        "ip_name": ip,
                        "tier": "ERR",
                        "final_score": 0.0,
                        "cause": str(exc),
                        "error": True,
                    }
                results.append(result)
                progress.advance(task)
                progress.update(
                    task,
                    description=f"Completed: {ip} -> {result.get('tier', '?')}",
                )

    # Sort by score descending
    results.sort(key=lambda r: r.get("final_score", 0), reverse=True)
    return results


def render_batch_table(results: list[dict[str, Any]]) -> None:
    """Render batch results as a Rich table."""
    if not results:
        return

    table = Table(title="GEODE Batch Analysis Results")
    table.add_column("Rank", justify="right", style="dim", width=5)
    table.add_column("IP", style="bold", min_width=20)
    table.add_column("Tier", justify="center", width=5)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Cause", min_width=15)
    table.add_column("Action", min_width=15)

    tier_colors = {"S": "bright_magenta", "A": "green", "B": "yellow", "C": "red", "ERR": "red"}

    for idx, r in enumerate(results, 1):
        tier = r.get("tier", "?")
        color = tier_colors.get(tier, "white")
        table.add_row(
            str(idx),
            r.get("ip_name", "?"),
            f"[{color}]{tier}[/{color}]",
            f"{r.get('final_score', 0):.1f}",
            r.get("cause", "—"),
            r.get("action", "—"),
        )

    console.print(table)

    # Summary stats
    scores = [r.get("final_score", 0) for r in results if not r.get("error")]
    if scores and len(scores) > 1:
        console.print(
            f"\n  Mean: {statistics.mean(scores):.1f} | "
            f"Median: {statistics.median(scores):.1f} | "
            f"Std: {statistics.stdev(scores):.1f}"
        )
    elif scores:
        console.print(f"\n  Score: {scores[0]:.1f}")
