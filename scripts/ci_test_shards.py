"""Partition pytest's collected items by file and verify all CI shard evidence.

Loaded with ``pytest -p scripts.ci_test_shards``; ordinary pytest collection
remains authoritative, including custom collectors and marker selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from coverage import CoverageData

_COLLECTION = pytest.StashKey[dict[str, str]]()


def file_shard(path: str, count: int) -> int:
    return int.from_bytes(hashlib.sha256(path.encode()).digest()[:8], "big") % count


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("ci-shards")
    group.addoption("--ci-shard", type=int)
    group.addoption("--ci-shards", type=int, default=4)
    group.addoption("--ci-shard-output", type=Path)


def pytest_configure(config: pytest.Config) -> None:
    index = config.getoption("ci_shard")
    if index is None:
        return
    count = config.getoption("ci_shards")
    if not 0 <= index < count or config.getoption("ci_shard_output") is None:
        raise pytest.UsageError("CI shard needs 0 <= index < count and an output directory")
    config.getoption("ci_shard_output").mkdir(parents=True, exist_ok=True)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> Iterator[None]:
    # Run after the normal selection hooks, including the existing not-live rule.
    yield
    index = config.getoption("ci_shard")
    if index is None:
        return
    count = config.getoption("ci_shards")
    collected = {item.nodeid: item.path.relative_to(config.rootpath).as_posix() for item in items}
    if len(collected) != len(items):
        raise pytest.UsageError("CI collection contains duplicate node IDs")
    config.stash[_COLLECTION] = collected
    selected = [item for item in items if file_shard(collected[item.nodeid], count) == index]
    selected_ids = {item.nodeid for item in selected}
    config.hook.pytest_deselected(items=[item for item in items if item.nodeid not in selected_ids])
    items[:] = selected


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    if _COLLECTION not in config.stash:
        return
    worker = getattr(config, "workerinput", {}).get("workerid", "main")
    output = config.getoption("ci_shard_output") / f"collection-{worker}.json"
    output.write_text(
        json.dumps(
            {
                "collected": config.stash[_COLLECTION],
                "selected": [item.nodeid for item in session.items],
            }
        )
        + "\n"
    )


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_sessionfinish(session: pytest.Session) -> Iterator[None]:
    yield
    config = session.config
    index = config.getoption("ci_shard")
    if index is None or hasattr(config, "workerinput"):
        return
    output = config.getoption("ci_shard_output") / "result.json"
    output.write_text(
        json.dumps(
            {
                "index": index,
                "count": config.getoption("ci_shards"),
                "exit_code": session.exitstatus,
            }
        )
        + "\n"
    )


def verify_shards(root: Path, count: int = 4) -> int:
    """Reject incomplete runs before coverage combine can ignore missing data."""
    expected_dirs = {f"test-shard-{index}" for index in range(count)}
    if {path.name for path in root.iterdir()} != expected_dirs:
        raise ValueError("Missing or unexpected shard artifacts")
    complete: dict[str, str] | None = None
    union: set[str] = set()
    for index in range(count):
        directory = root / f"test-shard-{index}"
        result = json.loads((directory / "result.json").read_text())
        if result != {"index": index, "count": count, "exit_code": 0} or any(
            type(value) is not int for value in result.values()
        ):
            raise ValueError(f"Shard {index} did not finish successfully")
        manifests = sorted(directory.glob("collection-*.json"))
        if not manifests:
            raise ValueError(f"Shard {index} has no pytest collection evidence")
        selected: set[str] | None = None
        for path in manifests:
            manifest = json.loads(path.read_text())
            collected = manifest["collected"]
            if (
                not isinstance(collected, dict)
                or not collected
                or any(
                    not isinstance(key, str) or not isinstance(value, str)
                    for key, value in collected.items()
                )
            ):
                raise ValueError("Invalid pytest collection evidence")
            if complete is None:
                complete = collected
            if collected != complete:
                raise ValueError("Shard workers disagree on the full pytest collection")
            assigned = manifest["selected"]
            if not isinstance(assigned, list) or any(
                not isinstance(item, str) for item in assigned
            ):
                raise ValueError("Invalid selected node IDs")
            expected = {
                node for node, file in collected.items() if file_shard(file, count) == index
            }
            if not expected or set(assigned) != expected or len(assigned) != len(expected):
                raise ValueError(f"Shard {index} omitted, duplicated, or misassigned tests")
            if selected is not None and selected != expected:
                raise ValueError("Shard workers disagree on selected tests")
            selected = expected
        assert selected is not None
        if union & selected:
            raise ValueError("Shard selections overlap")
        union.update(selected)
        coverage_path = directory / f".coverage.{index}"
        if not coverage_path.is_file():
            raise ValueError(f"Shard {index} has no coverage data")
        data = CoverageData(basename=str(coverage_path))
        data.read()
        if not data.has_arcs() or not data.measured_files():
            raise ValueError(f"Shard {index} has no branch coverage data")
    if complete is None or union != set(complete):
        raise ValueError("Shard union differs from the full pytest collection")
    print(f"Verified {len(union)} pytest node IDs across {count} disjoint file shards")
    return len(union)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    args = parser.parse_args()
    verify_shards(args.artifacts)


if __name__ == "__main__":
    main()
