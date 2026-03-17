"""GEODE CLI — Typer entrypoint with natural language interactive mode.

Architecture (OpenClaw-inspired):
  /command  -> commands.py (Binding Router: deterministic dispatch)
  free-text -> nl_router.py (NL Router: intent classification)
              -> search.py (IP Search Engine: keyword matching)

Split modules:
  repl.py          — _interactive_loop, _read_multiline_input, _build_prompt_session,
                     _restore_terminal, signal handling
  tool_handlers.py — _build_tool_handlers (tool name -> handler mapping)
  result_cache.py  — ResultCache (multi-IP LRU with disk persistence)
"""

from __future__ import annotations

import logging
import re as _re
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from typing import Any, cast

import typer

from core import __version__
from core.cli.commands import (
    cmd_auth,
    cmd_batch,
    cmd_generate,
    cmd_key,
    cmd_list,
    cmd_mcp,
    cmd_model,
    cmd_schedule,
    cmd_skills,
    cmd_trigger,
    resolve_action,
    show_help,
)
from core.cli.repl import _build_prompt_session as _build_prompt_session
from core.cli.repl import _interactive_loop as _interactive_loop
from core.cli.repl import _read_multiline_input as _read_multiline_input
from core.cli.repl import _render_agentic_result as _render_agentic_result
from core.cli.repl import _restore_terminal as _restore_terminal
from core.cli.result_cache import ResultCache
from core.cli.result_cache import _ResultCache as _ResultCache
from core.cli.search import IPSearchEngine
from core.cli.startup import (
    ReadinessReport,
    check_readiness,
    render_readiness,
    setup_project_memory,
)
from core.cli.tool_handlers import _build_tool_handlers as _build_tool_handlers
from core.config import settings
from core.extensibility.reports import ReportFormat, ReportGenerator, ReportTemplate
from core.infrastructure.ports.hook_port import HookSystemPort
from core.llm.commentary import generate_commentary
from core.runtime import GeodeRuntime
from core.state import AnalysisResult, EvaluatorResult, GeodeState
from core.ui.console import console
from core.ui.panels import (
    analyst_panel,
    evaluator_panel,
    gather_panel,
    header_panel,
    result_panel,
    score_panel,
    verify_panel,
)
from core.ui.status import GeodeStatus

log = logging.getLogger(__name__)

# Hook system context for memory event firing (P1.5)
_hooks_ctx: ContextVar[HookSystemPort | None] = ContextVar("cli_hooks", default=None)


def _fire_hook(event: Enum, data: dict[str, Any]) -> None:
    """Fire a hook event if HookSystem is available in context."""
    hooks = _hooks_ctx.get()
    if hooks is not None:
        try:
            hooks.trigger(event, data)
        except Exception:
            log.debug("Failed to fire hook %s", event, exc_info=True)


app = typer.Typer(
    name="geode",
    help=f"GEODE v{__version__} — 범용 자율 실행 에이전트",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Thread-safe singletons for REPL session via contextvars
_search_engine_ctx: ContextVar[Any] = ContextVar("search_engine", default=None)
_readiness_ctx: ContextVar[Any] = ContextVar("readiness", default=None)
_scheduler_service_ctx: ContextVar[Any] = ContextVar("scheduler_service", default=None)


# ---------------------------------------------------------------------------
# Result cache — delegated to result_cache.py
# ---------------------------------------------------------------------------

_result_cache = ResultCache()


def _get_search_engine() -> IPSearchEngine:
    """Get or create the context-local IPSearchEngine."""
    engine = _search_engine_ctx.get()
    if engine is None:
        engine = IPSearchEngine()
        _search_engine_ctx.set(engine)
    return cast(IPSearchEngine, engine)


def _get_readiness() -> ReadinessReport | None:
    """Get the context-local ReadinessReport."""
    return cast("ReadinessReport | None", _readiness_ctx.get())


def _set_readiness(report: ReadinessReport) -> None:
    """Set the context-local ReadinessReport."""
    _readiness_ctx.set(report)


def _get_last_result() -> dict[str, Any] | None:
    """Get the most recently cached pipeline result (any IP)."""
    if not _result_cache._cache:
        return None
    # Last item in OrderedDict = most recent
    key = next(reversed(_result_cache._cache))
    return _result_cache._cache[key]


def _set_last_result(result: dict[str, Any] | None) -> None:
    """Cache a pipeline result (multi-IP LRU)."""
    _result_cache.put(result)


# ---------------------------------------------------------------------------
# Report utilities
# ---------------------------------------------------------------------------

_FORMAT_KEYWORDS = {"html", "json", "md", "markdown"}
_TEMPLATE_KEYWORDS = {"summary", "detailed", "executive"}


def _state_to_report_dict(state: dict[str, Any]) -> dict[str, Any]:
    """Convert a GeodeState dict to a plain dict suitable for ReportGenerator.

    Pydantic models are dumped via .model_dump(); scalars pass through.
    Missing fields get safe defaults.
    """
    from pydantic import BaseModel

    out: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, BaseModel):
            out[key] = value.model_dump()
        elif isinstance(value, list):
            out[key] = [v.model_dump() if isinstance(v, BaseModel) else v for v in value]
        elif isinstance(value, dict):
            out[key] = {
                k: v.model_dump() if isinstance(v, BaseModel) else v for k, v in value.items()
            }
        else:
            out[key] = value

    # Safe defaults for required report fields
    out.setdefault("ip_name", "Unknown IP")
    out.setdefault("final_score", 0.0)
    out.setdefault("tier", "N/A")
    out.setdefault("subscores", {})
    out.setdefault("synthesis", {})
    out.setdefault("analyses", [])
    return out


def _parse_report_args(parts: list[str]) -> dict[str, str]:
    """Parse report arguments from a list of tokens.

    Returns dict with keys: ip_name, fmt, template.
    Example: ["Berserk", "html", "detailed"]
      -> {"ip_name": "Berserk", "fmt": "html", "template": "detailed"}
    """
    fmt = "md"
    template = "summary"
    ip_parts: list[str] = []

    for part in parts:
        lower = part.lower()
        if lower in _FORMAT_KEYWORDS:
            fmt = "markdown" if lower == "md" else lower
        elif lower in _TEMPLATE_KEYWORDS:
            template = lower
        else:
            ip_parts.append(part)

    return {
        "ip_name": " ".join(ip_parts) if ip_parts else "",
        "fmt": fmt,
        "template": template,
    }


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REPORT_DIR = _PROJECT_ROOT / ".geode" / "reports"

# Skills relevant for report quality enhancement
_REPORT_SKILL_NAMES = ["geode-scoring", "geode-analysis", "geode-verification"]


def _build_skill_narrative(
    report_dict: dict[str, Any],
    skill_registry: Any,
) -> str:
    """Generate an expert narrative using skills context and LLM.

    Injects scoring/analysis/verification skills into the prompt so the LLM
    produces a domain-aware evaluation narrative.  Returns empty string on
    failure or when API key is unavailable.
    """
    from core.config import settings as _settings

    if not _settings.anthropic_api_key:
        return ""

    # Collect skill bodies
    skill_blocks: list[str] = []
    for name in _REPORT_SKILL_NAMES:
        skill = skill_registry.get(name)
        if skill and skill.body:
            skill_blocks.append(f"### {skill.name}\n{skill.body[:2000]}")

    if not skill_blocks:
        return ""

    skills_context = "\n\n".join(skill_blocks)

    ip_name = report_dict.get("ip_name", "Unknown")
    score = report_dict.get("final_score", 0)
    tier = report_dict.get("tier", "N/A")
    subscores = report_dict.get("subscores", {})
    synthesis = report_dict.get("synthesis", {})
    analyses = report_dict.get("analyses", [])

    analyst_summary = ""
    for a in analyses[:4]:
        if isinstance(a, dict):
            analyst_summary += (
                f"- {a.get('analyst_type', '?')}: score={a.get('score', '?')}, "
                f"finding={a.get('key_finding', '')[:120]}\n"
            )

    system_prompt = f"""You are a GEODE analysis expert. Write an expert analysis
section for a report on the subject below. Use the domain knowledge provided.

## Domain Knowledge (GEODE Skills)
{skills_context}

## Rules
- Write 3-5 paragraphs of expert analysis in Korean.
- Reference specific scoring dimensions and formulas from the skills context.
- Explain WHY this subject received its tier/score using scoring dimensions from skills context.
- Provide actionable insights and recommendations.
- Do NOT repeat raw data -- interpret and synthesize it."""

    user_prompt = f"""## IP: {ip_name}
- Final Score: {score:.1f} / 100
- Tier: {tier}
- Subscores: {subscores}
- Synthesis: {synthesis}
- Analyst Findings:
{analyst_summary}

Write the Expert Analysis section."""

    try:
        from core.llm.client import call_llm

        return str(call_llm(system_prompt, user_prompt, max_tokens=2048, temperature=0.4))
    except Exception as exc:
        log.warning("Skill-enhanced narrative generation failed: %s", exc)
        return ""


def _generate_report(
    ip_name: str,
    *,
    fmt: str = "markdown",
    template: str = "summary",
    output: str | None = None,
    dry_run: bool = True,
    verbose: bool = False,
    skill_registry: Any = None,
) -> tuple[str, str] | None:
    """Generate a report for the given IP.

    Reuses cached pipeline result if available for the same IP,
    otherwise runs analysis first.  Always saves to ``.geode/reports/``
    and returns ``(file_path, content)``.
    """
    # Resolve format/template enums
    try:
        report_fmt = ReportFormat(fmt)
    except ValueError:
        console.print(f"  [warning]Unknown format: {fmt}. Using markdown.[/warning]")
        report_fmt = ReportFormat.MARKDOWN

    try:
        report_tpl = ReportTemplate(template)
    except ValueError:
        console.print(f"  [warning]Unknown template: {template}. Using summary.[/warning]")
        report_tpl = ReportTemplate.SUMMARY

    # Try cached result first (multi-IP LRU)
    cached = _result_cache.get(ip_name)
    if cached is not None:
        result: dict[str, Any] = cached
    else:
        fresh = _run_analysis(ip_name, dry_run=dry_run, verbose=verbose)
        if fresh is None:
            return None
        result = fresh

    report_dict = _state_to_report_dict(result)

    # Skill-enhanced narrative (skip in dry-run to avoid LLM call)
    enhanced_narrative = ""
    if skill_registry is not None and not dry_run:
        with GeodeStatus("Generating expert analysis...", model=settings.model) as st:
            enhanced_narrative = _build_skill_narrative(report_dict, skill_registry)
            st.stop("expert analysis" if enhanced_narrative else "expert analysis (skipped)")

    generator = ReportGenerator()
    with console.status("  [cyan]Building report...[/cyan]", spinner="dots", spinner_style="cyan"):
        content = generator.generate(
            report_dict, fmt=report_fmt, template=report_tpl, enhanced_narrative=enhanced_narrative
        )

    # Determine save path
    ext_map = {ReportFormat.HTML: "html", ReportFormat.JSON: "json", ReportFormat.MARKDOWN: "md"}
    ext = ext_map.get(report_fmt, "md")
    safe_name = ip_name.lower().replace(" ", "-")

    if output:
        save_path = Path(output)
    else:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        save_path = _REPORT_DIR / f"{safe_name}-{template}.{ext}"

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(content, encoding="utf-8")
    console.print(f"\n  [success]Report saved -> {save_path}[/success]")

    # Also print to console
    console.print()
    console.print(content)
    console.print()

    return str(save_path), content


# ---------------------------------------------------------------------------
# Interactive welcome screen
# ---------------------------------------------------------------------------


def _render_welcome_brand() -> None:
    """Render animated Claude Code-style branding with axolotl mascot."""
    from core.ui.mascot import play_mascot_animation

    cwd = str(Path.cwd())
    play_mascot_animation(version=__version__, model=settings.model, cwd=cwd)


def _render_readiness_compact(report: ReadinessReport) -> None:
    """Render readiness as a compact block."""
    ready = [c for c in report.capabilities if c.available]
    not_ready = [c for c in report.capabilities if not c.available]

    if ready:
        names = "  ".join(f"[success]✓[/success] {c.name}" for c in ready)
        console.print(f"  {names}")
    if not_ready:
        for c in not_ready:
            hint = f" [muted]({c.reason})[/muted]" if c.reason else ""
            console.print(f"  [warning]✗[/warning] {c.name}{hint}")

    if report.blocked:
        console.print()
        console.print("  [warning]API key not configured -- key registration required[/warning]")

    console.print()


def _suppress_noisy_warnings() -> None:
    """Suppress known noisy warnings from dependencies."""
    import warnings

    # Pydantic V1 deprecation from langchain_core on Python 3.14+
    warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")
    # LangGraph msgpack deserialization warning (warnings.warn path)
    warnings.filterwarnings("ignore", message="Deserializing unregistered type")

    # LangGraph checkpoint deserialization also logs via logging.warning --
    # suppress those at the logging level.
    for noisy_logger in (
        "langgraph.checkpoint.serde.jsonplus",
        "langgraph.checkpoint.serde.base",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.ERROR)


def _welcome_screen() -> None:
    """Show Claude Code-style welcome screen with readiness check."""
    _suppress_noisy_warnings()
    _render_welcome_brand()

    # OpenClaw gateway:startup -- readiness check
    readiness = check_readiness()
    _set_readiness(readiness)
    _render_readiness_compact(readiness)

    # OpenClaw boot-md -- initialize project memory if absent
    setup_project_memory()

    console.print(
        "  [muted]/help[/muted] for commands  [muted]·[/muted]  [muted]type naturally[/muted]"
    )
    console.print()


# ---------------------------------------------------------------------------
# Pipeline execution + rendering
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


def _progress_line(done: list[str], active: str = "") -> str:
    """Build a compact progress status line."""
    parts = [f"[dim]{s}[/dim]" for s in done]
    if active:
        parts.append(f"[header]{active}[/header]")
    return " → ".join(parts) if parts else "[header]Starting...[/header]"


def _merge_event_output(final_state: dict[str, Any], output: dict[str, Any]) -> None:
    """Merge a single node's output into the accumulated final state."""
    for k, v in output.items():
        if k in ("analyses", "errors"):
            lst = v if isinstance(v, list) else [v]
            final_state.setdefault(k, []).extend(lst)
        else:
            final_state[k] = v


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
    console.print(
        f"\n  [bold yellow]Pipeline paused[/bold yellow] (iter={iteration}, steps={len(done)})"
    )
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
                                done.append("Analyze ✓")
                                status.update(_progress_line(done))
                        else:
                            done.append(f"{label} ✓")
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
                                "[step]▸ [ANALYZE][/step] Running 4 Analysts (streaming)..."
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
                                "[step]▸ [EVALUATE][/step] 14-Axis Rubric Scoring (streaming)..."
                            )
                            evaluator_header_shown = True
                        evals = output.get("evaluations", {})
                        for key, ev in evals.items():
                            _render_streaming_evaluator(key, ev)

                    elif node_name == "router":
                        console.print()
                        console.print("[step]▸ [ROUTE][/step] Loading IP data...")

                    elif node_name == "signals":
                        console.print("[step]▸ [SIGNALS][/step] Fetching signals...")

                    elif node_name == "scoring":
                        console.print()
                        console.print("[step]▸ [SCORE][/step] Calculating final score...")
                        if output.get("final_score") is not None:
                            tier = output.get("tier", "?")
                            score = output.get("final_score", 0)
                            console.print(
                                f"  Score: [bold]{score:.1f}[/bold]  Tier: [bold]{tier}[/bold]"
                            )

                    elif node_name == "verification":
                        console.print("[step]▸ [VERIFY][/step] Running guardrails...")

                    elif node_name == "synthesizer":
                        console.print()
                        console.print("[step]▸ [SYNTHESIZE][/step] Generating narrative...")
                        synth = output.get("synthesis")
                        if synth:
                            console.print(f"  Cause: {synth.undervaluation_cause}")
                            console.print(f"  Action: {synth.action_type}")

                    else:
                        label = _STEP_LABELS.get(node_name, node_name)
                        console.print(f"[step]▸ [{label.upper()}][/step] Done.")

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


def _resolve_ip_name(ip_name: str) -> str | None:
    """Resolve an IP name to a fixture key with fuzzy matching.

    Resolution order:
    1. Exact fixture key match
    2. Canonical name -> fixture key map (ip_info.ip_name lookup)
    3. Substring: fixture key is contained in input
    4. Substring: input is contained in fixture key
    """
    from core.cli.nl_router import get_ip_name_map
    from core.fixtures import FIXTURE_MAP

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
    from core.fixtures import FIXTURE_MAP

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
    }
    if not dry_run:
        tool_injection = runtime.get_tool_state_injection(mode="full_pipeline")
        initial_state.update(tool_injection)  # type: ignore[typeddict-item]
    return initial_state


# ---------------------------------------------------------------------------
# Search result rendering
# ---------------------------------------------------------------------------


def _render_search_results(query: str, results: list[Any]) -> None:
    """Render IP search results."""
    console.print()
    console.print(f"  [header]Search: '{query}'[/header]")

    if not results:
        console.print("  [muted]No matching IPs found.[/muted]")
        console.print()
        return

    for r in results:
        bar_len = int(r.score * 20)
        bar = "\u2588" * bar_len + "\u2591" * (20 - bar_len)
        style = "success" if r.score >= 0.5 else "muted"
        console.print(
            f"    [{style}]{bar}[/{style}] [dim]relevance[/dim] {r.score:.0%}"
            f"  [value]{r.ip_name}[/value]"
        )
        console.print(f"      [muted]matched: {', '.join(r.matches[:5])}[/muted]")
    console.print()


# ---------------------------------------------------------------------------
# Interactive REPL — command handler
# ---------------------------------------------------------------------------


def _handle_command(
    cmd: str,
    args: str,
    verbose: bool,
    *,
    skill_registry: Any = None,
    mcp_manager: Any = None,
) -> tuple[bool, bool]:
    """Handle a slash command. Returns (should_break, new_verbose)."""
    action = resolve_action(cmd)

    if action == "quit":
        from core.ui.agentic_ui import render_session_cost_summary

        render_session_cost_summary()
        console.print("  [muted]Goodbye.[/muted]\n")
        return True, verbose

    if action == "help":
        show_help()
    elif action == "cost":
        from core.ui.agentic_ui import render_session_cost_summary

        render_session_cost_summary()
    elif action == "list":
        cmd_list()
    elif action == "verbose":
        verbose = not verbose
        state = "[success]ON[/success]" if verbose else "[muted]OFF[/muted]"
        console.print(f"  Verbose: {state}")
        console.print()
    elif action in ("analyze", "run"):
        # Default: live LLM. Dry-run only when no API key or explicitly requested.
        readiness = _get_readiness()
        force_dry = readiness.force_dry_run if readiness else True
        # Support "--dry-run" flag in slash command args
        if "--dry-run" in args or "--dry_run" in args:
            force_dry = True
            args = args.replace("--dry-run", "").replace("--dry_run", "").strip()
        if force_dry and readiness is not None and not readiness.force_dry_run:
            console.print("  [info]Dry-run mode (explicitly requested)[/info]")
        elif force_dry:
            console.print("  [warning]API key not configured -- forcing dry-run mode[/warning]")
        if not args:
            console.print(f"  [warning]Usage: /{action} <IP name>[/warning]")
        else:
            _run_analysis(args, dry_run=force_dry, verbose=verbose)
    elif action == "search":
        if not args:
            console.print("  [warning]Usage: /search <query>[/warning]")
        else:
            results = _get_search_engine().search(args)
            _render_search_results(args, results)
    elif action == "key":
        changed = cmd_key(args)
        if changed:
            new_readiness = check_readiness()
            _set_readiness(new_readiness)
            render_readiness(new_readiness)
    elif action == "model":
        cmd_model(args)
    elif action == "auth":
        cmd_auth(args)
    elif action == "generate":
        cmd_generate(args)
    elif action == "report":
        if not args:
            console.print(
                "  [warning]Usage: /report <IP name>"
                " [html|json|md] [summary|detailed|executive][/warning]"
            )
        else:
            dry_flag = "--dry-run" in args or "--dry_run" in args
            clean_args = args.replace("--dry-run", "").replace("--dry_run", "").strip()
            report_args = _parse_report_args(clean_args.split())
            readiness = _get_readiness()
            report_dry = readiness.force_dry_run if readiness else True
            if dry_flag:
                report_dry = True
            _generate_report(
                report_args["ip_name"],
                fmt=report_args["fmt"],
                template=report_args["template"],
                dry_run=report_dry,
                verbose=verbose,
                skill_registry=skill_registry,
            )
    elif action == "batch":
        readiness = _get_readiness()
        force_dry = readiness.force_dry_run if readiness else True
        if "--dry-run" in args or "--dry_run" in args:
            force_dry = True
            args = args.replace("--dry-run", "").replace("--dry_run", "").strip()
        cmd_batch(
            args,
            run_fn=_run_analysis,
            dry_run=force_dry,
            verbose=verbose,
        )
    elif action == "schedule":
        cmd_schedule(args, scheduler_service=_scheduler_service_ctx.get(None))
    elif action == "trigger":
        cmd_trigger(args)
    elif action == "status":
        console.print()
        console.print("  [header]GEODE System Status[/header]")
        console.print(f"  Model: [bold]{settings.model}[/bold]")
        console.print(f"  Ensemble: [bold]{settings.ensemble_mode}[/bold]")
        ant_ok = bool(settings.anthropic_api_key)
        oai_ok = bool(settings.openai_api_key)
        ant_status = "[green]configured[/green]" if ant_ok else "[red]not set[/red]"
        oai_status = "[green]configured[/green]" if oai_ok else "[red]not set[/red]"
        console.print(f"  Anthropic API: {ant_status}")
        console.print(f"  OpenAI API: {oai_status}")
        readiness = _get_readiness()
        if readiness:
            mode = "Full LLM" if not readiness.force_dry_run else "Dry-Run Only"
            console.print(f"  Mode: [bold]{mode}[/bold]")
        from core.fixtures import FIXTURE_MAP as _FM

        console.print(f"  Fixtures: [bold]{len(_FM)} IPs[/bold]")

        # MCP status section
        from core.infrastructure.adapters.mcp.registry import MCPRegistry as _MCPReg

        _reg = _MCPReg()
        _json_servers = None
        if mcp_manager is not None:
            _json_servers = {s["name"]: s for s in mcp_manager.list_servers()}
        _mcp_st = _reg.get_mcp_status(json_config_servers=_json_servers)
        console.print()
        console.print("  [header]MCP Servers[/header]")
        for srv in _mcp_st["active"]:
            _src = "json" if srv["source"] == "json_config" else "auto"
            _desc = f" -- {srv['description']}" if srv["description"] else ""
            console.print(f"    [green]OK[/green] {srv['name']} [dim]({_src}){_desc}[/dim]")
        if not _mcp_st["active"]:
            console.print("    [muted]No active servers[/muted]")
        if _mcp_st["available_inactive"]:
            console.print()
            console.print("  [header]MCP Available (env missing)[/header]")
            for srv in _mcp_st["available_inactive"]:
                _env = ", ".join(srv["missing_env"])
                console.print(f"    [yellow]--[/yellow] {srv['name']} [dim]needs: {_env}[/dim]")
        console.print()
    elif action == "compare":
        parts = args.strip().split()
        if len(parts) < 2:
            console.print("  [warning]Usage: /compare <IP_A> <IP_B>[/warning]")
        else:
            dry_flag = "--dry-run" in args or "--dry_run" in args
            clean_parts = [p for p in parts if p not in ("--dry-run", "--dry_run")]
            if len(clean_parts) < 2:
                console.print("  [warning]Usage: /compare <IP_A> <IP_B>[/warning]")
            else:
                ip_a, ip_b = clean_parts[0], clean_parts[1]
                console.print(f"\n  [header]Compare: {ip_a} vs {ip_b}[/header]\n")
                readiness = _get_readiness()
                force_dry = readiness.force_dry_run if readiness else True
                if dry_flag:
                    force_dry = True
                _run_analysis(ip_a, dry_run=force_dry, verbose=verbose)
                _run_analysis(ip_b, dry_run=force_dry, verbose=verbose)
    elif action == "mcp":
        cmd_mcp(args, mcp_manager=mcp_manager)
    elif action == "skills":
        if skill_registry is not None:
            cmd_skills(skill_registry, args)
        else:
            console.print("  [muted]Skills not loaded.[/muted]")
            console.print()
    else:
        console.print(f"  [warning]Unknown command: {cmd}[/warning]")
        console.print("  [muted]Type /help for available commands.[/muted]")
        console.print()

    return False, verbose


def _show_commentary(
    user_text: str, action: str, context: dict[str, Any], *, is_offline: bool
) -> None:
    """Generate and display LLM commentary after tool call results."""
    if is_offline:
        return
    with GeodeStatus("Generating response...", model=settings.model) as status:
        text = generate_commentary(user_query=user_text, action=action, context=context)
        status.stop("response" if text else "response (skipped)")
    if text:
        console.print()
        console.print(f"  {text}")
        console.print()


def _handle_memory_action(intent: Any, user_text: str, is_offline: bool) -> None:
    """Handle memory-related actions from NL Router (P0-A + P1-B)."""
    from core.cli.nl_router import NLIntent

    intent = cast(NLIntent, intent)
    args = intent.args

    # Determine sub-action from tool routing
    rule_action = args.get("rule_action")
    query = args.get("query")
    key = args.get("key")
    content = args.get("content")

    if rule_action:
        # manage_rule tool
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
                from core.orchestration.hooks import HookEvent

                _fire_hook(HookEvent.RULE_CREATED, {"name": name, "paths": paths})
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
                from core.orchestration.hooks import HookEvent

                _fire_hook(HookEvent.RULE_UPDATED, {"name": name})
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
                from core.orchestration.hooks import HookEvent

                _fire_hook(HookEvent.RULE_DELETED, {"name": name})
            else:
                console.print(f"  [warning]Rule '{name}' not found.[/warning]")
            console.print()

    elif query:
        # memory_search tool
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

    elif key and content:
        # memory_save tool
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
            from core.orchestration.hooks import HookEvent

            _fire_hook(HookEvent.MEMORY_SAVED, {"key": key})
        else:
            console.print("  [warning]Failed to save to memory.[/warning]")
        console.print()

    else:
        console.print()
        console.print("  [muted]Memory command not recognized. Try:[/muted]")
        console.print("  [muted]  '이전 분석 결과 검색해' -- search memory[/muted]")
        console.print("  [muted]  '규칙 목록 보여줘' -- list rules[/muted]")
        console.print("  [muted]  '이 결과 기억해' -- save to memory[/muted]")
        console.print()


_DRY_RUN_PATTERN = _re.compile(
    r"(?:dry[-_\s]?run|드라이런|LLM\s*(?:호출\s*)?없이|without\s+LLM|no[-_\s]?LLM|fixture로만|간단히)",
    _re.IGNORECASE,
)


def _text_requests_dry_run(text: str) -> bool:
    """Detect if user text explicitly requests dry-run mode."""
    return bool(_DRY_RUN_PATTERN.search(text))


def _build_sub_agent_manager(
    verbose: bool = False,
    *,
    action_handlers: dict[str, Any] | None = None,
    mcp_manager: Any = None,
    skill_registry: Any = None,
) -> Any:
    """Build a SubAgentManager wired to real pipeline functions.

    P2-B: When ``action_handlers`` is provided, sub-agents receive a full
    AgenticLoop with the same tool set, MCP servers, and skills as the parent.
    Falls back to legacy ``make_pipeline_handler`` if handlers are not provided.
    """
    from core.cli.sub_agent import (
        SubAgentManager,
        make_pipeline_handler,
    )
    from core.config import settings
    from core.extensibility.agents import AgentRegistry
    from core.orchestration.isolated_execution import IsolatedRunner

    readiness = _get_readiness()
    force_dry = readiness.force_dry_run if readiness else True

    # Legacy fallback handler (used when action_handlers is not provided)
    handler = make_pipeline_handler(
        run_analysis_fn=lambda ip_name, dry_run=force_dry, **_kw: _run_analysis(
            ip_name, dry_run=dry_run, verbose=verbose
        ),
        search_fn=lambda query="", **_kw: {
            "status": "ok",
            "action": "search",
            "query": query,
            "results": [
                {"name": r.ip_name, "score": r.score} for r in _get_search_engine().search(query)
            ],
        },
        report_fn=lambda ip_name, **kw: _generate_report(
            ip_name,
            dry_run=kw.get("dry_run", force_dry),
            verbose=verbose,
            fmt=kw.get("fmt", "markdown"),
            template=kw.get("template", "summary"),
        ),
        force_dry_run=readiness.force_dry_run if readiness else True,
    )
    runner = IsolatedRunner()
    registry = AgentRegistry()
    registry.load_defaults()
    return SubAgentManager(
        runner,
        handler,
        timeout_s=300.0,
        agent_registry=registry,
        # P2-B: Full AgenticLoop inheritance
        action_handlers=action_handlers,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        depth=0,
        max_depth=settings.max_subagent_depth,
    )


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@app.callback()
def main(ctx: typer.Context) -> None:
    """GEODE -- 게임화 IP 도메인 자율 실행 하네스."""
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
    stream: bool = typer.Option(False, "--stream", help="Enable streaming output"),
    domain: str = typer.Option("game_ip", "--domain", "-d", help="Domain adapter name"),
) -> None:
    """Analyze an IP for undervaluation potential."""
    _run_analysis(
        ip_name,
        dry_run=dry_run,
        verbose=verbose,
        skip_verification=skip_verification,
        stream=stream,
        domain_name=domain,
    )


@app.command()
def report(
    ip_name: str = typer.Argument(..., help="IP name to generate report for"),
    fmt: str = typer.Option("md", "--format", "-f", help="Output format: md, html, json"),
    template: str = typer.Option(
        "summary", "--template", "-t", help="summary, detailed, executive"
    ),
    output: str = typer.Option(None, "--output", "-o", help="Save report to file"),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run", help="Use fixture data (no LLM)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """Generate a report for an IP analysis."""
    resolved_fmt = "markdown" if fmt == "md" else fmt
    _generate_report(
        ip_name,
        fmt=resolved_fmt,
        template=template,
        output=output or None,
        dry_run=dry_run,
        verbose=verbose,
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (e.g. 'dark fantasy', '소울라이크')"),
) -> None:
    """Search IPs by keyword or genre."""
    results = _get_search_engine().search(query)
    _render_search_results(query, results)


@app.command()
def version() -> None:
    """Show GEODE version."""
    console.print(f"GEODE v{__version__}")


@app.command(name="list")
def list_ips() -> None:
    """List available IP fixtures."""
    from core.fixtures import FIXTURE_MAP as _FIXTURE_MAP

    console.print("[header]Available IPs:[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"  - {name.title()}")


@app.command()
def batch(
    top: int = typer.Option(10, help="Number of IPs to analyze"),
    genre: str = typer.Option(None, help="Filter by genre"),
    concurrency: int = typer.Option(2, help="Parallel workers"),
    dry_run: bool = typer.Option(False, "--dry-run/--live", help="Use dry-run mode"),
) -> None:
    """Run batch analysis on multiple IPs."""
    from core.cli.batch import render_batch_table, run_batch

    results = run_batch(top=top, genre=genre, concurrency=concurrency, dry_run=dry_run)
    if results:
        render_batch_table(results)


if __name__ == "__main__":
    app()
