"""OpenAI Responses tool_search defer — request shaping guards.

PR-CODEX-TOOL-SEARCH (2026-06-13). Official OpenAI mechanism
(defer_loading + {"type": "tool_search"}, Responses-only, gpt-5.4+)
wired into the shared builder, policy SoT shared with Anthropic via
core.llm.tool_defer. Codex backend acceptance was
live-verified 2026-06-13 (DEFER-OK, gpt-5.5) so the codex gate defaults
ON with a kill switch.
"""

from __future__ import annotations

from unittest.mock import patch

from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec
from core.llm.tool_defer import TOOL_DEFER_THRESHOLD, TOOL_SEARCH_ALWAYS_LOADED


def _request(model: str = "gpt-5.5", tool_count: int = TOOL_DEFER_THRESHOLD + 5):
    tool_specs = [
        ToolSpec(name=name, description=f"{name} core", input_schema={"type": "object"})
        for name in sorted(TOOL_SEARCH_ALWAYS_LOADED)[:3]
    ]
    tool_specs += [
        ToolSpec(name=f"extra_{i}", description=f"extra {i}", input_schema={"type": "object"})
        for i in range(tool_count - 3)
    ]
    return AdapterCallRequest(
        model=model,
        messages=(Message(role="user", content="hi"),),
        tools=tuple(tool_specs),
    )


def _tool_names(kwargs: dict) -> list[str]:
    return [t.get("name", t.get("type", "?")) for t in kwargs["tools"]]


def test_platform_defers_above_threshold_on_supported_model() -> None:
    request_kwargs = build_responses_kwargs(
        _request(), backend="platform", adapter_name="openai-payg"
    )
    tools = request_kwargs["tools"]
    assert tools[-1] == {"type": "tool_search"}, "hosted search tool appended"
    deferred_names = {t["name"] for t in tools if t.get("defer_loading")}
    assert deferred_names and all(n.startswith("extra_") for n in deferred_names)
    loaded = {t.get("name") for t in tools if not t.get("defer_loading")}
    for core_name in sorted(TOOL_SEARCH_ALWAYS_LOADED)[:3]:
        assert core_name in loaded, "core set never defers"


def test_unsupported_model_never_defers() -> None:
    """o3 lacks tool_search (gpt-5.4+ only) — shaping must not fire."""
    request_kwargs = build_responses_kwargs(
        _request(model="o3"), backend="platform", adapter_name="openai-payg"
    )
    assert not any(t.get("defer_loading") for t in request_kwargs["tools"])
    assert {"type": "tool_search"} not in request_kwargs["tools"]


def test_codex_backend_on_by_default_post_live_gate() -> None:
    """Codex backend acceptance was live-verified 2026-06-13 (DEFER-OK on
    gpt-5.5) — default ON since; _settings.py carries the attestation."""
    request_kwargs = build_responses_kwargs(_request(), backend="codex", adapter_name="codex-oauth")
    assert request_kwargs["tools"][-1] == {"type": "tool_search"}


def test_codex_backend_kill_switch() -> None:
    from core.config import settings

    with patch.object(settings, "tool_search_defer_codex", False):
        request_kwargs = build_responses_kwargs(
            _request(), backend="codex", adapter_name="codex-oauth"
        )
    assert not any(t.get("defer_loading") for t in request_kwargs["tools"])
    assert {"type": "tool_search"} not in request_kwargs["tools"]


def test_web_named_tool_never_defers() -> None:
    """Upstream 500: deferred function named "web" + tool_search +
    web_search (community.openai.com/t/.../1375850) — blocklisted."""
    base_request = _request()
    tool_specs = (
        *base_request.tools,
        ToolSpec(name="web", description="web tool", input_schema={"type": "object"}),
    )
    request_kwargs = build_responses_kwargs(
        AdapterCallRequest(model="gpt-5.5", messages=base_request.messages, tools=tool_specs),
        backend="platform",
        adapter_name="openai-payg",
    )
    web_tool = next(t for t in request_kwargs["tools"] if t.get("name") == "web")
    assert "defer_loading" not in web_tool


def test_shaping_is_idempotent() -> None:
    first = build_responses_kwargs(_request(), backend="platform", adapter_name="openai-payg")
    # feed the shaped tools back through the helper directly
    from core.llm.adapters._openai_common import (
        _apply_openai_tool_search_defer,
        get_openai_model_spec,
    )

    reshaped = _apply_openai_tool_search_defer(
        first["tools"],
        backend="platform",
        spec=get_openai_model_spec("gpt-5.5"),
        adapter_name="openai-payg",
    )
    assert reshaped is first["tools"]
