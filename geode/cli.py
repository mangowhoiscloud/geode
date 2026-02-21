"""GEODE CLI — Typer entrypoint with interactive mode."""

from __future__ import annotations

import typer
from rich.text import Text

from geode import __version__
from geode.config import settings
from geode.graph import compile_graph
from geode.state import GeodeState
from geode.ui.console import console
from geode.ui.panels import (
    analyst_panel,
    evaluator_panel,
    gather_panel,
    header_panel,
    result_panel,
    score_panel,
    verify_panel,
)

app = typer.Typer(
    name="geode",
    help="GEODE v6.0 — Undervalued IP Discovery Agent",
    no_args_is_help=False,
    invoke_without_command=True,
)


# ---------------------------------------------------------------------------
# Interactive welcome screen
# ---------------------------------------------------------------------------

_LOGO = r"""
   ____  _____ ___  ____  _____
  / ___|| ____/ _ \|  _ \| ____|
 | |  _ |  _|| | | | | | |  _|
 | |_| || |__| |_| | |_| | |___
  \____||_____\___/|____/|_____|
"""


def _welcome_screen() -> None:
    """Show Claude Code-style welcome screen."""
    console.print()
    logo = Text(_LOGO, style="bold cyan")
    console.print(logo)
    console.print(
        f"  [bold]GEODE v{__version__}[/bold]  [muted]— Undervalued IP Discovery Agent[/muted]"
    )
    console.print(f"  [muted]Model: {settings.model}[/muted]")
    console.print()
    console.print("  [muted]/help[/muted] for commands  [muted]·[/muted]  ", end="")
    console.print("[muted]/quit[/muted] to exit")
    console.print()


def _show_help() -> None:
    """Show interactive mode help."""
    console.print()
    console.print("  [header]Commands[/header]")
    console.print("  [label]/analyze[/label] <IP name>  — Analyze an IP (dry-run)")
    console.print("  [label]/run[/label] <IP name>      — Analyze with real LLM")
    console.print("  [label]/list[/label]               — Show available IPs")
    console.print("  [label]/verbose[/label]            — Toggle verbose mode")
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")
    console.print()
    console.print("  [muted]Or just type an IP name to analyze (dry-run).[/muted]")
    console.print()


# ---------------------------------------------------------------------------
# Pipeline execution + rendering
# ---------------------------------------------------------------------------


_STEP_LABELS: dict[str, str] = {
    "router": "Route",
    "cortex": "Gather",
    "signals": "Signals",
    "analyst": "Analyze",
    "evaluators": "Evaluate",
    "scoring": "Score",
    "verification": "Verify",
    "synthesizer": "Synthesize",
}


def _progress_line(done: list[str], active: str = "") -> str:
    """Build a compact progress status line."""
    parts = [f"[dim]{s}[/dim]" for s in done]
    if active:
        parts.append(f"[bold cyan]{active}[/bold cyan]")
    return " → ".join(parts) if parts else "[bold cyan]Starting...[/bold cyan]"


def _execute_pipeline(initial_state: GeodeState, verbose: bool) -> dict | None:
    """Execute the GEODE pipeline with step-by-step progress."""
    graph = compile_graph()
    done: list[str] = []
    analyst_count = 0
    final_state: dict = dict(initial_state)

    with console.status(_progress_line(done)) as status:
        try:
            for event in graph.stream(initial_state):
                for node_name, output in event.items():
                    if node_name == "__end__":
                        continue
                    label = _STEP_LABELS.get(node_name, node_name)

                    if node_name == "analyst":
                        analyst_count += 1
                        if analyst_count < 4:
                            status.update(
                                _progress_line(done, f"Analyze ({analyst_count}/4)")
                            )
                        else:
                            done.append("Analyze ✓")
                            status.update(_progress_line(done))
                    else:
                        done.append(f"{label} ✓")
                        status.update(_progress_line(done))

                    # Merge node output into accumulated state
                    for k, v in output.items():
                        if k in ("analyses", "errors"):
                            lst = v if isinstance(v, list) else [v]
                            final_state.setdefault(k, []).extend(lst)
                        else:
                            final_state[k] = v
        except Exception as e:
            console.print(f"[error]Pipeline error: {e}[/error]")
            if verbose:
                console.print_exception()
            return None

    return final_state


def _render_data_panels(result: dict) -> None:
    """Render gather/analyst/evaluator/score panels."""
    if result.get("ip_info"):
        gather_panel(result["ip_info"], result.get("monolake", {}), result.get("signals", {}))
    if result.get("analyses"):
        analyst_panel(result["analyses"])
    if result.get("evaluations"):
        evaluator_panel(result["evaluations"])
    if result.get("psm_result") is not None:
        score_panel(
            result["psm_result"],
            result.get("final_score", 0),
            result.get("subscores", {}),
            confidence=result.get("analyst_confidence", 0),
        )


def _render_verification(result: dict, *, verbose: bool) -> None:
    """Render guardrail + biasbuster verification panel."""
    guardrails = result.get("guardrails")
    biasbuster = result.get("biasbuster")
    g_pass = guardrails.all_passed if guardrails else False
    b_pass = biasbuster.overall_pass if biasbuster else False
    verify_panel(g_pass, b_pass)
    if guardrails and not g_pass:
        for detail in guardrails.details:
            if "FAIL" in detail:
                console.print(f"    [warning]{detail}[/warning]")
    if verbose and guardrails:
        for detail in guardrails.details:
            console.print(f"    [muted]{detail}[/muted]")
        console.print()


def _render_result(result: dict, *, skip_verification: bool, verbose: bool) -> None:
    """Render all output panels from pipeline result."""
    _render_data_panels(result)
    if not skip_verification:
        _render_verification(result, verbose=verbose)
    if result.get("synthesis"):
        result_panel(result.get("tier", "?"), result.get("final_score", 0), result["synthesis"])
    # Surface accumulated pipeline errors
    errors = result.get("errors", [])
    if errors:
        console.print(f"  [warning]Pipeline warnings ({len(errors)}):[/warning]")
        for err in errors:
            console.print(f"    [warning]- {err}[/warning]")
    console.print()


def _run_analysis(
    ip_name: str,
    *,
    dry_run: bool = True,
    verbose: bool = False,
    skip_verification: bool = False,
) -> None:
    """Core analysis logic shared by interactive and CLI modes."""
    model = "dry-run (no LLM)" if dry_run else settings.model
    header_panel(ip_name, "full_pipeline", model)

    initial_state: GeodeState = {
        "ip_name": ip_name,
        "pipeline_mode": "full_pipeline",
        "dry_run": dry_run,
        "verbose": verbose,
        "skip_verification": skip_verification,
        "analyses": [],
        "errors": [],
    }

    result = _execute_pipeline(initial_state, verbose)
    if result:
        _render_result(result, skip_verification=skip_verification, verbose=verbose)


# ---------------------------------------------------------------------------
# Interactive REPL — command dispatch
# ---------------------------------------------------------------------------

_COMMAND_MAP = {
    "/quit": "quit",
    "/exit": "quit",
    "/q": "quit",
    "/help": "help",
    "/list": "list",
    "/verbose": "verbose",
    "/analyze": "analyze",
    "/a": "analyze",
    "/run": "run",
    "/r": "run",
}


def _cmd_list() -> None:
    """List available IP fixtures."""
    from geode.nodes.cortex import _FIXTURE_MAP

    console.print()
    console.print("  [header]Available IPs[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"    [value]{name.title()}[/value]")
    console.print()


def _cmd_analyze_or_run(action: str, args: str, verbose: bool) -> None:
    """Handle /analyze or /run commands."""
    dry_run = action == "analyze"
    label = "/analyze" if dry_run else "/run"
    if not args:
        console.print(f"  [warning]Usage: {label} <IP name>[/warning]")
    else:
        _run_analysis(args, dry_run=dry_run, verbose=verbose)


def _handle_command(cmd: str, args: str, verbose: bool) -> tuple[bool, bool]:
    """Handle a slash command. Returns (should_break, new_verbose)."""
    action = _COMMAND_MAP.get(cmd)

    if action == "quit":
        console.print("  [muted]Goodbye.[/muted]\n")
        return True, verbose

    if action == "help":
        _show_help()
    elif action == "list":
        _cmd_list()
    elif action == "verbose":
        verbose = not verbose
        state = "[success]ON[/success]" if verbose else "[muted]OFF[/muted]"
        console.print(f"  Verbose: {state}")
        console.print()
    elif action in ("analyze", "run"):
        _cmd_analyze_or_run(action, args, verbose)
    else:
        console.print(f"  [warning]Unknown command: {cmd}[/warning]")
        console.print("  [muted]Type /help for available commands.[/muted]")
        console.print()

    return False, verbose


def _interactive_loop() -> None:
    """Claude Code-style interactive REPL."""
    verbose = False

    while True:
        try:
            user_input = console.input("[bold cyan]>[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [muted]Goodbye.[/muted]\n")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input.split()[0].lower()
            args = user_input[len(cmd):].strip()
            should_break, verbose = _handle_command(cmd, args, verbose)
            if should_break:
                break
        else:
            _run_analysis(user_input, dry_run=True, verbose=verbose)


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@app.callback()
def main(ctx: typer.Context) -> None:
    """GEODE v6.0 — Undervalued IP Discovery Agent."""
    if ctx.invoked_subcommand is None:
        _welcome_screen()
        _interactive_loop()


@app.command()
def analyze(
    ip_name: str = typer.Argument(..., help="IP name to analyze (e.g. 'Cowboy Bebop')"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Run without LLM calls (fixture data only)"
    ),
    skip_verification: bool = typer.Option(
        False, "--skip-verification", help="Skip guardrails and BiasBuster"
    ),
    pipeline: str = typer.Option("full_pipeline", "--pipeline", "-p", help="Pipeline mode"),
) -> None:
    """Analyze an IP for undervaluation potential."""
    _run_analysis(
        ip_name,
        dry_run=dry_run,
        verbose=verbose,
        skip_verification=skip_verification,
    )


@app.command()
def version() -> None:
    """Show GEODE version."""
    console.print(f"GEODE v{__version__}")


@app.command(name="list")
def list_ips() -> None:
    """List available IP fixtures."""
    from geode.nodes.cortex import _FIXTURE_MAP

    console.print("[header]Available IPs:[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"  - {name.title()}")


if __name__ == "__main__":
    app()
