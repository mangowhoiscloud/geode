"""Package-boundary checks for removed compatibility paths."""

import pytest
from scripts import check_package_artifacts as artifacts


@pytest.mark.parametrize(
    ("label", "required"),
    [("wheel", artifacts.REQUIRED_WHEEL_PATHS), ("sdist", artifacts.REQUIRED_SDIST_PATHS)],
)
@pytest.mark.parametrize(
    "missing",
    ["scripts/macos/build_computer_helper.sh", "scripts/macos/geode_computer_helper.swift"],
)
def test_missing_computer_helper_rejects_distribution(
    label: str, required: set[str], missing: str
) -> None:
    assert artifacts._check_required(label, required - {missing}, required) == [
        f"{label}: missing required path {missing}"
    ]


def test_worker_composition_roots_are_required_in_both_artifacts() -> None:
    required = {"core/worker.py", "evals/worker.py"}

    assert required <= artifacts.REQUIRED_WHEEL_PATHS
    assert required <= artifacts.REQUIRED_SDIST_PATHS


def test_self_contained_builtin_skills_are_exact_in_both_artifacts() -> None:
    required = {
        ".geode/skills/deep-researcher/SKILL.md",
        ".geode/skills/pdf/scripts/fill_fillable_fields.py",
    }

    assert required <= artifacts.REQUIRED_WHEEL_PATHS
    assert required <= artifacts.REQUIRED_SDIST_PATHS
    assert artifacts._check_banned(
        "wheel",
        {".geode/skills/wiki-sync/SKILL.md"},
        artifacts.BANNED_WHEEL_PREFIXES,
    ) == ["wheel: banned path .geode/skills/wiki-sync/SKILL.md"]


def test_removed_compatibility_layout_rejects_every_legacy_root() -> None:
    paths = {
        "core/self_improving/loop/mutate/runner.py",
        "core/self_improving/state/results.jsonl",
        "geode_product/cli.py",
        "plugins/petri_audit/runner.py",
    }

    assert artifacts._check_removed_compatibility_layout("wheel", paths) == [
        "wheel: removed compatibility path is packaged: core/self_improving/loop/mutate/runner.py",
        "wheel: removed compatibility path is packaged: core/self_improving/state/results.jsonl",
        "wheel: removed compatibility path is packaged: geode_product/cli.py",
        "wheel: removed compatibility path is packaged: plugins/petri_audit/runner.py",
    ]


def test_rolling_experiment_state_is_rejected() -> None:
    assert artifacts._check_mutable_state(
        "wheel",
        {"evolve/scaffold_search/state/mutations.jsonl"},
    ) == [
        "wheel: mutable experiment state is packaged: evolve/scaffold_search/state/mutations.jsonl"
    ]
