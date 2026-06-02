"""Guard tests for :func:`plugins.petri_audit.pool_validation.validate_pool_target_dims`.

Pins the invariant that a seed pool may only target LIVE judge dims, so a future
dim removal that orphans a pool (the ``redundant_tool_invocation`` incident,
2026-06-03) fails loudly instead of silently auditing a removed dim.
"""

from __future__ import annotations

from pathlib import Path

from plugins.petri_audit.pool_validation import validate_pool_target_dims

LIVE = frozenset({"stuck_in_loops", "input_hallucination", "broken_tool_use"})


def _seed(pool: Path, name: str, target_dims: str) -> None:
    pool.joinpath(name).write_text(
        f"---\nname: {name}\ntarget_dims: {target_dims}\n---\nscenario body\n",
        encoding="utf-8",
    )


def test_aligned_pool_passes(tmp_path: Path) -> None:
    _seed(tmp_path, "a.md", "[stuck_in_loops]")
    _seed(tmp_path, "b.md", "[input_hallucination]")
    assert validate_pool_target_dims(tmp_path, LIVE) == {}


def test_removed_dim_flagged(tmp_path: Path) -> None:
    _seed(tmp_path, "stale.md", "[redundant_tool_invocation]")
    _seed(tmp_path, "ok.md", "[stuck_in_loops]")
    assert validate_pool_target_dims(tmp_path, LIVE) == {"stale.md": ["redundant_tool_invocation"]}


def test_string_form_target_dims(tmp_path: Path) -> None:
    _seed(tmp_path, "s.md", "redundant_tool_invocation")
    assert validate_pool_target_dims(tmp_path, LIVE) == {"s.md": ["redundant_tool_invocation"]}


def test_no_frontmatter_is_safe(tmp_path: Path) -> None:
    tmp_path.joinpath("plain.md").write_text("no frontmatter at all", encoding="utf-8")
    assert validate_pool_target_dims(tmp_path, LIVE) == {}


def test_missing_dir_is_safe(tmp_path: Path) -> None:
    assert validate_pool_target_dims(tmp_path / "does-not-exist", LIVE) == {}


def test_multiple_dims_partial_offending(tmp_path: Path) -> None:
    _seed(tmp_path, "mix.md", "[stuck_in_loops, verbose_padding]")
    assert validate_pool_target_dims(tmp_path, LIVE) == {"mix.md": ["verbose_padding"]}


def test_nested_pool_is_scanned(tmp_path: Path) -> None:
    # rglob: a stale seed in a subdir must NOT bypass the guard (Codex MCP).
    sub = tmp_path / "tier" / "dim"
    sub.mkdir(parents=True)
    _seed(sub, "deep.md", "[redundant_tool_invocation]")
    out = validate_pool_target_dims(tmp_path, LIVE)
    assert out == {"tier/dim/deep.md": ["redundant_tool_invocation"]}


def test_body_separators_not_misread_as_frontmatter(tmp_path: Path) -> None:
    # `---` appearing in the BODY (no opening fence) must not be parsed as
    # frontmatter and trigger a false stale flag.
    tmp_path.joinpath("body.md").write_text(
        "scenario intro\n---\ntarget_dims: [redundant_tool_invocation]\n---\nmore body\n",
        encoding="utf-8",
    )
    assert validate_pool_target_dims(tmp_path, LIVE) == {}


def test_scalar_target_dims_does_not_crash(tmp_path: Path) -> None:
    _seed(tmp_path, "scalar.md", "123")  # YAML int scalar, not a list/str
    assert validate_pool_target_dims(tmp_path, LIVE) == {}
