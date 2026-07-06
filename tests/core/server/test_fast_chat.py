from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from core.server.ipc_server.fast_chat import fast_chat_system_prompt, should_use_fast_chat


def test_fast_chat_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_FAST_CHAT", raising=False)
    assert should_use_fast_chat("자기소개 부탁해") is False


def test_fast_chat_accepts_short_conversational_prompt_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_FAST_CHAT", "1")
    assert should_use_fast_chat("자기소개 부탁해") is True
    assert should_use_fast_chat("what is GEODE?") is True


def test_fast_chat_rejects_agentic_actions_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_FAST_CHAT", "1")
    assert should_use_fast_chat("파일을 읽고 수정해") is False
    assert should_use_fast_chat("search the web and summarize") is False
    assert should_use_fast_chat("계획 세워서 진행해") is False


def test_fast_chat_system_prompt_preserves_geode_identity_without_you_are() -> None:
    system = fast_chat_system_prompt()
    assert "GEODE" in system
    assert "AgenticLoop" in system
    assert "generic API assistant" in system
    assert "You are" not in system


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
    assert "GEODE" in str(kwargs["system"])
    assert "You are" not in str(kwargs["system"])


def test_ipc_poller_fast_chat_emits_visible_status_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.llm.adapters.base import TextCompletionResult, UsageSummary
    from core.server.ipc_server.poller import CLIPoller

    async def fake_complete_text(_prompt: str, **_kwargs: object) -> TextCompletionResult:
        return TextCompletionResult(
            text="짧은 답변",
            usage=UsageSummary(input_tokens=10, output_tokens=3),
            adapter_name="fake",
            adapter_provider="openai",
            adapter_source="subscription",
        )

    class FakeClient:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        async def send_json_async(self, payload: dict[str, object]) -> None:
            self.events.append(payload)

        async def drain_pending_sends(self) -> None:
            return None

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
    client = FakeClient()

    result = asyncio.run(poller._run_fast_chat_async("자기소개 부탁해", loop, cast(Any, client)))

    assert result["type"] == "result"
    assert client.events[0]["type"] == "fast_chat_start"
    assert client.events[0]["provider"] == "openai"
    assert client.events[1]["type"] == "tokens"
