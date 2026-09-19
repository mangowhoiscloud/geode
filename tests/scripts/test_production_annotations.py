"""Ruff enforces explicit production signatures without relaxing baseline rules."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[2] / "ruff-production.toml"


def _check(source: str) -> tuple[int, set[str]]:
    executable = shutil.which("ruff")
    assert executable is not None, "Run inside the locked development environment"
    result = subprocess.run(  # noqa: S603 -- fixed Ruff command from the development environment
        [
            executable,
            "check",
            "--config",
            str(CONFIG),
            "--output-format",
            "json",
            "--stdin-filename",
            "core/annotation_contract_probe.py",
            "-",
        ],
        input=source,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode in {0, 1}, result.stderr
    return result.returncode, {entry["code"] for entry in json.loads(result.stdout)}


@pytest.mark.parametrize(
    "source,code",
    [
        (
            "class Example:\n    def __init__(self, value: str):\n        self.value = value\n",
            "ANN204",
        ),
        ("def echo(value) -> str:\n    return str(value)\n", "ANN001"),
        ("def _answer():\n    return 42\n", "ANN202"),
        ("import os\n", "F401"),
    ],
)
def test_missing_annotations_and_existing_rules_block(source: str, code: str) -> None:
    exit_code, codes = _check(source)
    assert exit_code == 1
    assert code in codes


def test_annotated_constructor_passes() -> None:
    assert _check(
        "class Example:\n    def __init__(self, value: str) -> None:\n        self.value = value\n"
    ) == (0, set())
