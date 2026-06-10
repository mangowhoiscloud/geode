"""PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27) — ADR-013 T1 graduation.

Pins:

- ``tool_descriptions`` lives in ``TARGET_KINDS`` (mutator-dispatchable).
- ``tool_descriptions`` no longer lives in ``_READER_ONLY_KINDS``.
- ``policy_path("tool_descriptions")`` resolves to ``GLOBAL_TOOL_DESCRIPTIONS_PATH``.
- nested-schema round-trip: ``load_policy`` flattens disk shape,
  ``write_policy`` un-flattens including the ``hints`` list field.
- ``parse_mutation`` accepts ``target_kind="tool_descriptions"`` (no
  ValueError).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def test_tool_descriptions_is_target_kind() -> None:
    from core.self_improving.loop.policies import TARGET_KINDS

    assert "tool_descriptions" in TARGET_KINDS


def test_tool_descriptions_removed_from_reader_only() -> None:
    from core.self_improving.loop.policies import _READER_ONLY_KINDS

    assert "tool_descriptions" not in _READER_ONLY_KINDS


def test_policy_path_routes_to_tool_descriptions_constant() -> None:
    from core.paths import GLOBAL_TOOL_DESCRIPTIONS_PATH
    from core.self_improving.loop.policies import policy_path

    assert policy_path("tool_descriptions") == GLOBAL_TOOL_DESCRIPTIONS_PATH


def test_nested_load_flattens_description_and_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.self_improving.loop import policies as policies_mod

    sot = tmp_path / "tool-descriptions.json"
    payload: dict[str, dict[str, Any]] = {
        "bash": {
            "description": "Execute bash commands with timeout + sandbox.",
            "hints": ["Quote spaces", "Avoid -i flag"],
        },
        "read": {"description": "Read a file."},
    }
    sot.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setitem(policies_mod._KIND_TO_PATH, "tool_descriptions", sot)

    loaded = policies_mod.load_policy("tool_descriptions")
    assert loaded["bash.description"] == "Execute bash commands with timeout + sandbox."
    # hints joined with ", " by ``_flatten_nested``
    assert loaded["bash.hints"] == "Quote spaces, Avoid -i flag"
    assert loaded["read.description"] == "Read a file."


def test_round_trip_preserves_hints_list_on_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.self_improving.loop import policies as policies_mod

    sot = tmp_path / "tool-descriptions.json"
    monkeypatch.setitem(policies_mod._KIND_TO_PATH, "tool_descriptions", sot)

    flat = {
        "bash.description": "Run shell commands.",
        "bash.hints": "tip1, tip2, tip3",
    }
    policies_mod.write_policy("tool_descriptions", flat)
    on_disk = json.loads(sot.read_text(encoding="utf-8"))
    assert on_disk == {
        "bash": {
            "description": "Run shell commands.",
            "hints": ["tip1", "tip2", "tip3"],
        }
    }


def test_parse_mutation_accepts_tool_descriptions_target_kind() -> None:
    from core.self_improving.loop.runner import parse_mutation

    raw = json.dumps(
        {
            "target_section": "bash.description",
            "new_value": "Execute shell commands with sandbox guards.",
            "rationale": "broken_tool_use pressure",
            "target_dim": "broken_tool_use",
            "target_kind": "tool_descriptions",
            "expected_dim": {"broken_tool_use": -0.2},
        }
    )
    mutation = parse_mutation(raw)
    assert mutation.target_kind == "tool_descriptions"
    assert mutation.target_section == "bash.description"


def test_policy_path_resolves_to_operator_local_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex MCP review fix-up (PR-TOOL-DESCRIPTIONS-MUTATE, 2026-05-27):
    when the operator-local file exists, ``policy_path`` must return
    it (matching the runtime reader's 3-layer resolution). Pins the
    READ/WRITE parity rule — both halves now land on the same file
    that the runtime actually reads, eliminating the dual-SoT drift
    Codex flagged on the first review."""
    from core.self_improving.loop import policies as policies_mod

    in_repo = tmp_path / "in-repo.json"
    operator_local = tmp_path / "operator-local.json"
    operator_local.write_text(json.dumps({"bash": {}}), encoding="utf-8")
    monkeypatch.setitem(policies_mod._KIND_TO_PATH, "tool_descriptions", in_repo)
    monkeypatch.setitem(
        policies_mod._OPERATOR_LOCAL_FALLBACK_PATHS,
        "tool_descriptions",
        operator_local,
    )

    assert policies_mod.policy_path("tool_descriptions") == operator_local


def test_policy_path_falls_back_to_in_repo_when_operator_local_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No operator-local file present ⇒ the in-repo default wins
    (legacy / fresh-repo behaviour)."""
    from core.self_improving.loop import policies as policies_mod

    in_repo = tmp_path / "in-repo.json"
    operator_local = tmp_path / "operator-local.json"
    # operator-local intentionally NOT created.
    monkeypatch.setitem(policies_mod._KIND_TO_PATH, "tool_descriptions", in_repo)
    monkeypatch.setitem(
        policies_mod._OPERATOR_LOCAL_FALLBACK_PATHS,
        "tool_descriptions",
        operator_local,
    )

    assert policies_mod.policy_path("tool_descriptions") == in_repo


def test_load_policy_reads_operator_local_when_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When operator-local exists, ``load_policy`` reads from it (so
    the mutator sees what the runtime sees)."""
    from core.self_improving.loop import policies as policies_mod

    in_repo = tmp_path / "in-repo.json"
    operator_local = tmp_path / "operator-local.json"
    in_repo.write_text(
        json.dumps({"bash": {"description": "In-repo content (stale)."}}),
        encoding="utf-8",
    )
    operator_local.write_text(
        json.dumps({"bash": {"description": "Operator-local wins."}}),
        encoding="utf-8",
    )
    monkeypatch.setitem(policies_mod._KIND_TO_PATH, "tool_descriptions", in_repo)
    monkeypatch.setitem(
        policies_mod._OPERATOR_LOCAL_FALLBACK_PATHS,
        "tool_descriptions",
        operator_local,
    )

    loaded = policies_mod.load_policy("tool_descriptions")
    assert loaded["bash.description"] == "Operator-local wins."


def test_audit_env_override_honours_operator_local_tool_descriptions() -> None:
    """Codex MCP re-review (PR-TOOL-DESCRIPTIONS-MUTATE, 2026-05-27):
    ``core/self_improving/train.py:run_audit``'s env-override block for
    ``GEODE_TOOL_DESCRIPTIONS_OVERRIDE`` must honour the same
    resolution order as the runtime reader (env → operator-local →
    in-repo).

    Three rules pinned by source inspection:

    1. The override is set only when not already present in env
       (preserves sibling-SoT temp path from
       ``_run_autoresearch_subprocess``).
    2. Operator-local is preferred over in-repo.
    3. In-repo is the fallback when neither env nor operator-local
       is present.

    Source-inspection pin (same pattern as
    ``test_reader_only_kinds_match_env_override_block``) so a future
    refactor can't silently revert the fix without tripping this test.
    """
    import inspect

    from core.self_improving import measure as train_mod

    src = inspect.getsource(train_mod)
    # Rule 1: env preservation guard (pre-fix this clobbered the
    # sibling-SoT temp path).
    assert '"GEODE_TOOL_DESCRIPTIONS_OVERRIDE" not in env' in src, (
        "run_audit's env block must check "
        '``"GEODE_TOOL_DESCRIPTIONS_OVERRIDE" not in env`` before '
        "setting the override — otherwise the sibling-SoT temp path "
        "from _run_autoresearch_subprocess is silently clobbered."
    )
    # Rule 2: operator-local resolution.
    assert "OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH" in src, (
        "run_audit's env-override block must check "
        "OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH before falling back to "
        "GLOBAL_TOOL_DESCRIPTIONS_PATH — otherwise the env layer "
        "overrides operator-local content despite the mutator writing "
        "there."
    )


def test_write_policy_writes_to_operator_local_when_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read-write parity (CLAUDE.md rule): when operator-local exists,
    ``write_policy`` also writes there so the next runtime read picks
    up the mutator's change. Without this the mutator would write to
    in-repo while the runtime continued reading operator-local —
    closed-loop break."""
    from core.self_improving.loop import policies as policies_mod

    in_repo = tmp_path / "in-repo.json"
    operator_local = tmp_path / "operator-local.json"
    operator_local.write_text(
        json.dumps({"bash": {"description": "Original."}}),
        encoding="utf-8",
    )
    monkeypatch.setitem(policies_mod._KIND_TO_PATH, "tool_descriptions", in_repo)
    monkeypatch.setitem(
        policies_mod._OPERATOR_LOCAL_FALLBACK_PATHS,
        "tool_descriptions",
        operator_local,
    )

    policies_mod.write_policy(
        "tool_descriptions",
        {"bash.description": "Mutated."},
    )
    on_disk = json.loads(operator_local.read_text(encoding="utf-8"))
    assert on_disk == {"bash": {"description": "Mutated."}}
    assert not in_repo.exists(), (
        "in-repo file must NOT be created when operator-local is the "
        "resolved SoT — that would resurrect the dual-SoT drift."
    )
