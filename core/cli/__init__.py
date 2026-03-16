"""GEODE CLI — Typer entrypoint with natural language interactive mode.

Architecture (OpenClaw-inspired):
  /command  → commands.py (Binding Router: deterministic dispatch)
  free-text → nl_router.py (NL Router: intent classification)
              → search.py (IP Search Engine: keyword matching)
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
import select
import sys
import termios
from collections import OrderedDict
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from typing import Any, cast

import typer

from core import __version__
from core.cli.agentic_loop import AgenticLoop, AgenticResult
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
from core.cli.conversation import ConversationContext
from core.cli.search import IPSearchEngine
from core.cli.startup import (
    ReadinessReport,
    check_readiness,
    key_registration_gate,
    render_readiness,
    setup_project_memory,
)
from core.cli.tool_executor import ToolExecutor
from core.config import settings
from core.extensibility.reports import ReportFormat, ReportGenerator, ReportTemplate
from core.infrastructure.ports.hook_port import HookSystemPort
from core.llm.commentary import (
    generate_commentary,
)
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
# Multi-IP LRU analysis result cache
# ---------------------------------------------------------------------------

_RESULT_CACHE_DIR = Path(".geode/result_cache")
_RESULT_CACHE_MAX = 8


class _ResultCache:
    """OrderedDict-based LRU cache for pipeline results, with disk persistence."""

    def __init__(self, max_size: int = _RESULT_CACHE_MAX) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._load_from_disk()

    def get(self, ip_name: str) -> dict[str, Any] | None:
        key = ip_name.lower()
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, result: dict[str, Any] | None) -> None:
        if result is None:
            return
        ip_name = result.get("ip_name", "")
        if not ip_name:
            return
        key = ip_name.lower()
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        self._persist(key, result)

    def _persist(self, key: str, result: dict[str, Any]) -> None:
        try:
            _RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            safe = key.replace(" ", "-")
            fpath = _RESULT_CACHE_DIR / f"{safe}.json"
            from pydantic import BaseModel

            def _default(obj: Any) -> Any:
                if isinstance(obj, BaseModel):
                    return obj.model_dump()
                return str(obj)

            fpath.write_text(
                _json.dumps(result, ensure_ascii=False, default=_default),
                encoding="utf-8",
            )
        except Exception:
            log.debug("Failed to persist result cache for %s", key, exc_info=True)

    def _load_from_disk(self) -> None:
        if not _RESULT_CACHE_DIR.exists():
            return
        for fpath in sorted(_RESULT_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = _json.loads(fpath.read_text(encoding="utf-8"))
                ip = data.get("ip_name", fpath.stem)
                self._cache[ip.lower()] = data
            except Exception:
                log.debug("Failed to load result cache %s", fpath.name, exc_info=True)
        # Trim to max
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


_result_cache = _ResultCache()


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
      → {"ip_name": "Berserk", "fmt": "html", "template": "detailed"}
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
- Do NOT repeat raw data — interpret and synthesize it."""

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
    console.print(f"\n  [success]Report saved → {save_path}[/success]")

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
        console.print("  [warning]API key not configured — key registration required[/warning]")

    console.print()


def _suppress_noisy_warnings() -> None:
    """Suppress known noisy warnings from dependencies."""
    import warnings

    # Pydantic V1 deprecation from langchain_core on Python 3.14+
    warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")
    # LangGraph msgpack deserialization warning (warnings.warn path)
    warnings.filterwarnings("ignore", message="Deserializing unregistered type")

    # LangGraph checkpoint deserialization also logs via logging.warning —
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

    # OpenClaw gateway:startup — readiness check
    readiness = check_readiness()
    _set_readiness(readiness)
    _render_readiness_compact(readiness)

    # OpenClaw boot-md — initialize project memory if absent
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
    _restore_terminal()
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

                # interrupt_before triggered — ask user
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
    """Execute the pipeline with streaming output — display results as they arrive."""
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
        # In dry-run, confidence is from fixture data — flag it
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
    2. Canonical name → fixture key map (ip_info.ip_name lookup)
    3. Substring: fixture key is contained in input
    4. Substring: input is contained in fixture key
    """
    from core.cli.nl_router import get_ip_name_map
    from core.fixtures import FIXTURE_MAP

    key = ip_name.lower().strip()

    # 1. Exact fixture key match
    if key in FIXTURE_MAP:
        return key

    # 2. Canonical ip_info.ip_name → fixture key
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
        bar = "█" * bar_len + "░" * (20 - bar_len)
        style = "success" if r.score >= 0.5 else "muted"
        console.print(
            f"    [{style}]{bar}[/{style}] [dim]relevance[/dim] {r.score:.0%}"
            f"  [value]{r.ip_name}[/value]"
        )
        console.print(f"      [muted]matched: {', '.join(r.matches[:5])}[/muted]")
    console.print()


# ---------------------------------------------------------------------------
# Interactive REPL — OpenClaw-style dual routing
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
            console.print("  [warning]API key not configured — forcing dry-run mode[/warning]")
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
        console.print("  [muted]  '이전 분석 결과 검색해' — search memory[/muted]")
        console.print("  [muted]  '규칙 목록 보여줘' — list rules[/muted]")
        console.print("  [muted]  '이 결과 기억해' — save to memory[/muted]")
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


def _build_tool_handlers(
    verbose: bool = False,
    *,
    mcp_manager: Any = None,
    agentic_ref: list[Any] | None = None,
    skill_registry: Any = None,
) -> dict[str, Any]:
    """Build tool name → handler function mapping for ToolExecutor.

    Each handler receives tool_input kwargs and returns a dict result.
    ``mcp_manager`` and ``agentic_ref`` are used by install_mcp_server.
    ``skill_registry`` is used by generate_report for skill-enhanced narrative.
    """
    from core.cli.batch import run_batch
    from core.memory.project import ProjectMemory

    readiness = _get_readiness()
    force_dry = readiness.force_dry_run if readiness else True

    def _clarify(
        tool: str,
        missing: list[str],
        hint: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """Standard clarification response for missing required params."""
        return {
            "error": f"{tool} requires: {', '.join(missing)}",
            "clarification_needed": True,
            "missing": missing,
            "hint": hint,
            **extra,
        }

    def _safe_delegate(tool_class: type, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Wrap delegated tool execution — catch KeyError as clarification."""
        try:
            result: dict[str, Any] = tool_class().execute(**kwargs)
            return result
        except (KeyError, TypeError) as exc:
            param = str(exc).strip("'\"")
            return _clarify(
                tool_class.__name__,
                [param],
                f"'{param}' 값을 알려주세요.",
            )

    def handle_list_ips(**_kwargs: Any) -> dict[str, Any]:
        from core.fixtures import FIXTURE_MAP as _FM

        cmd_list()
        names = [n.title() for n in _FM]
        return {"status": "ok", "action": "list", "count": len(names), "ips": names}

    def handle_analyze_ip(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("analyze_ip", ["ip_name"], "어떤 IP를 분석할까요?")
        dry_run = kwargs.get("dry_run", force_dry)
        if _text_requests_dry_run(ip_name):
            dry_run = True
        result = _run_analysis(ip_name, dry_run=dry_run, verbose=verbose)
        if result is None:
            return {"error": f"Analysis failed for '{ip_name}'"}
        # Extract analyst summaries for LLM context
        analyses_summary = []
        for a in result.get("analyses", []):
            if hasattr(a, "model_dump"):
                a = a.model_dump()
            analyses_summary.append(
                {
                    "type": a.get("analyst_type", "?"),
                    "score": a.get("score", 0),
                    "finding": a.get("key_finding", ""),
                }
            )
        synthesis = result.get("synthesis")
        if synthesis is not None and hasattr(synthesis, "model_dump"):
            synthesis = synthesis.model_dump()
        return {
            "status": "ok",
            "action": "analyze",
            "ip_name": result.get("ip_name", ip_name),
            "tier": result.get("tier", "N/A"),
            "score": round(result.get("final_score", 0), 1),
            "cause": (
                (synthesis or {}).get("cause", "unknown")
                if isinstance(synthesis, dict)
                else "unknown"
            ),
            "analyses": analyses_summary,
        }

    def handle_search_ips(**kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return _clarify("search_ips", ["query"], "무엇을 검색할까요?")
        results = _get_search_engine().search(query)
        _render_search_results(query, results)
        return {
            "status": "ok",
            "action": "search",
            "query": query,
            "count": len(results),
            "results": [{"name": r.ip_name, "score": r.score} for r in results],
        }

    def handle_compare_ips(**kwargs: Any) -> dict[str, Any]:
        ip_a = kwargs.get("ip_a", "")
        ip_b = kwargs.get("ip_b", "")
        dry_run = kwargs.get("dry_run", force_dry)

        # Clarification: both IPs required
        if not ip_a or not ip_b:
            missing = [k for k, v in {"ip_a": ip_a, "ip_b": ip_b}.items() if not v]
            hint = "어떤 IP와 비교할까요?" if ip_a else "비교할 두 IP를 알려주세요."
            return _clarify("compare_ips", missing, hint, provided={"ip_a": ip_a, "ip_b": ip_b})

        console.print(f"\n  [header]Compare: {ip_a} vs {ip_b}[/header]\n")
        result_a = _run_analysis(ip_a, dry_run=dry_run, verbose=verbose)
        result_b = _run_analysis(ip_b, dry_run=dry_run, verbose=verbose)

        def _ip_summary(name: str, r: dict[str, Any] | None) -> dict[str, Any]:
            if not r:
                return {"name": name, "tier": "N/A", "score": 0}
            return {
                "name": name,
                "tier": r.get("tier", "N/A"),
                "score": round(r.get("final_score", 0), 1),
            }

        return {
            "status": "ok",
            "action": "compare",
            "ip_a": _ip_summary(ip_a, result_a),
            "ip_b": _ip_summary(ip_b, result_b),
        }

    def handle_show_help(**_kwargs: Any) -> dict[str, Any]:
        show_help()
        commands = [
            "/analyze <IP> — Analyze an IP (dry-run)",
            "/run <IP> — Analyze with real LLM",
            "/search <query> — Search IPs by keyword",
            "/list — Show available IPs",
            "/compare <A> <B> — Compare two IPs",
            "/report <IP> — Generate analysis report",
            "/batch — Batch analyze multiple IPs",
            "/status — Show system status",
            "/model — Switch LLM model",
            "/help — Show help",
        ]
        return {"status": "ok", "action": "help", "commands": commands}

    def handle_generate_report(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("generate_report", ["ip_name"], "어떤 IP의 리포트를 생성할까요?")
        fmt = kwargs.get("format", "markdown")
        if fmt == "md":
            fmt = "markdown"
        template = kwargs.get("template", "summary")
        dry_run = kwargs.get("dry_run", force_dry)
        report_result = _generate_report(
            ip_name,
            dry_run=dry_run,
            verbose=verbose,
            fmt=fmt,
            template=template,
            skill_registry=skill_registry,
        )
        if report_result is None:
            return {"error": f"Report generation failed for '{ip_name}'"}
        file_path, content = report_result
        return {
            "status": "ok",
            "action": "report",
            "ip_name": ip_name,
            "format": fmt,
            "template": template,
            "file_path": file_path,
            "content_preview": content[:500] if len(content) > 500 else content,
            "content_length": len(content),
        }

    def handle_batch_analyze(**kwargs: Any) -> dict[str, Any]:
        top = kwargs.get("top", 20)
        genre = kwargs.get("genre")
        dry_run = kwargs.get("dry_run", force_dry)
        batch_results = run_batch(top=top, genre=genre, dry_run=dry_run)
        from core.cli.batch import render_batch_table

        render_batch_table(batch_results)
        summary = []
        for br in batch_results:
            if br:
                summary.append(
                    {
                        "ip_name": br.get("ip_name", "?"),
                        "tier": br.get("tier", "?"),
                        "score": round(br.get("final_score", 0), 1),
                    }
                )
        return {
            "status": "ok",
            "action": "batch",
            "count": len(batch_results),
            "results": summary[:20],
        }

    def handle_check_status(**_kwargs: Any) -> dict[str, Any]:
        from core.fixtures import FIXTURE_MAP as _FM

        ant_ok = bool(settings.anthropic_api_key)
        oai_ok = bool(settings.openai_api_key)
        mode = "full_llm" if (readiness and not readiness.force_dry_run) else "dry_run"

        console.print()
        console.print("  [header]GEODE System Status[/header]")
        console.print(f"  Model: [bold]{settings.model}[/bold]")
        console.print(f"  Ensemble: [bold]{settings.ensemble_mode}[/bold]")
        ant_status = "[green]configured[/green]" if ant_ok else "[red]not set[/red]"
        oai_status = "[green]configured[/green]" if oai_ok else "[red]not set[/red]"
        console.print(f"  Anthropic API: {ant_status}")
        console.print(f"  OpenAI API: {oai_status}")
        console.print(f"  Mode: [bold]{mode}[/bold]")
        console.print(f"  Fixtures: [bold]{len(_FM)} IPs[/bold]")
        console.print()
        return {
            "status": "ok",
            "action": "status",
            "model": settings.model,
            "ensemble": settings.ensemble_mode,
            "anthropic_configured": ant_ok,
            "openai_configured": oai_ok,
            "mode": mode,
            "fixture_count": len(_FM),
        }

    def handle_switch_model(**kwargs: Any) -> dict[str, Any]:
        model_hint = kwargs.get("model_hint", "")
        cmd_model(model_hint)
        return {
            "status": "ok",
            "action": "model",
            "current_model": settings.model,
            "ensemble": settings.ensemble_mode,
        }

    def handle_memory_search(**kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return _clarify("memory_search", ["query"], "무엇을 검색할까요?")
        try:
            mem = ProjectMemory()
            content = mem.search(query) if hasattr(mem, "search") else mem.load_memory()
            return {"status": "ok", "action": "memory_search", "content": content[:2000]}
        except Exception as exc:
            return {"error": str(exc)}

    def handle_memory_save(**kwargs: Any) -> dict[str, Any]:
        key = kwargs.get("key", "")
        content = kwargs.get("content", "")
        if not key or not content:
            missing = [k for k, v in {"key": key, "content": content}.items() if not v]
            return _clarify("memory_save", missing, "저장할 키와 내용을 알려주세요.")
        try:
            mem = ProjectMemory()
            mem.add_insight(f"{key}: {content}")
            console.print(f"  [success]Saved to memory: {key}[/success]")
            return {"status": "ok", "action": "memory_save", "key": key}
        except Exception as exc:
            return {"error": str(exc)}

    def handle_manage_rule(**kwargs: Any) -> dict[str, Any]:
        from core.cli.nl_router import NLIntent

        rule_action = kwargs.get("action", "list")
        name = kwargs.get("name", "")
        if rule_action in ("add", "delete") and not name:
            return _clarify("manage_rule", ["name"], "규칙 이름을 알려주세요.")
        intent = NLIntent(
            action="memory",
            args={
                "rule_action": rule_action,
                "name": name,
                "paths": kwargs.get("paths", []),
                "content": kwargs.get("content", ""),
            },
        )
        _handle_memory_action(intent, "", False)
        # Return rule list for LLM context
        try:
            mem = ProjectMemory()
            rules = mem.list_rules() if hasattr(mem, "list_rules") else []
            return {
                "status": "ok",
                "action": "manage_rule",
                "sub_action": rule_action,
                "name": name,
                "rules": [str(r) for r in rules][:20],
            }
        except Exception:
            return {"status": "ok", "action": "manage_rule", "sub_action": rule_action}

    def handle_set_api_key(**kwargs: Any) -> dict[str, Any]:
        key_value = kwargs.get("key_value", "")
        changed = cmd_key(key_value)
        if changed:
            new_readiness = check_readiness()
            _set_readiness(new_readiness)
            render_readiness(new_readiness)
        return {
            "status": "ok",
            "action": "key",
            "changed": changed,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
        }

    def handle_manage_auth(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "")
        cmd_auth(sub_action)
        try:
            from core.cli.commands import _get_profile_store

            store = _get_profile_store()
            profiles = [
                {"name": p.name, "provider": p.provider, "type": p.credential_type.value}
                for p in store.list_all()
            ]
        except Exception:
            profiles = []
        return {
            "status": "ok",
            "action": "auth",
            "sub_action": sub_action,
            "profiles": profiles,
        }

    def handle_generate_data(**kwargs: Any) -> dict[str, Any]:
        count = kwargs.get("count", 5)
        genre = kwargs.get("genre", "")
        gen_args = str(count)
        if genre:
            gen_args += f" {genre}"
        cmd_generate(gen_args)
        return {
            "status": "ok",
            "action": "generate",
            "count": count,
            "genre": genre or "random",
        }

    def handle_schedule_job(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "") or "list"
        target_id = kwargs.get("target_id", "")
        expression = kwargs.get("expression", "")
        svc = _scheduler_service_ctx.get(None)

        if sub_action == "create" and expression:
            cmd_schedule(f"create {expression}", scheduler_service=svc)
            try:
                from core.automation.nl_scheduler import NLScheduleParser

                result = NLScheduleParser().parse(expression)
                if result.success and result.job:
                    return {
                        "status": "ok",
                        "action": "schedule",
                        "sub_action": "create",
                        "job_id": result.job.job_id,
                        "schedule_kind": (
                            result.inferred_kind.value if result.inferred_kind else ""
                        ),
                        "expression": expression,
                    }
                return {
                    "status": "error",
                    "action": "schedule",
                    "sub_action": "create",
                    "error": result.error or "parse failed",
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "action": "schedule",
                    "sub_action": "create",
                    "error": str(exc),
                }

        sched_args = f"{sub_action} {target_id}".strip() if sub_action else ""
        cmd_schedule(sched_args, scheduler_service=svc)
        try:
            from core.automation.predefined import PREDEFINED_AUTOMATIONS

            templates = [
                {"id": t.id, "name": t.name, "enabled": t.enabled} for t in PREDEFINED_AUTOMATIONS
            ]
        except Exception:
            templates = []
        result_dict: dict[str, Any] = {
            "status": "ok",
            "action": "schedule",
            "sub_action": sub_action,
            "templates": templates[:10],
        }
        if svc is not None:
            try:
                dynamic = [
                    {"id": j.job_id, "name": j.name, "enabled": j.enabled}
                    for j in svc.list_jobs(include_disabled=True)
                    if not j.job_id.startswith("predefined:")
                ]
                result_dict["dynamic_jobs"] = dynamic
            except Exception:
                log.debug("Failed to list dynamic jobs", exc_info=True)
        return result_dict

    def handle_trigger_event(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "") or "list"
        event_name = kwargs.get("event_name", "")
        trigger_args = f"{sub_action} {event_name}".strip() if sub_action else ""
        cmd_trigger(trigger_args)
        return {
            "status": "ok",
            "action": "trigger",
            "sub_action": sub_action,
            "event_name": event_name,
        }

    # --- Plan mode handlers (multi-plan cache keyed by plan_id) ---

    _plan_cache: dict[str, tuple[Any, Any]] = {}
    _human_ratings: dict[str, dict[str, Any]] = {}
    _result_feedback: dict[str, str] = {}

    def _resolve_plan(
        plan_id: str,
    ) -> tuple[Any, Any] | None:
        """Resolve plan from cache by ID, falling back to most recent."""
        cached = _plan_cache.get(plan_id)
        if not cached and _plan_cache:
            last_key = list(_plan_cache.keys())[-1]
            cached = _plan_cache.get(last_key)
            if cached:
                log.debug(
                    "Plan ID '%s' not found, using latest '%s'",
                    plan_id,
                    last_key,
                )
        return cached

    def handle_create_plan(**kwargs: Any) -> dict[str, Any]:
        from core.config import settings
        from core.orchestration.plan_mode import PlanExecutionMode, PlanMode

        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("create_plan", ["ip_name"], "어떤 IP의 분석 계획을 세울까요?")
        template = kwargs.get("template", "full_pipeline")
        planner = PlanMode()
        plan = planner.create_plan(ip_name, template=template)
        summary = planner.present_plan(plan)

        # Display plan steps
        console.print()
        console.print(f"  [header]● Plan: {ip_name} 분석 계획[/header]")
        for i, step in enumerate(plan.steps, 1):
            console.print(f"    {i}. {step.description}")
        console.print(
            f"  [muted]예상 시간: "
            f"{plan.total_estimated_time_s:.0f}s "
            f"| 단계: {plan.step_count}개[/muted]"
        )
        console.print()
        log.info(
            "Plan '%s' created for '%s' (%d steps)",
            plan.plan_id,
            ip_name,
            plan.step_count,
        )

        # AUTO mode: approve and execute immediately without user intervention
        if settings.plan_auto_execute:
            console.print(f"  [bold cyan]▸ Auto-executing plan {plan.plan_id}[/bold cyan]")
            exec_result = planner.auto_execute_plan(plan)

            completed = exec_result.get("completed_steps", 0)
            total = exec_result.get("total_steps", 0)
            failed = exec_result.get("failed_steps", [])

            if failed:
                console.print(
                    f"  [warning]Partial success: {completed}/{total} steps "
                    f"(failed: {', '.join(failed)})[/warning]"
                )
            else:
                console.print(f"  [success]✓ All {total} steps completed[/success]")
            console.print()

            return {
                "status": "ok",
                "action": "plan",
                "plan_id": plan.plan_id,
                "ip_name": ip_name,
                "template": template,
                "step_count": plan.step_count,
                "steps": [s.description for s in plan.steps],
                "summary": summary,
                "execution_mode": PlanExecutionMode.AUTO.value,
                "auto_executed": True,
                "execution_result": exec_result,
                "hint": (
                    f"Plan auto-executed. Call analyze_ip with "
                    f"ip_name='{ip_name}' to run the full analysis."
                ),
            }

        # MANUAL mode: cache plan and wait for user approval
        _plan_cache[plan.plan_id] = (planner, plan)
        return {
            "status": "ok",
            "action": "plan",
            "plan_id": plan.plan_id,
            "ip_name": ip_name,
            "template": template,
            "step_count": plan.step_count,
            "steps": [s.description for s in plan.steps],
            "summary": summary,
            "execution_mode": PlanExecutionMode.MANUAL.value,
            "hint": ("Use approve_plan, reject_plan, or modify_plan to proceed."),
        }

    def handle_approve_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        cached = _resolve_plan(plan_id)
        if not cached:
            return {"error": "No plan to approve. Use create_plan first."}

        planner, plan = cached
        if plan_id and plan.plan_id != plan_id:
            return {"error": (f"Plan ID mismatch: expected {plan.plan_id}, got {plan_id}")}

        planner.approve_plan(plan)
        result = planner.execute_plan(plan)
        _plan_cache.pop(plan.plan_id, None)

        ip = plan.ip_name
        console.print(f"  [success]✓ Plan approved: {ip}[/success]")
        console.print()
        log.info("Plan '%s' approved for '%s'", plan.plan_id, ip)
        return {
            "status": "ok",
            "action": "approve_plan",
            "plan_id": plan.plan_id,
            "executed": True,
            "result": str(result)[:500],
            "hint": (f"Plan approved. Call analyze_ip with ip_name='{ip}' to run the analysis."),
        }

    def handle_reject_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        reason = kwargs.get("reason", "")
        cached = _resolve_plan(plan_id)
        if not cached:
            return {"error": "No plan to reject."}

        planner, plan = cached
        planner.reject_plan(plan, reason=reason)
        _plan_cache.pop(plan.plan_id, None)
        console.print(f"  [warning]✗ Plan rejected: {plan.ip_name}[/warning]")
        log.info(
            "Plan '%s' rejected (reason=%s)",
            plan.plan_id,
            reason or "(none)",
        )
        return {
            "status": "ok",
            "action": "reject_plan",
            "plan_id": plan.plan_id,
            "reason": reason,
        }

    def handle_modify_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        cached = _resolve_plan(plan_id)
        if not cached:
            return {"error": "No plan to modify."}

        planner, plan = cached
        template = kwargs.get("template")
        remove = kwargs.get("remove_steps")
        planner.modify_plan(
            plan,
            template=template,
            remove_steps=remove,
        )
        _plan_cache[plan.plan_id] = (planner, plan)
        console.print(f"  [header]● Plan modified: {plan.ip_name}[/header]")
        for i, step in enumerate(plan.steps, 1):
            console.print(f"    {i}. {step.description}")
        console.print()
        log.info(
            "Plan '%s' modified (%d steps)",
            plan.plan_id,
            plan.step_count,
        )
        return {
            "status": "ok",
            "action": "modify_plan",
            "plan_id": plan.plan_id,
            "step_count": plan.step_count,
            "steps": [s.description for s in plan.steps],
        }

    def handle_list_plans(**kwargs: Any) -> dict[str, Any]:
        plans = []
        for pid, (_, plan) in _plan_cache.items():
            plans.append(
                {
                    "plan_id": pid,
                    "ip_name": plan.ip_name,
                    "status": plan.status.value,
                    "steps": plan.step_count,
                }
            )
        return {
            "status": "ok",
            "action": "list_plans",
            "count": len(plans),
            "plans": plans,
        }

    def handle_rate_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        rating = kwargs.get("rating", 0)
        if not ip_name:
            return _clarify("rate_result", ["ip_name"], "어떤 IP에 평점을 매길까요?")
        if not (1 <= rating <= 5):
            return _clarify("rate_result", ["rating"], "평점은 1-5 사이로 입력해주세요.")
        comment = kwargs.get("comment", "")
        _human_ratings[ip_name] = {
            "rating": rating,
            "comment": comment,
        }
        console.print(f"  [success]✓ Rating saved for {ip_name}: {rating}/5[/success]")
        log.info(
            "HITL rating: %s = %d/5",
            ip_name,
            rating,
        )
        return {
            "status": "ok",
            "action": "rate_result",
            "ip_name": ip_name,
            "rating": rating,
        }

    def handle_accept_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("accept_result", ["ip_name"], "어떤 IP 결과를 수락할까요?")
        _result_feedback[ip_name] = "accepted"
        console.print(f"  [success]✓ Result accepted: {ip_name}[/success]")
        log.info("HITL accept: %s", ip_name)
        return {
            "status": "ok",
            "action": "accept_result",
            "ip_name": ip_name,
        }

    def handle_reject_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("reject_result", ["ip_name"], "어떤 IP 결과를 거부할까요?")
        reason = kwargs.get("reason", "")
        _result_feedback[ip_name] = "rejected"
        console.print(f"  [warning]✗ Result rejected: {ip_name}[/warning]")
        log.info(
            "HITL reject: %s (reason=%s)",
            ip_name,
            reason or "(none)",
        )
        return {
            "status": "ok",
            "action": "reject_result",
            "ip_name": ip_name,
            "reason": reason,
            "hint": ("Use rerun_node to re-execute specific pipeline steps."),
        }

    def handle_rerun_node(**kwargs: Any) -> dict[str, Any]:
        node_name = kwargs.get("node_name", "")
        ip_name = kwargs.get("ip_name", "")
        if not node_name or not ip_name:
            missing = [k for k, v in {"node_name": node_name, "ip_name": ip_name}.items() if not v]
            return _clarify("rerun_node", missing, "재실행할 노드와 IP를 알려주세요.")
        allowed = {"scoring", "verification", "synthesizer"}
        if node_name not in allowed:
            return {
                "error": (f"Cannot rerun '{node_name}'. Allowed: {sorted(allowed)}"),
            }
        console.print(f"  [header]▸ Rerunning {node_name} for {ip_name}[/header]")
        log.info(
            "HITL rerun: %s for %s",
            node_name,
            ip_name,
        )
        return {
            "status": "ok",
            "action": "rerun_node",
            "node_name": node_name,
            "ip_name": ip_name,
            "hint": ("Node re-execution queued. Results will update in-place."),
        }

    # --- New tools: web, document, note, signal ---
    # All delegated tools wrapped with _safe_delegate for KeyError → clarification

    def handle_web_fetch(**kwargs: Any) -> dict[str, Any]:
        from core.tools.web_tools import WebFetchTool

        return _safe_delegate(WebFetchTool, kwargs)

    def handle_general_web_search(**kwargs: Any) -> dict[str, Any]:
        from core.tools.web_tools import GeneralWebSearchTool

        return _safe_delegate(GeneralWebSearchTool, kwargs)

    def handle_read_document(**kwargs: Any) -> dict[str, Any]:
        from core.tools.document_tools import ReadDocumentTool

        return _safe_delegate(ReadDocumentTool, kwargs)

    def handle_note_save(**kwargs: Any) -> dict[str, Any]:
        from core.tools.memory_tools import NoteSaveTool

        return _safe_delegate(NoteSaveTool, kwargs)

    def handle_note_read(**kwargs: Any) -> dict[str, Any]:
        from core.tools.memory_tools import NoteReadTool

        return _safe_delegate(NoteReadTool, kwargs)

    # Profile tools (Tier 0.5)
    def handle_profile_show(**kwargs: Any) -> dict[str, Any]:
        from core.tools.profile_tools import ProfileShowTool

        return _safe_delegate(ProfileShowTool, kwargs)

    def handle_profile_update(**kwargs: Any) -> dict[str, Any]:
        from core.tools.profile_tools import ProfileUpdateTool

        return _safe_delegate(ProfileUpdateTool, kwargs)

    def handle_profile_preference(**kwargs: Any) -> dict[str, Any]:
        from core.tools.profile_tools import ProfilePreferenceTool

        return _safe_delegate(ProfilePreferenceTool, kwargs)

    def handle_profile_learn(**kwargs: Any) -> dict[str, Any]:
        from core.tools.profile_tools import ProfileLearnTool

        return _safe_delegate(ProfileLearnTool, kwargs)

    def handle_youtube_search(**kwargs: Any) -> dict[str, Any]:
        from core.tools.signal_tools import YouTubeSearchTool

        return _safe_delegate(YouTubeSearchTool, kwargs)

    def handle_reddit_sentiment(**kwargs: Any) -> dict[str, Any]:
        from core.tools.signal_tools import RedditSentimentTool

        return _safe_delegate(RedditSentimentTool, kwargs)

    def handle_steam_info(**kwargs: Any) -> dict[str, Any]:
        from core.tools.signal_tools import SteamInfoTool

        return _safe_delegate(SteamInfoTool, kwargs)

    def handle_google_trends(**kwargs: Any) -> dict[str, Any]:
        from core.tools.signal_tools import GoogleTrendsTool

        return _safe_delegate(GoogleTrendsTool, kwargs)

    def handle_install_mcp_server(**kwargs: Any) -> dict[str, Any]:
        import os as _os

        from core.infrastructure.adapters.mcp.catalog import search_catalog

        query = kwargs.get("query", "")
        matches = search_catalog(query)
        if not matches:
            return {
                "status": "not_found",
                "message": f"'{query}'에 맞는 MCP 서버를 찾지 못했습니다.",
            }

        best = matches[0]

        # Already installed?
        if mcp_manager is not None:
            existing = {s["name"] for s in mcp_manager.list_servers()}
            if best.name in existing:
                return {
                    "status": "already_installed",
                    "server": best.name,
                    "message": f"{best.name}은 이미 설치되어 있습니다.",
                }

        if mcp_manager is None:
            return {"status": "error", "message": "MCP manager not available"}

        # Register server
        args = ["-y", best.package, *best.extra_args]
        env_map = {k: f"${{{k}}}" for k in best.env_keys} or None
        ok = mcp_manager.add_server(best.name, best.command, args=args, env=env_map)
        if not ok:
            return {"status": "error", "message": f"Failed to save {best.name}"}

        # Hot-reload tools into running AgenticLoop
        added = 0
        if agentic_ref and agentic_ref[0] is not None:
            added = agentic_ref[0].refresh_tools()

        # Check for missing env vars
        missing = [k for k in best.env_keys if not _os.environ.get(k)]

        msg = f"{best.name} 설치 완료. {added}개 도구 추가됨."
        if missing:
            msg += f" 환경변수 필요: {', '.join(missing)}"

        return {
            "status": "installed",
            "server": best.name,
            "package": best.package,
            "tools_added": added,
            "env_required": list(best.env_keys),
            "env_missing": missing,
            "message": msg,
        }

    return {
        "list_ips": handle_list_ips,
        "analyze_ip": handle_analyze_ip,
        "search_ips": handle_search_ips,
        "compare_ips": handle_compare_ips,
        "show_help": handle_show_help,
        "generate_report": handle_generate_report,
        "batch_analyze": handle_batch_analyze,
        "check_status": handle_check_status,
        "switch_model": handle_switch_model,
        "memory_search": handle_memory_search,
        "memory_save": handle_memory_save,
        "manage_rule": handle_manage_rule,
        "set_api_key": handle_set_api_key,
        "manage_auth": handle_manage_auth,
        "generate_data": handle_generate_data,
        "schedule_job": handle_schedule_job,
        "trigger_event": handle_trigger_event,
        "create_plan": handle_create_plan,
        "approve_plan": handle_approve_plan,
        "reject_plan": handle_reject_plan,
        "modify_plan": handle_modify_plan,
        "list_plans": handle_list_plans,
        "rate_result": handle_rate_result,
        "accept_result": handle_accept_result,
        "reject_result": handle_reject_result,
        "rerun_node": handle_rerun_node,
        # New tools
        "web_fetch": handle_web_fetch,
        "general_web_search": handle_general_web_search,
        "read_document": handle_read_document,
        "note_save": handle_note_save,
        "note_read": handle_note_read,
        # Profile tools (Tier 0.5)
        "profile_show": handle_profile_show,
        "profile_update": handle_profile_update,
        "profile_preference": handle_profile_preference,
        "profile_learn": handle_profile_learn,
        # Signal tools
        "youtube_search": handle_youtube_search,
        "reddit_sentiment": handle_reddit_sentiment,
        "steam_info": handle_steam_info,
        "google_trends": handle_google_trends,
        # MCP auto-install
        "install_mcp_server": handle_install_mcp_server,
    }


def _render_agentic_result(result: AgenticResult) -> None:
    """Render the final result from an agentic loop execution."""
    if result.error == "llm_call_failed":
        console.print()
        console.print("  [warning]LLM call failed. Try again or check your API key.[/warning]")
        console.print("  [muted]Use /help for available commands.[/muted]")
        console.print()
        return

    if result.text:
        console.print()
        # Render markdown if the response contains markdown indicators
        if any(md in result.text for md in ("## ", "| ", "```", "**", "- [")):
            from rich.markdown import Markdown
            from rich.padding import Padding

            md = Markdown(result.text)
            console.print(Padding(md, (0, 2)))
        else:
            console.print(f"  {result.text}")
        console.print()

    if result.tool_calls:
        tool_names = [tc["tool"] for tc in result.tool_calls]
        log.debug(
            "Agentic loop: %d rounds, %d tool calls (%s)",
            result.rounds,
            len(result.tool_calls),
            ", ".join(tool_names),
        )


def _restore_terminal() -> None:
    """Restore terminal to sane cooked mode.

    Rich Status/Live can leave the terminal in raw mode (echo off, no
    line-editing) if interrupted or if an exception escapes their context
    manager.  This ensures the terminal is usable before reading input.
    """
    try:
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        # Ensure ECHO and ICANON (cooked mode) are enabled
        attrs[3] |= termios.ECHO | termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (ValueError, OSError, termios.error):
        # Non-TTY or stdin not available — nothing to restore
        pass


# ---------------------------------------------------------------------------
# prompt_toolkit REPL input (arrow keys, history, multi-line paste)
# ---------------------------------------------------------------------------
def _build_prompt_session() -> Any:
    """Create a prompt_toolkit PromptSession with history + GEODE styling.

    Includes a custom Backspace/Delete key binding that forces a full
    renderer redraw after deletion — fixes wide-char (Korean jamo) ghost
    artifacts where the display doesn't update even though the buffer is
    correctly modified.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @kb.add("backspace")
    def _backspace(event: Any) -> None:
        buf = event.app.current_buffer
        if buf.cursor_position > 0:
            buf.delete_before_cursor(count=1)
            event.app.renderer.reset()
            event.app.invalidate()

    @kb.add("delete")
    def _delete(event: Any) -> None:
        buf = event.app.current_buffer
        if buf.cursor_position < len(buf.text):
            buf.delete(count=1)
            event.app.renderer.reset()
            event.app.invalidate()

    history_path = Path.home() / ".geode_history"
    return PromptSession(
        history=FileHistory(str(history_path)),
        message=HTML("<b>&gt;</b> "),
        enable_history_search=True,
        multiline=False,
        key_bindings=kb,
    )


# Module-level lazy singleton
_prompt_session: Any = None


def _get_prompt_session() -> Any:
    global _prompt_session
    if _prompt_session is None:
        try:
            _prompt_session = _build_prompt_session()
        except Exception:
            log.debug("prompt_toolkit init failed, falling back to console.input", exc_info=True)
    return _prompt_session


def _read_multiline_input(prompt: str) -> str:
    """Read user input via prompt_toolkit (arrow keys, history, paste).

    Falls back to Rich console.input if prompt_toolkit is unavailable.
    Multi-line paste is detected by draining buffered stdin (50 ms timeout).
    When paste is detected, shows ``[Pasted text +N lines]`` notification
    and waits for additional input before submitting.
    """
    _restore_terminal()

    session = _get_prompt_session()
    if session is not None:
        try:
            first_line = session.prompt().strip()
        except (KeyboardInterrupt, EOFError):
            raise
        except Exception:
            first_line = console.input("> ").strip()
    else:
        first_line = console.input("> ").strip()

    # Repaint the prompt line to erase wide-char rendering artifacts
    # (Korean jamo ghosts left after backspace in some terminals).
    # After Enter, cursor is on the NEXT line; move up, clear, rewrite.
    if first_line:
        sys.stdout.write(f"\x1b[F\x1b[2K> {first_line}\n")
        sys.stdout.flush()

    if not first_line:
        return ""

    # Drain pasted lines from stdin buffer (skip escape sequences)
    lines = [first_line]
    try:
        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0.05)[0]:
            line = sys.stdin.readline()
            if not line:
                break
            stripped = line.rstrip("\n")
            # Filter out arrow-key / terminal escape sequences that leak
            # into the buffer (e.g. \x1b[A for Up, \x1b[B for Down).
            if stripped and "\x1b" not in stripped:
                lines.append(stripped)
    except (ValueError, OSError):
        pass  # stdin not selectable (piped / non-TTY)

    # Paste notification — show count and wait for explicit submit
    extra_count = len(lines) - 1
    if extra_count > 0:
        console.print(f"  [dim][Pasted text +{extra_count} lines][/dim]")
        # Allow user to add more input or press Enter to submit
        _restore_terminal()
        if session is not None:
            try:
                additional = session.prompt().strip()
            except (KeyboardInterrupt, EOFError):
                additional = ""
            except Exception:
                additional = ""
        else:
            try:
                additional = console.input("> ").strip()
            except (KeyboardInterrupt, EOFError):
                additional = ""
        if additional:
            lines.append(additional)

    return "\n".join(lines)


def _interactive_loop() -> None:
    """Claude Code / OpenClaw-style interactive REPL.

    Three routing paths:
      /command  → deterministic dispatch (commands.py)
      free-text → agentic loop (AgenticLoop, multi-turn + multi-intent)
      fallback  → single-shot NL Router (when agentic unavailable)
    """
    verbose = False
    conversation = ConversationContext(max_turns=20)

    # --- Startup initialization with progressive status ---
    def _init_step(label: str) -> None:
        """Print a compact startup progress indicator."""
        console.print(f"  [dim]Loading {label}...[/dim]", end="\r")

    def _init_done(label: str, ok: bool = True) -> None:
        mark = "[bold green]ok[/bold green]" if ok else "[dim]skip[/dim]"
        console.print(f"  {mark} {label}          ")

    # 1. Domain adapter
    _init_step("domain")
    from core.domains.loader import load_domain_adapter
    from core.infrastructure.ports.domain_port import set_domain

    try:
        set_domain(load_domain_adapter("game_ip"))
        _init_done("Domain")
    except Exception:
        _init_done("Domain", ok=False)
        log.debug("Domain adapter initialization skipped", exc_info=True)

    # 2. Memory contextvars
    _init_step("memory")
    from core.memory.organization import MonoLakeOrganizationMemory
    from core.memory.project import ProjectMemory
    from core.tools.memory_tools import set_org_memory, set_project_memory

    try:
        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())
        _init_done("Memory")
    except Exception:
        _init_done("Memory", ok=False)
        log.debug("Memory context initialization skipped", exc_info=True)

    # 3. Key gate
    readiness = _get_readiness()
    if readiness is None or readiness.blocked:
        key = key_registration_gate()
        if key is None:
            return  # user quit
        readiness = check_readiness()
        _set_readiness(readiness)

    # 4. MCP servers (slowest — npx subprocess spawn)
    _init_step("MCP servers")
    from core.infrastructure.adapters.mcp.manager import MCPServerManager

    mcp_mgr: MCPServerManager | None = None
    try:
        _mgr = MCPServerManager()
        n_mcp = _mgr.load_config()
        if n_mcp > 0:
            mcp_mgr = _mgr
            import atexit

            atexit.register(_mgr.close_all)
            _init_done(f"MCP ({n_mcp} servers)")
        else:
            _init_done("MCP (none)", ok=False)
    except Exception:
        _init_done("MCP", ok=False)
        log.debug("MCP initialization skipped", exc_info=True)

    # 5. Skills
    _init_step("skills")
    from core.extensibility.skills import SkillLoader, SkillRegistry

    skill_registry = SkillRegistry()
    try:
        loaded_skills = SkillLoader().load_all(registry=skill_registry)
        _init_done(f"Skills ({len(loaded_skills)})" if loaded_skills else "Skills (0)")
    except Exception:
        _init_done("Skills", ok=False)
        log.debug("Skill loading skipped", exc_info=True)

    # 6. Scheduler
    _init_step("scheduler")
    try:
        from core.automation.scheduler import SchedulerService

        _sched_svc = SchedulerService()
        _sched_svc.load()
        _sched_svc.start()
        _scheduler_service_ctx.set(_sched_svc)
        _init_done("Scheduler")
    except Exception:
        _init_done("Scheduler", ok=False)
        log.debug("SchedulerService initialization skipped", exc_info=True)

    console.print()  # blank line before prompt

    # Build tool handlers and executor
    agentic_ref: list[Any] = [None]  # mutable ref for handler closure
    handlers = _build_tool_handlers(
        verbose=verbose, mcp_manager=mcp_mgr, agentic_ref=agentic_ref, skill_registry=skill_registry
    )
    sub_mgr = _build_sub_agent_manager(
        verbose=verbose,
        action_handlers=handlers,
        mcp_manager=mcp_mgr,
        skill_registry=skill_registry,
    )
    executor = ToolExecutor(
        action_handlers=handlers,
        mcp_manager=mcp_mgr,
        sub_agent_manager=sub_mgr,
    )
    agentic = AgenticLoop(
        conversation, executor, mcp_manager=mcp_mgr, skill_registry=skill_registry
    )
    agentic_ref[0] = agentic

    # Initialize session meter for status line
    from core.ui.agentic_ui import init_session_meter

    init_session_meter(model=agentic.model)

    while True:
        # Defensive: restore terminal state before each prompt
        # (Rich Status/Live may leave cursor hidden or echo off)
        console.show_cursor(True)

        try:
            user_input = _read_multiline_input("[header]>[/header] ")
        except (KeyboardInterrupt, EOFError):
            from core.ui.agentic_ui import render_session_cost_summary

            render_session_cost_summary()
            console.print("\n  [muted]Goodbye.[/muted]\n")
            break

        if not user_input:
            continue

        # Bare exit/quit → immediate shutdown (no LLM round-trip)
        if user_input.strip().lower() in ("exit", "quit", "q"):
            from core.ui.agentic_ui import render_session_cost_summary

            render_session_cost_summary()
            console.print("  [muted]Goodbye.[/muted]\n")
            break

        # Multi-line paste → always route to agentic (never slash-dispatch)
        is_multiline = "\n" in user_input
        if not is_multiline and user_input.startswith("/"):
            # Slash command → deterministic routing (OpenClaw Binding)
            cmd = user_input.split()[0].lower()
            args = user_input[len(cmd) :].strip()
            should_break, verbose = _handle_command(
                cmd,
                args,
                verbose,
                skill_registry=skill_registry,
                mcp_manager=mcp_mgr,
            )
            if should_break:
                break
            # Update handlers if verbose changed
            if verbose != (handlers.get("_verbose_flag") is True):
                handlers = _build_tool_handlers(
                    verbose=verbose,
                    mcp_manager=mcp_mgr,
                    agentic_ref=agentic_ref,
                    skill_registry=skill_registry,
                )
                sub_mgr = _build_sub_agent_manager(
                    verbose=verbose,
                    action_handlers=handlers,
                    mcp_manager=mcp_mgr,
                    skill_registry=skill_registry,
                )
                executor = ToolExecutor(
                    action_handlers=handlers,
                    mcp_manager=mcp_mgr,
                    sub_agent_manager=sub_mgr,
                )
                agentic = AgenticLoop(
                    conversation,
                    executor,
                    mcp_manager=mcp_mgr,
                    skill_registry=skill_registry,
                )
                agentic_ref[0] = agentic
        else:
            # Agentic loop: multi-turn + multi-intent (online) or offline regex
            try:
                result = agentic.run(user_input)
                _render_agentic_result(result)
                # Claude Code-style status line after each result
                from core.ui.agentic_ui import render_status_line

                render_status_line()
            except KeyboardInterrupt:
                console.show_cursor(True)
                console.print("\n  [dim]Interrupted.[/dim]\n")
            except Exception as exc:
                console.show_cursor(True)
                log.error("Agentic loop error: %s", exc, exc_info=True)
                console.print(f"\n  [error]Error: {exc}[/error]\n")

    # Clean shutdown: MCP servers → SchedulerService
    if mcp_mgr is not None:
        try:
            mcp_mgr.close_all()
        except Exception:
            log.debug("MCP shutdown error", exc_info=True)

    _sched = _scheduler_service_ctx.get(None)
    if _sched is not None:
        try:
            _sched.save()
            _sched.stop()
        except Exception:
            log.debug("SchedulerService shutdown error", exc_info=True)


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@app.callback()
def main(ctx: typer.Context) -> None:
    """GEODE — 게임화 IP 도메인 자율 실행 하네스."""
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
