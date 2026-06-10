"""PR-SIL-5THEME C5 — D4 X2 system-prompt model-identity injection telemetry.

`HookEvent.PROMPT_ASSEMBLED` 가 `core/hooks/system.py:69` 에 정의됐으나
fire 0회 였다 → X2 (Option B model identity injection,
``core/agent/system_prompt.py:337``) 가 매 round 마다 발화하지만 관측
marker 0. stale-ack purge 도 silent.

C5 가 2 wiring point 활성:
1. `_sync_model_and_rebuild_prompt` 가 rebuild 후 `PROMPT_ASSEMBLED` fire
   payload: {model, provider, reason, x2_injected, prompt_len}
2. `_inject_model_switch_breadcrumb` 가 purged count 반환 →
   `update_model_async` 가 `MODEL_SWITCHED` payload 에 동봉
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from core.agent.loop._model_switching import (
    _inject_model_switch_breadcrumb,
    purge_stale_model_switch_acks,
    update_model_async,
)
from core.hooks import HookEvent, HookSystem

# ---------------------------------------------------------------------------
# 1. purge_stale_model_switch_acks — returns purged count
# ---------------------------------------------------------------------------


class _FakeContext:
    """Minimal context for purge tests — mimics loop.context.messages contract."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = list(messages)

    @property
    def is_empty(self) -> bool:
        return not self.messages

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})


class _FakeLoop:
    """Minimal loop stand-in for _model_switching helpers."""

    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.context = _FakeContext(messages or [])

    def _purge_stale_model_switch_acks(self) -> int:
        return purge_stale_model_switch_acks(self)  # type: ignore[arg-type]


def test_purge_returns_zero_when_no_acks() -> None:
    """Clean history → purged count 0."""
    loop = _FakeLoop(messages=[{"role": "user", "content": "hi"}])
    assert purge_stale_model_switch_acks(loop) == 0  # type: ignore[arg-type]


def test_purge_returns_count_for_string_form_acks() -> None:
    """str-form `Understood. I am now ...` ack 가 N 개 → purge_count = N."""
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Understood. I am now gpt-5.4."},
        {"role": "user", "content": "follow-up"},
        {"role": "assistant", "content": "Understood. I am now gpt-5.5."},
    ]
    loop = _FakeLoop(messages=messages)
    assert purge_stale_model_switch_acks(loop) == 2  # type: ignore[arg-type]
    # 두 ack 모두 제거
    assert not any(
        isinstance(m.get("content"), str) and m["content"].startswith("Understood. I am now ")
        for m in loop.context.messages
    )


def test_purge_returns_count_for_block_form_acks() -> None:
    """Anthropic block-form `[{"type": "text", "text": "Understood. I am now …"}]`
    도 catch — PR-MIC 후속 case."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Understood. I am now claude-3."}],
        },
    ]
    loop = _FakeLoop(messages=messages)
    assert purge_stale_model_switch_acks(loop) == 1  # type: ignore[arg-type]


def test_purge_leaves_user_messages_untouched() -> None:
    """User message 가 ack-prefix 우연 matching 해도 절대 안 건드림 (보수적)."""
    messages = [
        {"role": "user", "content": "Understood. I am now confused."},
        {"role": "assistant", "content": "Understood. I am now gpt-5.5."},
    ]
    loop = _FakeLoop(messages=messages)
    purged = purge_stale_model_switch_acks(loop)  # type: ignore[arg-type]
    assert purged == 1  # only the assistant ack
    # User message 살아있음
    assert loop.context.messages[0]["role"] == "user"


# ---------------------------------------------------------------------------
# 2. _inject_model_switch_breadcrumb — forwards purged count
# ---------------------------------------------------------------------------


def test_inject_breadcrumb_returns_zero_for_empty_context() -> None:
    """빈 context → breadcrumb skip → purged count 0."""
    loop = _FakeLoop(messages=[])
    purged = _inject_model_switch_breadcrumb(loop, "old", "new")  # type: ignore[arg-type]
    assert purged == 0


def test_inject_breadcrumb_forwards_purged_count() -> None:
    """Non-empty context + 기존 ack 존재 → purged count 반환."""
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Understood. I am now gpt-5.4."},
    ]
    loop = _FakeLoop(messages=messages)
    purged = _inject_model_switch_breadcrumb(loop, "gpt-5.4", "gpt-5.5")  # type: ignore[arg-type]
    assert purged == 1


# ---------------------------------------------------------------------------
# 3. update_model_async — MODEL_SWITCHED payload includes purged_ack_count
# ---------------------------------------------------------------------------


def test_update_model_async_fires_model_switched_with_purged_count() -> None:
    """update_model_async 가 model 변경 시 MODEL_SWITCHED hook 발화 +
    payload 에 purged_ack_count 동봉. C5 의 핵심 wiring 검증."""
    hooks = HookSystem()
    received_payloads: list[dict[str, Any]] = []

    async def capture(_event: HookEvent, payload: dict[str, Any]) -> None:
        received_payloads.append(payload)

    hooks.register(HookEvent.MODEL_SWITCHED, capture)

    # Fake loop with prior stale ack — purge 가 1 count
    loop = MagicMock()
    loop.context = _FakeContext(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Understood. I am now gpt-5.4."},
        ]
    )
    loop._hooks = hooks
    loop._model = "gpt-5.4"
    loop._provider = "openai"
    loop._adapt_context_for_model = MagicMock()
    loop._purge_stale_model_switch_acks = lambda: purge_stale_model_switch_acks(loop)

    # _apply_model_update mock 으로 changed=True 강제
    from core.agent.loop import _model_switching as ms_module

    original_apply = ms_module._apply_model_update
    ms_module._apply_model_update = MagicMock(return_value=("gpt-5.4", True))
    try:
        # emit_model_switched 도 mock — UI 의존성 차단
        original_emit = None
        try:
            from core.ui import agentic_ui

            original_emit = agentic_ui.emit_model_switched
            agentic_ui.emit_model_switched = MagicMock()
        except (ImportError, AttributeError):
            pass

        asyncio.run(update_model_async(loop, "gpt-5.5", "openai", "user_switch"))

        if original_emit is not None:
            agentic_ui.emit_model_switched = original_emit
    finally:
        ms_module._apply_model_update = original_apply

    assert len(received_payloads) == 1
    payload = received_payloads[0]
    assert payload["from_model"] == "gpt-5.4"
    assert payload["to_model"] == "gpt-5.5"
    assert payload["reason"] == "user_switch"
    assert payload["purged_ack_count"] == 1  # stale ack 1 개 purge 됨


# ---------------------------------------------------------------------------
# 4. _sync_model_and_rebuild_prompt — fires PROMPT_ASSEMBLED hook
# ---------------------------------------------------------------------------


def test_sync_and_rebuild_fires_prompt_assembled_on_drift() -> None:
    """Model drift (settings.model 변경) 감지 시 PROMPT_ASSEMBLED 발화 +
    payload 에 model / provider / reason / x2_injected / prompt_len."""
    hooks = HookSystem()
    received: list[dict[str, Any]] = []

    async def capture(_event: HookEvent, payload: dict[str, Any]) -> None:
        received.append(payload)

    hooks.register(HookEvent.PROMPT_ASSEMBLED, capture)

    # Fake AgenticLoop
    loop = MagicMock()
    loop._hooks = hooks
    loop.model = "gpt-5.5"
    loop._provider = "openai"
    loop._prompt_dirty = False
    loop._sync_model_from_settings_async = AsyncMock(return_value=True)  # drift!
    loop._build_system_prompt = MagicMock(return_value="rebuilt system prompt body")

    # Manually invoke the bound method
    from core.agent.loop.agent_loop import AgenticLoop

    result = asyncio.run(AgenticLoop._sync_model_and_rebuild_prompt(loop, "old prompt", None))
    # rebuild 됐는지 — _build_system_prompt 가 호출됐는지 확인
    loop._build_system_prompt.assert_called_once()
    assert result == "rebuilt system prompt body"
    # hook 발화 확인
    assert len(received) == 1
    payload = received[0]
    assert payload["model"] == "gpt-5.5"
    assert payload["provider"] == "openai"
    assert payload["reason"] == "model_drift"
    assert payload["x2_injected"] is True
    assert payload["prompt_len"] == len("rebuilt system prompt body")


def test_sync_and_rebuild_fires_prompt_assembled_on_prompt_dirty() -> None:
    """_prompt_dirty=True 만 set 된 경우 (drift 없음) → reason='prompt_dirty'."""
    hooks = HookSystem()
    received: list[dict[str, Any]] = []

    async def capture(_event: HookEvent, payload: dict[str, Any]) -> None:
        received.append(payload)

    hooks.register(HookEvent.PROMPT_ASSEMBLED, capture)

    loop = MagicMock()
    loop._hooks = hooks
    loop.model = "claude-opus-4-7"
    loop._provider = "anthropic"
    loop._prompt_dirty = True  # dirty!
    loop._sync_model_from_settings_async = AsyncMock(return_value=False)  # no drift
    loop._build_system_prompt = MagicMock(return_value="rebuilt body")

    from core.agent.loop.agent_loop import AgenticLoop

    asyncio.run(AgenticLoop._sync_model_and_rebuild_prompt(loop, "old", None))
    assert received[0]["reason"] == "prompt_dirty"


def test_sync_and_rebuild_no_fire_when_no_drift_no_dirty() -> None:
    """drift / dirty 둘 다 False → rebuild skip + hook 미발화 (성능)."""
    hooks = HookSystem()
    received: list[dict[str, Any]] = []

    async def capture(_event: HookEvent, payload: dict[str, Any]) -> None:
        received.append(payload)

    hooks.register(HookEvent.PROMPT_ASSEMBLED, capture)

    loop = MagicMock()
    loop._hooks = hooks
    loop.model = "gpt-5.5"
    loop._provider = "openai"
    loop._prompt_dirty = False
    loop._sync_model_from_settings_async = AsyncMock(return_value=False)
    loop._build_system_prompt = MagicMock()

    from core.agent.loop.agent_loop import AgenticLoop

    result = asyncio.run(AgenticLoop._sync_model_and_rebuild_prompt(loop, "untouched", None))
    # rebuild 미발생
    loop._build_system_prompt.assert_not_called()
    assert result == "untouched"
    # hook 미발화
    assert received == []


def test_sync_and_rebuild_no_hook_when_loop_has_none_hooks() -> None:
    """``loop._hooks`` 가 None 일 때 (hook system 미초기화) graceful skip —
    rebuild 는 정상 진행, trigger 만 noop."""
    loop = MagicMock()
    loop._hooks = None
    loop.model = "gpt-5.5"
    loop._provider = "openai"
    loop._prompt_dirty = False
    loop._sync_model_from_settings_async = AsyncMock(return_value=True)
    loop._build_system_prompt = MagicMock(return_value="rebuilt")

    from core.agent.loop.agent_loop import AgenticLoop

    result = asyncio.run(AgenticLoop._sync_model_and_rebuild_prompt(loop, "old", None))
    assert result == "rebuilt"
    # 예외 없이 통과
