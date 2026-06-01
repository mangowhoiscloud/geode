"""PR-SOT-REVERT-ON-REJECT (2026-05-26) — SoT revert on rejected mutation.

Closes a CRITICAL silent leak surfaced in the 2026-05-26 autoresearch
attribution/wiring sprint Phase A audit:

* ``SelfImprovingLoopRunner.apply_proposal`` (runner.py:1865) writes the
  mutated section to the canonical SoT BEFORE the audit subprocess runs.
* ``core.self_improving.train.main`` (train.py:2453) used to call
  ``_write_baseline`` only when ``_should_promote`` returned ``True`` —
  the ``False`` branch had no else clause, so the SoT remained mutated
  even though the baseline was unchanged.
* Result: every rejected mutation accumulated as permanent SoT state,
  next-cycle baseline scoring ran against the stacked SoT, and
  regression-cause attribution became undecomposable.

This file pins two parts of the fix:

1. ``_revert_sot_after_reject`` correctly looks up the apply row by
   ``mutation_id`` and restores the previous_value to the SoT — for
   both ``prompt`` (wrapper-sections SoT) and policy kinds (policies.py
   SoT files).
2. The ``main()`` promote gate calls the revert only when
   ``GEODE_SIL_MUTATION_ID`` is set (runner-driven cycle), not on
   manual audits (operator-driven accumulation is intentional).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch


def _write_apply_row(
    log_path: Path,
    *,
    mutation_id: str,
    target_kind: str,
    target_section: str,
    previous_value: str,
    new_value: str = "mutated",
) -> None:
    """Append one apply row to a mutations.jsonl fixture."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": time.time(),
        "kind": "applied",
        "mutation_id": mutation_id,
        "target_kind": target_kind,
        "target_section": target_section,
        "previous_value": previous_value,
        "new_value": new_value,
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_revert_returns_false_when_mutation_id_missing(tmp_path: Path) -> None:
    """Empty mutations.jsonl → (False, 'not found') without raising."""
    from core.self_improving.train import _revert_sot_after_reject

    empty_log = tmp_path / "mutations.jsonl"
    empty_log.touch()

    ok, detail = _revert_sot_after_reject("mut-absent", audit_log_path=empty_log)

    assert ok is False
    assert "not found" in detail


def test_revert_returns_false_when_log_file_absent(tmp_path: Path) -> None:
    """Missing mutations.jsonl is graceful (iter_mutations yields empty)."""
    from core.self_improving.train import _revert_sot_after_reject

    nonexistent_log = tmp_path / "does-not-exist.jsonl"

    ok, detail = _revert_sot_after_reject("mut-x", audit_log_path=nonexistent_log)

    assert ok is False
    assert "not found" in detail


def test_revert_restores_prompt_kind_via_wrapper_sections(tmp_path: Path) -> None:
    """``prompt`` kind dispatches through wrapper-sections SoT helpers."""
    from core.self_improving.train import _revert_sot_after_reject

    from core.self_improving import train as train_module

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="mut-prompt-1",
        target_kind="prompt",
        target_section="role",
        previous_value="original-role-prose",
        new_value="mutated-role-prose",
    )

    # Patch the wrapper-sections helpers to capture revert behaviour
    # without touching the operator's real ``~/.geode`` SoT.
    current_state = {"role": "mutated-role-prose", "shell_caution": "untouched"}

    def fake_load() -> dict[str, str]:
        return dict(current_state)

    def fake_write(sections: dict[str, str]) -> None:
        current_state.clear()
        current_state.update(sections)

    with (
        patch.object(train_module, "load_wrapper_prompt_sections", fake_load),
        patch.object(train_module, "write_wrapper_prompt_sections", fake_write),
    ):
        ok, detail = _revert_sot_after_reject("mut-prompt-1", audit_log_path=log_path)

    assert ok is True
    assert detail == "prompt.role"
    assert current_state["role"] == "original-role-prose"
    # Symmetric branch parity — non-target section must be preserved.
    assert current_state["shell_caution"] == "untouched"


def test_revert_restores_policy_kind_via_policies_helpers(tmp_path: Path) -> None:
    """Non-prompt kinds dispatch through ``policies.load_policy`` /
    ``policies.write_policy``."""
    from core.self_improving.train import _revert_sot_after_reject

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="mut-tool-policy-1",
        target_kind="tool_policy",
        target_section="prefer_grep",
        previous_value="true",
        new_value="false",
    )

    current_state: dict[str, str] = {"prefer_grep": "false", "other_key": "kept"}

    def fake_load(kind: str) -> dict[str, str]:
        assert kind == "tool_policy"
        return dict(current_state)

    captured: dict[str, dict[str, str]] = {}

    def fake_write(kind: str, sections: dict[str, str]) -> Path:
        captured["kind"] = kind  # type: ignore[assignment]
        captured["sections"] = sections
        current_state.clear()
        current_state.update(sections)
        return tmp_path / f"{kind}.json"

    with (
        patch("core.self_improving.loop.policies.load_policy", fake_load),
        patch("core.self_improving.loop.policies.write_policy", fake_write),
    ):
        ok, detail = _revert_sot_after_reject("mut-tool-policy-1", audit_log_path=log_path)

    assert ok is True
    assert detail == "tool_policy.prefer_grep"
    assert captured["kind"] == "tool_policy"  # type: ignore[comparison-overlap]
    assert captured["sections"]["prefer_grep"] == "true"
    assert captured["sections"]["other_key"] == "kept"


def test_revert_picks_latest_apply_row_on_duplicate_mutation_id(tmp_path: Path) -> None:
    """When mutations.jsonl has multiple apply rows with the same
    mutation_id (rare; mutator should mint fresh IDs), revert restores
    the LATEST previous_value so the newest mutation is the one
    unwound."""
    from core.self_improving.train import _revert_sot_after_reject

    from core.self_improving import train as train_module

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="dup-mid",
        target_kind="prompt",
        target_section="role",
        previous_value="oldest-prev",
        new_value="first-mut",
    )
    _write_apply_row(
        log_path,
        mutation_id="dup-mid",
        target_kind="prompt",
        target_section="role",
        previous_value="newest-prev",
        new_value="second-mut",
    )

    current_state = {"role": "second-mut"}

    def fake_load() -> dict[str, str]:
        return dict(current_state)

    def fake_write(sections: dict[str, str]) -> None:
        current_state.clear()
        current_state.update(sections)

    with (
        patch.object(train_module, "load_wrapper_prompt_sections", fake_load),
        patch.object(train_module, "write_wrapper_prompt_sections", fake_write),
    ):
        ok, detail = _revert_sot_after_reject("dup-mid", audit_log_path=log_path)

    assert ok is True
    assert current_state["role"] == "newest-prev"


def test_revert_returns_false_when_writer_raises(tmp_path: Path) -> None:
    """Writer OSError must not bubble — caller surfaces the leak status
    in the audit's promoted_line, never crashes the audit."""
    from core.self_improving.train import _revert_sot_after_reject

    from core.self_improving import train as train_module

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="mut-fail",
        target_kind="prompt",
        target_section="role",
        previous_value="orig",
        new_value="new",
    )

    def fake_load() -> dict[str, str]:
        return {"role": "new"}

    def fake_write(sections: dict[str, str]) -> None:
        raise OSError("disk full")

    with (
        patch.object(train_module, "load_wrapper_prompt_sections", fake_load),
        patch.object(train_module, "write_wrapper_prompt_sections", fake_write),
    ):
        ok, detail = _revert_sot_after_reject("mut-fail", audit_log_path=log_path)

    assert ok is False
    assert "write failed" in detail
    assert "OSError" in detail


def test_only_kind_applied_is_considered_not_applied_sibling(tmp_path: Path) -> None:
    """Legacy ``applied_sibling`` rows (from the removed group-sampling
    era — PR-GROUP-REMOVAL) must NOT be used as revert targets: those
    non-best siblings were never committed to the canonical SoT. The
    current (1+1)-ES reader filters on ``kind="applied"`` only, so this
    pins that a stray legacy row is ignored rather than reverted."""
    from core.self_improving.train import _revert_sot_after_reject

    log_path = tmp_path / "mutations.jsonl"
    # Write a sibling-only row first (must be ignored)
    row = {
        "ts": time.time(),
        "kind": "applied_sibling",
        "mutation_id": "sibling-only-mid",
        "target_kind": "prompt",
        "target_section": "role",
        "previous_value": "this-should-not-revert",
        "new_value": "sibling-mut",
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")

    ok, detail = _revert_sot_after_reject("sibling-only-mid", audit_log_path=log_path)

    # iter_mutations is called with kinds={"applied"} so the sibling row
    # is filtered out. Result: row not found.
    assert ok is False
    assert "not found" in detail


def test_revert_deletes_section_when_previous_value_empty(tmp_path: Path) -> None:
    """Insertion-case symmetry — ``apply_mutation`` records
    ``previous_value=""`` when the target_section was absent before
    the mutation (runner.py:978, :991). Revert must DELETE the
    inserted key, not write back an empty string, or the rejected
    insertion leaves a residual empty-string section in the SoT."""
    from core.self_improving.train import _revert_sot_after_reject

    from core.self_improving import train as train_module

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="mut-insert-1",
        target_kind="prompt",
        target_section="newly_inserted",
        previous_value="",  # insertion: section was absent before
        new_value="inserted-content",
    )

    current_state = {
        "role": "kept",
        "newly_inserted": "inserted-content",  # mutator just added this
    }

    def fake_load() -> dict[str, str]:
        return dict(current_state)

    def fake_write(sections: dict[str, str]) -> None:
        current_state.clear()
        current_state.update(sections)

    with (
        patch.object(train_module, "load_wrapper_prompt_sections", fake_load),
        patch.object(train_module, "write_wrapper_prompt_sections", fake_write),
    ):
        ok, _ = _revert_sot_after_reject("mut-insert-1", audit_log_path=log_path)

    assert ok is True
    # Key must be REMOVED, not present with empty value.
    assert "newly_inserted" not in current_state
    assert current_state["role"] == "kept"


def test_revert_deletes_inserted_policy_kind_section(tmp_path: Path) -> None:
    """Same insertion semantics for non-prompt kinds — ``write_policy``
    must receive a sections dict without the inserted key."""
    from core.self_improving.train import _revert_sot_after_reject

    log_path = tmp_path / "mutations.jsonl"
    _write_apply_row(
        log_path,
        mutation_id="mut-insert-policy",
        target_kind="tool_policy",
        target_section="newly_added_rule",
        previous_value="",
        new_value="prefer-fd",
    )

    current_state: dict[str, str] = {
        "existing_key": "keep",
        "newly_added_rule": "prefer-fd",
    }

    captured: dict[str, dict[str, str]] = {}

    def fake_load(kind: str) -> dict[str, str]:
        return dict(current_state)

    def fake_write(kind: str, sections: dict[str, str]) -> Path:
        captured["sections"] = sections
        current_state.clear()
        current_state.update(sections)
        return tmp_path / f"{kind}.json"

    with (
        patch("core.self_improving.loop.policies.load_policy", fake_load),
        patch("core.self_improving.loop.policies.write_policy", fake_write),
    ):
        ok, _ = _revert_sot_after_reject("mut-insert-policy", audit_log_path=log_path)

    assert ok is True
    assert "newly_added_rule" not in captured["sections"]
    assert captured["sections"]["existing_key"] == "keep"
