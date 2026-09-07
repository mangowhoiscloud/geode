"""Mode A operator entry, current authorities, and bounded execution contracts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from core.paths import MUTATION_AUDIT_LOG_PATH
from evolve.scaffold_search.loop.mutate.policies import TARGET_KINDS, policy_path

_DOC = Path(__file__).resolve().parents[2] / "docs" / "operator-mode-a.md"


def _read_mode_a_doc() -> str:
    assert _DOC.is_file(), (
        "docs/operator-mode-a.md must exist on disk so Mode A operators "
        "have a written boot recipe (PR-C6 closes the documentation gap)."
    )
    return _DOC.read_text(encoding="utf-8")


def _read_linked_doc(relative_path: str) -> str:
    assert f"]({relative_path})" in _read_mode_a_doc()
    target = (_DOC.parent / relative_path).resolve()
    assert target.is_file(), f"Missing operator reference: {relative_path}"
    return target.read_text(encoding="utf-8")


def test_mode_a_doc_exists() -> None:
    text = _read_mode_a_doc()
    assert "Mode A" in text
    assert "Mode B" in text
    overview = _read_linked_doc("self-improving/loop-overview.md")
    assert "https://github.com/karpathy/autoresearch" in overview


def test_mode_a_doc_routes_to_current_policy_scope() -> None:
    program = _read_linked_doc("../evolve/scaffold_search/program.md")
    documented = dict(re.findall(r"^\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+\.json)`\s*\|", program, re.M))
    assert documented == {kind: policy_path(kind).name for kind in TARGET_KINDS}
    assert not {"retrieval", "hyperparam"} & documented.keys()


def test_mode_a_doc_gives_external_operators_one_authorized_recipe() -> None:
    text = " ".join(_read_mode_a_doc().split())
    assert "Claude Code" in text
    assert "Codex" in text
    assert "separately authorized" in text
    assert "frozen run contract" in text


def test_mode_a_doc_cross_references_design_doc() -> None:
    _read_linked_doc("plans/2026-05-21-self-improving-loop-ux.md")
    text = _read_mode_a_doc()
    assert "historical" in text
    assert "not current commands" in text


def test_mode_a_doc_references_wired_mode_b_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolve.cli import app
    from evolve.scaffold_search import cli_commands
    from evolve.slash_commands import EVOLVE_COMMAND_SPECS
    from typer.testing import CliRunner

    text = _read_mode_a_doc()
    spec = next(spec for spec in EVOLVE_COMMAND_SPECS if spec.name == "/self-improving")
    assert f"`{app.info.name} scaffold run`" in text
    assert f"`{spec.name} run`" in text
    handler = cli_commands.cmd_self_improving
    assert spec.handler_path == f"{handler.__module__}:{handler.__name__}"
    calls: list[list[str]] = []
    monkeypatch.setattr(cli_commands, "_cmd_run", lambda opts: calls.append(opts))
    result = CliRunner().invoke(app, ["scaffold", "run"])
    assert result.exit_code == 0, result.output
    assert calls == [[]]


def test_mode_a_doc_routes_to_mutation_history_and_preserves_it() -> None:
    campaign = _read_linked_doc("self-improving/campaign-procedure.md")
    assert MUTATION_AUDIT_LOG_PATH.name in campaign
    text = " ".join(_read_mode_a_doc().split())
    assert "preserve the rejected attempt" in text
    assert "Do not discard unrelated edits or erase a ledger" in text


def test_mode_a_doc_lists_program_md_recipe() -> None:
    program = " ".join(_read_linked_doc("../evolve/scaffold_search/program.md").split())
    assert "compatible baseline" in program
    assert "Do not delete a prior baseline" in program
    text = " ".join(_read_mode_a_doc().split())
    assert "owned worktree" in text
    assert "authorized experiment budget" in text
