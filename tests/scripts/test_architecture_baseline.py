"""Tests for the generated architecture inventory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import architecture_baseline as baseline


def test_build_baseline_is_deterministic_and_internally_consistent() -> None:
    first = baseline.build_baseline()
    second = baseline.build_baseline()

    assert first == second
    assert baseline.serialize_baseline(first) == baseline.serialize_baseline(second)

    for package in ("core", "plugins", "tests"):
        inventory = first["packages"][package]
        assert inventory["python_files"] > 0
        assert inventory["python_loc"] >= inventory["python_files"]

    tools = first["tools"]
    assert tools["definition_count"] == len(tools["definition_names"])
    assert tools["schema_count"] == len(tools["schema_names"])
    assert tools["execution_registration_count"] == len(tools["execution_registration_names"])
    assert set(tools["handler_registration_origins"]) == set(tools["handler_registration_names"])
    assert tools["duplicate_definition_names"] == []
    assert tools["schema_errors"] == []
    assert tools["definition_only"] == []
    assert tools["execution_only"] == [
        "computer",
        "doctor_slack",
        "recall_tool_result",
    ]


def test_inventory_lists_traceable_architecture_details() -> None:
    measured = baseline.build_baseline()

    assert measured["hook_events"]["count"] == len(measured["hook_events"]["members"])
    assert measured["built_in_adapters"]["count"] == len(measured["built_in_adapters"]["classes"])
    assert measured["context_vars"]["count"] == len(measured["context_vars"]["items"])
    assert measured["core_to_plugins_imports"]["site_count"] == len(
        measured["core_to_plugins_imports"]["sites"]
    )
    assert measured["import_linter"]["ignored_edge_count"] == sum(
        len(contract["ignored_edges"]) for contract in measured["import_linter"]["contracts"]
    )
    assert measured["coordinators"]["AgenticLoop"]["constructor_arg_count"] > 0
    assert measured["coordinators"]["RuntimeCoreConfig"]["field_count"] > 0

    serialized = baseline.serialize_baseline(measured)
    assert str(baseline.REPO_ROOT) not in serialized
    assert json.loads(serialized) == measured


def test_nested_tool_schema_validation_fails_closed() -> None:
    errors = baseline._schema_errors(
        {
            "name": "broken_tool",
            "description": "Broken nested schema fixture.",
            "category": "system",
            "cost_tier": "cheap",
            "input_schema": {
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "items": {"type": "imaginary"},
                    }
                },
                "required": [],
            },
        }
    )

    assert any(
        "input_schema.properties.values.items.type has unsupported values" in error
        for error in errors
    )


def test_tool_inventory_refuses_to_normalize_duplicate_definitions(tmp_path: Path) -> None:
    definitions_path = tmp_path / "core" / "tools" / "definitions.json"
    definitions_path.parent.mkdir(parents=True)
    definitions = json.loads(
        (baseline.REPO_ROOT / "core" / "tools" / "definitions.json").read_text(encoding="utf-8")
    )
    definitions.append(definitions[0])
    definitions_path.write_text(json.dumps(definitions), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate definitions"):
        baseline._tool_inventory(tmp_path)


def test_replace_managed_block_updates_exactly_one_region(tmp_path: Path) -> None:
    path = tmp_path / "document.md"
    original = "before\n<!-- start -->\nstale\n<!-- end -->\nafter\n"

    updated = baseline.replace_managed_block(
        original,
        start_marker="<!-- start -->",
        end_marker="<!-- end -->",
        replacement="<!-- start -->\nfresh\n<!-- end -->",
        path=path,
    )

    assert updated == "before\n<!-- start -->\nfresh\n<!-- end -->\nafter\n"


@pytest.mark.parametrize(
    "text",
    [
        "no markers",
        "<!-- start -->\nmissing end",
        "<!-- start --><!-- end --><!-- end -->",
    ],
)
def test_replace_managed_block_fails_closed_on_bad_markers(text: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected exactly one"):
        baseline.replace_managed_block(
            text,
            start_marker="<!-- start -->",
            end_marker="<!-- end -->",
            replacement="replacement",
            path=tmp_path / "bad.md",
        )


def test_committed_consumers_match_current_snapshot() -> None:
    measured = baseline.build_baseline()
    expected = baseline.expected_files(measured)

    assert baseline._drifted(expected) == []
