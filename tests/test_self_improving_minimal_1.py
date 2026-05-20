"""PR-MINIMAL-1 invariants — slash polish + DONT-table guardrail.

Pins:
- ``/self-improving history`` prints git log recipes (B1)
- ``/self-improving rollback`` prints git revert recipes (B2)
- ``/self-improving rollback <mutation_id>`` includes the grep form
- ``_load_program_md`` actually reads ``autoresearch/program.md``
  from disk (H4 regression guard for the PR-G5b incident in the
  CLAUDE.md DONT table)
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# B1 — ``/self-improving history`` delegates to git log
# ---------------------------------------------------------------------------


def test_history_action_prints_git_log_recipes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The action must point at ``git log`` over the mutation ledger
    + the policies dir, NOT print a deferred-design-doc pointer.
    PR-RATCHET-1 made both git-tracked so this delegation is now
    valid; PR-MINIMAL-1 wires the slash to that path."""
    from core.cli.commands.self_improving import cmd_self_improving

    cmd_self_improving("history")
    out = capsys.readouterr().out
    # NOT deferred any more
    assert "reserved for" not in out
    # Recipes present
    assert "git log -p autoresearch/state/mutations.jsonl" in out
    assert "git log --stat autoresearch/state/policies/" in out
    # Cross-reference back to status for the quick path
    assert "/self-improving status" in out


# ---------------------------------------------------------------------------
# B2 — ``/self-improving rollback`` delegates to git revert
# ---------------------------------------------------------------------------


def test_rollback_action_prints_git_revert_recipes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bare ``/self-improving rollback`` must point at ``git log``
    (to find the SHA) and ``git revert <sha>`` (to undo)."""
    from core.cli.commands.self_improving import cmd_self_improving

    cmd_self_improving("rollback")
    out = capsys.readouterr().out
    assert "git log --oneline -p autoresearch/state/mutations.jsonl" in out
    assert "git revert <sha>" in out
    # Hints the parametrized form
    assert "/self-improving rollback <mutation_id>" in out


def test_rollback_with_mutation_id_uses_grep_form(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``/self-improving rollback <mutation_id>`` must use the
    ``git log --grep=<id>`` form so the operator can find the commit
    that applied that specific mutation without scrolling."""
    from core.cli.commands.self_improving import cmd_self_improving

    cmd_self_improving("rollback mut-abc12345")
    out = capsys.readouterr().out
    assert "'mut-abc12345'" in out
    assert "git log --all --grep=" in out
    assert "autoresearch/state/mutations.jsonl" in out


# ---------------------------------------------------------------------------
# Dispatcher — KNOWN_ACTIONS includes history/rollback
# ---------------------------------------------------------------------------


def test_known_actions_includes_history_and_rollback() -> None:
    """Pin that the public-action set lists the now-wired
    ``history`` + ``rollback`` so the help-line and unknown-action
    fallback both stay in sync."""
    from core.cli.commands.self_improving import _KNOWN_ACTIONS

    assert "history" in _KNOWN_ACTIONS
    assert "rollback" in _KNOWN_ACTIONS
    assert "status" in _KNOWN_ACTIONS
    assert "run" in _KNOWN_ACTIONS


def test_unknown_action_help_line_lists_history_and_rollback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bogus action → help line must include ``history`` /
    ``rollback`` in the "Available now" group."""
    from core.cli.commands.self_improving import cmd_self_improving

    cmd_self_improving("nonsense")
    out = capsys.readouterr().out
    assert "Available now" in out
    assert "history" in out
    assert "rollback" in out


# ---------------------------------------------------------------------------
# H4 — _load_program_md regression guard
# ---------------------------------------------------------------------------


def test_load_program_md_actually_reads_disk_file() -> None:
    """CLAUDE.md DONT table 2026-05-20 PR-G5b #1350 row:
    ``_SYSTEM_PROMPT`` was a hardcoded f-string while the PR title
    claimed "program.md-driven". The G5b.fix1.b commit introduced
    ``_load_program_md`` which actually reads
    ``autoresearch/program.md``. Pin that behavior so a future
    refactor that regresses to hardcoded prompts surfaces here.
    """
    from core.self_improving_loop import runner as runner_mod

    content = runner_mod._load_program_md()
    assert content is not None, "program.md should be readable from disk"
    # Content sanity — these phrases come from autoresearch/program.md
    # body (per the README + module docstring).
    assert "autoresearch" in content.lower()
    assert "self-improving" in content.lower() or "self improving" in content.lower()


def test_build_system_prompt_includes_program_md_content() -> None:
    """The system prompt the mutator LLM actually sees must include
    the ``program.md`` body — otherwise the "program.md-driven" claim
    is fiction. Picks a phrase grep-provable from program.md."""
    from core.self_improving_loop import runner as runner_mod

    program_md = runner_mod._load_program_md()
    assert program_md is not None
    # Pick a stable phrase from program.md to look for in the prompt.
    # The Setup section header is the most stable anchor across edits.
    needle = "Setup" if "Setup" in program_md else program_md.strip().splitlines()[0]
    prompt = runner_mod._build_system_prompt()
    assert needle in prompt, (
        f"_build_system_prompt must splice in program.md body — "
        f"needle {needle!r} not found in built prompt"
    )
