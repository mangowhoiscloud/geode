"""CLI subcommand: ``geode adapters`` — inspect registered LLM adapters.

v0.99.40 Follow-up D of the paperclip-style LLMAdapter abstraction
(``docs/plans/2026-05-23-llm-adapter-abstraction.md``). Surface the
:class:`core.llm.adapters.LLMAdapter` registry so operators can see what
PAYG / Subscription / Adapter paths are available + verify each path's
environment before scheduling a seed-generation run.

Three read-only subcommands:

- ``geode adapters list`` — enumerate registered adapters with
  ``billing_type``, ``test_environment`` summary, and supported model
  count.
- ``geode adapters detect-model <adapter>`` — paperclip ``detectModel``
  equivalent; reports the currently configured model + provenance from
  the adapter's ``detect_credential()`` hook.
- ``geode adapters stats [--since 1h]`` — aggregate
  ``ADAPTER_DISPATCH_ATTEMPT`` hook events from ``~/.geode/runs/*.jsonl``
  by ``(capability, adapter_name)`` with per-outcome counts + p50/p95
  latency. Operators answer "what did dispatch actually route through in
  the last N minutes?" without grepping jsonl by hand
  (PR-DISPATCH-OBS-EXT 2026-05-28).

UI: dense aligned table, plain text. No box-card / no emoji (per
``feedback_no_box_ui_no_emoji`` memory).
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="adapters",
    help="Inspect registered LLM adapters (PAYG / Subscription / Adapter paths).",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("list")
def adapters_list() -> None:
    """List all registered adapters with billing_type + environment status."""
    from core.llm.adapters import bootstrap_builtins, list_adapters

    bootstrap_builtins()
    adapters = list_adapters()
    if not adapters:
        typer.echo("No LLM adapters registered.")
        raise typer.Exit()

    header = f"{'NAME':<20} {'PROVIDER':<10} {'SOURCE':<14} {'BILLING':<22} STATUS"
    typer.echo(header)
    typer.echo("-" * len(header))
    for a in adapters:
        report = a.test_environment()
        status = "ok" if report.ok else "missing — " + (report.hints[0] if report.hints else "")
        typer.echo(
            f"{a.name:<20} {a.provider:<10} {a.source:<14} {a.billing_type.value:<22} {status}"
        )
    typer.echo(f"\n{len(adapters)} adapter(s) registered.")
    typer.echo(
        'Override per role via ~/.geode/config.toml [seed_generation.role.<role>] source = "..."'
    )


@app.command("detect-model")
def adapters_detect_model(name: str) -> None:
    """Report the currently configured model + provenance for ``name``."""
    from core.llm.adapters import AdapterNotFoundError, bootstrap_builtins, get_adapter

    bootstrap_builtins()
    try:
        adapter = get_adapter(name)
    except AdapterNotFoundError as exc:
        typer.echo(f"adapter {name!r} not registered: {exc}")
        raise typer.Exit(code=1) from exc

    detection = adapter.detect_credential()
    if detection is None:
        typer.echo(f"{name}: no credential detected — run ``geode adapters list`` for hints.")
        raise typer.Exit(code=2)
    typer.echo(f"{name}: model={detection.model} provider={detection.provider}")
    typer.echo(f"  source: {detection.source_path}")
    if detection.candidates:
        typer.echo(f"  candidates: {', '.join(detection.candidates)}")


_SINCE_UNITS: dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_since(spec: str) -> int:
    """Parse ``1h`` / ``30m`` / ``2d`` style window into seconds.

    Raises ``typer.BadParameter`` on unparseable input — explicit failure
    beats silently defaulting to "all of history" which could surface
    weeks-old data with no warning.
    """
    spec = spec.strip().lower()
    if not spec:
        raise typer.BadParameter("--since cannot be empty (e.g. 1h, 30m, 24h, 7d)")
    unit = spec[-1]
    if unit not in _SINCE_UNITS:
        raise typer.BadParameter(
            f"--since unit {unit!r} not recognized. Use s/m/h/d/w (e.g. 1h, 30m, 7d)."
        )
    try:
        magnitude = int(spec[:-1])
    except ValueError as exc:
        raise typer.BadParameter(
            f"--since magnitude {spec[:-1]!r} not a number (e.g. 1h, 30m)"
        ) from exc
    return magnitude * _SINCE_UNITS[unit]


@app.command("stats")
def adapters_stats(
    since: str = typer.Option(
        "1h", "--since", help="Time window (1h / 30m / 24h / 7d). Default: 1h."
    ),
    runs_dir: str = typer.Option(
        "",
        "--runs-dir",
        help="Override runs directory. Defaults to ~/.geode/runs/.",
    ),
) -> None:
    """Aggregate ADAPTER_DISPATCH_ATTEMPT events from ``~/.geode/runs/*.jsonl``
    by ``(capability, adapter_name)``.

    PR-DISPATCH-OBS-EXT (2026-05-28) — operator-facing answer to "what
    did dispatch actually route through in the last N minutes/hours/days?"
    without having to grep through jsonl manually. Reads only the
    structured ``ADAPTER_DISPATCH_ATTEMPT`` rows the dispatch layer
    emits — no LLM call needed.
    """
    import json
    import time
    from pathlib import Path

    window_s = _parse_since(since)
    cutoff = time.time() - window_s

    if runs_dir:
        runs_path = Path(runs_dir).expanduser()
    else:
        from core.paths import GLOBAL_RUNS_DIR

        runs_path = GLOBAL_RUNS_DIR
    if not runs_path.exists():
        typer.echo(f"runs dir not found: {runs_path}")
        raise typer.Exit(code=1)

    # Key = (capability, adapter_name, provider, source) → list of (outcome, elapsed_ms)
    buckets: dict[tuple[str, str, str, str], list[tuple[str, float]]] = {}
    rows_scanned = 0
    for jsonl in sorted(runs_path.glob("*.jsonl")):
        try:
            with jsonl.open(encoding="utf-8") as fh:
                for line in fh:
                    rows_scanned += 1
                    # Cheap pre-filter — production gateway uses compact
                    # ``json.dumps`` (no spaces) but test-injected fixtures
                    # often use the default spaced form. Match the event
                    # name only, both forms include it.
                    if "adapter_dispatch_attempt" not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:  # noqa: S112 — malformed jsonl line, count + skip
                        continue
                    if d.get("timestamp", 0) < cutoff:
                        continue
                    md = d.get("metadata", {}) or {}
                    key = (
                        str(md.get("capability", "")),
                        str(md.get("adapter_name", "")),
                        str(md.get("provider", "")),
                        str(md.get("source", "")),
                    )
                    buckets.setdefault(key, []).append(
                        (str(md.get("outcome", "")), float(md.get("elapsed_ms", 0.0)))
                    )
        except OSError:
            continue

    if not buckets:
        n_files = len(list(runs_path.glob("*.jsonl")))
        typer.echo(f"No ADAPTER_DISPATCH_ATTEMPT events in {runs_path} within --since {since}.")
        typer.echo(f"  (scanned {rows_scanned} jsonl rows across {n_files} files)")
        raise typer.Exit()

    header = (
        f"{'CAPABILITY':<28} {'ADAPTER':<20} {'PROVIDER':<10} {'SOURCE':<14} "
        f"{'TOTAL':>6} {'OK':>6} {'BIL':>5} {'TRN':>5} {'UNV':>5} {'p50':>9} {'p95':>9}"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    sorted_keys = sorted(buckets.keys())
    for key in sorted_keys:
        capability, adapter_name, provider, source = key
        attempts = buckets[key]
        n = len(attempts)
        outcomes: dict[str, int] = {}
        for outcome, _ in attempts:
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        success = outcomes.get("success", 0)
        billing = outcomes.get("billing", 0)
        transient = outcomes.get("transient", 0)
        unavailable = outcomes.get("unavailable", 0)
        elapsed_sorted = sorted(e for _, e in attempts)
        p50 = elapsed_sorted[len(elapsed_sorted) // 2]
        p95_idx = min(len(elapsed_sorted) - 1, int(len(elapsed_sorted) * 0.95))
        p95 = elapsed_sorted[p95_idx]
        typer.echo(
            f"{capability:<28} {adapter_name:<20} {provider:<10} {source:<14} "
            f"{n:>6d} {success:>6d} {billing:>5d} {transient:>5d} {unavailable:>5d} "
            f"{p50:>7.0f}ms {p95:>7.0f}ms"
        )
    typer.echo(
        f"\n{sum(len(v) for v in buckets.values())} dispatch attempt(s) across "
        f"{len(buckets)} (capability,adapter) bucket(s), window=--since {since}."
    )


__all__ = ["app"]
