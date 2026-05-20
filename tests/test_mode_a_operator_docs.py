"""PR-C6 — Mode A operator docs presence + cross-reference invariants.

Pins:
- ``docs/operator-mode-a.md`` exists on disk (git-tracked under docs/).
- Doc references all 5 in-repo SoT policy files.
- Doc references both boot recipes (Claude Code + Codex CLI).
- Doc cross-references the design doc (2026-05-21-self-improving-loop-ux.md).
- Doc compares Mode A vs Mode B with the matching slash command.
"""

from __future__ import annotations

from pathlib import Path


def _read_mode_a_doc() -> str:
    repo_root = Path(__file__).resolve().parent.parent
    doc = repo_root / "docs" / "operator-mode-a.md"
    assert doc.is_file(), (
        "docs/operator-mode-a.md must exist on disk so Mode A operators "
        "have a written boot recipe (PR-C6 closes the documentation gap)."
    )
    return doc.read_text(encoding="utf-8")


def test_mode_a_doc_exists() -> None:
    text = _read_mode_a_doc()
    assert "Mode A" in text
    assert "Karpathy" in text


def test_mode_a_doc_references_all_5_policy_sots() -> None:
    """The 5-kind policy table (PR-MINIMAL-2 C5) lists wrapper-sections /
    tool-policy / decomposition / retrieval / reflection. Mode A
    operators need to know which files they can edit; pin that the
    doc surfaces all five so a refactor that adds / drops a kind
    forces a docs update."""
    text = _read_mode_a_doc()
    for filename in (
        "wrapper-sections.json",
        "tool-policy.json",
        "decomposition.json",
        "retrieval.json",
        "reflection.json",
    ):
        assert filename in text, f"docs/operator-mode-a.md must list {filename}"


def test_mode_a_doc_references_both_boot_recipes() -> None:
    """Doc covers Claude Code AND Codex CLI boot. Both clients are
    valid Mode A entry points."""
    text = _read_mode_a_doc()
    assert "Claude Code" in text
    assert "Codex CLI" in text


def test_mode_a_doc_cross_references_design_doc() -> None:
    """The design doc carries the canonical Mode A vs Mode B matrix.
    Pin the cross-reference so an operator who lands on operator-mode-a.md
    can find the full design."""
    text = _read_mode_a_doc()
    assert "docs/plans/2026-05-21-self-improving-loop-ux.md" in text


def test_mode_a_doc_compares_to_slash_run() -> None:
    """Pin the Mode B slash entry point reference so the doc explains
    the choice point between Mode A and Mode B."""
    text = _read_mode_a_doc()
    assert "/self-improving run" in text


def test_mode_a_doc_references_mutations_jsonl_ledger() -> None:
    """Pin that the doc mentions the shared audit ledger — Mode A and
    Mode B both write to the same git-tracked mutations.jsonl."""
    text = _read_mode_a_doc()
    assert "mutations.jsonl" in text


def test_mode_a_doc_lists_program_md_recipe() -> None:
    """Pin the canonical boot prompt (Karpathy minimal idiom)."""
    text = _read_mode_a_doc()
    assert "program.md" in text
    assert "Begin with the baseline" in text
