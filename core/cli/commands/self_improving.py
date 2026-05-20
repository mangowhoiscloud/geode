"""``/self-improving`` (and alias ``/sil``) REPL slash command.

PR-OPS-1 (2026-05-21) — smallest operator-facing surface for the
self-improving loop. Today only the ``status`` sub-action is wired:
it reads ``autoresearch/state/mutations.jsonl`` (the git-tracked
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
reading ``autoresearch/program.md``) stays a parallel, manual path.
See ``docs/plans/2026-05-21-self-improving-loop-ux.md`` for the full
design.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.ui.console import console

__all__ = ["cmd_self_improving"]


_HISTORY_DEFAULT_N = 5
# PR-MINIMAL-1 (2026-05-21) — only ``config`` stays deferred. The
# ``history`` and ``rollback`` actions used to be reserved slots
# (PR-OPS-1) but git already provides both — ``git log`` for the
# audit ledger, ``git revert`` for the rollback — now that
# PR-RATCHET-1 has the 5 policy SoT files in-repo. The slash
# handlers below print the exact git command instead, keeping the
# operator inside one tool surface without re-implementing what
# git does natively.
_RUN_DEFERRED_ACTIONS = frozenset({"config"})
_KNOWN_ACTIONS = frozenset({"status", "run", "history", "rollback"}) | _RUN_DEFERRED_ACTIONS
_DESIGN_DOC = "docs/plans/2026-05-21-self-improving-loop-ux.md"
_RUN_DEFAULT_ITERATIONS = 1
_RUN_MAX_ITERATIONS = 10


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

    if action in _RUN_DEFERRED_ACTIONS:
        console.print()
        console.print(
            f"  [warning]/{action} is reserved for PR-OPS-2b/3[/warning] — "
            f"see [muted]{_DESIGN_DOC}[/muted]"
        )
        console.print()
        return

    console.print()
    console.print(f"  [warning]Unknown action: /self-improving {action}[/warning]")
    console.print(
        "  [muted]Available now: [/muted]status / run / history / rollback   "
        "[muted]Coming PR-OPS-3:[/muted] config"
    )
    console.print()


def _cmd_status() -> None:
    """Render current baseline + recent mutations.

    Output blocks (Mode B mutator state):
      1. Baseline — ``autoresearch/state/baseline.json`` (if exists)
         · ``fitness`` scalar, ``promote_reason``, ``timestamp``
      2. Recent mutations — last N rows from
         ``autoresearch/state/mutations.jsonl``
         · per-row ``ts`` / ``mutation_id`` / ``target_kind`` /
           ``target_section`` / ``kind`` (applied | rejected | rolled_back)

    Both files are git-tracked; missing files render an empty-state
    line rather than raising so an operator can call ``status`` on a
    fresh clone before any run.
    """
    from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH

    console.print()
    console.print("  [header]Self-improving loop — status[/header]")

    baseline_path = _baseline_path()
    baseline = _load_json(baseline_path)
    console.print()
    console.print("  [bold]Baseline[/bold]")
    if baseline is None:
        console.print(f"    [muted]no baseline yet — {baseline_path} absent[/muted]")
    else:
        fitness = baseline.get("fitness")
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
    """Resolve ``autoresearch/state/baseline.json`` relative to the
    project root. The audit ledger lives in the same dir, so we lean
    on its constant rather than reinventing root-detection here."""
    from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH

    return Path(MUTATION_AUDIT_LOG_PATH).parent / "baseline.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    """Return the parsed JSON dict, or ``None`` on missing/malformed
    file. Slash output must never raise on bad input — operator may
    inspect mid-run when the file is being rewritten."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


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

    console.print(f"  [muted]summary:[/muted] applied={applied}  rejected={rejected}")
    console.print()


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
    if target_kind and target_kind not in {
        "prompt",
        "tool_policy",
        "decomposition",
        "retrieval",
        "reflection",
    }:
        console.print(
            "  [warning]--target-kind must be one of "
            "prompt|tool_policy|decomposition|retrieval|reflection[/warning]"
        )
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
        from core.self_improving_loop.runner import SelfImprovingLoopRunner

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
        from core.config.self_improving_loop import load_self_improving_loop_config

        cfg = load_self_improving_loop_config()
        mutator_model = cfg.mutator.default_model
        mutator_source = cfg.mutator.source
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

    from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH

    log = logging.getLogger(__name__)
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
# ledger (``autoresearch/state/mutations.jsonl``) + the 5 policy SoT
# JSONs at ``autoresearch/state/policies/`` (both git-tracked since
# PR-RATCHET-1, 2026-05-21). Re-implementing the JSONL tail walker +
# a custom rollback verb would duplicate `git log` + `git revert`
# while losing standard git ergonomics (refs / SHAs / signed
# commits / hooks). The handlers below print the exact git command
# so the operator stays inside one mental model.


def _cmd_history() -> None:
    """Show the operator how to read the mutation history via git.

    The mutation ledger (``autoresearch/state/mutations.jsonl``) +
    the 5 policy SoT JSONs (``autoresearch/state/policies/``) are
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
    console.print("    [bold]git log -p autoresearch/state/mutations.jsonl[/bold]")
    console.print(
        "    [muted]→ empty when no mutation has been applied yet "
        "(first /self-improving run apply seeds the ledger).[/muted]"
    )
    console.print()
    console.print("  [muted]Compact form (commit message + 1-line ledger row):[/muted]")
    console.print("    [bold]git log --oneline autoresearch/state/mutations.jsonl[/bold]")
    console.print()
    console.print(
        "  [muted]Current policy state (5 SoT files, see ``git diff`` for "
        "the current vs last-promoted snapshot):[/muted]"
    )
    console.print("    [bold]git log --stat autoresearch/state/policies/[/bold]")
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
            "autoresearch/state/mutations.jsonl[/bold]"
        )
        console.print()
        console.print("  [muted]Revert that commit:[/muted]")
        console.print("    [bold]git revert <sha-from-above>[/bold]")
    else:
        console.print("  [muted]Find the SHA of the mutation you want to undo:[/muted]")
        console.print("    [bold]git log --oneline -p autoresearch/state/mutations.jsonl[/bold]")
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
