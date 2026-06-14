"""PR-WIRE-1 (2026-05-26) — orphan helper CLI wiring.

The 2026-05-26 autoresearch attribution sprint Phase A audit identified
production-orphan helpers in ``core/self_improving/loop/``:

* ``compute_kind_dim_matrix`` / ``rank_dims_by_kind`` (kind_dim_matrix.py)
  — 0 production callers
* ``evaluate_rollback_condition`` (rollback_condition.py) — 0 production
  callers; only the *field* ``rollback_condition`` on Mutation was
  wired (displayed in CLI), never evaluated.

This PR adds two REPL sub-actions that invoke each helper:
``/self-improving matrix``, ``rollback-check``. The tests
pin (a) that the dispatcher routes the new actions, (b) that each
sub-command actually invokes the helper at runtime (not just renders
a placeholder), (c) graceful empty-state output when the prerequisite
data is missing, (d) the ``--last N`` argv parsing.

(The ``credit`` sub-action wiring ``aggregate_credit_history`` was
removed with the group-sampling machinery in PR-GROUP-REMOVAL,
2026-05-29. The transpose helper ``rank_kinds_by_dim`` — never wired by
this PR, transpose of the still-wired ``rank_dims_by_kind`` — was removed
as dead code in PR-CLEANUP-SIL, 2026-05-31.)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


def _write_apply_row(
    log_path: Path,
    *,
    mutation_id: str,
    target_kind: str,
    target_section: str,
    expected_dim: dict[str, float] | None = None,
    rollback_condition: str = "",
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": time.time(),
        "kind": "applied",
        "mutation_id": mutation_id,
        "target_kind": target_kind,
        "target_section": target_section,
        "previous_value": "orig",
        "new_value": "new",
        "expected_dim": expected_dim or {},
        "rollback_condition": rollback_condition,
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _write_attribution_row(
    log_path: Path,
    *,
    mutation_id: str,
    observed_dim: dict[str, float],
    attribution_score: float = 1.0,
    fitness_after: float | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, object] = {
        "ts": time.time(),
        "kind": "attribution",
        "mutation_id": mutation_id,
        "observed_dim": observed_dim,
        "ci95": dict.fromkeys(observed_dim, 0.05),
        "significant": dict.fromkeys(observed_dim, True),
        "attribution_score": attribution_score,
        "missing_baseline": False,
    }
    if fitness_after is not None:
        row["fitness_after"] = fitness_after
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# Dispatcher routing — the three new actions actually reach their handlers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["matrix", "rollback-check"])
def test_dispatcher_routes_new_action_to_handler(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``cmd_self_improving("matrix")`` must invoke ``_cmd_matrix``, etc.
    Pin the dispatcher branch so a typo in the action string fails fast
    in CI instead of silently falling through to the unknown-action path."""
    from core.cli.commands import self_improving as mod

    calls: list[tuple[str, list[str]]] = []

    handler_attr = {
        "matrix": "_cmd_matrix",
        "rollback-check": "_cmd_rollback_check",
    }[action]

    def fake_handler(opts: list[str]) -> None:
        calls.append((handler_attr, opts))

    monkeypatch.setattr(mod, handler_attr, fake_handler)

    mod.cmd_self_improving(f"{action} --last 7")

    assert calls == [(handler_attr, ["--last", "7"])]


def test_unknown_action_help_lists_new_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The unknown-action help text must mention matrix /
    rollback-check so an operator who typos a sub-action sees the new
    wiring as available."""
    from core.cli.commands.self_improving import cmd_self_improving

    cmd_self_improving("nonexistent-action")
    output = capsys.readouterr().out
    assert "matrix" in output
    assert "rollback-check" in output


# ---------------------------------------------------------------------------
# Argv parsing — --last N
# ---------------------------------------------------------------------------


def test_parse_last_n_default() -> None:
    from core.cli.commands.self_improving import _parse_last_n

    assert _parse_last_n([]) == 20


def test_parse_last_n_explicit() -> None:
    from core.cli.commands.self_improving import _parse_last_n

    assert _parse_last_n(["--last", "5"]) == 5


def test_parse_last_n_invalid_falls_back() -> None:
    from core.cli.commands.self_improving import _parse_last_n

    assert _parse_last_n(["--last", "not-a-number"]) == 20
    assert _parse_last_n(["--last", "0"]) == 20
    assert _parse_last_n(["--last", "-5"]) == 20
    assert _parse_last_n(["--last"]) == 20  # missing value


# ---------------------------------------------------------------------------
# _cmd_matrix — wires compute_kind_dim_matrix + rank_dims_by_kind
# ---------------------------------------------------------------------------


def test_matrix_invokes_matrix_helper_on_real_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pin that ``/self-improving matrix`` actually calls the previously
    orphan ``compute_kind_dim_matrix`` helper. Writes matched apply +
    attribution rows so the inner-join yields a non-empty matrix, then
    checks the target_kind names appear in stdout."""
    from core.cli.commands.self_improving import _cmd_matrix

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="m1",
        target_kind="prompt",
        target_section="role",
    )
    _write_attribution_row(
        log_path,
        mutation_id="m1",
        observed_dim={"output_quality": 0.7, "conciseness": -0.3},
        attribution_score=0.9,
    )
    _write_apply_row(
        log_path,
        mutation_id="m2",
        target_kind="tool_policy",
        target_section="prefer_grep",
    )
    _write_attribution_row(
        log_path,
        mutation_id="m2",
        observed_dim={"output_quality": 0.4},
        attribution_score=0.5,
    )
    monkeypatch.setattr("core.paths.MUTATION_AUDIT_LOG_PATH", log_path)

    _cmd_matrix([])
    output = capsys.readouterr().out

    assert "Kind × Dim contribution matrix" in output
    assert "prompt" in output
    assert "tool_policy" in output
    assert "output_quality" in output
    assert "2 kinds" in output
    assert "2 dims" in output


def test_matrix_empty_state_when_no_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Apply + attribution rows with disjoint mutation_id → empty matrix
    → muted "no mutation_id overlap" line."""
    from core.cli.commands.self_improving import _cmd_matrix

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(log_path, mutation_id="m1", target_kind="prompt", target_section="role")
    _write_attribution_row(log_path, mutation_id="m-orphan", observed_dim={"x": 1.0})
    monkeypatch.setattr("core.paths.MUTATION_AUDIT_LOG_PATH", log_path)

    _cmd_matrix([])
    output = capsys.readouterr().out

    assert "no mutation_id overlap" in output


# ---------------------------------------------------------------------------
# _cmd_rollback_check — wires evaluate_rollback_condition
# ---------------------------------------------------------------------------


def test_rollback_check_evaluates_predicate_on_real_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pin that ``/self-improving rollback-check`` actually calls the
    previously orphan ``evaluate_rollback_condition``. Writes one apply
    row with a "fitness drops below X" predicate + a matching
    attribution row whose ``fitness_after`` triggers the predicate;
    checks that the WOULD-TRIGGER label appears in stdout."""
    from core.cli.commands.self_improving import _cmd_rollback_check

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="m-fires",
        target_kind="prompt",
        target_section="role",
        rollback_condition="rollback if fitness drops below 0.5",
    )
    _write_attribution_row(
        log_path,
        mutation_id="m-fires",
        observed_dim={"output_quality": 0.6},
        attribution_score=0.9,
        fitness_after=0.3,  # below threshold 0.5 → predicate fires
    )
    _write_apply_row(
        log_path,
        mutation_id="m-safe",
        target_kind="tool_policy",
        target_section="prefer_grep",
        rollback_condition="rollback if fitness drops below 0.5",
    )
    _write_attribution_row(
        log_path,
        mutation_id="m-safe",
        observed_dim={"output_quality": 0.7},
        attribution_score=0.9,
        fitness_after=0.8,  # above threshold → safe
    )
    monkeypatch.setattr("core.paths.MUTATION_AUDIT_LOG_PATH", log_path)

    _cmd_rollback_check([])
    output = capsys.readouterr().out

    assert "Rollback-condition evaluation" in output
    assert "WOULD-TRIGGER" in output
    assert "safe" in output
    # Both predicates were evaluated → 1 of 2 fires
    assert "1 of 2 predicates trigger" in output


def test_rollback_check_empty_state_when_no_predicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Apply rows without ``rollback_condition`` string → muted "no
    rollback_condition predicates" line. The predicate field has
    always been wired into the apply row but the evaluator function
    was orphan pre-PR-WIRE-1."""
    from core.cli.commands.self_improving import _cmd_rollback_check

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="m1",
        target_kind="prompt",
        target_section="role",
        rollback_condition="",  # empty — predicate field missing
    )
    monkeypatch.setattr("core.paths.MUTATION_AUDIT_LOG_PATH", log_path)

    _cmd_rollback_check([])
    output = capsys.readouterr().out

    assert "no rollback_condition predicates" in output


def test_rollback_check_baseline_dependent_predicate_uses_patched_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Codex MCP review #2 (CONDITIONAL_PASS must-fix #2) — pin that the
    rollback-check command reads baseline.json from the *patched*
    ``BASELINE_JSON_PATH`` location, NOT from the operator's real runtime
    baseline. Post PR-STATE-SOT-RUNTIME-SPLIT baseline.json is a separate
    runtime constant (no longer a sibling of ``MUTATION_AUDIT_LOG_PATH``). The
    predicate "any dim regresses by more than X" depends on baseline_dim — if
    baseline.json isn't read from the right place, the predicate either returns
    False silently (no baseline_dim → fall through to False) or evaluates
    against operator's real baseline.

    Writes a baseline.json with one dim at 5.0, an apply row with the
    regression-by-more-than-0.5 predicate, and an attribution row whose
    observed_dim shows dim at 6.0 (regression of 1.0 > threshold 0.5).
    Asserts WOULD-TRIGGER fires."""
    from core.cli.commands.self_improving import _cmd_rollback_check

    log_path = tmp_path / "mutations.jsonl"
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"dim_means": {"output_quality": 5.0}, "fitness": 0.7}),
        encoding="utf-8",
    )

    _write_apply_row(
        log_path,
        mutation_id="m-regress",
        target_kind="prompt",
        target_section="role",
        rollback_condition="rollback if any dim regresses by more than 0.5",
    )
    _write_attribution_row(
        log_path,
        mutation_id="m-regress",
        observed_dim={"output_quality": 6.0},  # +1.0 from baseline 5.0 > 0.5 threshold
        attribution_score=0.9,
    )

    monkeypatch.setattr("core.paths.MUTATION_AUDIT_LOG_PATH", log_path)
    monkeypatch.setattr("core.paths.BASELINE_JSON_PATH", baseline_path)

    _cmd_rollback_check([])
    output = capsys.readouterr().out

    assert "WOULD-TRIGGER" in output
    assert "1 of 1 predicates trigger" in output


def test_rollback_check_no_apply_rows_empty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fresh mutations.jsonl → muted "no applied mutations" line."""
    from core.cli.commands.self_improving import _cmd_rollback_check

    log_path = tmp_path / "mutations.jsonl"
    monkeypatch.setattr("core.paths.MUTATION_AUDIT_LOG_PATH", log_path)

    _cmd_rollback_check([])
    output = capsys.readouterr().out

    assert "no applied mutations yet" in output
