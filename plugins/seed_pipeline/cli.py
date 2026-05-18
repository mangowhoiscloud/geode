"""Seed-pipeline CLI sub-app — `geode audit-seeds` + `/audit-seeds`.

S11 wires the seed-pipeline orchestrator into both the top-level
``geode audit-seeds`` Typer command and the in-REPL ``/audit-seeds``
slash command. The CLI composes the existing modules:

1. :func:`plugins.seed_pipeline.picker.pick_bindings` — resolve per-role
   ``(model, family, source)`` bindings (S5.5 picker).
2. :func:`plugins.seed_pipeline.cost_preview.estimate_cost` — render
   per-role + aggregate USD estimate (S6.5 cost preview).
3. :func:`plugins.seed_pipeline.pre_flight.run_pre_flight` — credential
   + budget + diversity gate (S6.5 pre-flight).
4. **Human gate** — print cost summary + ToS notice + pre-flight
   issues; abort unless the user confirms (``y`` / ``--yes``). This is
   the last off-ramp before LLM calls.
5. :class:`plugins.seed_pipeline.orchestrator.Pipeline` — actual run
   (S1-S8).

The CLI is intentionally thin — every layer above is already covered
by per-module unit tests; the CLI just composes them.

P-checklist application:

- **P4 Environment Anchor**: paths read from
  :mod:`plugins.seed_pipeline.picker` / cost_preview / pre_flight; the
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
from typing import IO

import typer

from plugins.seed_pipeline.cost_preview import estimate_cost, format_cost_summary
from plugins.seed_pipeline.picker import (
    PickerResult,
    pick_bindings,
    print_tos_notice,
)
from plugins.seed_pipeline.pre_flight import PreFlightReport, run_pre_flight

log = logging.getLogger(__name__)

__all__ = [
    "audit_seeds_app",
    "cmd_audit_seeds_slash",
    "render_pre_flight_report",
    "run_audit_seeds",
]


audit_seeds_app = typer.Typer(
    name="audit-seeds",
    help="Run the seed-pipeline (generate-debate-evolve) for one target dim.",
    no_args_is_help=True,
    add_completion=False,
)


@audit_seeds_app.command("generate")
def audit_seeds_generate(
    target_dim: str = typer.Option(
        ...,
        "--target-dim",
        "-d",
        help="Target Petri dim for this generation (e.g. broken_tool_use).",
    ),
    gen_tag: str = typer.Option(
        "gen1",
        "--gen-tag",
        "-g",
        help="Generation tag — used in candidate ids and run_dir.",
    ),
    candidates: int = typer.Option(
        15,
        "--candidates",
        "-n",
        help="Target N for the generator phase (default 15).",
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
    """
    exit_code = run_audit_seeds(
        target_dim=target_dim,
        gen_tag=gen_tag,
        candidates=candidates,
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
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    picker_result = pick_bindings()
    print_tos_notice(picker_result, file=err, quiet=quiet)

    cost = estimate_cost(picker_result, candidate_count=candidates)
    out.write(format_cost_summary(cost) + "\n")

    report = run_pre_flight(picker_result)
    out.write(render_pre_flight_report(report) + "\n")
    if report.has_errors:
        err.write("seed-pipeline: pre-flight failed; aborting.\n")
        return 1

    if not yes:
        prompter = confirm_fn or _default_confirm
        if not prompter(out, err):
            err.write("seed-pipeline: user aborted at confirm prompt.\n")
            return 1

    # Pipeline construction is deferred until after the gate so the
    # heavy SubAgentManager wiring isn't paid on a dry preview.
    try:
        _dispatch_pipeline(
            picker_result=picker_result,
            target_dim=target_dim,
            gen_tag=gen_tag,
            candidates_requested=candidates,
            out=out,
            err=err,
        )
    except Exception as exc:  # pragma: no cover - bubbles up rich error
        err.write(f"seed-pipeline: run failed — {exc}\n")
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
    out: IO[str],
    err: IO[str],
) -> None:
    """Build orchestrator + run.

    Imports are deferred so the CLI smoke-import (`geode audit-seeds
    --help`) doesn't pay the SubAgentManager + orchestrator cold-start
    cost. The function is monkeypatched in tests to assert the gate
    flow before the heavy import.
    """
    from core.paths import GEODE_HOME

    from core.observability import SessionJournal, session_journal_scope
    from plugins.seed_pipeline.orchestrator import (
        Pipeline,
        PipelineRegistry,
        PipelineState,
    )

    run_id = f"{gen_tag}-{target_dim}"
    run_dir = GEODE_HOME / "seed-pipeline" / run_id
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
    out.write(f"seed-pipeline: starting run {run_id!r}\n")
    out.write(f"seed-pipeline: run_dir={run_dir}\n")
    out.flush()
    # P1c — bind a SessionJournal so hook-routed subagent events land in
    # ``~/.geode/outer-loop/<session_id>/journal.jsonl`` (default path),
    # keeping the cross-loop journal location uniform with the
    # autoresearch driver. The seed-pipeline ``<run_dir>`` keeps the
    # state.json + survivors.json + elo_log.tsv (per-run artifacts);
    # observability events live one level up under outer-loop/.
    journal = SessionJournal(
        session_id=run_id,
        gen_tag=gen_tag,
        component="seed-pipeline",
    )
    journal.append("pipeline_started", payload={"target_dim": target_dim})
    with session_journal_scope(journal):
        pipeline.run()
    journal.append(
        "pipeline_finished",
        payload={
            "survivors": len(state.survivors),
            "usd_spent": round(state.usd_spent, 6),
            "pool_path_out": (
                str(state.pool_path_out) if state.pool_path_out is not None else None
            ),
        },
    )
    survivors_line = (
        f"seed-pipeline: survivors.json at {state.pool_path_out}\n"
        if state.pool_path_out is not None
        else "seed-pipeline: survivors.json not written (run_dir unset)\n"
    )
    out.write(
        f"seed-pipeline: run {run_id!r} finished; "
        f"survivors={len(state.survivors)} usd={state.usd_spent:.4f}\n"
        f"seed-pipeline: state.json at {run_dir / 'state.json'}\n"
        f"seed-pipeline: journal at {journal.path}\n" + survivors_line
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
    parser.add_argument("--gen-tag", "-g", default="gen1")
    parser.add_argument("--candidates", "-n", type=int, default=15)
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
    return run_audit_seeds(
        target_dim=ns.target_dim,
        gen_tag=ns.gen_tag,
        candidates=ns.candidates,
        yes=ns.yes,
        quiet=ns.quiet,
    )
