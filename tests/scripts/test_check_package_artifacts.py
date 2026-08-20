"""Package-boundary checks for the self-improving relocation."""

from scripts import check_package_artifacts as artifacts


def test_self_improving_layout_rejects_deep_facades_and_duplicated_state() -> None:
    paths = {
        *artifacts.SELF_IMPROVING_FACADES,
        "core/self_improving/loop/mutate/runner.py",
        "geode_product/self_improving/state/results.jsonl",
    }

    assert artifacts._check_self_improving_layout("wheel", paths) == [
        "wheel: unexpected legacy self-improving module core/self_improving/loop/mutate/runner.py",
        "wheel: self-improving state duplicated under product package: "
        "geode_product/self_improving/state/results.jsonl",
    ]
