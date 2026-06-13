"""openai-payg Responses API migration guards.

PR-OPENAI-RESPONSES (2026-06-13). ``acomplete``/``astream`` left Chat
Completions and joined the shared Responses builder
(``build_responses_kwargs``, ``backend="platform"``) that codex-oauth
already used — completing the migration ``acomplete_text``/
``aweb_search`` started, and putting openai-payg on the surface where
OpenAI ships new features (tool_search deferred loading is
Responses-only).
"""

from __future__ import annotations

from pathlib import Path

from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec

REPO_ROOT = Path(__file__).resolve().parents[4]


def _request(**overrides: object) -> AdapterCallRequest:
    request_kwargs: dict = {
        "model": "gpt-5.5",
        "messages": (Message(role="user", content="hi"),),
        "system_prompt": "test system",
        "max_tokens": 4096,
    }
    request_kwargs.update(overrides)
    return AdapterCallRequest(**request_kwargs)


def test_platform_backend_sends_max_output_tokens() -> None:
    """The Codex backend 400s on max_output_tokens; the platform API
    supports it — the backend param must carry exactly this delta."""
    platform = build_responses_kwargs(_request(), backend="platform", adapter_name="openai-payg")
    codex = build_responses_kwargs(_request(), backend="codex", adapter_name="codex-oauth")
    assert platform["max_output_tokens"] == 4096
    assert "max_output_tokens" not in codex


def test_platform_backend_shares_responses_shape_with_codex() -> None:
    """Everything except the max_output_tokens delta is one builder —
    instructions carry the system prompt, store=False, flat tools."""
    tool_specs = (ToolSpec(name="demo", description="demo", input_schema={"type": "object"}),)
    platform = build_responses_kwargs(
        _request(tools=tool_specs), backend="platform", adapter_name="openai-payg"
    )
    assert platform["instructions"] == "test system"
    assert platform["store"] is False
    flat_tool = platform["tools"][0]
    assert flat_tool["type"] == "function"
    assert flat_tool["name"] == "demo"
    assert "function" not in flat_tool, "Responses uses the FLAT shape, not Chat nesting"


def test_payg_adapter_module_has_left_chat_completions() -> None:
    """Source pin: the adapter must not fall back to chat.completions —
    Chat Completions now lives only on the GLM adapters."""
    adapter_source = (REPO_ROOT / "core" / "llm" / "adapters" / "openai_payg.py").read_text(
        encoding="utf-8"
    )
    assert "chat.completions" not in adapter_source
    assert "responses.stream" in adapter_source
    assert 'backend="platform"' in adapter_source


def test_reasoning_branch_applies_on_platform_backend() -> None:
    """gpt-5.x on the platform backend keeps the reasoning passthrough
    (encrypted content replay) exactly as on codex."""
    platform = build_responses_kwargs(
        _request(effort="high"), backend="platform", adapter_name="openai-payg"
    )
    assert platform["include"] == ["reasoning.encrypted_content"]
    assert platform["reasoning"]["effort"] == "high"
    assert "temperature" not in platform
