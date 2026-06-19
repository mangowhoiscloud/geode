"""``/self-improving`` (and alias ``/sil``) REPL slash command.

PR-OPS-1 (2026-05-21) — smallest operator-facing surface for the
self-improving loop. Today only the ``status`` sub-action is wired:
it reads ``core/self_improving/state/mutations.jsonl`` (the git-tracked
mutation audit) and the most recent ``baseline.json`` to print a
two-block summary — current baseline fitness + the last N mutations.

The ``run`` / ``history`` / ``rollback`` / ``config`` sub-actions
are reserved for PR-OPS-2/3. Invoking them today prints a
"not-yet-wired" pointer to the design doc.

Wiring path:

  REPL slash ``/self-improving status``
    → ``core/cli/routing.py`` ``COMMAND_REGISTRY`` (THIN location)
    → ``core/cli/commands/_state.py`` ``COMMAND_MAP`` action="self-improving"
    → ``core/cli/dispatcher.py`` ``_handle_command`` dispatch
    → ``cmd_self_improving(args)``  (this module)

Mode B only — this surface triggers ``SelfImprovingLoopRunner``
programmatic mutation. The Karpathy idiom (Mode A — external agent
reading ``core/self_improving/program.md``) stays a parallel, manual path.
See ``docs/plans/2026-05-21-self-improving-loop-ux.md`` for the full
design.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.config.toml_edit import persist_toml_section
from core.memory.atomic_write import read_json_or_none
from core.ui.console import console

__all__ = ["cmd_self_improving"]


_HISTORY_DEFAULT_N = 5
# PR-PAPERCLIP (2026-05-21) — ``config`` and ``source`` are now wired
# for interactive + non-interactive selection of paperclip-pattern
# (claude-cli / openai-codex / api_key) per component. ``history`` and
# ``rollback`` continue to delegate to git natively.
_RUN_DEFERRED_ACTIONS: frozenset[str] = frozenset()
_KNOWN_ACTIONS = frozenset(
    {
        "status",
        "run",
        "history",
        "rollback",
        "migrate",
        "config",
        "source",
        # PR-WIRE-1 (2026-05-26) — operator visibility into the previously
        # orphan observability helpers (kind_dim_matrix / rollback_condition).
        # See ``feedback-sot-revert-on-reject`` memory for the audit context.
        "matrix",
        "rollback-check",
    }
)
_DESIGN_DOC = "docs/plans/2026-05-21-self-improving-loop-ux.md"
_RUN_DEFAULT_ITERATIONS = 1
_RUN_MAX_ITERATIONS = 10
_VALID_SOURCES = ("auto", "api_key", "claude-cli", "openai-codex")


def cmd_self_improving(args: str) -> None:
    """Dispatch the ``/self-improving`` sub-action.

    Empty args → ``status`` (default action).
    Unknown action → help-style hint listing wired vs deferred.
    """
    parts = args.split() if args else []
    action = parts[0] if parts else "status"

    if action == "status":
        _cmd_status()
        return

    if action == "run":
        _cmd_run(parts[1:])
        return

    if action == "history":
        _cmd_history()
        return

    if action == "rollback":
        _cmd_rollback(parts[1:])
        return

    if action == "migrate":
        _cmd_migrate()
        return

    if action == "config":
        _cmd_config()
        return

    if action == "source":
        _cmd_source(parts[1:])
        return

    # PR-WIRE-1 (2026-05-26) — operator-facing visibility into the previously
    # orphan helpers. Each sub-action reads mutations.jsonl, runs the helper,
    # renders a dense table.
    if action == "matrix":
        _cmd_matrix(parts[1:])
        return

    if action == "rollback-check":
        _cmd_rollback_check(parts[1:])
        return

    console.print()
    console.print(f"  [warning]Unknown action: /self-improving {action}[/warning]")
    console.print(
        "  [muted]Available now: [/muted]"
        "status / run / history / rollback / migrate / config / source / "
        "matrix / rollback-check"
    )
    console.print()


def _cmd_status() -> None:
    """Render current baseline + recent mutations.

    Output blocks (Mode B mutator state):
      1. Baseline — ``~/.geode/self-improving/baseline.json`` (if exists)
         · ``fitness`` scalar, ``promote_reason``, ``timestamp``
      2. Recent mutations — last N rows from
         ``core/self_improving/state/mutations.jsonl``
         · per-row ``ts`` / ``mutation_id`` / ``target_kind`` /
           ``target_section`` / ``kind`` (applied | rejected | rolled_back)

    The mutation ledger is git-tracked (in-repo) and ``baseline.json`` is
    runtime (``~/.geode/self-improving/``, out-of-repo); missing files render an
    empty-state line rather than raising so an operator can call ``status`` on a
    fresh clone before any run.
    """
    from core.self_improving.loop.mutate.runner import MUTATION_AUDIT_LOG_PATH

    console.print()
    console.print("  [header]Self-improving loop — status[/header]")

    baseline_path = _baseline_path()
    baseline = read_json_or_none(baseline_path)
    console.print()
    console.print("  [bold]Baseline[/bold]")
    if baseline is None:
        console.print(f"    [muted]no baseline yet — {baseline_path} absent[/muted]")
    else:
        # PR-2 of petri-schema-v2 (2026-05-23) — schema_version=2 nests
        # the run metadata under top-level ``ts_utc`` + ``session_id``
        # instead of the legacy ``timestamp`` / ``ts`` / ``promote_reason``
        # fields. Fall through to legacy keys for v1 baselines still on
        # disk; the next promotion overwrites them in v2 shape.
        fitness = baseline.get("fitness")
        if baseline.get("schema_version") == 2:
            ts = baseline.get("ts_utc") or "?"
            reason = baseline.get("session_id") or "?"
        else:
            ts = baseline.get("timestamp") or baseline.get("ts") or "?"
            reason = baseline.get("promote_reason") or baseline.get("reason") or "?"
        fitness_str = f"{fitness:.4f}" if isinstance(fitness, int | float) else "?"
        console.print(f"    fitness  [bold]{fitness_str}[/bold]")
        console.print(f"    promoted [muted]{ts}[/muted]")
        console.print(f"    reason   [muted]{reason}[/muted]")

    audit_path = Path(MUTATION_AUDIT_LOG_PATH)
    rows = list(_tail_jsonl(audit_path, _HISTORY_DEFAULT_N))
    console.print()
    console.print(f"  [bold]Recent mutations[/bold] (last {_HISTORY_DEFAULT_N})")
    if not rows:
        console.print(f"    [muted]no mutations recorded — {audit_path} absent or empty[/muted]")
    else:
        for row in rows:
            _print_audit_row(row)
    console.print()


def _baseline_path() -> Path:
    """Resolve the LATEST runtime ``baseline.json`` (``~/.geode/self-improving/``).

    Post PR-STATE-SOT-RUNTIME-SPLIT the runtime baseline no longer sits beside
    the tracked ``mutations.jsonl``; read it from its own constant (which honours
    ``GEODE_STATE_ROOT`` so an isolated worker still resolves its own copy)."""
    import core.paths

    return Path(core.paths.BASELINE_JSON_PATH)


def _tail_jsonl(path: Path, n: int) -> Iterable[dict[str, Any]]:
    """Yield the last ``n`` valid JSON rows from a JSONL file.

    Yields nothing on missing path. Skips malformed lines silently —
    the file is append-only so a partial last row during concurrent
    write should not break ``status``.
    """
    if not path.is_file() or n <= 0:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    parsed: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            parsed.append(row)
    yield from parsed[-n:]


def _print_audit_row(row: dict[str, Any]) -> None:
    """Render one mutation audit row as a single line."""
    ts = str(row.get("ts") or row.get("timestamp") or "?")[:19]
    kind_label = str(row.get("kind") or "applied")
    target_kind = str(row.get("target_kind") or row.get("kind_target") or "?")
    target_section = str(row.get("target_section") or "?")
    mutation_id = str(row.get("mutation_id") or row.get("id") or "?")[:12]
    style = {
        "applied": "success",
        "rejected": "warning",
        "rolled_back": "muted",
    }.get(kind_label, "muted")
    console.print(
        f"    [{style}]{kind_label:11}[/{style}] "
        f"[muted]{ts}[/muted]  "
        f"{target_kind}.{target_section}  "
        f"[muted]id={mutation_id}[/muted]"
    )


# ---------------------------------------------------------------------------
# ``/self-improving run`` — PR-OPS-2a
# ---------------------------------------------------------------------------


def _cmd_run(opts: list[str]) -> None:
    """Drive one or more propose/confirm/apply iterations.

    Flags:
      --dry-run        propose only — show the mutation, NO write
      --n N            run up to N iterations (default 1, max 10)
      --target-kind X  filter — abort iteration if the LLM proposes a
                       different kind; useful when the operator wants
                       to constrain mutation scope to one SoT
    """
    flags = _parse_run_opts(opts)
    if flags is None:
        return

    runner = _build_runner()
    if runner is None:
        return

    console.print()
    console.print("  [header]Self-improving loop — run[/header]")
    _render_preflight(flags)
    console.print()

    applied = 0
    rejected = 0
    for i in range(1, flags["iterations"] + 1):
        try:
            proposal = runner.propose()
        except Exception as exc:
            console.print(
                f"  [warning]iteration {i}/{flags['iterations']} — propose failed:[/warning] {exc}"
            )
            break
        if flags["target_kind"] and proposal.mutation.target_kind != flags["target_kind"]:
            console.print(
                f"  [warning]iteration {i}/{flags['iterations']} — "
                f"LLM proposed {proposal.mutation.target_kind!r}, "
                f"requested {flags['target_kind']!r}; skipping[/warning]"
            )
            continue

        _render_proposal(proposal, index=i, total=flags["iterations"])

        if flags["dry_run"]:
            console.print(
                "  [muted]--dry-run: proposal NOT applied. "
                "Re-run without --dry-run to confirm interactively.[/muted]"
            )
            console.print()
            continue

        decision = _prompt_confirmation(proposal)
        if decision == "apply":
            try:
                runner.apply_proposal(proposal)
                applied += 1
                console.print(
                    f"  [success]applied[/success]  id={proposal.mutation.mutation_id[:12]}"
                )
            except Exception as exc:
                console.print(f"  [warning]apply failed:[/warning] {exc}")
        elif decision == "reject":
            _record_rejection(runner, proposal)
            rejected += 1
            console.print(f"  [muted]rejected[/muted]  id={proposal.mutation.mutation_id[:12]}")
        else:  # "abort"
            console.print("  [muted]aborted by user[/muted]")
            break

        console.print()

    # PR-G4 (2026-05-21) — surface the mutator's resolved (model, source)
    # so the operator knows which channel was billed for this run.
    # Both are read from the same toml SoT (``[self_improving_loop.mutator]``)
    # the runner consults at dispatch time; with PR-MINIMAL-2 G1a a
    # ``None`` default_model means the mutator inherited
    # ``Settings.model``, which we resolve here for the display line.
    resolved_model, resolved_source = _resolve_run_summary_telemetry()
    console.print(
        f"  [muted]summary:[/muted] applied={applied}  rejected={rejected}  "
        f"model={resolved_model}  source={resolved_source}"
    )
    console.print()


def _resolve_run_summary_telemetry() -> tuple[str, str]:
    """Resolve the (model, source) the mutator just dispatched against.

    Mirrors the runner's ``_default_llm_call`` resolution: read
    ``MutatorConfig.default_model`` from ``~/.geode/config.toml``, fall
    back to ``Settings.model`` when unset (PR-MINIMAL-2 G1a). Read
    ``MutatorConfig.source`` directly. Best-effort — returns ``"?"``
    placeholders when the config layer cannot be imported (e.g. test
    contexts that stub ``core.config``).
    """
    try:
        from core.config import settings
        from core.config.self_improving import load_self_improving_loop_config

        cfg = load_self_improving_loop_config()
        model = cfg.autoresearch.mutator.default_model or settings.model
        source = cfg.autoresearch.mutator.source
        return (model, source)
    except Exception:
        import logging

        logging.getLogger(__name__).debug("run-summary telemetry resolve failed", exc_info=True)
        return ("?", "?")


def _parse_run_opts(opts: list[str]) -> dict[str, Any] | None:
    """Parse the ``--dry-run`` / ``--n`` / ``--target-kind`` flags.

    Returns ``None`` (after printing an error) on invalid input so
    the slash exits cleanly. Defaults: ``iterations=1``,
    ``target_kind=""`` (no filter), ``dry_run=False``.
    """
    dry_run = False
    iterations = _RUN_DEFAULT_ITERATIONS
    target_kind = ""
    i = 0
    while i < len(opts):
        tok = opts[i]
        if tok == "--dry-run":
            dry_run = True
        elif tok == "--n":
            if i + 1 >= len(opts):
                console.print("  [warning]--n requires a value[/warning]")
                return None
            try:
                iterations = int(opts[i + 1])
            except ValueError:
                console.print(f"  [warning]--n: not an int: {opts[i + 1]!r}[/warning]")
                return None
            i += 1
        elif tok.startswith("--n="):
            try:
                iterations = int(tok.split("=", 1)[1])
            except ValueError:
                console.print(f"  [warning]--n: not an int: {tok!r}[/warning]")
                return None
        elif tok == "--target-kind":
            if i + 1 >= len(opts):
                console.print("  [warning]--target-kind requires a value[/warning]")
                return None
            target_kind = opts[i + 1]
            i += 1
        elif tok.startswith("--target-kind="):
            target_kind = tok.split("=", 1)[1]
        else:
            console.print(f"  [warning]unknown flag: {tok!r}[/warning]")
            return None
        i += 1
    if iterations < 1 or iterations > _RUN_MAX_ITERATIONS:
        console.print(f"  [warning]--n must be 1 ~ {_RUN_MAX_ITERATIONS}[/warning]")
        return None
    # ADR-012 S0d (2026-05-21) — TARGET_KINDS 가 4축으로 축소 후 (retrieval
    # deprecated). policies.TARGET_KINDS 를 직접 import 해서 single source.
    from core.self_improving.loop.mutate.policies import TARGET_KINDS

    if target_kind and target_kind not in TARGET_KINDS:
        valid_kinds = "|".join(TARGET_KINDS)
        console.print(f"  [warning]--target-kind must be one of {valid_kinds}[/warning]")
        return None
    return {
        "dry_run": dry_run,
        "iterations": iterations,
        "target_kind": target_kind,
    }


def _build_runner() -> Any | None:
    """Construct ``SelfImprovingLoopRunner`` with safe defaults.

    Returns ``None`` (after printing an error) on construction
    failure so the slash exits cleanly. ``rerun_enabled=False``
    keeps the slash cheap by default — the operator must explicitly
    run autoresearch separately for a measurement.
    """
    try:
        from core.self_improving.loop.mutate.runner import SelfImprovingLoopRunner

        return SelfImprovingLoopRunner(
            rerun_enabled=False,
            commit_enabled=True,
        )
    except Exception as exc:
        console.print(f"  [warning]runner init failed:[/warning] {exc}")
        return None


def _render_preflight(flags: dict[str, Any]) -> None:
    """Render the static text pre-flight block.

    PR-OPS-2a (no Rich Panel yet — interactive dashboard lands in
    PR-OPS-2b). Surfaces the slice of knobs an operator needs to
    sanity-check before approving a mutation.
    """
    target_kind = flags["target_kind"] or "any"
    mode = "dry-run (no write)" if flags["dry_run"] else "interactive (per-iter confirm)"
    mutator_model: str = "?"
    mutator_source: str = "?"
    try:
        from core.config import settings
        from core.config.self_improving import load_self_improving_loop_config

        cfg = load_self_improving_loop_config()
        # PR-MINIMAL-2 (2026-05-21) — G1a inherit: when
        # MutatorConfig.default_model is None (the new default), fall
        # back to Settings.model so the pre-flight display reflects
        # what the runner will actually invoke. Explicit override
        # (operator set ``[self_improving_loop.mutator] default_model``
        # in config.toml) still wins.
        mutator_model = cfg.autoresearch.mutator.default_model or settings.model
        mutator_source = cfg.autoresearch.mutator.source
    except Exception:
        # Best-effort UI: missing config falls through to the "?" placeholders.
        import logging

        logging.getLogger(__name__).debug("mutator config read failed", exc_info=True)
    console.print()
    console.print("  [bold]Pre-flight[/bold]")
    console.print(f"    mutator      [bold]{mutator_model}[/bold]  source={mutator_source}")
    console.print(f"    target_kind  {target_kind}")
    console.print(f"    iterations   {flags['iterations']}")
    console.print(f"    mode         {mode}")
    console.print("    harness      [muted]no-op (PR-OPS-2b wires autoresearch/petri_raw)[/muted]")


def _render_proposal(proposal: Any, *, index: int, total: int) -> None:
    """Render one Mutation as a confirmation block."""
    mut = proposal.mutation
    prev = proposal.target_sections.get(mut.target_section, "")
    console.print(f"  [header][Self-improving loop — proposal {index}/{total}][/header]")
    console.print(f"    target_kind     {mut.target_kind}")
    console.print(f"    target_section  {mut.target_section}")
    console.print(
        f"    previous_value  {_clip(prev, 80) if prev else '[muted](new section)[/muted]'}"
    )
    console.print(f"    new_value       {_clip(mut.new_value, 80)}")
    if mut.rationale:
        console.print(f"    rationale       {_clip(mut.rationale, 200)}")
    if proposal.baseline_fitness is not None:
        console.print(f"    baseline_fitness {proposal.baseline_fitness:.4f}  [muted](SoT)[/muted]")
    if mut.expected_dim:
        console.print(f"    expected_dim    {dict(mut.expected_dim)}")
    if mut.rollback_condition:
        console.print(f"    rollback_cond   {_clip(mut.rollback_condition, 120)}")


def _prompt_confirmation(proposal: Any) -> str:
    """Read one y/N/d/s response. Loops on d/s (auxiliary outputs).

    Returns one of ``"apply"`` / ``"reject"`` / ``"abort"``. EOF /
    Ctrl-D returns ``"abort"`` so the slash exits cleanly.
    """
    while True:
        try:
            raw = console.input(
                "  Apply this mutation? "
                "[bold]y[/bold]=apply / [bold]N[/bold]=reject / "
                "d=show-diff / s=show-rationale: "
            )
        except (EOFError, KeyboardInterrupt):
            return "abort"
        ans = raw.strip().lower()
        if ans in {"y", "yes"}:
            return "apply"
        if ans in {"", "n", "no"}:
            return "reject"
        if ans == "d":
            console.print("    [muted]diff (truncated):[/muted]")
            prev_val = proposal.target_sections.get(proposal.mutation.target_section, "")
            console.print(f"      - {_clip(prev_val, 240)}")
            console.print(f"      + {_clip(proposal.mutation.new_value, 240)}")
            continue
        if ans == "s":
            console.print("    [muted]rationale:[/muted]")
            console.print(f"      {_clip(proposal.mutation.rationale, 600)}")
            continue
        console.print("  [muted]please answer y / N / d / s[/muted]")


def _record_rejection(runner: Any, proposal: Any) -> None:
    """Append a ``kind=rejected`` row to the audit log.

    The operator chose not to apply, but the rejection itself is
    signal — record it so the mutator LLM can learn (via the next
    iteration's context) which proposals get rejected and why.
    Best-effort: failure logged but not surfaced.

    Codex MCP catch (2026-05-21, PR #1395): the runner's
    ``audit_log_path`` defaults to ``None`` (lazy resolution — the
    ``append_audit_log`` helper falls back to
    ``MUTATION_AUDIT_LOG_PATH``). Mirror that resolution here so
    ``Path(None)`` never trips on the real slash path where the
    operator constructs the runner via ``_build_runner`` without
    passing an audit_log_path.
    """
    import logging
    import time

    from core.self_improving.loop.mutate.runner import MUTATION_AUDIT_LOG_PATH

    log = logging.getLogger(__name__)

    # PR-AUDIT-AB (2026-06-10) — operator decline is a mutation rejection
    # too; fire the lifecycle event alongside the audit row.
    from core.hooks.system import HookEvent
    from core.self_improving.loop._hooks import _fire_hook

    _fire_hook(
        HookEvent.MUTATION_REJECTED,
        {
            "mutation_id": proposal.mutation.mutation_id,
            "target_kind": proposal.mutation.target_kind,
            "target_path": f"{proposal.mutation.target_kind}.{proposal.mutation.target_section}",
            "ts": time.time(),
            "run_id": "",
            "reason": "operator declined at confirmation prompt",
            "rejected_by": "operator",
        },
    )
    raw_path = runner.audit_log_path or MUTATION_AUDIT_LOG_PATH
    audit_path = Path(raw_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": time.time(),
        "kind": "rejected",
        "mutation_id": proposal.mutation.mutation_id,
        "target_kind": proposal.mutation.target_kind,
        "target_section": proposal.mutation.target_section,
        "previous_value": proposal.target_sections.get(proposal.mutation.target_section, ""),
        "new_value": proposal.mutation.new_value,
        "rationale": proposal.mutation.rationale,
        "target_dim": proposal.mutation.target_dim,
        "expected_dim": dict(proposal.mutation.expected_dim),
        "rollback_condition": proposal.mutation.rollback_condition,
        "baseline_fitness": proposal.baseline_fitness,
    }
    try:
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("audit-log rejection write failed", exc_info=True)


def _clip(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# ``/self-improving history`` + ``/self-improving rollback`` — PR-MINIMAL-1
# ---------------------------------------------------------------------------
#
# These two actions intentionally delegate to git rather than
# re-implement what git already does on top of the in-repo mutation
# ledger (``core/self_improving/state/mutations.jsonl``) + the 5 policy SoT
# JSONs at ``core/self_improving/state/policies/`` (both git-tracked since
# PR-RATCHET-1, 2026-05-21). Re-implementing the JSONL tail walker +
# a custom rollback verb would duplicate `git log` + `git revert`
# while losing standard git ergonomics (refs / SHAs / signed
# commits / hooks). The handlers below print the exact git command
# so the operator stays inside one mental model.


def _cmd_history() -> None:
    """Show the operator how to read the mutation history via git.

    The mutation ledger (``core/self_improving/state/mutations.jsonl``) +
    the 5 policy SoT JSONs (``core/self_improving/state/policies/``) are
    git-trackable (``.gitignore`` negation lets them be added);
    after the first applied mutation lands a commit, ``git log``
    over either path is the canonical history view. Codex MCP
    catch on PR-MINIMAL-1: until that first commit, the files are
    NOT YET tracked (``git ls-files`` returns only the ``.gitkeep``
    placeholders), so we print an empty-state caveat alongside the
    recipes.
    """
    console.print()
    console.print("  [header]Self-improving loop — history[/header]")
    console.print()
    console.print(
        "  [muted]Mutation ledger (one row per mutation, with ts / id / "
        "target_kind / target_section / rationale):[/muted]"
    )
    console.print("    [bold]git log -p core/self_improving/state/mutations.jsonl[/bold]")
    console.print(
        "    [muted]→ empty when no mutation has been applied yet "
        "(first /self-improving run apply seeds the ledger).[/muted]"
    )
    console.print()
    console.print("  [muted]Compact form (commit message + 1-line ledger row):[/muted]")
    console.print("    [bold]git log --oneline core/self_improving/state/mutations.jsonl[/bold]")
    console.print()
    console.print(
        "  [muted]Current policy state (5 SoT files, see ``git diff`` for "
        "the current vs last-promoted snapshot):[/muted]"
    )
    console.print("    [bold]git log --stat core/self_improving/state/policies/[/bold]")
    console.print()
    console.print(
        "  [muted]Quick recent summary (last N applied/rejected/rolled_back rows):[/muted]"
    )
    console.print("    [bold]/self-improving status[/bold]")
    console.print()


def _cmd_rollback(opts: list[str]) -> None:
    """Show the operator how to undo a mutation via git.

    Every applied mutation is a git commit (``_git_commit_audit_log``
    PR-G5b idiom), so ``git revert <sha>`` is the canonical rollback.
    We print the recipe + a small helper command for finding the SHA
    matching a ``mutation_id``.
    """
    target = opts[0] if opts else None
    console.print()
    console.print("  [header]Self-improving loop — rollback[/header]")
    console.print()
    if target is not None:
        console.print(f"  [muted]Find the commit that applied mutation_id={target!r}:[/muted]")
        console.print(
            f"    [bold]git log --all --grep={target!r} -- "
            "core/self_improving/state/mutations.jsonl[/bold]"
        )
        console.print()
        console.print("  [muted]Revert that commit:[/muted]")
        console.print("    [bold]git revert <sha-from-above>[/bold]")
    else:
        console.print("  [muted]Find the SHA of the mutation you want to undo:[/muted]")
        console.print(
            "    [bold]git log --oneline -p core/self_improving/state/mutations.jsonl[/bold]"
        )
        console.print()
        console.print("  [muted]Revert it:[/muted]")
        console.print("    [bold]git revert <sha>[/bold]")
        console.print()
        console.print(
            "  [muted]Tip: give a mutation_id explicitly to get the grep "
            "form, e.g.[/muted] [bold]/self-improving rollback "
            "<mutation_id>[/bold]"
        )
    console.print()


# ---------------------------------------------------------------------------
# ``/self-improving migrate`` — PR-MINIMAL-2 (B7)
# ---------------------------------------------------------------------------
#
# PR-RATCHET-1 introduced a *lazy* migration helper that copies
# pre-PR ``~/.geode/autoresearch/handoff/<file>.json`` payloads to
# the new in-repo ``core/self_improving/state/policies/`` location on the
# first ``load_policy`` / ``write_policy`` call. The lazy path is
# operator-invisible — they don't see a "migration in progress"
# signal, so they can't confirm the move happened. PR-MINIMAL-2's
# ``/self-improving migrate`` slash invokes the helper explicitly
# for every target_kind so the operator sees a per-kind status
# table and can verify the in-repo location now carries their
# pre-PR policy state.


def _cmd_migrate() -> None:
    """Explicit one-shot migration from ``~/.geode/autoresearch/handoff/``
    to the in-repo ``core/self_improving/state/policies/`` directory.

    Iterates every ``TARGET_KINDS`` entry, calls
    ``_maybe_migrate_legacy_sot`` for each, and renders a per-kind
    status table: ``migrated`` (legacy file existed + new path was
    missing, copy succeeded), ``up-to-date`` (new path already
    present, no-op), ``no-legacy`` (no pre-PR file to migrate from),
    or ``error`` (best-effort copy raised — never crashes the slash).

    Lifetime: this slash is the operator's escape hatch from the
    lazy-migration code path. Once every install has run it the
    ``_maybe_migrate_legacy_sot`` helper can be removed in a future
    minor release.
    """
    from core.paths import LEGACY_SOT_DIR
    from core.self_improving.loop.mutate.policies import (
        _LEGACY_FILE_NAMES,
        TARGET_KINDS,
        _maybe_migrate_legacy_sot,
        policy_path,
    )

    console.print()
    console.print("  [header]Self-improving loop — migrate[/header]")
    console.print()
    console.print(f"  [muted]Legacy dir:[/muted] {LEGACY_SOT_DIR}")
    console.print()

    rows: list[tuple[str, str, str]] = []
    for kind in TARGET_KINDS:
        new_path = policy_path(kind)
        legacy_name = _LEGACY_FILE_NAMES.get(kind, "?")
        legacy_path = LEGACY_SOT_DIR / legacy_name
        if new_path.is_file():
            rows.append((kind, "up-to-date", str(new_path)))
            continue
        if not legacy_path.is_file():
            rows.append((kind, "no-legacy", str(legacy_path)))
            continue
        try:
            _maybe_migrate_legacy_sot(kind, new_path)
        except Exception as exc:
            rows.append((kind, f"error: {exc}", str(new_path)))
            continue
        if new_path.is_file():
            rows.append((kind, "migrated", str(new_path)))
        else:
            rows.append((kind, "error: helper no-op", str(new_path)))

    for kind, status, path in rows:
        style = {
            "migrated": "success",
            "up-to-date": "muted",
            "no-legacy": "muted",
        }.get(status, "warning")
        console.print(f"    [{style}]{status:14}[/{style}] {kind:14} {path}")
    console.print()
    console.print(
        "  [muted]Legacy files are PRESERVED (not deleted) so you "
        "can manually roll back. Remove them yourself when ready.[/muted]"
    )
    console.print()


# ---------------------------------------------------------------------------
# ``/self-improving source`` + ``/self-improving config`` — PR-PAPERCLIP
# ---------------------------------------------------------------------------
#
# ``source`` is the paperclip-pattern entry point — operator picks which
# credential channel (api_key default / claude-cli subscription /
# openai-codex subscription) the mutator routes its LLM call through.
# ``config`` is the full interactive settings panel: walk every
# self-improving-loop component (mutator + petri.<role> + seed_generation.<role>),
# ask provider/model/source per component, persist to
# ``~/.geode/config.toml``, then optionally chain into ``/self-improving
# run`` so the operator's configuration is immediately exercised.


def _cmd_source(opts: list[str]) -> None:
    """Show or set the mutator credential source.

    Sub-actions:
      (no args)               show current per-component source table
      set <key>=<value> [...]  non-interactive set on the mutator
                              (keys: source / default_model)
    """
    if not opts:
        _render_source_table()
        return
    sub = opts[0]
    if sub == "set":
        _cmd_source_set(opts[1:])
        return
    console.print()
    console.print(f"  [warning]Unknown sub-action: source {sub!r}[/warning]")
    console.print("  [muted]Available: (no args) | set <key>=<value>[/muted]")
    console.print()


def _render_source_table() -> None:
    """Render the current paperclip-source state for every component."""
    try:
        from core.config import settings
        from core.config.self_improving import load_self_improving_loop_config

        cfg = load_self_improving_loop_config()
    except Exception as exc:
        console.print()
        console.print(f"  [warning]config load failed:[/warning] {exc}")
        console.print()
        return
    console.print()
    console.print("  [header]Self-improving loop — source[/header]")
    console.print()
    inherit_model = settings.model
    rows: list[tuple[str, str, str]] = [
        (
            "autoresearch.mutator",
            cfg.autoresearch.mutator.default_model or f"{inherit_model}  [muted](inherit)[/muted]",
            cfg.autoresearch.mutator.source,
        ),
    ]
    for role_name in ("auditor", "target", "judge"):
        role_cfg = getattr(cfg.autoresearch, role_name)
        rows.append((f"autoresearch.{role_name}", role_cfg.model, role_cfg.source))
    for seed_name, seed_cfg in cfg.seed_generation.roles.items():
        rows.append((f"seed_generation.{seed_name}", seed_cfg.model, seed_cfg.source))
    console.print(f"    {'component':32} {'model':28} source")
    for comp, model, src in rows:
        console.print(f"    {comp:32} {model:28} [bold]{src}[/bold]")
    console.print()
    console.print("  [muted]Valid sources: " + " / ".join(_VALID_SOURCES) + "[/muted]")
    console.print()


def _cmd_source_set(opts: list[str]) -> None:
    """Non-interactive setter — ``/self-improving source set <key>=<value> [...]``.

    Targets the mutator section only — paperclip scope per session
    decision Q1=b (mutator). Use ``/self-improving config`` for
    per-component (petri / seed_generation) editing.

    Supported keys: ``source`` / ``default_model``.
    """
    if not opts:
        console.print("  [warning]source set: needs at least one key=value pair[/warning]")
        console.print("  [muted]Example: /self-improving source set source=claude-cli[/muted]")
        return
    updates: dict[str, str] = {}
    for tok in opts:
        if "=" not in tok:
            console.print(f"  [warning]not key=value: {tok!r}[/warning]")
            return
        key, val = tok.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key not in {"source", "default_model"}:
            console.print(
                f"  [warning]unknown key: {key!r} (supported: source / default_model)[/warning]"
            )
            return
        if key == "source" and val not in _VALID_SOURCES:
            valid = " / ".join(_VALID_SOURCES)
            console.print(f"  [warning]invalid source: {val!r} (valid: {valid})[/warning]")
            return
        updates[key] = val
    try:
        _persist_mutator_updates(updates)
    except Exception as exc:
        console.print(f"  [warning]write failed:[/warning] {exc}")
        return
    console.print()
    console.print("  [success]mutator config updated[/success]")
    for key, val in updates.items():
        console.print(f"    {key} = {val!r}")
    console.print()


def _cmd_config() -> None:
    """Interactive self-improving-loop settings panel.

    Walks mutator + petri.<role> + seed_generation.<role> components.
    For each, prompts provider/model/source with current value as
    default (Enter to keep). After every component is collected,
    persists the diff to ``~/.geode/config.toml`` and offers to run
    ``/self-improving run`` immediately so the operator's choice is
    exercised end-to-end.
    """
    try:
        from core.config import settings
        from core.config.self_improving import load_self_improving_loop_config

        cfg = load_self_improving_loop_config()
    except Exception as exc:
        console.print()
        console.print(f"  [warning]config load failed:[/warning] {exc}")
        console.print()
        return

    console.print()
    console.print("  [header]Self-improving loop — interactive configuration[/header]")
    console.print("  [muted]Enter to keep current value. Ctrl-D aborts without writing.[/muted]")
    console.print()

    mutator_changes = _prompt_component(
        "mutator",
        current_model=cfg.autoresearch.mutator.default_model or settings.model,
        current_source=cfg.autoresearch.mutator.source,
        model_is_inherited=cfg.autoresearch.mutator.default_model is None,
    )
    if mutator_changes is None:
        return  # aborted

    petri_changes: dict[str, dict[str, str]] = {}
    for role_name in ("auditor", "target", "judge"):
        role_cfg = getattr(cfg.autoresearch, role_name)
        diff = _prompt_component(
            f"autoresearch.{role_name}",
            current_model=role_cfg.model,
            current_source=role_cfg.source,
            model_is_inherited=False,
        )
        if diff is None:
            return
        if diff:
            petri_changes[role_name] = diff

    seed_changes: dict[str, dict[str, str]] = {}
    for seed_name, seed_cfg in cfg.seed_generation.roles.items():
        diff = _prompt_component(
            f"seed_generation.{seed_name}",
            current_model=seed_cfg.model,
            current_source=seed_cfg.source,
            model_is_inherited=False,
        )
        if diff is None:
            return
        if diff:
            seed_changes[seed_name] = diff

    if not mutator_changes and not petri_changes and not seed_changes:
        console.print()
        console.print("  [muted]no changes — nothing to write[/muted]")
        console.print()
    else:
        try:
            _persist_full_config(
                mutator=mutator_changes, petri=petri_changes, seed_generation=seed_changes
            )
        except Exception as exc:
            console.print(f"  [warning]write failed:[/warning] {exc}")
            return
        console.print()
        console.print("  [success]config saved to ~/.geode/config.toml[/success]")
        console.print()

    # Offer to immediately exercise the new config — per session
    # directive "선택이 완료되면 절차가 수행이 되도록 구성".
    try:
        raw = console.input("  Run /self-improving run now? [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        console.print()
        return
    if raw.strip().lower() in {"y", "yes"}:
        _cmd_run([])


def _prompt_component(
    label: str,
    *,
    current_model: str,
    current_source: str,
    model_is_inherited: bool,
) -> dict[str, str] | None:
    """Prompt one component's model + source. Returns dict of changed fields, or None on abort.

    ``model_is_inherited`` is the mutator-only signal that ``default_model``
    is currently ``None`` and we're displaying the inherited
    ``Settings.model`` — writing the same value back should *not*
    persist it (keeps inherit semantics intact). For petri /
    seed_generation roles this flag is always False.
    """
    console.print(f"  [bold]{label}[/bold]")
    suffix = " [muted](inherit)[/muted]" if model_is_inherited else ""
    console.print(f"    current model:  {current_model}{suffix}")
    console.print(f"    current source: {current_source}")
    try:
        new_model = console.input("    model  [muted](Enter to keep)[/muted]: ").strip()
        new_source = console.input(
            f"    source [muted](Enter to keep — {' / '.join(_VALID_SOURCES)})[/muted]: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        console.print("  [muted]aborted[/muted]")
        console.print()
        return None
    diff: dict[str, str] = {}
    if new_model and new_model != current_model:
        diff["model" if not label.startswith("mutator") else "default_model"] = new_model
    if new_source:
        if new_source not in _VALID_SOURCES:
            console.print(f"    [warning]invalid source — kept {current_source!r}[/warning]")
        elif new_source != current_source:
            diff["source"] = new_source
    console.print()
    return diff


# ---------------------------------------------------------------------------
# TOML writer — section-keyed config updates
# ---------------------------------------------------------------------------
#
# The string-splice writer (read → splice key=value under section header →
# atomic write) lives in ``core.config.toml_edit`` so the loader-side path
# resolution and this writer share one home (PR-DEDUP-CONFIG-TOML). The two
# wrappers below name the self-improving-loop sections the interactive
# editor targets.


def _persist_mutator_updates(updates: dict[str, str]) -> None:
    """Persist mutator-only `key = "value"` lines to config.toml.

    Step J-b.1 (2026-05-23) — writer target moved from
    ``[self_improving_loop.mutator]`` to
    ``[self_improving_loop.autoresearch.mutator]`` (control-layer SoT).
    Old configs auto-migrate via the loader's
    ``_migrate_legacy_role_namespaces`` validator with a
    ``DeprecationWarning``.
    """
    if updates:
        persist_toml_section("self_improving_loop.autoresearch.mutator", updates)


def _persist_full_config(
    *,
    mutator: dict[str, str],
    petri: dict[str, dict[str, str]],
    seed_generation: dict[str, dict[str, str]],
) -> None:
    """Persist the interactive form's diff across every component."""
    if mutator:
        persist_toml_section("self_improving_loop.autoresearch.mutator", mutator)
    for role, diff in petri.items():
        if diff:
            persist_toml_section(f"self_improving_loop.autoresearch.{role}", diff)
    for role, diff in seed_generation.items():
        # Note: loader uses ``[self_improving_loop.seed_generation.roles.<role>]``
        # (plural ``roles``) — see ``SeedGenerationConfig.roles`` field. Singular
        # would land outside the schema's ``extra="forbid"`` allowlist and break
        # the next config load. Codex MCP catch on PR-PAPERCLIP.
        if diff:
            persist_toml_section(f"self_improving_loop.seed_generation.roles.{role}", diff)


# ---------------------------------------------------------------------------
# PR-WIRE-1 (2026-05-26) — orphan helper CLI wiring
# ---------------------------------------------------------------------------
#
# Phase A audit of the 2026-05-26 autoresearch attribution sprint found
# two observability helpers (``compute_kind_dim_matrix`` /
# ``evaluate_rollback_condition``) that were defined in
# ``core/self_improving/loop/`` but had zero production callers — only
# test fixtures imported them. PR-17/18 had shipped the helpers as
# "operator dashboard" infrastructure with caller wiring explicitly
# deferred (each module docstring said so).
#
# This PR closes that gap by wiring the helpers through two new
# REPL sub-actions:
#
#   /self-improving matrix [--last N]
#     → compute_kind_dim_matrix + rank_dims_by_kind (kind × dim contribution
#       cross-join on mutation_id between apply and attribution rows)
#
#   /self-improving rollback-check [--last N]
#     → evaluate_rollback_condition (per-row predicate eval against current
#       baseline + latest observed_dim from attribution rows)
#
# Output is dense table / list per ``[[feedback-no-box-ui-no-emoji]]`` —
# no decorative card grids, no emoji, monospace-friendly.

_WIRE_DEFAULT_LAST = 20


def _parse_last_n(opts: list[str], default: int = _WIRE_DEFAULT_LAST) -> int:
    """Parse ``--last N`` from sub-action argv; default to ``default``."""
    if "--last" in opts:
        idx = opts.index("--last")
        if idx + 1 < len(opts):
            try:
                n = int(opts[idx + 1])
                if n > 0:
                    return n
            except ValueError:
                pass
    return default


def _cmd_matrix(opts: list[str]) -> None:
    """Render ``compute_kind_dim_matrix`` as a target_kind × dim grid.

    Wires the previously orphan ``core.self_improving.loop.observe.kind_dim_matrix``
    helpers. Inner-joins apply rows and attribution rows on
    ``mutation_id``. Each cell is ``attribution_score × observed_dim[d]``
    accumulated across the matched rows — signed contribution preserved.

    Renders the top-3 dims per kind by absolute magnitude (operator
    overview) plus a one-line summary "X kinds × Y dims tracked".
    """
    from core.paths import MUTATION_AUDIT_LOG_PATH
    from core.self_improving.loop.observe.kind_dim_matrix import (
        compute_kind_dim_matrix,
        rank_dims_by_kind,
    )
    from core.self_improving.loop.observe.mutations_reader import (
        read_recent_applies,
        read_recent_attributions,
    )

    last_n = _parse_last_n(opts)
    apply_rows = read_recent_applies(n=last_n, path=MUTATION_AUDIT_LOG_PATH)
    attr_rows = read_recent_attributions(n=last_n, path=MUTATION_AUDIT_LOG_PATH)

    console.print()
    console.print(f"  [header]Kind × Dim contribution matrix[/header] (last {last_n} rows each)")
    if not apply_rows or not attr_rows:
        console.print(
            f"    [muted]need both apply and attribution rows — "
            f"have {len(apply_rows)} applied / {len(attr_rows)} attribution[/muted]"
        )
        console.print()
        return

    matrix = compute_kind_dim_matrix(apply_rows, attr_rows)
    if not matrix:
        console.print(
            "    [muted]no mutation_id overlap between apply and attribution rows — "
            "either the W2/W3 cross-ref env propagation missed the cycle, or the "
            "window is too small to capture both halves of any cycle[/muted]"
        )
        console.print()
        return

    total_kinds = len(matrix)
    total_dims = len({dim for dims in matrix.values() for dim in dims})
    console.print(f"    [muted]{total_kinds} kinds × {total_dims} dims tracked[/muted]")
    # Cells are the cumulative attribution-weighted contribution
    # (``attribution_score × observed_dim``). The sign is NOT a clean
    # goodness signal — ``attribution_score`` is itself signed [-1, 1] —
    # so this view keeps its raw contribution semantics. The canonical
    # "+ = improvement" polarity view lives on the per-mutation
    # ``signed_improvement`` attribution field (PR-SIL-MULTIOBJ A4).
    console.print()
    kind_width = max(len(k) for k in matrix)
    for kind in sorted(matrix):
        top3 = rank_dims_by_kind(matrix, kind, limit=3)
        cells = "  ".join(f"{dim}={score:+.3f}" for dim, score in top3) or "[muted]no dims[/muted]"
        console.print(f"    {kind:<{kind_width}}  {cells}")
    console.print()


def _cmd_rollback_check(opts: list[str]) -> None:
    """Render ``evaluate_rollback_condition`` over recent apply rows.

    Wires the previously orphan
    ``core.self_improving.loop.observe.rollback_condition.evaluate_rollback_condition``.
    For each of the last N apply rows that has a non-empty
    ``rollback_condition`` predicate, evaluates the predicate against
    the current baseline.json (baseline_dim + baseline_fitness) and the
    latest matching attribution row's ``observed_dim`` (when available).

    Output rows: ``mutation_id  target_section  WOULD-TRIGGER|safe  predicate``.
    Operators use this to spot mutations whose rollback condition is now
    firing against current state — manual rollback candidates.
    """
    import core.paths
    from core.self_improving.loop.observe.mutations_reader import (
        read_recent_applies,
        read_recent_attributions,
    )
    from core.self_improving.loop.observe.rollback_condition import evaluate_rollback_condition

    last_n = _parse_last_n(opts)
    apply_rows = read_recent_applies(n=last_n, path=core.paths.MUTATION_AUDIT_LOG_PATH)
    attr_rows = read_recent_attributions(n=last_n, path=core.paths.MUTATION_AUDIT_LOG_PATH)

    console.print()
    console.print(f"  [header]Rollback-condition evaluation[/header] (last {last_n} applied rows)")
    if not apply_rows:
        console.print("    [muted]no applied mutations yet[/muted]")
        console.print()
        return

    # baseline.json is RUNTIME (out-of-repo, PR-STATE-SOT-RUNTIME-SPLIT), no
    # longer a sibling of the tracked mutations.jsonl — read it from the live
    # ``core.paths.BASELINE_JSON_PATH`` via attribute access so a test monkeypatch
    # on that constant is seen here (the original Codex must-fix #1 isolation
    # property, now keyed on the baseline constant rather than the audit log).
    baseline_path = Path(core.paths.BASELINE_JSON_PATH)
    baseline = read_json_or_none(baseline_path) or {}
    baseline_dim_raw = baseline.get("dim_means") if isinstance(baseline, dict) else None
    if not isinstance(baseline_dim_raw, dict):
        baseline_dim_raw = None
    baseline_dim: dict[str, float] | None = None
    if baseline_dim_raw is not None:
        baseline_dim = {
            k: float(v) for k, v in baseline_dim_raw.items() if isinstance(v, int | float)
        }
    raw_fitness = baseline.get("fitness") if isinstance(baseline, dict) else None
    baseline_fitness = float(raw_fitness) if isinstance(raw_fitness, int | float) else None

    attr_by_id = {a.mutation_id: a for a in attr_rows if getattr(a, "mutation_id", None)}

    rows_with_predicate = [r for r in apply_rows if getattr(r, "rollback_condition", "").strip()]
    if not rows_with_predicate:
        console.print(
            "    [muted]no rollback_condition predicates set on recent mutations — "
            "mutator output didn't include the field, or the window is empty[/muted]"
        )
        console.print()
        return

    triggered = 0
    for row in rows_with_predicate:
        mid = getattr(row, "mutation_id", "?")
        section = getattr(row, "target_section", "?")
        predicate = getattr(row, "rollback_condition", "")
        attr = attr_by_id.get(mid)
        observed_dim = dict(getattr(attr, "observed_dim", {}) or {}) if attr else {}
        observed_fitness = None
        if attr is not None:
            raw_obs_fitness = getattr(attr, "fitness_after", None)
            if isinstance(raw_obs_fitness, int | float):
                observed_fitness = float(raw_obs_fitness)
        fires = evaluate_rollback_condition(
            predicate,
            observed_dim=observed_dim,
            baseline_dim=baseline_dim,
            observed_fitness=observed_fitness,
            baseline_fitness=baseline_fitness,
        )
        label = "[bold red]WOULD-TRIGGER[/bold red]" if fires else "[muted]safe[/muted]"
        if fires:
            triggered += 1
        console.print(f"    {mid[:12]:<12}  {section:<24}  {label}  {_clip(predicate, 60)}")
    console.print()
    summary_color = "bold" if triggered else "muted"
    console.print(
        f"  [{summary_color}]{triggered} of {len(rows_with_predicate)} predicates "
        f"trigger against current baseline[/{summary_color}]"
    )
    console.print()
