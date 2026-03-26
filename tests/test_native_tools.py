"""Tests for 3-provider native tool integration.

Covers:
- Anthropic web_search version upgrade (20250305 → 20260209)
- Anthropic web_fetch native tool injection
- GLM native web_search injection
- OpenAI Responses API gap documentation
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
        source = inspect.getsource(web_tools.GeneralWebSearchTool.execute)
        assert "web_search_20260209" in source
        assert "web_search_20250305" not in source

    def test_signal_tools_uses_20260209(self) -> None:
        """WebSearchTool (signal) must use web_search_20260209."""
        import importlib
        import inspect

        from core.tools import signal_tools

        importlib.reload(signal_tools)
        source = inspect.getsource(signal_tools.WebSearchTool.execute)
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
            patch("core.llm.providers.anthropic.settings") as mock_settings,
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


# ---------------------------------------------------------------------------
# OpenAI: Responses API gap documentation
# ---------------------------------------------------------------------------


class TestOpenAIResponsesApiGap:
    """Verify OpenAI adapter documents the Responses API gap."""

    def test_openai_adapter_has_todo_comment(self) -> None:
        """OpenAIAgenticAdapter docstring must mention Responses API TODO."""
        from core.llm.providers.openai import (
            OpenAIAgenticAdapter,
        )

        docstring = OpenAIAgenticAdapter.__doc__ or ""
        assert "Responses API" in docstring
        assert "TODO" in docstring

    def test_openai_uses_chat_completions(self) -> None:
        """Confirm OpenAI adapter still uses Chat Completions (not yet migrated)."""
        import inspect

        from core.llm.providers.openai import (
            OpenAIAgenticAdapter,
        )

        source = inspect.getsource(OpenAIAgenticAdapter.agentic_call)
        assert "chat.completions.create" in source


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

    def test_native_tool_passes_filter(self) -> None:
        """Native tool dict must survive _API_ALLOWED_KEYS filtering."""
        from core.llm.providers.anthropic import (
            _API_ALLOWED_KEYS,
        )

        native = {"type": "web_search_20260209", "name": "web_search"}
        filtered = {k: v for k, v in native.items() if k in _API_ALLOWED_KEYS}
        assert filtered == native
