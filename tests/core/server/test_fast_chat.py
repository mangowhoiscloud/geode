from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from core.server.ipc_server.fast_chat import fast_chat_system_prompt, should_use_fast_chat


def test_fast_chat_accepts_short_conversational_prompt() -> None:
    assert should_use_fast_chat("자기소개 부탁해") is True
    assert should_use_fast_chat("what is GEODE?") is True


def test_fast_chat_rejects_agentic_actions() -> None:
    assert should_use_fast_chat("파일을 읽고 수정해") is False
    assert should_use_fast_chat("search the web and summarize") is False
    assert should_use_fast_chat("계획 세워서 진행해") is False


def test_fast_chat_system_prompt_carries_geode_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator report 2026-07-06 — fast-chat introduced itself as a generic
    'AI assistant used via API'. The prompt must carry the same GEODE.md
    identity block the full loop injects (G1 SoT), followed by the
    lightweight-mode constraints."""
    monkeypatch.delenv("GEODE_PERSONA", raising=False)
    prompt = fast_chat_system_prompt()
    assert "<agent_identity>" in prompt
    assert "GEODE" in prompt
    # mode constraints must FOLLOW the identity so they override its
    # tool-capability claims
    assert prompt.index("<agent_identity>") < prompt.index("lightweight chat mode")


def test_fast_chat_system_prompt_keeps_no_tool_claims_rule() -> None:
    """The original intent of the pre-identity pin — fast-chat must never
    claim tool execution — survives the identity injection."""
    prompt = fast_chat_system_prompt()
    assert "do not claim file inspection" in prompt.lower()
    assert "full agent path" in prompt.lower()


def test_fast_chat_system_prompt_honors_persona_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GEODE_PERSONA=off (thin-wrapper mode) strips the identity block from
    fast-chat exactly as it does from the full loop."""
    monkeypatch.setenv("GEODE_PERSONA", "off")
    prompt = fast_chat_system_prompt()
    assert "<agent_identity>" not in prompt
    assert "lightweight chat mode" in prompt


def test_ipc_poller_fast_chat_uses_text_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.llm.adapters.base import TextCompletionResult, UsageSummary
    from core.server.ipc_server.poller import CLIPoller

    calls: dict[str, object] = {}

    async def fake_complete_text(prompt: str, **kwargs: object) -> TextCompletionResult:
        calls["prompt"] = prompt
        calls["kwargs"] = kwargs
        return TextCompletionResult(
            text="짧은 답변",
            usage=UsageSummary(input_tokens=10, output_tokens=3),
            adapter_name="fake",
            adapter_provider="openai",
            adapter_source="subscription",
        )

    monkeypatch.setattr(
        "core.llm.adapters.dispatch.complete_text_via_adapters",
        fake_complete_text,
    )

    poller = CLIPoller(services=cast(Any, object()))
    loop = type(
        "Loop",
        (),
        {"model": "gpt-5.5", "_provider": "openai-codex", "_source": "subscription"},
    )()

    result = asyncio.run(poller._run_fast_chat_async("자기소개 부탁해", loop, None))

    assert result["type"] == "result"
    assert result["text"] == "짧은 답변"
    assert result["rounds"] == 0
    assert result["tool_calls"] == []
    assert result["fast_path"] == "simple_chat"
    assert calls["prompt"] == "자기소개 부탁해"
    kwargs = cast(dict[str, object], calls["kwargs"])
    assert kwargs["prefer_provider"] == "openai"
    assert kwargs["prefer_source"] == "subscription"
    # identity ships with the turn; the no-tool-claims rule rides after it
    assert "GEODE" in str(kwargs["system"])
    assert "do not claim file inspection" in str(kwargs["system"]).lower()
