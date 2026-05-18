"""Tests for 3-provider native tool integration.

Covers:
- Anthropic web_search version upgrade (20250305 → 20260209)
- Anthropic web_fetch native tool injection
- GLM native web_search injection
- OpenAI Responses API migration + native web_search injection
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Anthropic: web_search version string tests
# ---------------------------------------------------------------------------


class TestAnthropicWebSearchVersion:
    """Verify web_search_20260209 is used everywhere (not 20250305)."""

    def test_web_tools_uses_20260209(self) -> None:
        """GeneralWebSearchTool must use web_search_20260209."""
        import importlib
        import inspect

        from core.tools import web_tools

        importlib.reload(web_tools)
        source = inspect.getsource(web_tools.GeneralWebSearchTool)
        assert "web_search_20260209" in source
        assert "web_search_20250305" not in source

    def test_signal_tools_uses_20260209(self) -> None:
        """WebSearchTool must use web_search_20260209."""
        import importlib
        import inspect

        from core.tools import web_search

        importlib.reload(web_search)
        source = inspect.getsource(web_search.WebSearchTool)
        assert "web_search_20260209" in source
        assert "web_search_20250305" not in source


# ---------------------------------------------------------------------------
# Anthropic: native tool injection in adapter
# ---------------------------------------------------------------------------


class TestAnthropicNativeToolInjection:
    """ClaudeAgenticAdapter must inject native tools into API call."""

    def test_native_tools_constant_has_web_search(self) -> None:
        """_ANTHROPIC_NATIVE_TOOLS must include web_search_20260209."""
        from core.llm.providers.anthropic import (
            _ANTHROPIC_NATIVE_TOOLS,
        )

        names = {t["name"] for t in _ANTHROPIC_NATIVE_TOOLS}
        types = {t["type"] for t in _ANTHROPIC_NATIVE_TOOLS}
        assert "web_search" in names
        assert "web_search_20260209" in types

    def test_native_tools_constant_has_web_fetch(self) -> None:
        """_ANTHROPIC_NATIVE_TOOLS must include web_fetch_20260209."""
        from core.llm.providers.anthropic import (
            _ANTHROPIC_NATIVE_TOOLS,
        )

        names = {t["name"] for t in _ANTHROPIC_NATIVE_TOOLS}
        types = {t["type"] for t in _ANTHROPIC_NATIVE_TOOLS}
        assert "web_fetch" in names
        assert "web_fetch_20260209" in types

    def test_native_tools_have_allowed_callers_direct(self) -> None:
        """All native tools must set allowed_callers=["direct"] for Haiku compatibility."""
        from core.llm.providers.anthropic import (
            _ANTHROPIC_NATIVE_TOOLS,
        )

        for tool in _ANTHROPIC_NATIVE_TOOLS:
            assert "allowed_callers" in tool, f"{tool['name']} missing allowed_callers"
            assert tool["allowed_callers"] == ["direct"], (
                f"{tool['name']} allowed_callers must be ['direct'], got {tool['allowed_callers']}"
            )

    def test_native_tools_deduplication(self) -> None:
        """Native tools should not duplicate existing tool names."""
        from core.llm.providers.anthropic import (
            _ANTHROPIC_NATIVE_TOOLS,
            _API_ALLOWED_KEYS,
        )

        # Simulate tools list with a web_search tool already present
        tools: list[dict[str, Any]] = [
            {
                "name": "web_search",
                "description": "Custom web search",
                "input_schema": {"type": "object"},
                "type": "function",
            },
            {
                "name": "other_tool",
                "description": "Another tool",
                "input_schema": {"type": "object"},
            },
        ]

        api_tools = [{k: v for k, v in t.items() if k in _API_ALLOWED_KEYS} for t in tools]
        existing_names = {t.get("name") for t in api_tools}
        for native in _ANTHROPIC_NATIVE_TOOLS:
            if native["name"] not in existing_names:
                api_tools.append(native)

        # web_search should appear only once (original, not native)
        web_search_entries = [t for t in api_tools if t.get("name") == "web_search"]
        assert len(web_search_entries) == 1
        # web_fetch should be added (not in original)
        web_fetch_entries = [t for t in api_tools if t.get("name") == "web_fetch"]
        assert len(web_fetch_entries) == 1

    def test_agentic_call_injects_native_tools(self) -> None:
        """agentic_call must include native tools in the API request."""
        import asyncio

        from core.llm.providers.anthropic import (
            ClaudeAgenticAdapter,
        )

        adapter = ClaudeAgenticAdapter()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="hello")]
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        mock_response.model = "claude-opus-4-6"

        with (
            patch("core.config.settings") as mock_settings,
            patch("core.llm.router.call_with_failover") as mock_failover,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_failover.return_value = (mock_response, "claude-opus-4-6")

            # Set a mock client so _ensure_client path is skipped
            adapter._client = MagicMock()

            result = asyncio.run(
                adapter.agentic_call(
                    model="claude-opus-4-6",
                    system="test",
                    messages=[{"role": "user", "content": "hello"}],
                    tools=[
                        {
                            "name": "test_tool",
                            "description": "A test",
                            "input_schema": {"type": "object"},
                        }
                    ],
                    tool_choice={"type": "auto"},
                    max_tokens=1024,
                    temperature=0.0,
                )
            )

            assert result is not None
            # Verify call_with_failover was called
            assert mock_failover.called

            # Inspect the callable passed to call_with_failover
            # The first positional arg is the model list, second is the async callable
            call_args = mock_failover.call_args
            model_list = call_args[0][0]
            assert "claude-opus-4-6" in model_list


# ---------------------------------------------------------------------------
# GLM: native web_search injection
# ---------------------------------------------------------------------------


class TestGlmNativeWebSearch:
    """GlmAgenticAdapter must inject native web_search."""

    def test_glm_native_web_search_constant(self) -> None:
        """_GLM_NATIVE_WEB_SEARCH must have correct structure."""
        from core.llm.providers.glm import (
            _GLM_NATIVE_WEB_SEARCH,
        )

        assert _GLM_NATIVE_WEB_SEARCH["type"] == "web_search"
        assert _GLM_NATIVE_WEB_SEARCH["web_search"]["enable"] is True

    def test_glm_adapter_is_subclass_of_openai(self) -> None:
        """GlmAgenticAdapter must inherit from OpenAIAgenticAdapter."""
        from core.llm.providers.glm import (
            GlmAgenticAdapter,
        )
        from core.llm.providers.openai import (
            OpenAIAgenticAdapter,
        )

        assert issubclass(GlmAgenticAdapter, OpenAIAgenticAdapter)

    def test_glm_provider_name(self) -> None:
        """GlmAgenticAdapter.provider_name must be 'glm'."""
        from core.llm.providers.glm import (
            GlmAgenticAdapter,
        )

        adapter = GlmAgenticAdapter()
        assert adapter.provider_name == "glm"

    def test_glm_has_own_agentic_call(self) -> None:
        """GlmAgenticAdapter must override agentic_call (not inherit from OpenAI)."""
        from core.llm.providers.glm import (
            GlmAgenticAdapter,
        )
        from core.llm.providers.openai import (
            OpenAIAgenticAdapter,
        )

        # GlmAgenticAdapter.agentic_call should be defined on the class itself
        assert "agentic_call" in GlmAgenticAdapter.__dict__
        # And it should be different from the parent
        assert GlmAgenticAdapter.agentic_call is not OpenAIAgenticAdapter.agentic_call

    def test_glm_agentic_call_defers_record_to_agent_loop(self) -> None:
        """GlmAgenticAdapter.agentic_call must NOT call ``get_tracker().record()``.

        The agent loop's ``_track_usage`` records on the normalized
        ``AgenticResponse`` returned below — recording at the provider
        layer too caused every GLM / Codex / OpenAI agentic call to
        double-count into ``~/.geode/usage/*.jsonl`` (gpt-5.5 saw
        50.5 % paired duplicates, gpt-5.3-codex 64 %).  Single-record
        rule: the agent loop is the sole writer for ``agentic_call``
        invocations; provider ``LLMClientPort.generate*`` paths
        (cross-LLM verification) keep their own record() because the
        loop never sees those responses.
        """
        import inspect

        from core.llm.providers.codex import CodexAgenticAdapter
        from core.llm.providers.glm import GlmAgenticAdapter

        for adapter_cls, name in (
            (GlmAgenticAdapter, "GLM"),
            (CodexAgenticAdapter, "Codex"),
        ):
            source = inspect.getsource(adapter_cls.agentic_call)
            assert "get_tracker" not in source, (
                f"{name} agentic_call must defer record() to agent loop's "
                f"_track_usage to avoid double-counting"
            )

    def test_glm_cost_is_nonzero(self) -> None:
        """GLM models with non-free pricing must produce non-zero cost."""
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        cost = tracker.calculate_cost("glm-5", 1000, 500)
        assert cost > 0, "glm-5 should have non-zero cost"

    def test_glm_free_tier_zero_cost(self) -> None:
        """glm-4.7-flash (free tier) should produce zero cost."""
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        cost = tracker.calculate_cost("glm-4.7-flash", 1000, 500)
        assert cost == 0.0, "glm-4.7-flash is free tier"


# ---------------------------------------------------------------------------
# OpenAI: Responses API migration
# ---------------------------------------------------------------------------


class TestOpenAIResponsesApiMigration:
    """Verify OpenAI adapter uses Responses API with native web_search."""

    def test_openai_adapter_mentions_responses_api(self) -> None:
        """OpenAIAgenticAdapter docstring must mention Responses API."""
        from core.llm.providers.openai import OpenAIAgenticAdapter

        docstring = OpenAIAgenticAdapter.__doc__ or ""
        assert "Responses API" in docstring

    def test_openai_uses_responses_api(self) -> None:
        """OpenAI adapter must use Responses API (create or stream), not chat.completions."""
        import inspect

        from core.llm.providers import openai as openai_module
        from core.llm.providers.openai import OpenAIAgenticAdapter

        call_source = inspect.getsource(OpenAIAgenticAdapter.agentic_call)
        module_source = inspect.getsource(openai_module)
        # PR #1316 — PAYG switched from blocking responses.create to streaming
        # responses.stream (via _stream_openai_response helper) for TTFB parity
        # with Anthropic/Codex.
        uses_responses = (
            "responses.create" in module_source or "responses.stream" in module_source
        )
        assert uses_responses
        assert "chat.completions.create" not in call_source

    def test_openai_native_web_search_constant(self) -> None:
        """_OPENAI_NATIVE_TOOLS must include web_search."""
        from core.llm.providers.openai import _OPENAI_NATIVE_TOOLS

        types = {t.get("type") for t in _OPENAI_NATIVE_TOOLS}
        assert "web_search" in types


# ---------------------------------------------------------------------------
# Cross-provider: _API_ALLOWED_KEYS includes 'type'
# ---------------------------------------------------------------------------


class TestApiAllowedKeys:
    """Verify _API_ALLOWED_KEYS allows native tool type passthrough."""

    def test_type_key_in_allowed(self) -> None:
        """'type' must be in _API_ALLOWED_KEYS for native tool passthrough."""
        from core.llm.providers.anthropic import (
            _API_ALLOWED_KEYS,
        )

        assert "type" in _API_ALLOWED_KEYS

    def test_native_tool_core_keys_pass_filter(self) -> None:
        """Native tool type/name keys must survive _API_ALLOWED_KEYS filtering."""
        from core.llm.providers.anthropic import (
            _ANTHROPIC_NATIVE_TOOLS,
            _API_ALLOWED_KEYS,
        )

        for native in _ANTHROPIC_NATIVE_TOOLS:
            filtered = {k: v for k, v in native.items() if k in _API_ALLOWED_KEYS}
            assert "type" in filtered
            assert "name" in filtered
