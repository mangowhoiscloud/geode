"""PR-MUTATION-CODE-FOUNDATION (Phase 3.0) — code-mutation safety invariants.

Pins the path whitelist + EVOLVE-BLOCK scanner that gate the upcoming
``target_kind="plugin_impl"`` apply path. Layer-1 (path whitelist) ships
first as the absolute floor; layer-2 (EVOLVE-BLOCK) lights up in Phase 4
when ``core/agent/loop/`` becomes mutable. These tests pin both layers
now so PR 3.1 (wiring) can rely on the invariants.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.self_improving_loop.code_mutation_whitelist import (
    EVOLVE_BLOCK_END_MARKER,
    EVOLVE_BLOCK_START_MARKER,
    MutationPathDeniedError,
    find_evolve_blocks,
    is_path_allowed,
    validate_diff_paths,
    validate_plugin_impl_target,
)

# ---------------------------------------------------------------------------
# validate_plugin_impl_target — snake_case + reserved-name guards
# ---------------------------------------------------------------------------


def test_validate_plugin_impl_target_accepts_fresh_snake_case() -> None:
    """A fresh snake_case name resolves to ``plugins/<name>/``."""
    assert validate_plugin_impl_target("new_optimizer") == Path("plugins/new_optimizer")
    assert validate_plugin_impl_target("a") == Path("plugins/a")
    assert validate_plugin_impl_target("name_with_digits9") == Path("plugins/name_with_digits9")


@pytest.mark.parametrize(
    "bad",
    [
        "CamelCase",
        "kebab-case",
        "with space",
        "../traversal",
        "plugins/nested",
        "9_leading_digit",
        "",
        "_leading_underscore",
        "trailing/",
    ],
)
def test_validate_plugin_impl_target_rejects_non_snake_case(bad: str) -> None:
    """Anything that isn't ``[a-z][a-z0-9_]*`` is denied — defends against
    path-traversal-shaped section names."""
    with pytest.raises(MutationPathDeniedError):
        validate_plugin_impl_target(bad)


def test_validate_plugin_impl_target_rejects_reserved_names() -> None:
    """Existing plugins are frozen at the plugin_impl scope — the LLM
    cannot pick ``petri_audit`` / ``seed_generation`` as its target."""
    for reserved in ("petri_audit", "seed_generation"):
        with pytest.raises(MutationPathDeniedError) as exc_info:
            validate_plugin_impl_target(reserved)
        assert reserved in str(exc_info.value)


# ---------------------------------------------------------------------------
# is_path_allowed — allowlist prefixes only
# ---------------------------------------------------------------------------


def test_is_path_allowed_accepts_plugin_directory() -> None:
    """Any path under ``plugins/<target_section>/`` is allowed."""
    assert is_path_allowed("plugins/foo/runner.py", "foo") is True
    assert is_path_allowed("plugins/foo/sub/nested.py", "foo") is True
    assert is_path_allowed("plugins/foo/__init__.py", "foo") is True


def test_is_path_allowed_accepts_parallel_tests_directory() -> None:
    """Tests for the new plugin live in ``tests/plugins/<target_section>/``."""
    assert is_path_allowed("tests/plugins/foo/test_runner.py", "foo") is True
    assert is_path_allowed("tests/plugins/foo/conftest.py", "foo") is True


@pytest.mark.parametrize(
    "denied",
    [
        # Orchestrator / harness
        "core/agent/loop/agent_loop.py",
        "core/self_improving_loop/runner.py",
        "autoresearch/train.py",
        "scripts/build_self_improving_hub.py",
        # Meta / config
        ".github/workflows/pages.yml",
        ".gitignore",
        "CLAUDE.md",
        "GEODE.md",
        "pyproject.toml",
        # Bare top-level plugin manifest (not under the target dir)
        "plugins/__init__.py",
        # Random tests outside parallel tree
        "tests/test_runner.py",
        "tests/self_improving_loop/test_foo.py",
    ],
)
def test_is_path_allowed_denies_outside_allowlist(denied: str) -> None:
    """Anything outside the two allowlisted prefixes is denied."""
    assert is_path_allowed(denied, "foo") is False


def test_is_path_allowed_denies_sibling_plugin() -> None:
    """Sibling plugins are frozen — the LLM cannot edit ``plugins/bar/``
    while ``target_section="foo"``."""
    assert is_path_allowed("plugins/bar/runner.py", "foo") is False
    assert is_path_allowed("tests/plugins/bar/test_runner.py", "foo") is False


def test_is_path_allowed_denies_path_traversal() -> None:
    """``..`` anywhere in the path → deny (regardless of textual prefix)."""
    assert is_path_allowed("plugins/foo/../core/runtime.py", "foo") is False
    assert is_path_allowed("../plugins/foo/runner.py", "foo") is False
    assert is_path_allowed("plugins/../core/runtime.py", "foo") is False


def test_is_path_allowed_denies_absolute_paths() -> None:
    """Absolute paths are denied — apply path should normalise to repo-
    relative before validation; if the parser leaks an absolute path
    that's a bug, fail closed."""
    assert is_path_allowed("/etc/passwd", "foo") is False
    assert is_path_allowed("/Users/mango/workspace/geode/core/runtime.py", "foo") is False


def test_is_path_allowed_denies_lookalike_prefix() -> None:
    """``plugins/foo_evil/`` must NOT match ``target_section="foo"``
    (substring vs path-segment boundary). Same for the tests tree."""
    assert is_path_allowed("plugins/foo_evil/runner.py", "foo") is False
    assert is_path_allowed("plugins/foobar/runner.py", "foo") is False
    assert is_path_allowed("tests/plugins/foobar/test.py", "foo") is False


# ---------------------------------------------------------------------------
# validate_diff_paths — batch enforcement
# ---------------------------------------------------------------------------


def test_validate_diff_paths_passes_when_all_allowed() -> None:
    """A diff that only touches ``plugins/<section>/`` + tests passes silently."""
    validate_diff_paths(
        [
            "plugins/foo/runner.py",
            "plugins/foo/__init__.py",
            "tests/plugins/foo/test_runner.py",
        ],
        target_section="foo",
    )


def test_validate_diff_paths_raises_on_any_denied() -> None:
    """Even one denied path → raise with the offending path in the message."""
    with pytest.raises(MutationPathDeniedError) as exc_info:
        validate_diff_paths(
            [
                "plugins/foo/runner.py",
                "core/agent/loop/agent_loop.py",  # denied
            ],
            target_section="foo",
        )
    assert "core/agent/loop/agent_loop.py" in str(exc_info.value)
    assert "foo" in str(exc_info.value)


def test_validate_diff_paths_lists_all_denied() -> None:
    """All denied paths are surfaced — operator sees the full picture."""
    with pytest.raises(MutationPathDeniedError) as exc_info:
        validate_diff_paths(
            [
                "core/runtime.py",
                "autoresearch/train.py",
                "plugins/foo/ok.py",
            ],
            target_section="foo",
        )
    msg = str(exc_info.value)
    assert "core/runtime.py" in msg
    assert "autoresearch/train.py" in msg


def test_validate_diff_paths_accepts_empty_list() -> None:
    """An empty diff is vacuously allowed — caller's responsibility to
    flag empty mutations elsewhere."""
    validate_diff_paths([], target_section="foo")


# ---------------------------------------------------------------------------
# find_evolve_blocks — AlphaEvolve §A scanner
# ---------------------------------------------------------------------------


def test_find_evolve_blocks_empty_source() -> None:
    """Empty source → no blocks."""
    assert find_evolve_blocks("") == []


def test_find_evolve_blocks_no_markers() -> None:
    """Source without any markers → no blocks."""
    assert find_evolve_blocks("def foo():\n    return 1\n") == []


def test_find_evolve_blocks_single_block() -> None:
    """One START + one END → one block; line numbers are 1-indexed inclusive."""
    source = "\n".join(
        [
            "def foo():",  # line 1
            f"    {EVOLVE_BLOCK_START_MARKER}",  # line 2
            "    return 1",  # line 3
            f"    {EVOLVE_BLOCK_END_MARKER}",  # line 4
            "",  # line 5
        ]
    )
    assert find_evolve_blocks(source) == [(2, 4)]


def test_find_evolve_blocks_multiple_flat_blocks() -> None:
    """Two non-overlapping blocks → two ranges in order."""
    source = "\n".join(
        [
            EVOLVE_BLOCK_START_MARKER,  # 1
            "a = 1",  # 2
            EVOLVE_BLOCK_END_MARKER,  # 3
            "b = 2",  # 4
            EVOLVE_BLOCK_START_MARKER,  # 5
            "c = 3",  # 6
            EVOLVE_BLOCK_END_MARKER,  # 7
        ]
    )
    assert find_evolve_blocks(source) == [(1, 3), (5, 7)]


def test_find_evolve_blocks_rejects_nested() -> None:
    """Nested START before matching END → ValueError. AlphaEvolve §A
    treats blocks as flat — nesting would make the diff applier
    ambiguous about which range a hunk belongs to."""
    source = "\n".join(
        [
            EVOLVE_BLOCK_START_MARKER,  # 1
            EVOLVE_BLOCK_START_MARKER,  # 2 — nested
            "x = 1",
            EVOLVE_BLOCK_END_MARKER,
            EVOLVE_BLOCK_END_MARKER,
        ]
    )
    with pytest.raises(ValueError, match="nested"):
        find_evolve_blocks(source)


def test_find_evolve_blocks_rejects_unmatched_end() -> None:
    """END without prior START → ValueError."""
    source = "\n".join(
        [
            "a = 1",
            EVOLVE_BLOCK_END_MARKER,
        ]
    )
    with pytest.raises(ValueError, match="unmatched"):
        find_evolve_blocks(source)


def test_find_evolve_blocks_rejects_unclosed() -> None:
    """START without END before EOF → ValueError."""
    source = "\n".join(
        [
            EVOLVE_BLOCK_START_MARKER,
            "x = 1",
            "y = 2",
        ]
    )
    with pytest.raises(ValueError, match="unclosed"):
        find_evolve_blocks(source)


def test_find_evolve_blocks_tolerates_indented_markers() -> None:
    """Markers may be indented (inside a function body, for example) —
    the scanner left-strips whitespace before comparing."""
    source = "\n".join(
        [
            "def foo():",
            f"        {EVOLVE_BLOCK_START_MARKER}",
            "        return 1",
            f"        {EVOLVE_BLOCK_END_MARKER}",
        ]
    )
    assert find_evolve_blocks(source) == [(2, 4)]
