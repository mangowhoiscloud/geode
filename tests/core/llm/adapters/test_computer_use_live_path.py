"""Computer-use on the LIVE Anthropic adapter path (Phase A).

Computer-use was wired only into the legacy ``ClaudeAgenticAdapter.agentic_call``
request builder; PR-MAINPATH-67 (2026-05-24) deleted that branch, so the
production AgenticLoop — which reaches Anthropic through
``_anthropic_common.build_create_kwargs`` / ``build_stream_kwargs`` — never
offered the model the ``computer`` tool at all (the same docstring-vs-live-path
class of bug the tool-search-defer review caught). These tests pin the
resurrected injection on the live builders + the ComputerUseCapable contract.
"""

from __future__ import annotations

from unittest.mock import patch

from core.llm.adapters import _anthropic_common as common
from core.llm.adapters.base import (
    AdapterCallRequest,
    ComputerUseCapable,
    Message,
    ToolSpec,
)
from core.tools.computer_use import TARGET_HEIGHT, TARGET_WIDTH

_ENABLED = "core.llm.providers.anthropic.is_computer_use_enabled"


def _req(tools: tuple[ToolSpec, ...] = ()) -> AdapterCallRequest:
    return AdapterCallRequest(
        model="claude-opus-4-8",
        messages=(Message(role="user", content="hi"),),
        tools=tools,
    )


class TestLivePathInjection:
    def test_create_injects_computer_tool_and_beta_when_enabled(self) -> None:
        with patch(_ENABLED, return_value=True):
            kwargs = common.build_create_kwargs(_req())
        tools = kwargs.get("tools", [])
        assert any(
            t.get("name") == "computer" and t.get("type") == "computer_20251124" for t in tools
        ), tools
        assert "computer-use-2025-01-24" in kwargs["extra_headers"]["anthropic-beta"]

    def test_stream_injects_computer_tool_when_enabled(self) -> None:
        with patch(_ENABLED, return_value=True):
            kwargs = common.build_stream_kwargs(_req())
        assert any(t.get("name") == "computer" for t in kwargs.get("tools", []))
        assert "computer-use-2025-01-24" in kwargs["extra_headers"]["anthropic-beta"]

    def test_disabled_injects_nothing(self) -> None:
        with patch(_ENABLED, return_value=False):
            kwargs = common.build_create_kwargs(_req())
        assert not any(t.get("name") == "computer" for t in kwargs.get("tools", []))
        assert "extra_headers" not in kwargs

    def test_injects_even_with_no_registry_tools(self) -> None:
        """The model must be offered ``computer`` even when the request carries
        no registry tools — injection is not gated on ``req.tools``."""
        with patch(_ENABLED, return_value=True):
            kwargs = common.build_create_kwargs(_req(tools=()))
        assert [t.get("name") for t in kwargs["tools"]] == ["computer"]

    def test_no_double_inject_if_already_present(self) -> None:
        kwargs: dict = {
            "tools": [common.anthropic_computer_tool_param(TARGET_WIDTH, TARGET_HEIGHT)]
        }
        with patch(_ENABLED, return_value=True):
            common._maybe_inject_computer_use(kwargs)
        # not doubled, and the beta header is still ensured for the native tool.
        assert sum(1 for t in kwargs["tools"] if t.get("type") == "computer_20251124") == 1
        assert "computer-use-2025-01-24" in kwargs["extra_headers"]["anthropic-beta"]

    def test_custom_same_name_tool_does_not_suppress_native(self) -> None:
        """Dedup is by native TYPE, not name — a caller's custom ``computer``
        tool must not block the native ``computer_20251124`` injection."""
        kwargs: dict = {
            "tools": [{"name": "computer", "description": "custom", "input_schema": {}}]
        }
        with patch(_ENABLED, return_value=True):
            common._maybe_inject_computer_use(kwargs)
        assert any(t.get("type") == "computer_20251124" for t in kwargs["tools"])
        assert "computer-use-2025-01-24" in kwargs["extra_headers"]["anthropic-beta"]

    def test_beta_header_merges_not_clobbers(self) -> None:
        kwargs: dict = {"extra_headers": {"anthropic-beta": "context-management-2025-06-27"}}
        with patch(_ENABLED, return_value=True):
            common._maybe_inject_computer_use(kwargs)
        beta = kwargs["extra_headers"]["anthropic-beta"]
        assert "context-management-2025-06-27" in beta
        assert "computer-use-2025-01-24" in beta

    def test_computer_tool_is_type_carrying_so_defer_exempt(self) -> None:
        """Defer skips type-carrying entries — the injected computer tool must
        survive a large toolset unshaped (never deferred behind the search tool)."""
        from core.llm.providers.anthropic import apply_tool_search_defer

        param = common.anthropic_computer_tool_param(TARGET_WIDTH, TARGET_HEIGHT)
        big = [
            {"name": f"t{i}", "description": "x", "input_schema": {"type": "object"}}
            for i in range(40)
        ]
        shaped = apply_tool_search_defer([*big, param])
        computer = next(t for t in shaped if t.get("name") == "computer")
        assert "defer_loading" not in computer


class TestComputerUseCapableContract:
    def test_live_anthropic_adapters_are_computer_use_capable(self) -> None:
        from core.llm.adapters.anthropic_oauth import AnthropicOAuthAdapter
        from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter

        assert isinstance(AnthropicOAuthAdapter(), ComputerUseCapable)
        assert isinstance(AnthropicPaygAdapter(), ComputerUseCapable)

    def test_adapter_param_matches_injected_param(self) -> None:
        """The enumerable contract (``computer_tool_param``) must return the
        exact payload the live builder injects — no drift between the two."""
        from core.llm.adapters.anthropic_oauth import AnthropicOAuthAdapter

        adapter = AnthropicOAuthAdapter()
        from_method = adapter.computer_tool_param(
            display_width=TARGET_WIDTH, display_height=TARGET_HEIGHT
        )
        with patch(_ENABLED, return_value=True):
            injected = next(
                t
                for t in common.build_create_kwargs(_req())["tools"]
                if t.get("name") == "computer"
            )
        assert from_method == injected

    def test_display_dims_unified_with_harness(self) -> None:
        """Single SoT: the live builder's dims are the harness TARGET dims."""
        assert common._COMPUTER_DISPLAY_WIDTH == TARGET_WIDTH
        assert common._COMPUTER_DISPLAY_HEIGHT == TARGET_HEIGHT
