"""Package-boundary checks for removed compatibility paths."""

from scripts import check_package_artifacts as artifacts


def test_worker_composition_roots_are_required_in_both_artifacts() -> None:
    required = {"core/worker.py", "evals/worker.py"}

    assert required <= artifacts.REQUIRED_WHEEL_PATHS
    assert required <= artifacts.REQUIRED_SDIST_PATHS


def test_current_architecture_skills_are_required_in_both_artifacts() -> None:
    required = {
        ".geode/skills/geode-context/SKILL.md",
        ".geode/skills/slop-audit/SKILL.md",
    }

    assert required <= artifacts.REQUIRED_WHEEL_PATHS
    assert required <= artifacts.REQUIRED_SDIST_PATHS


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
