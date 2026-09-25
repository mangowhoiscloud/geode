"""Learning dispatch and context-exhausted terminal boundary regressions."""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.agent.loop.models import TerminationReason


@pytest.mark.parametrize("reason", [*TerminationReason, "future_terminal", None])
def test_final_turn_hooks_only_enrich_deliverable_outcomes(monkeypatch, reason):
    from core.agent.loop._lifecycle import _final_hook_payloads
    from core.agent.loop.models import AgenticResult
    from core.hooks.llm_extract_learning import make_llm_extract_handler
    from core.hooks.system import RuntimeEvent, RuntimeEventBus
    from core.memory.dreaming import make_dreaming_handler

    extract = AsyncMock(return_value="[correction] Preserve zero quantities. Why: zero is valid.")
    profile = MagicMock()
    dream_service = MagicMock()
    monkeypatch.setattr("core.hooks.llm_extract_learning._call_budget_llm", extract)
    loop = SimpleNamespace(
        model="test-model", _provider="openai", _session_id="test-session", _effort="high"
    )
    result = AgenticResult(
        text="The verifier rejected this answer; preserve zero quantities on the next attempt.",
        rounds=3,
        termination_reason=reason,
    )
    _session, payload, _metrics = _final_hook_payloads(
        loop, result, "Do not drop zero quantities.", verify_payload={"passed": False}
    )
    bus = RuntimeEventBus()
    for name, handler in (
        make_llm_extract_handler(profile_provider=lambda: profile),
        make_dreaming_handler(service=dream_service),
    ):
        bus.register(RuntimeEvent.TURN_COMPLETED, handler, name=name)
    try:
        dispatched = asyncio.run(bus.emit_async(RuntimeEvent.TURN_COMPLETED, payload))
        assert len(dispatched) == 2
        assert all(item.success for item in dispatched)
        if reason in {"natural", "forced_text", "actionable_partial"}:
            extract.assert_awaited_once()
            profile.add_learned_pattern.assert_called_once()
            dream_service.dream_session_background.assert_called_once_with(
                "test-session", provider="openai", model="test-model", effort="high"
            )
        else:
            extract.assert_not_awaited()
            profile.add_learned_pattern.assert_not_called()
            dream_service.dream_session_background.assert_not_called()
    finally:
        bus.close()


def test_skipped_extraction_does_not_consume_input_cursor(monkeypatch):
    from core.hooks.llm_extract_learning import make_llm_extract_handler
    from core.hooks.system import RuntimeEvent

    extract = AsyncMock(return_value="[correction] Preserve zero quantities. Why: zero is valid.")
    profile = MagicMock()
    monkeypatch.setattr("core.hooks.llm_extract_learning._call_budget_llm", extract)
    _name, handler = make_llm_extract_handler(profile_provider=lambda: profile)
    data = {
        "user_input": "Do not drop zero quantities when transforming inventory records.",
        "text": "The requested output must preserve zero quantities.",
    }
    asyncio.run(handler(RuntimeEvent.TURN_COMPLETED, data))
    extract.assert_not_awaited()
    asyncio.run(handler(RuntimeEvent.TURN_COMPLETED, {**data, "termination_reason": "natural"}))
    extract.assert_awaited_once()
    profile.add_learned_pattern.assert_called_once()


# ---------------------------------------------------------------------------
# llm_extract_learning — async + adapter dispatch + no direct SDK imports
# ---------------------------------------------------------------------------


def test_call_budget_llm_is_async() -> None:
    from core.hooks.llm_extract_learning import _call_budget_llm

    assert inspect.iscoroutinefunction(_call_budget_llm), (
        "_call_budget_llm must be async so it can await the central "
        "adapter dispatch — otherwise the hook handler can't bridge."
    )


def test_extract_handler_is_async() -> None:
    """``HookSystem.trigger_async`` (the TURN_COMPLETED firer) supports
    async handlers; the extract handler must be one so it can await
    the dispatch without a sync→async bridge."""
    from core.hooks.llm_extract_learning import make_llm_extract_handler

    _name, handler = make_llm_extract_handler()
    assert inspect.iscoroutinefunction(handler)


@pytest.mark.parametrize("effort", [None, "max"])
def test_extract_handler_preserves_turn_effort(
    monkeypatch: pytest.MonkeyPatch, effort: str | None
) -> None:
    from core.config import settings
    from core.hooks import HookEvent
    from core.hooks.llm_extract_learning import make_llm_extract_handler

    monkeypatch.setattr(settings, "agentic_effort", "low")
    dispatch = AsyncMock(return_value=SimpleNamespace(text="NONE"))
    monkeypatch.setattr("core.llm.adapters.dispatch.complete_text_via_adapters", dispatch)
    _name, handler = make_llm_extract_handler(lambda: SimpleNamespace())
    asyncio.run(
        handler(
            HookEvent.TURN_COMPLETED,
            {"user_input": "context" * 10, "effort": effort, "termination_reason": "natural"},
        )
    )
    dispatch.assert_awaited_once()
    assert dispatch.await_args.kwargs["effort"] == (effort or "low")
    assert settings.agentic_effort == "low"


def test_extract_helpers_no_longer_import_provider_sdks_directly() -> None:
    """Source-level pin: the legacy ``_call_glm_flash`` / ``_call_haiku``
    helpers (each instantiating a fresh sync SDK client) are gone; the
    module no longer ``import anthropic`` or ``import openai``
    standalone. The adapter dispatch encapsulates all SDK touch."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "hooks" / "llm_extract_learning.py"
    ).read_text(encoding="utf-8")
    assert "def _call_glm_flash" not in src and "def _call_haiku" not in src, (
        "Legacy direct-SDK helpers must be deleted — the dispatch chain owns provider selection."
    )
    assert "import anthropic" not in src, (
        "llm_extract_learning must not import anthropic directly anymore."
    )
    assert "import openai" not in src, (
        "llm_extract_learning must not import openai directly anymore."
    )
    assert "complete_text_via_adapters" in src


def test_extract_dispatch_uses_learning_extract_model_route() -> None:
    """Extraction must route through ``settings.learning_extract_model``
    rather than scanning a cross-provider order."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "hooks" / "llm_extract_learning.py"
    ).read_text(encoding="utf-8")
    assert "_resolve_provider(settings.learning_extract_model)" in src
    assert "prefer_provider=provider" in src
    assert "prefer_source=source" in src
    assert "provider_order" not in src


def test_extract_session_cursor_and_quota_do_not_bleed_between_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.hooks import HookEvent
    from core.hooks.llm_extract_learning import (
        _MAX_PER_SESSION,
        make_llm_extract_handler,
    )

    profile = MagicMock()
    profile.add_learned_pattern.return_value = True

    async def extract(*args: object, **kwargs: object) -> str:
        return "[preference] Keep responses concise. Why: explicit user preference"

    monkeypatch.setattr("core.hooks.llm_extract_learning._call_budget_llm", extract)
    ticks = iter(range(0, 31 * (_MAX_PER_SESSION + 2), 31))
    monkeypatch.setattr(
        "core.hooks.llm_extract_learning.time", SimpleNamespace(monotonic=lambda: next(ticks))
    )
    _name, handler = make_llm_extract_handler(lambda: profile)

    async def run() -> None:
        for index in range(_MAX_PER_SESSION):
            await handler(
                HookEvent.TURN_COMPLETED,
                {
                    "session_id": "session-a",
                    "termination_reason": "natural",
                    "user_input": f"preference {index} " + "x" * 50,
                    "text": "context " + "y" * 50,
                },
            )
        await handler(
            HookEvent.TURN_COMPLETED,
            {
                "session_id": "session-b",
                "termination_reason": "natural",
                "user_input": "new session preference " + "z" * 50,
                "text": "context " + "q" * 50,
            },
        )

    asyncio.run(run())
    assert profile.add_learned_pattern.call_count == _MAX_PER_SESSION + 1


# ---------------------------------------------------------------------------
# models._context_exhausted_message — async compatibility, no provider dispatch
# ---------------------------------------------------------------------------


def test_context_exhausted_message_is_async() -> None:
    from core.agent.loop.models import _context_exhausted_message

    assert inspect.iscoroutinefunction(_context_exhausted_message)


def test_context_exhausted_call_sites_are_awaited() -> None:
    """Every _context_exhausted_message call must await — a non-await would
    embed a coroutine object into the result text (visible UI bug).

    PR-LOOP-DESLOP folded the three duplicated recovery-failed tails into one
    ``_finalize_context_exhausted`` helper, so there is now a single call site;
    assert ALL occurrences are awaited (the real invariant) rather than pinning
    a fixed count of duplicates."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "_guards.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_context_exhausted_message"
    ]
    awaited = [node.value for node in ast.walk(tree) if isinstance(node, ast.Await)]
    assert calls, "expected at least one _context_exhausted_message call site"
    assert all(call in awaited for call in calls)
    assert all({"hooks", "correlation"} <= {kw.arg for kw in call.keywords} for call in calls)


@pytest.mark.parametrize("credential_source", ["api_key", "none", "oauth"])
def test_context_exhausted_terminal_preserves_history_without_model_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    credential_source: str,
) -> None:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig, _guards
    from core.agent.tool_executor import ToolExecutor
    from core.config import settings
    from core.memory.session_checkpoint import SessionCheckpoint

    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers={}, auto_approve=True),
        config=AgenticLoopConfig(source="payg"),
        model="gpt-5.6-sol",
        provider="openai",
        quiet=True,
    )
    loop._session_id = "exhausted-session"
    loop._checkpoint = SessionCheckpoint(tmp_path / "sessions")
    messages = [
        {"role": "user", "content": "Preserve my unfinished request."},
        {"role": "assistant", "content": "Partial work to keep."},
    ]
    monkeypatch.setattr(settings, "model", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "anthropic_credential_source", credential_source)
    dispatch = AsyncMock(return_value=SimpleNamespace(text="Automatically reset."))
    monkeypatch.setattr("core.llm.adapters.dispatch.complete_text_via_adapters", dispatch)
    loop._call_llm = AsyncMock(side_effect=AssertionError("Terminal must not call a model"))

    result = asyncio.run(_guards._finalize_context_exhausted(loop, "Continue", messages, 2))

    assert result.termination_reason is TerminationReason.CONTEXT_EXHAUSTED
    assert result.error == "context_exhausted"
    assert "exhausted" in result.text.lower()
    assert "new" in result.text.lower()
    assert "reset" not in result.text.lower()
    assert loop.context.messages == messages
    checkpoint = loop._checkpoint.load(loop._session_id)
    assert checkpoint is not None
    assert [(message["role"], message["content"]) for message in checkpoint.messages] == [
        (message["role"], message["content"]) for message in messages
    ]
    assert checkpoint.model == "gpt-5.6-sol"
    assert checkpoint.status == "active"
    assert checkpoint.round_idx == 3
    dispatch.assert_not_awaited()
    loop._call_llm.assert_not_awaited()
