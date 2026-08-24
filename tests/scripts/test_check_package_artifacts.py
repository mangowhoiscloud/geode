"""Package-boundary checks for removed compatibility paths."""

from scripts import check_package_artifacts as artifacts


def test_removed_compatibility_layout_rejects_every_legacy_root() -> None:
    paths = {
        "core/self_improving/loop/mutate/runner.py",
        "core/self_improving/state/results.jsonl",
        "plugins/petri_audit/runner.py",
    }

    assert artifacts._check_removed_compatibility_layout("wheel", paths) == [
        "wheel: removed compatibility path is packaged: core/self_improving/loop/mutate/runner.py",
        "wheel: removed compatibility path is packaged: core/self_improving/state/results.jsonl",
        "wheel: removed compatibility path is packaged: plugins/petri_audit/runner.py",
    ]
