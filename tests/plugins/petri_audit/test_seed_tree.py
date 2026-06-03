"""Tests for ``plugins.petri_audit.seed_tree`` — hierarchical → flat stage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from plugins.petri_audit.seed_tree import (
    flatten_for_inspect_petri,
    is_hierarchical_seed_tree,
)


def test_is_hierarchical_seed_tree_flat_dir_returns_false(tmp_path: Path) -> None:
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "seed_a.md").write_text("x", encoding="utf-8")
    assert is_hierarchical_seed_tree(flat) is False


def test_is_hierarchical_seed_tree_missing_one_tier_returns_false(tmp_path: Path) -> None:
    tree = tmp_path / "partial"
    (tree / "critical").mkdir(parents=True)
    (tree / "auxiliary").mkdir(parents=True)
    # missing info/
    assert is_hierarchical_seed_tree(tree) is False


def test_is_hierarchical_seed_tree_all_three_tiers_returns_true(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    (tree / "critical").mkdir(parents=True)
    (tree / "auxiliary").mkdir(parents=True)
    (tree / "info").mkdir(parents=True)
    assert is_hierarchical_seed_tree(tree) is True


def test_is_hierarchical_seed_tree_nonexistent_returns_false(tmp_path: Path) -> None:
    assert is_hierarchical_seed_tree(tmp_path / "nope") is False


def test_flatten_for_inspect_petri_flat_dir_returns_unchanged(tmp_path: Path) -> None:
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "seed_a.md").write_text("x", encoding="utf-8")
    out = flatten_for_inspect_petri(flat)
    assert out.resolve() == flat.resolve()


def test_flatten_for_inspect_petri_hierarchical_creates_stage(
    tmp_path: Path, monkeypatch: object
) -> None:
    """Hierarchical tree → stage dir with symlinks/copies for every .md."""
    tree = tmp_path / "tree"
    (tree / "critical" / "broken_tool_use").mkdir(parents=True)
    (tree / "critical" / "broken_tool_use" / "01_base.md").write_text("a", encoding="utf-8")
    (tree / "auxiliary" / "overrefusal").mkdir(parents=True)
    (tree / "auxiliary" / "overrefusal" / "02_paraphrase.md").write_text("b", encoding="utf-8")
    (tree / "info").mkdir()

    stage_root = tmp_path / "stage_root"
    # Redirect GEODE_HOME to a tmp path so the test doesn't write to ~/.geode/
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        out = flatten_for_inspect_petri(tree)

    assert out.is_dir()
    md_files = list(out.iterdir())
    assert len(md_files) == 2
    names = sorted(p.name for p in md_files)
    assert names == [
        "auxiliary__overrefusal__02_paraphrase.md",
        "critical__broken_tool_use__01_base.md",
    ]


def test_flatten_for_inspect_petri_idempotent(tmp_path: Path, monkeypatch: object) -> None:
    """Repeated calls reuse the same stage dir (content-addressed hash)."""
    tree = tmp_path / "tree"
    (tree / "critical" / "broken_tool_use").mkdir(parents=True)
    (tree / "critical" / "broken_tool_use" / "01_base.md").write_text("x", encoding="utf-8")
    (tree / "auxiliary").mkdir()
    (tree / "info").mkdir()

    stage_root = tmp_path / "stage_root"
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        out1 = flatten_for_inspect_petri(tree)
        out2 = flatten_for_inspect_petri(tree)
    assert out1 == out2


def test_flatten_for_inspect_petri_symlink_content_preserved(
    tmp_path: Path, monkeypatch: object
) -> None:
    """The flat-dir entry must surface the original file contents (via symlink)."""
    tree = tmp_path / "tree"
    (tree / "critical" / "broken_tool_use").mkdir(parents=True)
    seed_body = "# seed body\nthis is the original content"
    (tree / "critical" / "broken_tool_use" / "01_base.md").write_text(seed_body, encoding="utf-8")
    (tree / "auxiliary").mkdir()
    (tree / "info").mkdir()

    stage_root = tmp_path / "stage_root"
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        out = flatten_for_inspect_petri(tree)
    target = out / "critical__broken_tool_use__01_base.md"
    assert target.read_text(encoding="utf-8") == seed_body


# ── single .md staging (project_seedgen_pilot_seed_delivery_bug) ──────────────


def test_flatten_single_md_stages_n_copies(tmp_path: Path, monkeypatch: object) -> None:
    """A lone candidate .md is staged into a directory of `samples` distinct
    copies (so inspect-petri's directory loader reads it as N real seeds,
    instead of splitlines-shredding the lone file into empty seeds)."""
    cand = tmp_path / "cand.md"
    cand.write_text("---\nname: c\n---\nscenario body", encoding="utf-8")
    stage_root = tmp_path / "stage_root"
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        out = flatten_for_inspect_petri(cand, samples=3)
    assert isinstance(out, Path) and out.is_dir()
    mds = sorted(p.name for p in out.glob("*.md"))
    assert mds == ["cand__s1.md", "cand__s2.md", "cand__s3.md"]
    # Every copy preserves the candidate body verbatim.
    for p in out.glob("*.md"):
        assert p.read_text(encoding="utf-8") == "---\nname: c\n---\nscenario body"


def test_flatten_single_md_default_one_copy(tmp_path: Path, monkeypatch: object) -> None:
    cand = tmp_path / "cand.md"
    cand.write_text("body", encoding="utf-8")
    stage_root = tmp_path / "stage_root"
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        out = flatten_for_inspect_petri(cand)  # samples defaults to 1
    assert isinstance(out, Path) and out.is_dir()
    assert [p.name for p in out.glob("*.md")] == ["cand__s1.md"]


def test_flatten_single_md_idempotent(tmp_path: Path, monkeypatch: object) -> None:
    cand = tmp_path / "cand.md"
    cand.write_text("body", encoding="utf-8")
    stage_root = tmp_path / "stage_root"
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        out1 = flatten_for_inspect_petri(cand, samples=2)
        out2 = flatten_for_inspect_petri(cand, samples=2)
    assert out1 == out2  # content-addressed → same stage reused


def test_flatten_single_md_distinct_stage_per_sample_count(
    tmp_path: Path, monkeypatch: object
) -> None:
    cand = tmp_path / "cand.md"
    cand.write_text("body", encoding="utf-8")
    stage_root = tmp_path / "stage_root"
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        out2 = flatten_for_inspect_petri(cand, samples=2)
        out3 = flatten_for_inspect_petri(cand, samples=3)
    assert out2 != out3  # the copy count is part of the content address
