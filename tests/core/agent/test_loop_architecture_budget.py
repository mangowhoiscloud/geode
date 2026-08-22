"""R3.3 structural budgets for the production loop coordinator."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOOP = ROOT / "core/agent/loop/agent_loop.py"


def test_agentic_loop_stays_within_structural_budget() -> None:
    tree = ast.parse(LOOP.read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AgenticLoop"
    )
    methods = [
        node for node in cls.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    init = next(node for node in methods if node.name == "__init__")
    args = [*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs][1:]

    assert len(LOOP.read_text(encoding="utf-8").splitlines()) <= 1600
    assert len(methods) <= 40
    assert len(args) <= 12


def test_loop_collaborators_stay_within_ruff_budget() -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and module
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "core/agent/loop",
            "--select",
            "C901,PLR0912,PLR0915",
            "--config",
            "lint.mccabe.max-complexity=30",
            "--config",
            "lint.pylint.max-branches=35",
            "--config",
            "lint.pylint.max-statements=120",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
