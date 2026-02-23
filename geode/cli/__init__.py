"""GEODE CLI — Typer entrypoint with natural language interactive mode.

Architecture (OpenClaw-inspired):
  /command  → commands.py (Binding Router: deterministic dispatch)
  free-text → nl_router.py (NL Router: intent classification)
              → search.py (IP Search Engine: keyword matching)
"""

from __future__ import annotations

import logging

import typer
from rich.text import Text

from geode import __version__
from geode.cli.commands import (
    cmd_auth,
    cmd_generate,
    cmd_key,
    cmd_list,
    cmd_model,
    resolve_action,
    show_help,
)
from geode.cli.nl_router import NLRouter
from geode.cli.search import IPSearchEngine
from geode.cli.startup import (
    ReadinessReport,
    check_readiness,
    render_readiness,
    setup_project_memory,
)
from geode.config import settings
from geode.runtime import GeodeRuntime
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

log = logging.getLogger(__name__)

app = typer.Typer(
    name="geode",
    help="GEODE v6.0 — Undervalued IP Discovery Agent",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Singletons for REPL session
_nl_router = NLRouter()
_search_engine = IPSearchEngine()
_readiness: ReadinessReport | None = None


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
    """Show Claude Code-style welcome screen with readiness check."""
    global _readiness  # noqa: PLW0603

    console.print()
    logo = Text(_LOGO, style="bold cyan")
    console.print(logo)
    console.print(
        f"  [bold]GEODE v{__version__}[/bold]  [muted]— Undervalued IP Discovery Agent[/muted]"
    )
    console.print(f"  [muted]Model: {settings.model}[/muted]")
    console.print()

    # OpenClaw gateway:startup — readiness check
    _readiness = check_readiness()
    render_readiness(_readiness)

    # OpenClaw boot-md — initialize project memory if absent
    setup_project_memory()

    console.print("  [muted]/help[/muted] for commands  [muted]·[/muted]  ", end="")
    console.print("[muted]type naturally[/muted] to search & analyze")
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


def _execute_pipeline(
    initial_state: GeodeState,
    verbose: bool,
    *,
    runtime: GeodeRuntime,
) -> dict | None:
    """Execute the GEODE pipeline with step-by-step progress."""
    graph = runtime.compile_graph()

    # Store initial state in session
    runtime.store_session_data(dict(initial_state))

    done: list[str] = []
    analyst_count = 0
    final_state: dict = dict(initial_state)

    with console.status(_progress_line(done)) as status:
        try:
            for event in graph.stream(initial_state, config=runtime.thread_config):
                for node_name, output in event.items():
                    if node_name == "__end__":
                        continue
                    label = _STEP_LABELS.get(node_name, node_name)

                    if node_name == "analyst":
                        analyst_count += 1
                        if analyst_count < 4:
                            status.update(_progress_line(done, f"Analyze ({analyst_count}/4)"))
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

    # Update session with final state
    runtime.store_session_data(final_state)

    # Prune logs if needed
    runtime.prune_logs()

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
    pipeline_mode = "full_pipeline"
    header_panel(ip_name, pipeline_mode, model)

    # Create runtime with all infrastructure wired
    runtime = GeodeRuntime.create(ip_name)

    # Log available tools for current mode
    mode = "dry_run" if dry_run else pipeline_mode
    available_tools = runtime.get_available_tools(mode=mode)
    log.debug("Available tools for mode=%s: %s", mode, available_tools)

    initial_state: GeodeState = {
        "ip_name": ip_name,
        "pipeline_mode": pipeline_mode,
        "dry_run": dry_run,
        "verbose": verbose,
        "skip_verification": skip_verification,
        "analyses": [],
        "errors": [],
        "iteration": 1,
        "max_iterations": 3,
    }

    result = _execute_pipeline(initial_state, verbose, runtime=runtime)
    if result:
        _render_result(result, skip_verification=skip_verification, verbose=verbose)


# ---------------------------------------------------------------------------
# Search result rendering
# ---------------------------------------------------------------------------


def _render_search_results(query: str, results: list) -> None:
    """Render IP search results."""
    console.print()
    console.print(f"  [header]Search: '{query}'[/header]")

    if not results:
        console.print("  [muted]No matching IPs found.[/muted]")
        console.print()
        return

    for r in results:
        bar_len = int(r.score * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        style = "success" if r.score >= 0.5 else "muted"
        console.print(f"    [{style}]{bar}[/{style}] {r.score:.0%}  [value]{r.ip_name}[/value]")
        console.print(f"      [muted]matched: {', '.join(r.matches[:5])}[/muted]")
    console.print()


# ---------------------------------------------------------------------------
# Interactive REPL — OpenClaw-style dual routing
# ---------------------------------------------------------------------------


def _handle_command(cmd: str, args: str, verbose: bool) -> tuple[bool, bool]:
    """Handle a slash command. Returns (should_break, new_verbose)."""
    global _readiness  # noqa: PLW0603

    action = resolve_action(cmd)

    if action == "quit":
        console.print("  [muted]Goodbye.[/muted]\n")
        return True, verbose

    if action == "help":
        show_help()
    elif action == "list":
        cmd_list()
    elif action == "verbose":
        verbose = not verbose
        state = "[success]ON[/success]" if verbose else "[muted]OFF[/muted]"
        console.print(f"  Verbose: {state}")
        console.print()
    elif action in ("analyze", "run"):
        dry_run = action == "analyze"
        # Graceful Degradation: force dry-run if no API key
        if action == "run" and _readiness and _readiness.force_dry_run:
            console.print("  [warning]API key not configured — forcing dry-run mode[/warning]")
            dry_run = True
        label = "/analyze" if dry_run else "/run"
        if not args:
            console.print(f"  [warning]Usage: {label} <IP name>[/warning]")
        else:
            _run_analysis(args, dry_run=dry_run, verbose=verbose)
    elif action == "search":
        if not args:
            console.print("  [warning]Usage: /search <query>[/warning]")
        else:
            results = _search_engine.search(args)
            _render_search_results(args, results)
    elif action == "key":
        changed = cmd_key(args)
        if changed:
            _readiness = check_readiness()
            render_readiness(_readiness)
    elif action == "model":
        cmd_model(args)
    elif action == "auth":
        cmd_auth(args)
    elif action == "generate":
        cmd_generate(args)
    else:
        console.print(f"  [warning]Unknown command: {cmd}[/warning]")
        console.print("  [muted]Type /help for available commands.[/muted]")
        console.print()

    return False, verbose


def _handle_natural_language(text: str, verbose: bool) -> None:
    """Route natural language input via NLRouter."""
    intent = _nl_router.classify(text)

    if intent.action == "search":
        results = _search_engine.search(intent.args.get("query", text))
        _render_search_results(intent.args.get("query", text), results)

    elif intent.action == "analyze":
        ip_name = intent.args.get("ip_name", text)
        _run_analysis(ip_name, dry_run=True, verbose=verbose)

    elif intent.action == "compare":
        ip_a = intent.args.get("ip_a", "")
        ip_b = intent.args.get("ip_b", "")
        console.print(f"\n  [header]Compare: {ip_a} vs {ip_b}[/header]\n")
        _run_analysis(ip_a, dry_run=True, verbose=verbose)
        _run_analysis(ip_b, dry_run=True, verbose=verbose)

    elif intent.action == "list":
        cmd_list()

    elif intent.action == "help":
        show_help()

    else:
        _run_analysis(text, dry_run=True, verbose=verbose)


def _interactive_loop() -> None:
    """Claude Code / OpenClaw-style interactive REPL.

    Two routing paths:
      /command → deterministic dispatch (commands.py)
      free-text → NL intent classification (nl_router.py)
    """
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
            # Slash command → deterministic routing (OpenClaw Binding)
            cmd = user_input.split()[0].lower()
            args = user_input[len(cmd) :].strip()
            should_break, verbose = _handle_command(cmd, args, verbose)
            if should_break:
                break
        else:
            # Natural language → NL Router (intent classification)
            _handle_natural_language(user_input, verbose)


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
def search(
    query: str = typer.Argument(..., help="Search query (e.g. 'dark fantasy', '소울라이크')"),
) -> None:
    """Search IPs by keyword or genre."""
    results = _search_engine.search(query)
    _render_search_results(query, results)


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
