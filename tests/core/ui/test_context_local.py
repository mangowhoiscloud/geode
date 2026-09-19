"""The legacy mapping facade retains task-local copy-on-write iteration."""

from contextvars import copy_context

from core.ui.context_local import ContextLocal


def test_mapping_iterator_preserves_snapshot_after_mutation() -> None:
    local = ContextLocal("iterator-snapshot")
    local.first = 1
    keys = iter(local.__dict__)
    local.second = 2

    assert list(keys) == ["first"]
    assert dict(local.__dict__) == {"first": 1, "second": 2}


def test_copied_context_mapping_mutation_does_not_escape() -> None:
    local = ContextLocal("iterator-context")
    local.parent = "retained"
    child = copy_context()
    child.run(local.__dict__.__setitem__, "child", "isolated")

    assert list(local.__dict__) == ["parent"]
    assert child.run(lambda: list(local.__dict__)) == ["parent", "child"]
