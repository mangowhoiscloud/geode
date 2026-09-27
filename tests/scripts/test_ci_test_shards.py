"""Real pytest/xdist collection, exit, and coverage evidence for the CI reducer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from coverage import CoverageData
from coverage.exceptions import DataError
from scripts.ci_test_shards import verify_shards

ROOT = Path(__file__).resolve().parents[2]


def _pytest(
    root: Path, output: Path, index: int, count: int = 4
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - isolated synthetic tests, no external services
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-c",
            str(root / "pytest.ini"),
            f"--rootdir={root}",
            "-p",
            "pytest_cov",
            "-p",
            "xdist.plugin",
            "-p",
            "scripts.ci_test_shards",
            "--ci-shard",
            str(index),
            "--ci-shards",
            str(count),
            "--ci-shard-output",
            str(output),
            "-n",
            "2",
            "--dist=loadfile",
            "--cov=demo",
            "--cov-report=",
            "--cov-fail-under=0",
        ],
        cwd=root,
        env=os.environ
        | {
            "PYTHONPATH": str(ROOT) + os.pathsep + str(root),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "COVERAGE_FILE": str(output / f".coverage.{index}"),
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def completed_shards(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("real-pytest-shards")
    (root / "pytest.ini").write_text(
        "[pytest]\npython_files = case_*.py\naddopts = -m 'not live'\nmarkers = live: online\n"
    )
    (root / ".coveragerc").write_text("[run]\nbranch = true\n[report]\nfail_under = 75\n")
    (root / "demo.py").write_text(
        "def value(flag):\n    if flag:\n        return 1\n    return 0\n"
    )
    (root / "helper.py").write_text("raise AssertionError('helper is not a test file')\n")
    for index in range(16):
        (root / f"case_{index}.py").write_text(
            "import pytest\nfrom demo import value\n"
            "@pytest.mark.parametrize('flag', [True, False])\n"
            "def test_value(flag):\n    assert value(flag) == int(flag)\n"
            "@pytest.mark.live\ndef test_online():\n    raise AssertionError('must remain excluded')\n"
        )
    (root / "conftest.py").write_text(
        "import pytest\n"
        "class SpecFile(pytest.File):\n"
        "    def collect(self):\n        yield SpecItem.from_parent(self, name='custom')\n"
        "class SpecItem(pytest.Item):\n"
        "    def runtest(self):\n        from demo import value\n        assert value(True) == 1\n"
        "def pytest_collect_file(file_path, parent):\n"
        "    if file_path.suffix == '.spec':\n"
        "        return SpecFile.from_parent(parent, path=file_path)\n"
    )
    (root / "example.spec").write_text("custom pytest collector\n")
    artifacts = tmp_path_factory.mktemp("external-shard-artifacts")
    for index in range(4):
        result = _pytest(root, artifacts / f"test-shard-{index}", index)
        assert result.returncode == 0, result.stdout + result.stderr
    return root, artifacts


def test_real_pytest_collection_partition_and_coverage(
    completed_shards: tuple[Path, Path],
) -> None:
    _, artifacts = completed_shards
    assert verify_shards(artifacts) == 33
    manifests = list(artifacts.glob("*/collection-*.json"))
    assert len(manifests) == 8  # Every real xdist worker supplies its own collection.
    full = json.loads(manifests[0].read_text())["collected"]
    assert "example.spec::custom" in full
    assert not any("test_online" in node or "helper.py" in node for node in full)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_shard",
        "failed",
        "missing_collection",
        "missing_coverage",
        "corrupt_coverage",
        "missing_test",
        "duplicate_test",
        "changed_collection",
        "wrong_shard",
    ],
)
def test_reducer_rejects_incomplete_evidence(
    completed_shards: tuple[Path, Path], tmp_path: Path, damage: str
) -> None:
    artifacts = tmp_path / "artifacts"
    shutil.copytree(completed_shards[1], artifacts)
    directory = artifacts / "test-shard-0"
    manifest_path = next(directory.glob("collection-*.json"))
    manifest = json.loads(manifest_path.read_text())
    if damage == "missing_shard":
        shutil.rmtree(directory)
    elif damage == "failed":
        (directory / "result.json").write_text('{"index": 0, "count": 4, "exit_code": 1}')
    elif damage == "missing_collection":
        for path in directory.glob("collection-*.json"):
            path.unlink()
    elif damage == "missing_coverage":
        (directory / ".coverage.0").unlink()
    elif damage == "corrupt_coverage":
        (directory / ".coverage.0").write_text("not coverage data")
    else:
        if damage == "missing_test":
            manifest["selected"].pop()
        elif damage == "duplicate_test":
            manifest["selected"].append(manifest["selected"][0])
        elif damage == "changed_collection":
            manifest["collected"].pop(next(iter(manifest["collected"])))
        else:
            manifest["selected"].append(
                next(node for node in manifest["collected"] if node not in manifest["selected"])
            )
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DataError if damage == "corrupt_coverage" else ValueError):
        verify_shards(artifacts)


def test_real_pytest_failure_keeps_nonzero_result(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "demo.py").write_text("value = False\n")
    (tmp_path / "test_failure.py").write_text(
        "from demo import value\ndef test_bad():\n    assert value\n"
    )
    output = tmp_path / "result"
    result = _pytest(tmp_path, output, 0, count=1)
    assert result.returncode == 1
    assert json.loads((output / "result.json").read_text())["exit_code"] == 1


def test_combined_report_preserves_coverage_threshold(
    completed_shards: tuple[Path, Path], tmp_path: Path
) -> None:
    source, artifacts = completed_shards
    data_file = tmp_path / ".coverage"
    config = source / ".coveragerc"
    command = [sys.executable, "-m", "coverage"]
    combined = subprocess.run(  # noqa: S603 - existing coverage CLI, synthetic measured files
        [
            *command,
            "combine",
            "--keep",
            "--data-file",
            str(data_file),
            *(str(path) for path in sorted(artifacts.iterdir())),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert combined.returncode == 0, combined.stdout + combined.stderr
    report = [*command, "report", "--rcfile", str(config), "--data-file", str(data_file)]
    good = subprocess.run(report, capture_output=True, text=True, check=False)  # noqa: S603
    assert good.returncode == 0, good.stdout + good.stderr
    assert "100%" in good.stdout
    data = CoverageData(basename=str(data_file))
    data.erase()
    data.add_arcs({str(source / "demo.py"): [(-1, 1)]})
    data.write()
    low = subprocess.run(report, capture_output=True, text=True, check=False)  # noqa: S603
    assert low.returncode == 2
    assert "fail-under=75" in low.stdout
