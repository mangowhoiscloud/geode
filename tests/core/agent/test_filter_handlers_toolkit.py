"""Tests for ``filter_handlers`` toolkit resolution (CSP-1, 2026-05-22)."""

from __future__ import annotations

from core.agent.worker import filter_handlers
from core.tools.toolkit_registry import ToolkitRegistry


def _stub_handlers() -> dict[str, object]:
    """Mock handler map covering the names used by seed_*.md AgentDefs."""
    names = [
        "read_document",
        "write_file",
        "grep_files",
        "glob_files",
        "edit_file",
        "petri_audit",
        "general_web_search",
        "memory_save",
        "delegate_task",
    ]
    return {name: object() for name in names}


def _registry() -> ToolkitRegistry:
    return ToolkitRegistry.from_dict(
        {
            "_default": {"tools": ["read_document"]},
            "common_read": {"tools": ["read_document", "grep_files"]},
            "kit_generator": {
                "includes": ["common_read"],
                "tools": ["write_file"],
            },
            "kit_pilot": {"tools": ["petri_audit", "read_document"]},
        }
    )


class TestFilterHandlersToolkitPriority:
    def test_toolkit_takes_precedence(self) -> None:
        """When ``toolkit`` is set, ``agent_allowed_tools`` is ignored."""
        handlers = _stub_handlers()
        # agent_allowed_tools also lists write_file but with a typo'd
        # extra; toolkit resolution should win and ignore the legacy list.
        filtered = filter_handlers(
            handlers=handlers,
            denied_tools=[],
            agent_allowed_tools=["edit_file"],
            toolkit="kit_generator",
            toolkit_registry=_registry(),
        )
        assert set(filtered) == {"read_document", "write_file", "grep_files"}
        assert "edit_file" not in filtered  # legacy list ignored
        assert "delegate_task" not in filtered  # depth=1 guard

    def test_legacy_tools_list_when_no_toolkit(self) -> None:
        """When toolkit is empty, fall back to ``agent_allowed_tools``."""
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=[],
            agent_allowed_tools=["edit_file", "memory_save"],
            toolkit="",
            toolkit_registry=_registry(),
        )
        assert set(filtered) == {"edit_file", "memory_save"}

    def test_default_fallback_when_neither(self) -> None:
        """No toolkit + no legacy tools → ``_default`` toolkit safety net."""
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=[],
            agent_allowed_tools=[],
            toolkit="",
            toolkit_registry=_registry(),
        )
        assert set(filtered) == {"read_document"}

    def test_no_registry_no_legacy_keeps_all_minus_denied(self) -> None:
        """Pre-CSP-1 behaviour: no registry passed → only depth=1 + denied filter applies."""
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=["run_bash"],
            agent_allowed_tools=[],
            toolkit="",
            toolkit_registry=None,
        )
        # delegate_task always denied; everything else stays.
        assert "delegate_task" not in filtered
        assert "read_document" in filtered
        assert "write_file" in filtered

    def test_unknown_toolkit_falls_back_to_default(self) -> None:
        """A typo'd toolkit name routes through ``_default`` with WARNING."""
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=[],
            agent_allowed_tools=[],
            toolkit="kit_typo",
            toolkit_registry=_registry(),
        )
        assert set(filtered) == {"read_document"}

    def test_pilot_toolkit_resolves_petri_audit(self) -> None:
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=[],
            agent_allowed_tools=[],
            toolkit="kit_pilot",
            toolkit_registry=_registry(),
        )
        assert set(filtered) == {"petri_audit", "read_document"}

    def test_denied_tools_post_apply(self) -> None:
        """``denied_tools`` is applied AFTER toolkit expansion."""
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=["write_file"],
            agent_allowed_tools=[],
            toolkit="kit_generator",
            toolkit_registry=_registry(),
        )
        # kit_generator pulls write_file via composition; denied list
        # subtracts it.
        assert "write_file" not in filtered
        assert "read_document" in filtered
        assert "grep_files" in filtered


class TestFilterHandlersBackwardsCompat:
    """Pre-CSP-1 call signatures must still work without ``toolkit`` kwargs."""

    def test_legacy_signature_unchanged(self) -> None:
        """Calls without toolkit kwargs behave exactly as before."""
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=["run_bash"],
            agent_allowed_tools=["read_document", "write_file"],
        )
        assert set(filtered) == {"read_document", "write_file"}


class TestFilterHandlersFailClosed:
    """Codex MCP HIGH #2 + MEDIUM #2 — silent re-open paths must fail closed."""

    def test_empty_registry_no_default_fails_closed(self) -> None:
        """Registry without ``_default`` + no toolkit + no legacy list →
        all handlers denied (no silent re-open of full surface)."""
        empty_reg = ToolkitRegistry.from_dict({"kit_only": {"tools": ["read_document"]}})
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=[],
            agent_allowed_tools=[],
            toolkit="",
            toolkit_registry=empty_reg,
        )
        # delegate_task is always denied; nothing else survived because
        # ``_default`` was missing and tier-3 now fails closed.
        assert filtered == {}

    def test_empty_default_toolkit_fails_closed(self) -> None:
        """``_default`` declared but resolving to empty set → all denied."""
        reg = ToolkitRegistry.from_dict({"_default": {}})
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=[],
            agent_allowed_tools=[],
            toolkit="",
            toolkit_registry=reg,
        )
        assert filtered == {}

    def test_explicit_toolkit_without_registry_fails_closed(self) -> None:
        """toolkit declared but ``toolkit_registry=None`` → empty allowlist.

        Pre-fix this silently fell through to ``agent_allowed_tools`` or
        the full surface, masking misconfigured spawns.
        """
        filtered = filter_handlers(
            handlers=_stub_handlers(),
            denied_tools=[],
            agent_allowed_tools=["edit_file"],
            toolkit="kit_generator",
            toolkit_registry=None,
        )
        # toolkit declared → fail closed; legacy ``agent_allowed_tools``
        # is NOT used as a fallback here.
        assert filtered == {}


class TestSeedAgentDefBackwardsContract:
    """Smoke test — the seed_*.md AgentDefs all declare a real toolkit.

    (``seed_pilot`` was removed in PR-PILOT-UNIFY-DIM-EXTRACT, 2026-06-04 —
    the Pilot runs the audit directly instead of spawning a sub-agent.)
    """

    def test_seed_toolkits_resolve(self) -> None:
        from core.tools.toolkit_registry import load_default_registry

        reg = load_default_registry(force_reload=True)
        kits = [
            "seed_generation",
            "seed_critique",
            "seed_ranker",
            "seed_evolver",
            "seed_meta_review",
            "seed_proximity",
        ]
        for kit in kits:
            tools = reg.resolve(kit)
            assert tools, f"toolkit {kit!r} resolved to empty set — review toolkits.toml"
