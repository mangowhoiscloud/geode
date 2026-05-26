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
    from core.self_improving_loop.policies import TARGET_KINDS

    assert "tool_descriptions" in TARGET_KINDS


def test_tool_descriptions_removed_from_reader_only() -> None:
    from core.self_improving_loop.policies import _READER_ONLY_KINDS

    assert "tool_descriptions" not in _READER_ONLY_KINDS


def test_policy_path_routes_to_tool_descriptions_constant() -> None:
    from core.paths import GLOBAL_TOOL_DESCRIPTIONS_PATH
    from core.self_improving_loop.policies import policy_path

    assert policy_path("tool_descriptions") == GLOBAL_TOOL_DESCRIPTIONS_PATH


def test_nested_load_flattens_description_and_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.self_improving_loop import policies as policies_mod

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
    from core.self_improving_loop import policies as policies_mod

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
    from core.self_improving_loop.runner import parse_mutation

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
