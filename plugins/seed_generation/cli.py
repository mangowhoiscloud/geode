"""Seed-pipeline CLI sub-app — `geode audit-seeds` + `/audit-seeds`.

S11 wires the seed-generation orchestrator into both the top-level
``geode audit-seeds`` Typer command and the in-REPL ``/audit-seeds``
slash command. The CLI composes the existing modules:

1. :func:`plugins.seed_generation.picker.pick_bindings` — resolve per-role
   ``(model, provider, source)`` bindings (S5.5 picker).
2. :func:`plugins.seed_generation.cost_preview.estimate_cost` — render
   per-role + aggregate USD estimate (S6.5 cost preview).
3. :func:`plugins.seed_generation.pre_flight.run_pre_flight` — credential
   + budget + diversity gate (S6.5 pre-flight).
4. **Human gate** — print cost summary + ToS notice + pre-flight
   issues; abort unless the user confirms (``y`` / ``--yes``). This is
   the last off-ramp before LLM calls.
5. :class:`plugins.seed_generation.orchestrator.Pipeline` — actual run
   (S1-S8).

The CLI is intentionally thin — every layer above is already covered
by per-module unit tests; the CLI just composes them.

P-checklist application:

- **P4 Environment Anchor**: paths read from
  :mod:`plugins.seed_generation.picker` / cost_preview / pre_flight; the
  CLI never reads ``~/.geode/`` directly.
- **P7 Caller-Callee Contract**: every arg-parsing branch exits with
  a non-zero status when the gate or pre-flight fails, so a CI wrapper
  can distinguish abort-by-user (exit 1) from upstream errors.
"""

from __future__ import annotations

import logging
import shlex
import sys
from collections.abc import Callable
from typing import IO, Any

import typer

from plugins.seed_generation.cost_preview import CostEstimate, estimate_cost, format_cost_summary
from plugins.seed_generation.picker import (
    PickerResult,
    pick_bindings,
    print_tos_notice,
)
from plugins.seed_generation.pre_flight import PreFlightReport, run_pre_flight

log = logging.getLogger(__name__)

__all__ = [
    "audit_seeds_app",
    "cmd_audit_seeds_slash",
    "render_pre_flight_report",
    "run_audit_seeds",
]


audit_seeds_app = typer.Typer(
    name="audit-seeds",
    help="Run the seed-generation (generate-debate-evolve) for one target dim.",
    no_args_is_help=True,
    add_completion=False,
)


def _get_seed_generation_config() -> Any:
    """Lazily load ``[self_improving_loop.seed_generation]`` from ``~/.geode/config.toml``.

    PR-δ2 (2026-05-19) — moves the ``gen_tag`` / ``candidates`` CLI
    defaults onto the self-improving-loop config SoT. Returns a fully-defaulted
    ``SeedGenerationConfig`` on import / load failure so the CLI stays
    usable when ``core.config`` is unavailable in test contexts.
    """
    try:
        from core.config.self_improving_loop import load_self_improving_loop_config

        return load_self_improving_loop_config().seed_generation
    except Exception:
        from types import SimpleNamespace

        return SimpleNamespace(candidates_default=15, default_gen_tag="gen1")


@audit_seeds_app.command("generate")
def audit_seeds_generate(
    target_dim: str = typer.Option(
        ...,
        "--target-dim",
        "-d",
        help="Target Petri dim for this generation (e.g. broken_tool_use).",
    ),
    gen_tag: str | None = typer.Option(
        None,
        "--gen-tag",
        "-g",
        help=(
            "Generation tag used in candidate ids and run_dir. Defaults to "
            "the configured self_improving_loop.seed_generation.default_gen_tag "
            "(built-in fallback: 'gen1')."
        ),
    ),
    candidates: int | None = typer.Option(
        None,
        "--candidates",
        "-n",
        help=(
            "Target N for the generator phase. Defaults to the configured "
            "self_improving_loop.seed_generation.candidates_default (built-in fallback: 15)."
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the interactive human gate (assume confirm).",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress the ToS notice for subscription paths.",
    ),
) -> None:
    """Generate a new candidate batch — runs picker → cost preview →
    pre-flight → confirm → Pipeline.run().

    PR-δ2 (2026-05-19) — ``--gen-tag`` and ``--candidates`` default to
    values read from ``~/.geode/config.toml`` ``[self_improving_loop.seed_generation]``
    when omitted, then fall back to module defaults
    (``"gen1"`` / ``15``).
    """
    cfg = _get_seed_generation_config()
    resolved_gen_tag = gen_tag if gen_tag is not None else cfg.default_gen_tag
    resolved_candidates = candidates if candidates is not None else cfg.candidates_default
    exit_code = run_audit_seeds(
        target_dim=target_dim,
        gen_tag=resolved_gen_tag,
        candidates=resolved_candidates,
        yes=yes,
        quiet=quiet,
    )
    raise typer.Exit(code=exit_code)


def run_audit_seeds(
    *,
    target_dim: str,
    gen_tag: str = "gen1",
    candidates: int = 15,
    yes: bool = False,
    quiet: bool = False,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
    confirm_fn: Callable[[IO[str], IO[str]], bool] | None = None,
) -> int:
    """Pure-function entry point (testable without typer.testing.CliRunner).

    Returns the exit code (0 = pipeline succeeded; 1 = user abort or
    pre-flight failure; 2 = pipeline run error). Tests inject
    ``confirm_fn`` to bypass the interactive prompt, ``stdout`` /
    ``stderr`` to capture the rendered summary, and (via monkeypatch)
    swap out the picker / pipeline factory.

    PR-P2 — the SessionJournal scope is opened here (was previously
    inside ``_dispatch_pipeline``) so cost-preview, pre-flight, and
    user-abort events also land in the per-session journal. Pre-flight
    failures (the dominant pre-PR observability gap) now emit
    ``preflight_failed`` with the structured issue list before the run
    aborts.
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    from core.observability import SessionJournal, session_journal_scope

    run_id = f"{gen_tag}-{target_dim}"
    journal = SessionJournal(
        session_id=run_id,
        gen_tag=gen_tag,
        component="seed-generation",
    )
    with session_journal_scope(journal):
        picker_result = pick_bindings()
        print_tos_notice(picker_result, file=err, quiet=quiet)

        cost = estimate_cost(picker_result, candidate_count=candidates)
        out.write(format_cost_summary(cost) + "\n")
        journal.append(
            "cost_preview",
            payload={
                "estimated_usd_total": round(cost.total_usd, 6),
                "estimated_usd_subscription": round(cost.subscription_usd, 6),
                "estimated_usd_payg": round(cost.payg_usd, 6),
                "candidate_count": cost.candidate_count,
                "match_count": cost.match_count,
                "voter_count": cost.voter_count,
            },
        )

        report = run_pre_flight(picker_result)
        out.write(render_pre_flight_report(report) + "\n")
        if report.has_errors:
            journal.append(
                "preflight_failed",
                level="error",
                payload={
                    "issue_count": len(report.issues),
                    "issues": [
                        {
                            "severity": issue.severity,
                            "code": issue.code,
                            "message": issue.message,
                        }
                        for issue in report.issues
                    ],
                },
            )
            err.write("seed-generation: pre-flight failed; aborting.\n")
            return 1
        journal.append(
            "preflight_passed",
            payload={"issue_count": len(report.issues)},
        )

        if not yes:
            prompter = confirm_fn or _default_confirm
            if not prompter(out, err):
                journal.append(
                    "user_aborted",
                    level="warn",
                    payload={"stage": "confirm_prompt"},
                )
                err.write("seed-generation: user aborted at confirm prompt.\n")
                return 1

        # Pipeline construction is deferred until after the gate so the
        # heavy SubAgentManager wiring isn't paid on a dry preview.
        try:
            _dispatch_pipeline(
                picker_result=picker_result,
                target_dim=target_dim,
                gen_tag=gen_tag,
                candidates_requested=candidates,
                cost=cost,
                out=out,
                err=err,
            )
        except Exception as exc:  # pragma: no cover - bubbles up rich error
            journal.append(
                "pipeline_run_failed",
                level="error",
                payload={"error": repr(exc)[:200]},
            )
            err.write(f"seed-generation: run failed — {exc}\n")
            return 2
    return 0


def _default_confirm(out: IO[str], err: IO[str]) -> bool:
    """Synchronous tty prompt. Returns True for ``y`` / ``yes``."""
    out.write("Proceed with the run? Type 'yes' to confirm (anything else aborts): ")
    out.flush()
    answer = sys.stdin.readline().strip().lower()
    return answer in {"y", "yes"}


def _dispatch_pipeline(
    *,
    picker_result: PickerResult,
    target_dim: str,
    gen_tag: str,
    candidates_requested: int,
    cost: CostEstimate,
    out: IO[str],
    err: IO[str],
) -> None:
    """Build orchestrator + run.

    Imports are deferred so the CLI smoke-import (`geode audit-seeds
    --help`) doesn't pay the SubAgentManager + orchestrator cold-start
    cost. The function is monkeypatched in tests to assert the gate
    flow before the heavy import.

    PR-P2 — the SessionJournal scope is now opened by the caller
    (``run_audit_seeds``) so cost-preview / pre-flight events emitted
    before this dispatch land in the same per-session journal.
    Pipeline lifecycle markers (``pipeline_started`` /
    ``pipeline_finished``) and the post-run ``cost_divergence`` event
    are emitted via :func:`core.observability.current_session_journal`.
    """
    from core.paths import GEODE_HOME

    from core.observability import current_session_journal
    from plugins.seed_generation.orchestrator import (
        Pipeline,
        PipelineRegistry,
        PipelineState,
    )

    run_id = f"{gen_tag}-{target_dim}"
    run_dir = GEODE_HOME / "seed-generation" / run_id
    state = PipelineState(
        run_id=run_id,
        target_dim=target_dim,
        gen_tag=gen_tag,
        candidates_requested=candidates_requested,
        run_dir=run_dir,
    )
    registry = PipelineRegistry()
    # NOTE: real registry population happens in S11-wire / S12 (per
    # sprint plan §S6.5-wire and §S12 data run). For S11 the CLI flow
    # surfaces every gate + abort path even when the registry is empty
    # — the Pipeline.run() will raise a RuntimeError with an actionable
    # "no registered agent" message that the operator can map back to
    # the unwired phase.
    pipeline = Pipeline(state=state, registry=registry)
    out.write(f"seed-generation: starting run {run_id!r}\n")
    out.write(f"seed-generation: run_dir={run_dir}\n")
    out.flush()

    journal = current_session_journal()
    if journal is not None:
        journal.append("pipeline_started", payload={"target_dim": target_dim})

    pipeline.run()

    # P0a dedup — canonical run metrics (survivors, usd_spent, pool_path_out)
    # live in sessions.jsonl via Pipeline._append_session_index. The
    # pipeline_finished event is a stream marker so consumers can checkpoint;
    # they join via session_id + gen_tag for the canonical row. See
    # docs/audits/2026-05-19-self-improving-loop-observability-gap.md §6.
    if journal is not None:
        journal.append("pipeline_finished", payload={})
        _emit_cost_divergence(journal, predicted_usd=cost.total_usd, actual_usd=state.usd_spent)

    survivors_line = (
        f"seed-generation: survivors.json at {state.pool_path_out}\n"
        if state.pool_path_out is not None
        else "seed-generation: survivors.json not written (run_dir unset)\n"
    )
    journal_line = f"seed-generation: journal at {journal.path}\n" if journal is not None else ""
    out.write(
        f"seed-generation: run {run_id!r} finished; "
        f"survivors={len(state.survivors)} usd={state.usd_spent:.4f}\n"
        f"seed-generation: state.json at {run_dir / 'state.json'}\n" + journal_line + survivors_line
    )


# P2-2 — cost_divergence threshold above which the event is elevated to
# ``warn`` so a log scanner / dashboard can highlight runs that materially
# overshot the pre-run estimate. Set at 50 % drift — matches the audit
# §4 "예측-실측 divergence 추적 불가" gap where any sizeable miss should
# surface, but small variance from the empirical token-budget heuristic
# (typical ±20 %) stays at info level.
_COST_DIVERGENCE_WARN_RATIO: float = 0.5


def _emit_cost_divergence(journal: Any, *, predicted_usd: float, actual_usd: float) -> None:
    """Emit a ``cost_divergence`` event comparing pre-run estimate to actual spend.

    ``ratio`` is ``(actual - predicted) / predicted`` so a positive
    value means overspend; ``None`` when the prediction was zero (e.g.
    a fully subscription-backed run where the PAYG total is $0). Above
    the warn threshold the event is elevated to ``warn`` level.
    """
    delta = actual_usd - predicted_usd
    ratio: float | None = (delta / predicted_usd) if predicted_usd > 0 else None
    level = "warn" if (ratio is not None and abs(ratio) >= _COST_DIVERGENCE_WARN_RATIO) else "info"
    journal.append(
        "cost_divergence",
        level=level,
        payload={
            "predicted_usd": round(predicted_usd, 6),
            "actual_usd": round(actual_usd, 6),
            "delta_usd": round(delta, 6),
            "ratio": round(ratio, 4) if ratio is not None else None,
        },
    )


def render_pre_flight_report(report: PreFlightReport) -> str:
    """Human-readable rendering of the pre-flight issue list."""
    if not report.issues:
        return "pre-flight: all checks passed."
    lines = ["pre-flight findings:"]
    for issue in report.issues:
        tag = f"[{issue.severity:>7s}]"
        lines.append(f"  {tag} {issue.code}: {issue.message}")
        lines.append(f"          fix: {issue.fix}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Slash command (in-REPL)
# ---------------------------------------------------------------------------


def cmd_audit_seeds_slash(args: str) -> int:
    """Handle ``/audit-seeds`` slash command. ``args`` is the raw post-slash string.

    Argument shape mirrors the Typer command:

    .. code-block:: text

       /audit-seeds --target-dim broken_tool_use --gen-tag gen1 --candidates 15 [--yes]

    Returns the same exit code as :func:`run_audit_seeds`. Parsing
    errors return exit 2 and print to stderr.
    """
    try:
        argv = shlex.split(args or "")
    except ValueError as exc:
        sys.stderr.write(f"/audit-seeds: argument parse error — {exc}\n")
        return 2
    import argparse

    parser = argparse.ArgumentParser(
        prog="/audit-seeds",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument("--target-dim", "-d", required=True)
    parser.add_argument("--gen-tag", "-g", default=None)
    parser.add_argument("--candidates", "-n", type=int, default=None)
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    try:
        ns = parser.parse_args(argv)
    except SystemExit:
        # argparse calls sys.exit on error; turn that into a clean exit 2.
        return 2
    except argparse.ArgumentError as exc:
        sys.stderr.write(f"/audit-seeds: {exc}\n")
        return 2
    cfg = _get_seed_generation_config()
    resolved_gen_tag = ns.gen_tag if ns.gen_tag is not None else cfg.default_gen_tag
    resolved_candidates = ns.candidates if ns.candidates is not None else cfg.candidates_default
    return run_audit_seeds(
        target_dim=ns.target_dim,
        gen_tag=resolved_gen_tag,
        candidates=resolved_candidates,
        yes=ns.yes,
        quiet=ns.quiet,
    )
