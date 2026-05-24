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


@audit_seeds_app.command("config")
def audit_seeds_config() -> None:
    """Show the 7-role × (model, source) binding matrix.

    Resolved by :func:`plugins.seed_generation.picker.pick_bindings`
    after merging in user overrides from ``~/.geode/config.toml``
    ``[seed_generation.role.<role>]`` (or the legacy
    ``~/.geode/seed-generation.toml`` fallback).

    Read-only — to change a role's source, edit
    ``~/.geode/config.toml`` directly:

      [seed_generation.role.generator]
      source = "payg" | "subscription" | "adapter"

    See ``geode adapters list`` for the available source names per
    provider.
    """
    from plugins.seed_generation.picker import pick_bindings

    picker = pick_bindings(auto_probe=False)
    header = f"{'ROLE':<18} {'PROVIDER':<10} {'MODEL':<26} {'SOURCE':<14}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for role_name in sorted(picker.bindings):
        b = picker.bindings[role_name]
        typer.echo(f"{role_name:<18} {b.provider:<10} {b.model:<26} {b.source:<14}")

    if picker.voters:
        typer.echo("\nJudge panel voters:")
        voter_header = f"  {'PROVIDER':<10} {'MODEL':<26} {'SOURCE':<14}"
        typer.echo(voter_header)
        typer.echo("  " + "-" * (len(voter_header) - 2))
        for v in picker.voters:
            typer.echo(f"  {v.provider:<10} {v.model:<26} {v.source:<14}")

    typer.echo(
        f"\n{len(picker.bindings)} role(s) bound; "
        f"{len(picker.voters)} voter(s); "
        f"{len(picker.subscription_paths_in_use)} subscription path(s) active."
    )


@audit_seeds_app.command("generate")
def audit_seeds_generate(
    target_dim: str | None = typer.Option(
        None,
        "--target-dim",
        "-d",
        help=(
            "Target Petri dim for this generation (e.g. broken_tool_use). "
            "Omit / pass 'auto' to let G3 pick the worst-regressed dim from "
            "``autoresearch/state/baseline.json``. Required only when no "
            "baseline exists yet."
        ),
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
    max_iterations: int = typer.Option(
        0,
        "--max-iterations",
        "-i",
        min=0,
        max=10,
        help=(
            "CSP-5 (2026-05-22): number of post-meta_reviewer iteration "
            "cycles to run AFTER the initial draft batch. 0 (default) keeps "
            "the pre-CSP-5 single-pass behaviour. Each iteration promotes "
            "the Evolver's outputs into candidates and re-runs the "
            "critic → pilot → ranker → evolver → meta_reviewer cycle."
        ),
    ),
) -> None:
    """Generate a new candidate batch — runs picker → cost preview →
    pre-flight → confirm → Pipeline.arun().

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
        max_iterations=max_iterations,
    )
    raise typer.Exit(code=exit_code)


def _resolve_target_dim(
    target_dim: str | None,
    *,
    err: IO[str],
) -> tuple[str | None, Any]:
    """Resolve --target-dim, falling back to G3 auto-pick from baseline.json.

    Returns ``(dim, snapshot)``. ``dim`` is the resolved target dim
    name; ``snapshot`` is the loaded baseline (or ``None`` when the
    operator supplied an explicit dim — auto-pick stays opt-in).

    When ``target_dim`` is ``None`` / ``"auto"``:
    1. Load ``autoresearch/state/baseline.json``.
    2. Pick the worst-regressed dim via
       :func:`plugins.seed_generation.baseline_reader.pick_regression_target_dim`.
    3. On no baseline / no operational dim → print actionable error and
       return ``(None, None)``; the caller surfaces an exit code.

    Lazy import so the import graph stays:
    cli → baseline_reader (only when needed) → autoresearch.train (lazy
    inside baseline_reader).
    """
    from plugins.seed_generation.baseline_reader import (
        load_baseline,
        pick_regression_target_dim,
    )

    if target_dim and target_dim.lower() != "auto":
        # G3.fix1 (2026-05-20) — Conditional read parity (Codex finding):
        # the explicit-dim branch previously returned ``(dim, None)`` so
        # generator/critic/evolver never saw baseline evidence even when
        # baseline.json was populated. Load the snapshot here too so the
        # operator-specified dim still gets G2 evidence injection.
        snapshot = load_baseline()
        return target_dim, snapshot
    snapshot = load_baseline()
    if snapshot is None:
        err.write(
            "seed-generation: --target-dim required (no autoresearch baseline "
            "found at autoresearch/state/baseline.json yet; run an audit + "
            "promote first, or pass --target-dim <dim> explicitly).\n"
        )
        return None, None
    picked = pick_regression_target_dim(snapshot)
    if picked is None:
        err.write(
            "seed-generation: --target-dim required (baseline has no operational "
            "dim_means — every entry is in the info tier or unrecognised).\n"
        )
        return None, snapshot
    err.write(
        f"seed-generation: --target-dim auto → {picked!r} "
        f"(baseline mean {snapshot.dim_means[picked]:.2f})\n"
    )
    return picked, snapshot


def _load_priors_snapshot(*, err: IO[str]) -> Any:
    """Load ``latest_meta_review.json`` priors for the next run.

    Returns the :class:`MetaReviewSnapshot` (or ``None`` for bootstrap /
    unparseable). Best-effort — never raises; the run proceeds without
    priors when the symlink is missing or the payload has no signal.

    Lazy import keeps the cold start free of baseline_reader machinery
    when the operator never touches the meta-review wiring.
    """
    from plugins.seed_generation.baseline_reader import load_latest_meta_review

    snapshot = load_latest_meta_review()
    if snapshot is None:
        return None
    priors_count = len(snapshot.next_gen_priors)
    underrep_count = len(snapshot.underrepresented_dims)
    err.write(
        f"seed-generation: loaded previous meta-review "
        f"({priors_count} priors, {underrep_count} underrepresented dims)\n"
    )
    return snapshot


def run_audit_seeds(
    *,
    target_dim: str | None = None,
    gen_tag: str = "gen1",
    candidates: int = 15,
    yes: bool = False,
    quiet: bool = False,
    max_iterations: int = 0,
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

    PR-P2 — the RunTranscript scope is opened here (was previously
    inside ``_dispatch_pipeline``) so cost-preview, pre-flight, and
    user-abort events also land in the per-session journal. Pre-flight
    failures (the dominant pre-PR observability gap) now emit
    ``preflight_failed`` with the structured issue list before the run
    aborts.
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    resolved_dim, baseline_snapshot = _resolve_target_dim(target_dim, err=err)
    if resolved_dim is None:
        return 1

    # G4 — best-effort load of the previous run's meta_review.json (priors).
    # Bootstrap runs (no prior) get None and skip the priors block in
    # generator / critic prompts.
    meta_review_snapshot = _load_priors_snapshot(err=err)

    from core.self_improving_loop.run_transcript import RunTranscript, run_transcript_scope

    run_id = f"{gen_tag}-{resolved_dim}"
    journal = RunTranscript(
        session_id=run_id,
        gen_tag=gen_tag,
        component="seed-generation",
    )
    with run_transcript_scope(journal):
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
                target_dim=resolved_dim,
                gen_tag=gen_tag,
                candidates_requested=candidates,
                cost=cost,
                out=out,
                err=err,
                baseline_snapshot=baseline_snapshot,
                meta_review_snapshot=meta_review_snapshot,
                max_iterations=max_iterations,
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
    baseline_snapshot: Any = None,
    meta_review_snapshot: Any = None,
    max_iterations: int = 0,
) -> None:
    """Build orchestrator + run.

    Imports are deferred so the CLI smoke-import (`geode audit-seeds
    --help`) doesn't pay the SubAgentManager + orchestrator cold-start
    cost. The function is monkeypatched in tests to assert the gate
    flow before the heavy import.

    PR-P2 — the RunTranscript scope is now opened by the caller
    (``run_audit_seeds``) so cost-preview / pre-flight events emitted
    before this dispatch land in the same per-session journal.
    Pipeline lifecycle markers (``pipeline_started`` /
    ``pipeline_finished``) and the post-run ``cost_divergence`` event
    are emitted via :func:`core.self_improving_loop.run_transcript.current_run_transcript`.
    """
    # CSP-7 (2026-05-22) — per-run artefacts moved into the repo
    # under ``state/seed-generation/`` (env-overridable via
    # ``GEODE_STATE_ROOT``). Pre-CSP-7 base was
    # ``~/.geode/seed-generation/`` — machine-specific, broke
    # cross-host reproducibility.
    from core.paths import STATE_SEED_GENERATION_DIR
    from core.self_improving_loop.run_transcript import current_run_transcript

    from plugins.seed_generation.orchestrator import (
        Pipeline,
        PipelineRegistry,
        PipelineState,
    )

    run_id = f"{gen_tag}-{target_dim}"
    run_dir = STATE_SEED_GENERATION_DIR / run_id
    state = PipelineState(
        run_id=run_id,
        target_dim=target_dim,
        gen_tag=gen_tag,
        candidates_requested=candidates_requested,
        run_dir=run_dir,
        baseline_snapshot=baseline_snapshot,
        meta_review_snapshot=meta_review_snapshot,
        max_iterations=max_iterations,
    )
    registry = PipelineRegistry()
    # v0.99.40 Follow-up C — S11 registry wire-up. Each enabled role's
    # concrete agent is instantiated with the picker-resolved binding
    # (``model`` + ``source``) and the shared SubAgentManager so the
    # spawned worker's AgenticLoop receives the per-role source via
    # SubTask.source threading (Follow-up A + B).
    from plugins.seed_generation._registry_builder import populate_registry
    from plugins.seed_generation.manifest import load_manifest

    populate_registry(registry, picker_result=picker_result, manifest=load_manifest())
    pipeline = Pipeline(state=state, registry=registry, bindings=dict(picker_result.bindings))
    out.write(f"seed-generation: starting run {run_id!r}\n")
    out.write(f"seed-generation: run_dir={run_dir}\n")
    out.flush()

    journal = current_run_transcript()
    if journal is not None:
        journal.append("pipeline_started", payload={"target_dim": target_dim})

    # PR-Async-Phase-C step 2 (2026-05-22) — Typer command must remain
    # sync (Typer 0.25.1 doesn't natively support ``async def`` commands;
    # issue #950 closed without merged implementation). Bridge the
    # async pipeline via the OS-process-boundary adapter.
    from core.async_runtime import run_process_coroutine

    run_process_coroutine(pipeline.arun())

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
