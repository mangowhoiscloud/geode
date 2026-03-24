"""Pipeline execution and result rendering for GEODE CLI.

Extracted from core.cli.__init__ to reduce module size.
Contains pipeline execution (streaming + status-bar modes),
result rendering, IP name resolution, and initial state building.
"""

from __future__ import annotations

import logging
import re as _re
import shutil
from typing import Any

from core.config import settings
from core.runtime import GeodeRuntime
from core.state import AnalysisResult, EvaluatorResult, GeodeState
from core.cli.ui.console import console
from core.cli.ui.panels import (
    analyst_panel,
    evaluator_panel,
    gather_panel,
    header_panel,
    result_panel,
    score_panel,
    verify_panel,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step labels for pipeline progress display
# ---------------------------------------------------------------------------

_STEP_LABELS: dict[str, str] = {
    "router": "Route",
    "signals": "Signals",
    "analyst": "Analyze",
    "evaluators": "Evaluate",
    "scoring": "Score",
    "verification": "Verify",
    "synthesizer": "Synthesize",
}


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------


def _progress_line(done: list[str], active: str = "") -> str:
    """Build a compact progress status line, truncated to terminal width.

    When the full line would exceed the terminal width, shows the first 2
    completed steps, a ``... (+N tasks)`` summary, and the current active step.
    """
    cols = shutil.get_terminal_size().columns
    # Reserve space for spinner frame + padding ("  X " = 4 chars)
    max_width = cols - 4

    parts = [f"[dim]{s}[/dim]" for s in done]
    if active:
        parts.append(f"[header]{active}[/header]")
    if not parts:
        return "[header]Starting...[/header]"

    full = " \u2192 ".join(parts)
    # Estimate plain-text length by stripping Rich markup tags
    plain = _re.sub(r"\[/?[^\]]*\]", "", full)
    if len(plain) <= max_width:
        return full

    # Truncate: first 2 done steps + ... (+N tasks) [+ active]
    keep = 2
    shown = [f"[dim]{s}[/dim]" for s in done[:keep]]
    remaining = len(done) - keep
    if active:
        suffix = f"[dim]... (+{remaining} tasks)[/dim] \u2192 [header]{active}[/header]"
    else:
        suffix = f"[dim]... (+{remaining} tasks)[/dim]"
    shown.append(suffix)
    return " \u2192 ".join(shown)


# ---------------------------------------------------------------------------
# Event merging
# ---------------------------------------------------------------------------


def _merge_event_output(final_state: dict[str, Any], output: dict[str, Any] | None) -> None:
    """Merge a single node's output into the accumulated final state."""
    if output is None:
        log.debug("Node returned None output, skipping merge")
        return
    for k, v in output.items():
        if k in ("analyses", "errors"):
            lst = v if isinstance(v, list) else [v]
            final_state.setdefault(k, []).extend(lst)
        else:
            final_state[k] = v


# ---------------------------------------------------------------------------
# Interrupt handling
# ---------------------------------------------------------------------------


def _inspect_pipeline_state(state: dict[str, Any]) -> None:
    """Display current pipeline state for user inspection."""
    console.print("  [header]Pipeline State[/header]")
    console.print(f"    IP: {state.get('ip_name', '?')}")
    console.print(f"    Iteration: {state.get('iteration', 1)}")

    analyses = state.get("analyses", [])
    if analyses:
        console.print(f"    Analyses: {len(analyses)} completed")
        for a in analyses[-4:]:
            if hasattr(a, "model_dump"):
                a = a.model_dump()
            atype = a.get("analyst_type", "?")
            score = a.get("score", 0)
            console.print(f"      - {atype}: {score}")

    comp = state.get("composite_score", {})
    if comp:
        console.print(f"    Score: {comp}")

    tier = state.get("tier")
    if tier:
        console.print(f"    Tier: {tier}")
    console.print()


def _handle_interrupt(
    graph: Any,
    config: dict[str, Any],
    final_state: dict[str, Any],
    done: list[str],
) -> bool:
    """Handle a graph interrupt_before pause.

    Options: [C]ontinue / [I]nspect / [S]kip / [A]bort.
    Returns True to continue, False to abort.
    """
    iteration = final_state.get("iteration", 1)
    confidence = final_state.get("composite_score", {})
    console.print(f"\n  [warning]Pipeline paused[/warning] (iter={iteration}, steps={len(done)})")
    if confidence:
        console.print(f"  [dim]Current confidence: {confidence}[/dim]")

    while True:
        try:
            choice = (
                console.input(
                    "  [bold][C]ontinue / [I]nspect / [S]kip / [A]bort[/bold] (default: Continue): "
                )
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            console.print()
            return False

        if choice in ("", "c", "continue"):
            return True
        if choice in ("a", "abort"):
            console.print("  [dim]Pipeline aborted by user.[/dim]")
            return False
        if choice in ("i", "inspect"):
            _inspect_pipeline_state(final_state)
            continue
        if choice in ("s", "skip"):
            console.print("  [dim]Skipping current step...[/dim]")
            return True
        console.print("  [dim]Unknown option. Use C/I/S/A.[/dim]")


# ---------------------------------------------------------------------------
# Pipeline execution (status-bar mode)
# ---------------------------------------------------------------------------


def _execute_pipeline(
    initial_state: GeodeState,
    verbose: bool,
    *,
    runtime: GeodeRuntime,
) -> dict[str, Any] | None:
    """Execute the GEODE pipeline with step-by-step progress."""
    graph = runtime.compile_graph()

    # Store initial state in session
    runtime.store_session_data(dict(initial_state))

    done: list[str] = []
    analyst_count = 0
    evaluator_count = 0
    final_state: dict[str, Any] = dict(initial_state)
    config = runtime.thread_config
    input_state: GeodeState | None = initial_state

    with console.status(_progress_line(done)) as status:
        try:
            while True:
                for event in graph.stream(input_state, config=config):  # type: ignore[call-overload]
                    for node_name, output in event.items():
                        if node_name == "__end__":
                            continue
                        label = _STEP_LABELS.get(node_name, node_name)

                        if node_name == "analyst":
                            analyst_count += 1
                            if analyst_count < 4:
                                status.update(_progress_line(done, f"Analyze ({analyst_count}/4)"))
                            else:
                                done.append("Analyze \u2713")
                                status.update(_progress_line(done))
                        elif node_name == "evaluator":
                            evaluator_count += 1
                            if evaluator_count < 3:
                                status.update(
                                    _progress_line(done, f"Evaluate ({evaluator_count}/3)")
                                )
                            else:
                                done.append("Evaluate \u2713")
                                status.update(_progress_line(done))
                        else:
                            done.append(f"{label} \u2713")
                            status.update(_progress_line(done))

                        _merge_event_output(final_state, output)

                # If stream ended normally (all nodes done), break
                snapshot = graph.get_state(config)  # type: ignore[arg-type]
                if not snapshot.next:
                    break

                # interrupt_before triggered -- ask user
                status.stop()
                if not _handle_interrupt(graph, config, final_state, done):
                    return final_state  # abort: return partial results
                input_state = None  # resume from checkpoint
                status.start()
        except Exception as e:
            # Ensure cursor/spinner cleanup before printing error
            console.show_cursor(True)
            console.print(f"[error]Pipeline error: {e}[/error]")
            if verbose:
                console.print_exception()
            return None

    # Update session with final state
    runtime.store_session_data(final_state)

    # Prune logs if needed
    runtime.prune_logs()

    return final_state


# ---------------------------------------------------------------------------
# Streaming renderers
# ---------------------------------------------------------------------------


def _render_streaming_analyst(analysis: AnalysisResult) -> None:
    """Render a single analyst result row immediately in streaming mode."""
    score_style = (
        "bold green" if analysis.score >= 4.0 else "yellow" if analysis.score >= 3.0 else "red"
    )
    console.print(
        f"  [label]{analysis.analyst_type.capitalize():14s}[/label] "
        f"[{score_style}]{analysis.score:.1f}[/{score_style}]  "
        f"{analysis.key_finding}"
    )


def _render_streaming_evaluator(key: str, ev: EvaluatorResult) -> None:
    """Render a single evaluator result immediately in streaming mode."""
    labels = {
        "quality_judge": "Quality",
        "hidden_value": "Hidden",
        "community_momentum": "Momentum",
        "prospect_judge": "Prospect",
    }
    label = labels.get(key, key)
    score = ev.composite_score
    filled = int(score / 100 * 24)
    bar = "[green]" + "\u2588" * filled + "[/green][dim]" + "\u2591" * (24 - filled) + "[/dim]"
    console.print(f"  {label:10s} {bar} {score:.0f}/100")


# ---------------------------------------------------------------------------
# Pipeline execution (streaming mode)
# ---------------------------------------------------------------------------


def _execute_pipeline_streaming(
    initial_state: GeodeState,
    verbose: bool,
    *,
    runtime: GeodeRuntime,
) -> dict[str, Any] | None:
    """Execute the pipeline with streaming output -- display results as they arrive."""
    graph = runtime.compile_graph()
    runtime.store_session_data(dict(initial_state))

    final_state: dict[str, Any] = dict(initial_state)
    analyst_count = 0
    analyst_header_shown = False
    evaluator_header_shown = False
    config = runtime.thread_config
    input_state: GeodeState | None = initial_state
    done: list[str] = []

    try:
        while True:
            for event in graph.stream(input_state, config=config):  # type: ignore[call-overload]
                for node_name, output in event.items():
                    if node_name == "__end__":
                        continue

                    _merge_event_output(final_state, output)

                    # Progressive rendering per node type
                    if node_name == "analyst":
                        if not analyst_header_shown:
                            console.print()
                            console.print(
                                "[step]\u25b8 [ANALYZE][/step] Running 4 Analysts (streaming)..."
                            )
                            analyst_header_shown = True
                        analyst_count += 1
                        analyses = output.get("analyses", [])
                        for a in analyses:
                            _render_streaming_analyst(a)

                    elif node_name == "evaluator":
                        if not evaluator_header_shown:
                            console.print()
                            console.print(
                                "[step]\u25b8 [EVALUATE][/step]"
                                " 14-Axis Rubric Scoring (streaming)..."
                            )
                            evaluator_header_shown = True
                        evals = output.get("evaluations", {})
                        for key, ev in evals.items():
                            _render_streaming_evaluator(key, ev)

                    elif node_name == "router":
                        console.print()
                        console.print("[step]\u25b8 [ROUTE][/step] Loading IP data...")

                    elif node_name == "signals":
                        console.print("[step]\u25b8 [SIGNALS][/step] Fetching signals...")

                    elif node_name == "scoring":
                        console.print()
                        console.print("[step]\u25b8 [SCORE][/step] Calculating final score...")
                        if output.get("final_score") is not None:
                            tier = output.get("tier", "?")
                            score = output.get("final_score", 0)
                            console.print(
                                f"  Score: [bold]{score:.1f}[/bold]  Tier: [bold]{tier}[/bold]"
                            )

                    elif node_name == "verification":
                        console.print("[step]\u25b8 [VERIFY][/step] Running guardrails...")

                    elif node_name == "synthesizer":
                        console.print()
                        console.print("[step]\u25b8 [SYNTHESIZE][/step] Generating narrative...")
                        synth = output.get("synthesis")
                        if synth:
                            console.print(f"  Cause: {synth.undervaluation_cause}")
                            console.print(f"  Action: {synth.action_type}")

                    else:
                        label = _STEP_LABELS.get(node_name, node_name)
                        console.print(f"[step]\u25b8 [{label.upper()}][/step] Done.")

            # Check for interrupt_before pause
            snapshot = graph.get_state(config)  # type: ignore[arg-type]
            if not snapshot.next:
                break

            if not _handle_interrupt(graph, config, final_state, done):
                return final_state
            input_state = None

    except Exception as e:
        console.show_cursor(True)
        console.print(f"[error]Pipeline error: {e}[/error]")
        if verbose:
            console.print_exception()
        return None

    console.print()
    runtime.store_session_data(final_state)
    runtime.prune_logs()
    return final_state


# ---------------------------------------------------------------------------
# Result rendering
# ---------------------------------------------------------------------------


def _render_data_panels(result: dict[str, Any]) -> None:
    """Render gather/analyst/evaluator/score panels."""
    if result.get("ip_info"):
        gather_panel(result["ip_info"], result.get("monolake", {}), result.get("signals", {}))
    if result.get("analyses"):
        analyst_panel(result["analyses"])
    if result.get("evaluations"):
        evaluator_panel(result["evaluations"])
    if result.get("psm_result") is not None:
        conf = result.get("analyst_confidence", 0)
        # In dry-run, confidence is from fixture data -- flag it
        if result.get("dry_run"):
            conf = 0  # suppress misleading confidence in dry-run
        score_panel(
            result["psm_result"],
            result.get("final_score", 0),
            result.get("subscores", {}),
            confidence=conf,
        )


def _render_verification(result: dict[str, Any], *, verbose: bool) -> None:
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
        seen: set[str] = set()
        for detail in guardrails.details:
            if detail not in seen:
                seen.add(detail)
                console.print(f"    [muted]{detail}[/muted]")
        console.print()


def _render_result(result: dict[str, Any], *, skip_verification: bool, verbose: bool) -> None:
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


# ---------------------------------------------------------------------------
# IP name resolution
# ---------------------------------------------------------------------------


def _resolve_ip_name(ip_name: str) -> str | None:
    """Resolve an IP name to a fixture key with fuzzy matching.

    Resolution order:
    1. Exact fixture key match
    2. Canonical name -> fixture key map (ip_info.ip_name lookup)
    3. Substring: fixture key is contained in input
    4. Substring: input is contained in fixture key
    """
    from core.cli.ip_names import get_ip_name_map
    from core.domains.game_ip.fixtures import FIXTURE_MAP

    key = ip_name.lower().strip()

    # 1. Exact fixture key match
    if key in FIXTURE_MAP:
        return key

    # 2. Canonical ip_info.ip_name -> fixture key
    name_map = get_ip_name_map()
    if key in name_map:
        return name_map[key]

    # 3. Fixture key is a substring of input (e.g. "ghost in shell" in "ghost in the shell")
    for fk in FIXTURE_MAP:
        if fk in key:
            return fk

    # 4. Input is a substring of fixture key
    for fk in FIXTURE_MAP:
        if key in fk:
            return fk

    return None


# ---------------------------------------------------------------------------
# Core analysis runner
# ---------------------------------------------------------------------------


def _run_analysis(
    ip_name: str,
    *,
    dry_run: bool = True,
    verbose: bool = False,
    skip_verification: bool = False,
    stream: bool = False,
    domain_name: str = "game_ip",
) -> dict[str, Any] | None:
    """Core analysis logic shared by interactive and CLI modes."""
    from core.cli import _hooks_ctx, _set_last_result
    from core.domains.game_ip.fixtures import FIXTURE_MAP

    resolved = _resolve_ip_name(ip_name)
    if resolved is None:
        available = [n.title() for n in FIXTURE_MAP]
        console.print(f"\n  [warning]Unknown IP: '{ip_name}'[/warning]")
        console.print(f"  [muted]Available IPs: {', '.join(available)}[/muted]")
        console.print("  [muted]Use /search <query> to find IPs by genre or keyword.[/muted]\n")
        return None

    # Use the resolved fixture key for downstream operations
    ip_name = resolved

    model = "dry-run (no LLM)" if dry_run else settings.model
    pipeline_mode = "full_pipeline"
    header_panel(ip_name, pipeline_mode, model)

    # Create runtime with all infrastructure wired (domain adapter activated)
    runtime = GeodeRuntime.create(ip_name, domain_name=domain_name)

    # Subagent session isolation: force MemorySaver fallback (G7 fix)
    from core.cli.sub_agent import get_subagent_context

    is_subagent, _child_key = get_subagent_context()
    if is_subagent:
        runtime.is_subagent = True

    _hooks_ctx.set(runtime.hooks)

    # Log available tools for current mode
    mode = "dry_run" if dry_run else pipeline_mode
    available_tools = runtime.get_available_tools(mode=mode)
    log.debug("Available tools for mode=%s: %s", mode, available_tools)

    # Build session key for 3-tier memory assembly (GAP-001 fix)
    from core.memory.session_key import build_session_key

    session_id = build_session_key(ip_name, "pipeline")

    initial_state: GeodeState = {
        "ip_name": ip_name,
        "pipeline_mode": pipeline_mode,
        "session_id": session_id,
        "dry_run": dry_run,
        "verbose": verbose,
        "skip_verification": skip_verification,
        "analyses": [],
        "errors": [],
        "iteration": 1,
        "max_iterations": 3,
        # Ensemble config injection (L5 nodes read from state, not settings)
        "_ensemble_mode": settings.ensemble_mode,
        "_secondary_analysts": settings.secondary_analysts,
    }

    # Inject tool definitions for tool-augmented nodes (Synthesizer, BiasBuster)
    if not dry_run:
        tool_injection = runtime.get_tool_state_injection(mode=pipeline_mode)
        initial_state.update(tool_injection)  # type: ignore[typeddict-item]

    if stream:
        result = _execute_pipeline_streaming(initial_state, verbose, runtime=runtime)
        if result:
            _set_last_result(result)
            # In streaming mode, most panels are already rendered progressively.
            # Only render verification + synthesis result if not yet shown.
            if not skip_verification:
                _render_verification(result, verbose=verbose)
            if result.get("synthesis"):
                result_panel(
                    result.get("tier", "?"), result.get("final_score", 0), result["synthesis"]
                )
            errors = result.get("errors", [])
            if errors:
                console.print(f"  [warning]Pipeline warnings ({len(errors)}):[/warning]")
                for err in errors:
                    console.print(f"    [warning]- {err}[/warning]")
            console.print()
    else:
        result = _execute_pipeline(initial_state, verbose, runtime=runtime)
        if result:
            _set_last_result(result)
            _render_result(result, skip_verification=skip_verification, verbose=verbose)
    return result


# ---------------------------------------------------------------------------
# Batch initial state builder
# ---------------------------------------------------------------------------


def _build_initial_state(
    ip_name: str,
    *,
    dry_run: bool = True,
    runtime: GeodeRuntime,
) -> GeodeState:
    """Build initial pipeline state for batch mode."""
    from core.memory.session_key import build_session_key

    session_id = build_session_key(ip_name, "pipeline")
    initial_state: GeodeState = {
        "ip_name": ip_name,
        "pipeline_mode": "full_pipeline",
        "session_id": session_id,
        "dry_run": dry_run,
        "verbose": False,
        "skip_verification": False,
        "analyses": [],
        "errors": [],
        "iteration": 1,
        "max_iterations": 3,
        # Ensemble config injection (L5 nodes read from state, not settings)
        "_ensemble_mode": settings.ensemble_mode,
        "_secondary_analysts": settings.secondary_analysts,
    }
    if not dry_run:
        tool_injection = runtime.get_tool_state_injection(mode="full_pipeline")
        initial_state.update(tool_injection)  # type: ignore[typeddict-item]
    return initial_state
