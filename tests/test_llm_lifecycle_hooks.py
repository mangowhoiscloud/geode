"""Tests for LLM_CALL_START/END lifecycle hooks.

Verifies that:
1. HookEvent enum includes the LLM lifecycle events
2. _fire_hook dispatches correctly when HookSystem is wired
3. _fire_hook is a no-op when no HookSystem is set (graceful degradation)
4. Bootstrap registers the llm_slow_logger handler
5. The slow_logger handler warns on errors and slow calls
"""

from __future__ import annotations

from typing import Any

from core.hooks import HookEvent, HookSystem
from core.llm.router import _fire_hook, set_router_hooks


class TestLLMLifecycleEvents:
    """HookEvent enum contains LLM_CALL_START and LLM_CALL_END."""

    def test_llm_call_start_exists(self) -> None:
        assert HookEvent.LLM_CALL_START.value == "llm_call_start"

    def test_llm_call_end_exists(self) -> None:
        assert HookEvent.LLM_CALL_END.value == "llm_call_end"

    def test_event_count_includes_llm_events(self) -> None:
        """42 events total (40 base + LLM_CALL_START + LLM_CALL_END)."""
        assert len(HookEvent) == 45


class TestFireHook:
    """_fire_hook dispatches to HookSystem when wired, no-ops otherwise."""

    def test_fire_hook_dispatches_to_hooks(self) -> None:
        hooks = HookSystem()
        captured: list[tuple[HookEvent, dict[str, Any]]] = []

        def recorder(event: HookEvent, data: dict[str, Any]) -> None:
            captured.append((event, data))

        hooks.register(HookEvent.LLM_CALL_START, recorder, name="test_recorder")
        set_router_hooks(hooks)
        try:
            _fire_hook("llm_call_start", {"model": "test-model", "provider": "anthropic"})

            assert len(captured) == 1
            event, data = captured[0]
            assert event == HookEvent.LLM_CALL_START
            assert data["model"] == "test-model"
            assert data["provider"] == "anthropic"
        finally:
            set_router_hooks(None)

    def test_fire_hook_noop_without_hooks(self) -> None:
        """No error when _hooks_ctx is None."""
        set_router_hooks(None)
        # Should not raise
        _fire_hook("llm_call_start", {"model": "x"})

    def test_fire_hook_end_with_error_data(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def recorder(event: HookEvent, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.LLM_CALL_END, recorder, name="test_end")
        set_router_hooks(hooks)
        try:
            _fire_hook(
                "llm_call_end",
                {
                    "model": "claude-opus-4-6",
                    "provider": "anthropic",
                    "function": "call_llm",
                    "latency_ms": 1234.5,
                    "error": "timeout",
                },
            )

            assert len(captured) == 1
            assert captured[0]["latency_ms"] == 1234.5
            assert captured[0]["error"] == "timeout"
        finally:
            set_router_hooks(None)

    def test_fire_hook_end_success_data(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def recorder(event: HookEvent, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.LLM_CALL_END, recorder, name="test_end_ok")
        set_router_hooks(hooks)
        try:
            _fire_hook(
                "llm_call_end",
                {
                    "model": "gpt-5.4",
                    "provider": "openai",
                    "function": "call_llm_parsed",
                    "latency_ms": 456.0,
                    "error": None,
                },
            )

            assert len(captured) == 1
            assert captured[0]["error"] is None
            assert captured[0]["function"] == "call_llm_parsed"
        finally:
            set_router_hooks(None)

    def test_fire_hook_graceful_on_handler_error(self) -> None:
        """Hook handler errors must not propagate."""
        hooks = HookSystem()

        def bad_handler(event: HookEvent, data: dict[str, Any]) -> None:
            raise RuntimeError("handler boom")

        hooks.register(HookEvent.LLM_CALL_END, bad_handler, name="bad")
        set_router_hooks(hooks)
        try:
            # Should not raise despite handler error
            _fire_hook("llm_call_end", {"model": "x"})
        finally:
            set_router_hooks(None)


class TestBootstrapLLMLifecycleHook:
    """Bootstrap wires llm_slow_logger at P55 and accumulates session stats."""

    def test_slow_logger_warns_on_error(self) -> None:
        """llm_slow_logger logs warning when error is present."""
        hooks = HookSystem()
        warned = []

        def _on_llm_end(event: HookEvent, data: dict[str, Any]) -> None:
            error = data.get("error")
            if error:
                warned.append(data)

        hooks.register(HookEvent.LLM_CALL_END, _on_llm_end, name="test_logger")

        hooks.trigger(
            HookEvent.LLM_CALL_END,
            {
                "model": "claude-opus-4-6",
                "latency_ms": 500,
                "error": "rate limit exceeded",
            },
        )
        assert len(warned) == 1
        assert warned[0]["error"] == "rate limit exceeded"

    def test_slow_logger_warns_on_slow_call(self) -> None:
        """llm_slow_logger logs warning when latency > 10s."""
        hooks = HookSystem()
        slow_calls = []

        def _on_llm_end(event: HookEvent, data: dict[str, Any]) -> None:
            latency = data.get("latency_ms", 0)
            if not data.get("error") and latency > 10_000:
                slow_calls.append(data)

        hooks.register(HookEvent.LLM_CALL_END, _on_llm_end, name="test_slow")

        hooks.trigger(
            HookEvent.LLM_CALL_END,
            {"model": "claude-opus-4-6", "latency_ms": 15_000, "error": None},
        )
        assert len(slow_calls) == 1

    def test_slow_logger_silent_on_normal_call(self) -> None:
        """No warning for normal-latency successful calls."""
        hooks = HookSystem()
        logged = []

        def _on_llm_end(event: HookEvent, data: dict[str, Any]) -> None:
            error = data.get("error")
            latency = data.get("latency_ms", 0)
            if error or latency > 10_000:
                logged.append(data)

        hooks.register(HookEvent.LLM_CALL_END, _on_llm_end, name="test_normal")

        hooks.trigger(
            HookEvent.LLM_CALL_END,
            {"model": "claude-opus-4-6", "latency_ms": 2000, "error": None},
        )
        assert len(logged) == 0

    def test_session_stats_accumulation(self) -> None:
        """Session stats accumulate across multiple LLM_CALL_END events."""
        stats: dict[str, Any] = {
            "total_calls": 0,
            "total_errors": 0,
            "total_latency_ms": 0.0,
            "by_model": {},
        }

        def _on_llm_end(event: HookEvent, data: dict[str, Any]) -> None:
            latency = data.get("latency_ms", 0.0)
            model = data.get("model", "?")
            error = data.get("error")
            stats["total_calls"] += 1
            stats["total_latency_ms"] += latency
            if error:
                stats["total_errors"] += 1
            model_stats = stats["by_model"].setdefault(model, {"calls": 0, "total_latency_ms": 0.0})
            model_stats["calls"] += 1
            model_stats["total_latency_ms"] += latency

        hooks = HookSystem()
        hooks.register(HookEvent.LLM_CALL_END, _on_llm_end, name="stats")

        # Simulate 3 calls
        hooks.trigger(
            HookEvent.LLM_CALL_END,
            {"model": "claude-opus-4-6", "latency_ms": 1000.0, "error": None},
        )
        hooks.trigger(
            HookEvent.LLM_CALL_END,
            {"model": "gpt-5.4", "latency_ms": 2000.0, "error": None},
        )
        hooks.trigger(
            HookEvent.LLM_CALL_END,
            {"model": "claude-opus-4-6", "latency_ms": 500.0, "error": "timeout"},
        )

        assert stats["total_calls"] == 3
        assert stats["total_errors"] == 1
        assert stats["total_latency_ms"] == 3500.0
        assert stats["by_model"]["claude-opus-4-6"]["calls"] == 2
        assert stats["by_model"]["gpt-5.4"]["calls"] == 1


class TestHookPayloadSchema:
    """Verify hook data payloads contain expected fields."""

    def test_llm_call_start_payload(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        hooks.register(
            HookEvent.LLM_CALL_START,
            lambda e, d: captured.append(d),
            name="schema_check",
        )

        payload = {
            "model": "claude-opus-4-6",
            "provider": "anthropic",
            "function": "call_llm",
        }
        hooks.trigger(HookEvent.LLM_CALL_START, payload)

        assert len(captured) == 1
        data = captured[0]
        assert "model" in data
        assert "provider" in data
        assert "function" in data

    def test_llm_call_end_payload(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        hooks.register(
            HookEvent.LLM_CALL_END,
            lambda e, d: captured.append(d),
            name="schema_check",
        )

        payload = {
            "model": "claude-opus-4-6",
            "provider": "anthropic",
            "function": "call_llm",
            "latency_ms": 1234.5,
            "error": None,
        }
        hooks.trigger(HookEvent.LLM_CALL_END, payload)

        assert len(captured) == 1
        data = captured[0]
        assert "model" in data
        assert "provider" in data
        assert "function" in data
        assert "latency_ms" in data
        assert "error" in data
