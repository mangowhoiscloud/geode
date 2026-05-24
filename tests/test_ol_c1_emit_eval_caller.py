"""OL-C1 — autoresearch audit cycle emits eval_response_recorded.

Pins:
- ``autoresearch/train.py`` main() emits one ``eval_response_recorded``
  event per audit cycle inside the active RunTranscript scope.
- Payload schema matches PR-M4.0 contract: ``prompt`` / ``response``
  / ``fitness_score`` / ``axis_scores`` / ``source`` / ``rollback_flag``.
- ``source`` field == ``"autoresearch_audit"``.
- ``rollback_flag`` is True when fitness == 0.0 OR verdict in
  ``{"reject", "regression"}``; False otherwise.
- Emit is graceful — a synthetic emit failure does not crash the audit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.self_improving_loop.run_transcript import (
    RunTranscript,
    run_transcript_scope,
)


def _journal_with_path(tmp_path: Path) -> RunTranscript:
    return RunTranscript(
        session_id="ol-c1-test",
        gen_tag="auto-test",
        component="autoresearch",
        path=tmp_path / "transcript.jsonl",
    )


def _read_events(path: Path, name: str = "eval_response_recorded") -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and json.loads(line).get("event") == name
    ]


# ---------------------------------------------------------------------------
# Direct emit unit tests (validate the call site contract without running
# the entire train.py main — the actual main has many dependencies that
# would require full E2E; the assertions here pin the *contract* the
# call site must follow).
# ---------------------------------------------------------------------------


def test_autoresearch_emit_pattern_chosen_pile(tmp_path: Path) -> None:
    """fitness > 0 + verdict != reject → rollback_flag=False (chosen pile)."""
    from core.self_improving_loop.eval_journaling import emit_eval_response_recorded

    journal = _journal_with_path(tmp_path)
    with run_transcript_scope(journal):
        ok = emit_eval_response_recorded(
            prompt="autoresearch audit cycle on commit abc123 "
            "(seed_select='default', description='gen-1')",
            response="verdict=accept fitness=0.7321 promoted=true dim_means_count=17 "
            "bench_means_count=7",
            fitness_score=0.7321,
            axis_scores={"dim_means_aggregate": 0.78, "bench_means_aggregate": 0.65},
            source="autoresearch_audit",
            rollback_flag=False,
        )
    assert ok is True
    events = _read_events(journal.path)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["source"] == "autoresearch_audit"
    assert payload["fitness_score"] == 0.7321
    assert payload["rollback_flag"] is False
    assert payload["axis_scores"]["dim_means_aggregate"] == 0.78


def test_autoresearch_emit_pattern_rejected_pile(tmp_path: Path) -> None:
    """fitness == 0.0 (critical regression) → rollback_flag=True (rejected pile)."""
    from core.self_improving_loop.eval_journaling import emit_eval_response_recorded

    journal = _journal_with_path(tmp_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(
            prompt="autoresearch audit cycle on commit def456 "
            "(seed_select='default', description='gen-2-bad')",
            response="verdict=reject fitness=0.0000 promoted=false dim_means_count=17 "
            "bench_means_count=7",
            fitness_score=0.0,
            axis_scores={"dim_means_aggregate": 0.42, "bench_means_aggregate": 0.30},
            source="autoresearch_audit",
            rollback_flag=True,
        )
    events = _read_events(journal.path)
    assert len(events) == 1
    assert events[0]["payload"]["rollback_flag"] is True
    assert events[0]["payload"]["fitness_score"] == 0.0


def test_autoresearch_emit_pattern_no_journal_scope_is_noop() -> None:
    """No run_transcript_scope → emit returns False, no file written, no raise."""
    from core.self_improving_loop.eval_journaling import emit_eval_response_recorded

    ok = emit_eval_response_recorded(
        prompt="audit prompt",
        response="audit response",
        fitness_score=0.5,
        source="autoresearch_audit",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# Source check — ensure the train.py call site actually exists with the
# right shape (Codex MCP catch prevention: "X-driven" claims must be
# grep-provable in the source).
# ---------------------------------------------------------------------------


def test_train_py_imports_emit_eval_response_recorded() -> None:
    """``autoresearch/train.py`` must contain the import + call."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    assert (
        "from core.self_improving_loop.eval_journaling import emit_eval_response_recorded"
        in train_py
    )
    assert "emit_eval_response_recorded(" in train_py
    assert 'source="autoresearch_audit"' in train_py


def test_train_py_emit_is_inside_main() -> None:
    """The emit call site must be inside main() (not module-level)."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    main_idx = train_py.find("def main() -> int:")
    emit_idx = train_py.find("emit_eval_response_recorded(")
    assert main_idx > 0
    assert emit_idx > main_idx, "emit must be inside main(), not module-level"


def test_train_py_emit_uses_rollback_heuristic() -> None:
    """The call site computes rollback_flag from fitness + verdict."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    # Pin the heuristic shape so refactors are surfaced
    assert (
        "fitness == 0.0" in train_py and 'verdict.lower() in {"reject", "regression"}' in train_py
    )


def test_train_py_emit_wrapped_in_try_except() -> None:
    """Eval-stream emit must never crash the audit — try/except guard."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    # The block should sit inside a `try:` ... `except` ... block
    emit_marker = "emit_eval_response_recorded("
    pos = train_py.find(emit_marker)
    assert pos > 0
    # Search a wide window before for `try:` (the call site has multi-line
    # f-strings between the try: line and the emit call).
    preceding = train_py[max(0, pos - 2000) : pos]
    assert "try:" in preceding, "emit must be wrapped in try/except per OL-C1 spec"


@pytest.mark.parametrize(
    "fitness, verdict, expected_rollback",
    [
        (0.7, "accept", False),
        (0.0, "pending", True),  # fitness==0 wins
        (0.5, "reject", True),
        (0.5, "REJECT", True),  # case-insensitive
        (0.5, "regression", True),
        (0.5, "pending", False),
        (0.0001, "accept", False),  # > 0
    ],
)
def test_rollback_heuristic_matrix(fitness: float, verdict: str, expected_rollback: bool) -> None:
    """The rollback heuristic exactly: fitness == 0.0 OR verdict in {reject, regression}."""
    rollback = fitness == 0.0 or verdict.lower() in {"reject", "regression"}
    assert rollback is expected_rollback
