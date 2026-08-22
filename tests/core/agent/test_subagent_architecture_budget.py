"""R3.4 structural budget for the sub-agent orchestrator."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANAGER = ROOT / "core/agent/sub_agent.py"


def test_subagent_manager_stays_within_structural_budget() -> None:
    source = MANAGER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SubAgentManager"
    )
    methods = [
        node for node in cls.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    init = next(node for node in methods if node.name == "__init__")
    args = [*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs][1:]

    assert len(source.splitlines()) <= 900
    assert len(methods) <= 18
    assert len(args) <= 18
