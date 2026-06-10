"""Hermes Phase 2 — ``core.llm.platform_hints`` invariants.

Pins the resolution order (env override → ContextVar → ``cli`` default),
the ``<platform_hint>`` block shape, and the graceful no-op for
unrecognised surfaces.
"""

from __future__ import annotations

import contextvars

import pytest
from core.llm import platform_hints
from core.llm.platform_hints import (
    GEODE_SURFACE_TYPE_ENV,
    PLATFORM_HINTS,
    SURFACE_CLI,
    SURFACE_CRON,
    SURFACE_MCP_REMOTE,
    SURFACE_SERVE_REPL,
    SURFACE_SLACK,
    SURFACE_WORKTREE,
    VALID_SURFACES,
    get_current_surface,
    render_platform_hint,
    set_current_surface,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GEODE_SURFACE_TYPE_ENV, raising=False)


def test_six_canonical_surfaces_covered():
    expected = {
        SURFACE_CLI,
        SURFACE_CRON,
        SURFACE_MCP_REMOTE,
        SURFACE_SERVE_REPL,
        SURFACE_SLACK,
        SURFACE_WORKTREE,
    }
    assert expected == VALID_SURFACES
    assert set(PLATFORM_HINTS) == expected, "every surface must have a hint body"


def test_get_current_surface_default_cli():
    assert get_current_surface() == SURFACE_CLI


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(GEODE_SURFACE_TYPE_ENV, SURFACE_SLACK)
    assert get_current_surface() == SURFACE_SLACK


def test_env_unknown_value_falls_through_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(GEODE_SURFACE_TYPE_ENV, "telegram")
    assert get_current_surface() == SURFACE_CLI


def test_context_var_used_when_env_unset():
    def _scoped() -> str:
        set_current_surface(SURFACE_CRON)
        return get_current_surface()

    ctx = contextvars.copy_context()
    assert ctx.run(_scoped) == SURFACE_CRON
    # Outside the copied context the binding does not leak.
    assert get_current_surface() == SURFACE_CLI


def test_env_beats_context_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(GEODE_SURFACE_TYPE_ENV, SURFACE_WORKTREE)

    def _scoped() -> str:
        set_current_surface(SURFACE_SLACK)
        return get_current_surface()

    ctx = contextvars.copy_context()
    assert ctx.run(_scoped) == SURFACE_WORKTREE


def test_render_uses_resolved_surface(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(GEODE_SURFACE_TYPE_ENV, SURFACE_SLACK)
    block = render_platform_hint()
    assert block.startswith("<platform_hint surface='slack'>")
    assert block.rstrip().endswith("</platform_hint>")
    assert PLATFORM_HINTS[SURFACE_SLACK] in block


def test_render_explicit_surface_overrides_lookup():
    block = render_platform_hint(SURFACE_MCP_REMOTE)
    assert "surface='mcp_remote'" in block
    assert PLATFORM_HINTS[SURFACE_MCP_REMOTE] in block


def test_render_unknown_surface_returns_empty_string():
    assert render_platform_hint("telegram") == ""


@pytest.mark.parametrize("surface", sorted(VALID_SURFACES))
def test_render_returns_xml_block_for_each_surface(surface: str):
    block = render_platform_hint(surface)
    assert block.startswith(f"<platform_hint surface={surface!r}>"), f"surface={surface}"
    assert block.rstrip().endswith("</platform_hint>"), f"surface={surface}"
    assert PLATFORM_HINTS[surface] in block, f"surface={surface} body missing"


def test_module_exports_stable():
    expected = {
        "GEODE_SURFACE_TYPE_ENV",
        "PLATFORM_HINTS",
        "SURFACE_CLI",
        "SURFACE_CRON",
        "SURFACE_MCP_REMOTE",
        "SURFACE_SERVE_REPL",
        "SURFACE_SLACK",
        "SURFACE_WORKTREE",
        "VALID_SURFACES",
        "get_current_surface",
        "render_platform_hint",
        "set_current_surface",
    }
    assert set(platform_hints.__all__) == expected
