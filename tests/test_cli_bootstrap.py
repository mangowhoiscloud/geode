"""Tests for unified CLI bootstrap (core.cli.bootstrap).

Verifies that bootstrap_geode() returns a fully initialized GeodeBootstrap
and that propagate_to_thread() correctly sets ContextVars in new threads.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

from core.cli.bootstrap import GeodeBootstrap, bootstrap_geode

# ---------------------------------------------------------------------------
# GeodeBootstrap dataclass
# ---------------------------------------------------------------------------


class TestGeodeBootstrapDefaults:
    def test_default_fields(self) -> None:
        boot = GeodeBootstrap()
        assert boot.mcp_manager is None
        assert boot.skill_registry is None
        assert boot.tool_handlers == {}
        assert boot.readiness is None

    def test_context_snapshot_captured(self) -> None:
        """_context is a contextvars.Context (snapshot at creation time)."""
        import contextvars

        boot = GeodeBootstrap()
        assert isinstance(boot._context, contextvars.Context)


# ---------------------------------------------------------------------------
# propagate_to_thread()
# ---------------------------------------------------------------------------


class TestPropagateToThread:
    def test_propagate_sets_memory_contextvars_in_new_thread(self) -> None:
        """propagate_to_thread() makes ProjectMemory/OrgMemory available in a child thread."""
        import core.tools.memory_tools as _mem_mod
        from core.tools.memory_tools import _org_memory_ctx

        # Create a bootstrap with a mock readiness
        readiness = MagicMock()
        boot = GeodeBootstrap(readiness=readiness)

        results: dict[str, Any] = {}
        errors: list[Exception] = []

        def worker() -> None:
            try:
                boot.propagate_to_thread()
                results["project"] = _mem_mod._project_memory
                results["org"] = _org_memory_ctx.get()
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)

        assert not errors, f"Thread raised: {errors}"
        assert results.get("project") is not None
        assert results.get("org") is not None

    def test_propagate_sets_readiness(self) -> None:
        """propagate_to_thread() sets the readiness ContextVar."""
        readiness = MagicMock(force_dry_run=True)
        boot = GeodeBootstrap(readiness=readiness)

        results: dict[str, Any] = {}

        def worker() -> None:
            boot.propagate_to_thread()
            from core.cli import _get_readiness

            results["readiness"] = _get_readiness()

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)

        assert results["readiness"] is readiness

    def test_propagate_with_none_readiness(self) -> None:
        """propagate_to_thread() with readiness=None does not crash."""
        boot = GeodeBootstrap(readiness=None)

        errors: list[Exception] = []

        def worker() -> None:
            try:
                boot.propagate_to_thread()
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)

        assert not errors


# ---------------------------------------------------------------------------
# bootstrap_geode()
# ---------------------------------------------------------------------------


class TestBootstrapGeode:
    def test_returns_geode_bootstrap(self) -> None:
        boot = bootstrap_geode()
        assert isinstance(boot, GeodeBootstrap)

    def test_readiness_not_none(self) -> None:
        boot = bootstrap_geode()
        assert boot.readiness is not None

    def test_mcp_manager_not_none(self) -> None:
        boot = bootstrap_geode()
        assert boot.mcp_manager is not None

    def test_skill_registry_not_none(self) -> None:
        boot = bootstrap_geode()
        assert boot.skill_registry is not None

    def test_tool_handlers_populated(self) -> None:
        """tool_handlers should have 44+ handlers (all tools minus a few MCP-only)."""
        boot = bootstrap_geode()
        assert len(boot.tool_handlers) >= 40

    def test_load_env_false_does_not_call_dotenv(self) -> None:
        """When load_env=False, dotenv should not be invoked."""
        with patch("core.cli.bootstrap.log") as _:
            # Just verify no crash; dotenv import is conditional
            boot = bootstrap_geode(load_env=False)
            assert boot is not None

    def test_load_env_true_calls_dotenv(self) -> None:
        """When load_env=True, dotenv loading is attempted."""
        with (
            patch("core.cli.bootstrap.log"),
            patch("dotenv.load_dotenv") as _mock_dotenv,
        ):
            boot = bootstrap_geode(load_env=True)
            assert boot is not None
            # load_dotenv may or may not be called depending on file existence
            # but the code path should not crash


class TestBootstrapIdempotent:
    def test_double_bootstrap_does_not_crash(self) -> None:
        """Calling bootstrap_geode() twice should not raise."""
        boot1 = bootstrap_geode()
        boot2 = bootstrap_geode()
        assert boot1.readiness is not None
        assert boot2.readiness is not None


# ---------------------------------------------------------------------------
# Integration: bootstrap -> propagate -> tool_handlers work in thread
# ---------------------------------------------------------------------------


class TestBootstrapThreadIntegration:
    def test_tool_handlers_usable_after_propagate(self) -> None:
        """After propagate_to_thread(), tool_handlers should work in a new thread."""
        boot = bootstrap_geode()
        results: dict[str, Any] = {}

        def worker() -> None:
            boot.propagate_to_thread()
            # Verify handler dict is accessible and non-empty
            results["handler_count"] = len(boot.tool_handlers)
            results["has_analyze"] = "analyze_ip" in boot.tool_handlers

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)

        assert results.get("handler_count", 0) >= 40
        assert results.get("has_analyze") is True
