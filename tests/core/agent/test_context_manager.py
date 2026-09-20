"""Tests for ContextWindowManager — extracted from AgenticLoop."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.agent.context_manager import ContextWindowManager
from core.agent.loop import _ContextExhaustedError
from core.hooks import HookAction, HookDecision, HookName, HookRegistry


class TestContextWindowManager:
    """Test context window management logic."""

    def _make_mgr(self, *, quiet: bool = True) -> ContextWindowManager:
        return ContextWindowManager(hooks=None, quiet=quiet)

    @pytest.mark.parametrize(
        "replay_key", ["anthropic_content", "codex_output_items", "codex_reasoning_items"]
    )
    @pytest.mark.parametrize("hard", [False, True])
    def test_native_replay_pressure_reaches_existing_recovery(self, replay_key, hard, monkeypatch):
        from core.orchestration.context_budget import resolve_context_budget_policy
        from core.orchestration.context_monitor import CHARS_PER_TOKEN, check_context

        monkeypatch.delenv("GEODE_CODEX_DISABLE_OUTPUT_REPLAY", raising=False)
        anthropic = replay_key == "anthropic_content"
        model, provider = (
            ("claude-fable-5", "anthropic") if anthropic else ("gpt-5.6-sol", "openai")
        )
        policy = resolve_context_budget_policy(model)
        target = (
            policy.critical_tokens + 1000
            if hard
            else (policy.warning_tokens + policy.critical_tokens) // 2
        )
        chars = (
            int(target / policy.safety_margin - policy.default_tools_overhead_tokens)
            * CHARS_PER_TOKEN
        )
        replay = (
            [{"type": "thinking", "thinking": "r" * chars, "signature": "signed"}]
            if anthropic
            else [
                {"type": "reasoning", "encrypted_content": "r" * chars, "summary": []},
            ]
        )
        original = deepcopy(replay)
        messages = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "earlier", replay_key: replay},
            *[
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"recent-{i}"}
                for i in range(20)
            ],
        ]
        metrics = check_context(messages, model)
        assert metrics.is_warning
        assert metrics.is_critical is hard
        summarize = AsyncMock(
            return_value="Earlier task context.",
            side_effect=RuntimeError("synthetic compaction failure") if hard else None,
        )
        with patch("core.orchestration.compaction._call_summarize", summarize):
            asyncio.run(self._make_mgr().check_context_overflow("", messages, model, provider))
        if anthropic:
            summarize.assert_not_awaited()  # Native warning policy remains server-side.
        else:
            summarize.assert_awaited()
        if hard or not anthropic:
            assert not check_context(messages, model).is_warning
            assert not any(message.get(replay_key) is replay for message in messages)
        else:
            assert messages[1][replay_key] is replay
        assert replay == original  # Only whole old messages may be removed.

    @pytest.mark.parametrize(
        "replay_key", ["anthropic_content", "codex_output_items", "codex_reasoning_items"]
    )
    def test_unfit_native_replay_stops_without_rewriting_signed_payload(
        self, replay_key, monkeypatch
    ):
        from core.orchestration.context_budget import resolve_context_budget_policy
        from core.orchestration.context_monitor import CHARS_PER_TOKEN, check_context

        monkeypatch.delenv("GEODE_CODEX_DISABLE_OUTPUT_REPLAY", raising=False)
        anthropic = replay_key == "anthropic_content"
        model, provider = (
            ("claude-fable-5", "anthropic") if anthropic else ("gpt-5.6-sol", "openai")
        )
        policy = resolve_context_budget_policy(model)
        chars = policy.critical_tokens * CHARS_PER_TOKEN
        tool = {"type": "tool_use", "id": "c", "name": "read_file", "input": {}}
        replay = (
            [{"type": "thinking", "thinking": "r" * chars, "signature": "signed"}, tool]
            if anthropic
            else [
                {"type": "reasoning", "encrypted_content": "r" * chars, "summary": []},
            ]
        )
        if replay_key == "codex_output_items":
            replay.append(
                {"type": "function_call", "call_id": "c", "name": "read_file", "arguments": "{}"}
            )
        original = deepcopy(replay)
        messages = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": [tool], replay_key: replay},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "c", "content": "done"}],
            },
        ]
        assert check_context(messages, model).is_critical
        with (
            patch("core.orchestration.compaction._call_summarize", AsyncMock()) as summarize,
            pytest.raises(_ContextExhaustedError, match="Context exhausted"),
        ):
            asyncio.run(self._make_mgr().check_context_overflow("", messages, model, provider))
        summarize.assert_not_awaited()
        assert messages[1][replay_key] == original

    @pytest.mark.parametrize("hard", [False, True])
    def test_chat_replay_pressure_reaches_warning_or_hard_recovery(self, hard: bool) -> None:
        from core.orchestration.context_monitor import check_context

        replay = {
            "provider": "glm",
            "source": "glm-payg",
            "model": "glm-5",
            "fields": {"reasoning_content": "r" * (800_000 if hard else 320_000)},
        }
        original = deepcopy(replay)
        messages = [
            {"role": "user", "content": "original task"},
            {"role": "assistant", "content": "earlier", "chat_reasoning": replay},
            *[
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"recent-{i}"}
                for i in range(20)
            ],
        ]
        metrics = check_context(messages, "glm-5")
        assert metrics.is_warning
        assert metrics.is_critical is hard
        summarize = AsyncMock(
            return_value="Earlier task context.",
            side_effect=RuntimeError("synthetic compaction failure") if hard else None,
        )
        with patch("core.orchestration.compaction._call_summarize", summarize):
            asyncio.run(self._make_mgr().check_context_overflow("", messages, "glm-5", "glm"))

        summarize.assert_awaited()
        assert not check_context(messages, "glm-5").is_warning
        assert not any(message.get("chat_reasoning") is replay for message in messages)
        assert replay == original  # Old messages are removed whole, never partially rewritten.

    def test_unfit_latest_chat_replay_stops_without_rewriting_signed_sequence(self) -> None:
        replay = {
            "provider": "openrouter",
            "source": "openrouter-payg",
            "model": "anthropic/claude-fable-5",
            "fields": {
                "reasoning_details": [
                    {"type": "reasoning.text", "text": "first", "signature": "signed"},
                    {"type": "reasoning.encrypted", "data": "opaque" * 160_000},
                ]
            },
        }
        original = deepcopy(replay)
        messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "c", "name": "read_file", "input": {}}],
                "chat_reasoning": replay,
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "c", "content": "done"}],
            },
        ]
        with (
            patch("core.orchestration.compaction._call_summarize", AsyncMock()) as summarize,
            pytest.raises(_ContextExhaustedError, match="Context exhausted"),
        ):
            asyncio.run(
                self._make_mgr().check_context_overflow(
                    "", messages, "openrouter/anthropic/claude-fable-5", "openrouter"
                )
            )

        summarize.assert_not_awaited()
        assert messages[1]["chat_reasoning"] == original

    @pytest.mark.parametrize("shape", ["anthropic", "openai"])
    @pytest.mark.parametrize("recovery", ["compact", "failed_compact", "prune"])
    def test_fresh_skill_survives_compaction_and_hard_prune_fallback(
        self, shape: str, recovery: str
    ) -> None:
        body = "IMPORTANT_RULE " + "x" * 16_000
        arguments = {"name": "demo"}
        if shape == "anthropic":
            tail = [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "skill", "name": "use_skill", "input": arguments}
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "skill", "content": body}],
                },
            ]
        else:
            tail = [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "skill",
                            "type": "function",
                            "function": {"name": "use_skill", "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "skill", "content": body},
            ]
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"old-{i}"}
            for i in range(20)
        ] + tail
        summarize = AsyncMock(
            return_value="Earlier task context.",
            side_effect=RuntimeError("synthetic summary failure")
            if recovery == "failed_compact"
            else None,
        )
        mgr = self._make_mgr()
        with patch("core.orchestration.compaction._call_summarize", summarize):
            result = asyncio.run(
                mgr._apply_overflow_strategy(
                    {
                        "strategy": "prune" if recovery == "prune" else "compact",
                        "keep_recent": 1,
                        "hard": True,
                    },
                    messages,
                    SimpleNamespace(compact_keep_recent=1),
                    "gpt-5.6-sol",
                    "openai",
                )
            )

        assert result.status == "changed"
        assert messages[-2:] == tail

    def test_warning_maintenance_does_not_summarize_unread_skill(self) -> None:
        body = "IMPORTANT_RULE " + "x" * 16_000
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "skill",
                        "name": "use_skill",
                        "input": {"name": "demo"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "skill", "content": body}],
            },
        ]
        metrics = SimpleNamespace(
            estimated_tokens=100_000,
            context_window=200_000,
            usage_pct=50.0,
            is_warning=True,
            is_critical=False,
            is_ceiling_exceeded=False,
            policy=None,
        )
        with patch("core.orchestration.context_monitor.check_context", return_value=metrics):
            asyncio.run(
                self._make_mgr().check_context_overflow(
                    "system", messages, "claude-opus-4-8", "anthropic"
                )
            )

        assert messages[-1]["content"][0]["content"] == body

    @pytest.mark.parametrize("hard", [False, True])
    @pytest.mark.parametrize("raises", [False, True])
    def test_failed_compaction_prunes_only_at_hard_boundary(self, hard: bool, raises: bool) -> None:
        registry = HookRegistry()
        post = MagicMock(return_value=None)
        registry.register(HookName.POST_COMPACT, post)
        mgr = ContextWindowManager(hooks=None, hook_registry=registry, quiet=True)
        original = [
            {"role": "assistant" if i % 2 else "user", "content": f"m{i}"} for i in range(20)
        ]
        messages = list(original)
        compact = AsyncMock(
            side_effect=OSError("disk full") if raises else None,
            return_value=(messages, False),
        )
        with patch("core.orchestration.compaction.compact_conversation", compact):
            asyncio.run(
                mgr._apply_overflow_strategy(
                    {"strategy": "compact", "hard": hard, "trigger": "test"},
                    messages,
                    SimpleNamespace(compact_keep_recent=4),
                    "gpt-5.6-sol",
                    "openai",
                )
            )
        assert messages == ([original[0], *original[-4:]] if hard else original)
        post.assert_not_called()

    # -- repair_messages --

    def test_repair_no_orphans(self) -> None:
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
            },
        ]
        original_len = len(msgs)
        ContextWindowManager.repair_messages(msgs)
        assert len(msgs) == original_len

    def test_repair_removes_orphan(self) -> None:
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t99", "content": "orphan"}],
            },
        ]
        ContextWindowManager.repair_messages(msgs)
        # Orphaned tool_result should be removed
        assert len(msgs) < 3

    # -- _notify_context_event --

    def test_notify_quiet_mode_no_error(self) -> None:
        """Quiet mode should not raise even with no UI available."""
        mgr = self._make_mgr(quiet=True)
        mgr._notify_context_event("prune", original_count=10, new_count=5)

    # -- _resolve_overflow_strategy --

    def test_resolve_strategy_anthropic_no_action(self) -> None:
        """Anthropic below policy critical pressure should return 'none'."""

        class FakeMetrics:
            usage_pct = 60.0
            context_window = 200_000

        class FakeSettings:
            compact_keep_recent = 8

        mgr = self._make_mgr()
        result = asyncio.run(
            mgr._resolve_overflow_strategy(FakeMetrics(), FakeSettings(), "claude-3", "anthropic")
        )
        assert result["strategy"] == "none"

    def test_resolve_strategy_openai_compact(self) -> None:
        """OpenAI at policy warning pressure should trigger compact."""

        class FakeMetrics:
            usage_pct = 60.0
            context_window = 200_000

        class FakeSettings:
            compact_keep_recent = 8

        mgr = self._make_mgr()
        result = asyncio.run(
            mgr._resolve_overflow_strategy(FakeMetrics(), FakeSettings(), "gpt-4o", "openai")
        )
        assert result["strategy"] == "compact"

    def test_resolve_strategy_compact_at_critical_for_openai(self) -> None:
        """Non-Anthropic critical pressure should try LLM compaction before prune."""

        class FakeMetrics:
            usage_pct = 96.0
            context_window = 200_000

        class FakeSettings:
            compact_keep_recent = 8

        mgr = self._make_mgr()
        result = asyncio.run(
            mgr._resolve_overflow_strategy(FakeMetrics(), FakeSettings(), "gpt-4o", "openai")
        )
        assert result["strategy"] == "compact"

    def test_check_context_overflow_awaits_compaction_inside_running_loop(self) -> None:
        """Compaction should be awaited, not driven via run_until_complete."""
        owner = SimpleNamespace(effort="low")
        mgr = ContextWindowManager(hooks=None, quiet=True, effort_provider=lambda: owner.effort)
        owner.effort = "max"
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"},
        ]
        compacted = [{"role": "user", "content": "compacted"}]

        warning_metrics = SimpleNamespace(
            estimated_tokens=170_000,
            context_window=200_000,
            usage_pct=85.0,
            remaining_tokens=30_000,
            is_warning=True,
            is_critical=False,
            is_ceiling_exceeded=False,
        )
        settings = MagicMock()
        settings.compact_keep_recent = 8
        settings.observation_mask_keep_rounds = 3
        compact = AsyncMock(return_value=(compacted, True))

        async def _run() -> None:
            with (
                patch(
                    "core.orchestration.context_monitor.check_context", return_value=warning_metrics
                ),
                patch("core.orchestration.context_monitor.mask_stale_observations", return_value=0),
                patch("core.orchestration.compaction.compact_conversation", compact),
                patch("core.config.settings", settings),
            ):
                await mgr.check_context_overflow("system", messages, "gpt-4o", "openai")

        asyncio.run(_run())

        compact.assert_awaited_once()
        assert compact.await_args.kwargs["effort"] == "max"
        assert messages == compacted

    def test_soft_pre_compact_can_defer(self) -> None:
        registry = HookRegistry()
        registry.register(
            HookName.PRE_COMPACT,
            lambda _invocation: HookDecision(action=HookAction.DEFER),
        )
        mgr = ContextWindowManager(hooks=None, hook_registry=registry, quiet=True)
        messages = [{"role": "user", "content": "old"}] * 20
        settings = SimpleNamespace(compact_keep_recent=8)

        asyncio.run(
            mgr._apply_overflow_strategy(
                {"strategy": "compact", "trigger": "warning"},
                messages,
                settings,
                "gpt-5",
                "openai",
            )
        )

        assert len(messages) == 20

    def test_post_compact_fires_only_after_commit(self) -> None:
        observed: list[HookName] = []
        registry = HookRegistry()
        registry.register(
            HookName.PRE_COMPACT,
            lambda invocation: (
                observed.append(invocation.name)
                or HookDecision(
                    action=HookAction.REWRITE,
                    updates={"keep_recent": 6},
                )
            ),
        )
        registry.register(
            HookName.POST_COMPACT,
            lambda invocation: observed.append(invocation.name),
        )
        mgr = ContextWindowManager(hooks=None, hook_registry=registry, quiet=True)
        messages = [{"role": "user", "content": "old"}] * 20
        settings = SimpleNamespace(compact_keep_recent=8)
        compact = AsyncMock(return_value=([{"role": "user", "content": "summary"}], True))

        async def _run() -> None:
            with patch("core.orchestration.compaction.compact_conversation", compact):
                await mgr._apply_overflow_strategy(
                    {"strategy": "compact", "trigger": "warning"},
                    messages,
                    settings,
                    "gpt-5",
                    "openai",
                )

        asyncio.run(_run())

        assert observed == [HookName.PRE_COMPACT, HookName.POST_COMPACT]
        assert compact.await_args.kwargs["keep_recent"] == 6

    def test_check_context_overflow_raises_context_exhausted(self) -> None:
        """Unrecoverable critical context should propagate to AgenticLoop."""
        mgr = self._make_mgr()
        metrics = SimpleNamespace(
            estimated_tokens=198_000,
            context_window=200_000,
            usage_pct=99.0,
            remaining_tokens=2_000,
            is_warning=True,
            is_critical=True,
            is_ceiling_exceeded=False,
        )
        settings = MagicMock()
        settings.compact_keep_recent = 8

        async def _run() -> None:
            with (
                patch("core.orchestration.context_monitor.check_context", return_value=metrics),
                patch(
                    "core.orchestration.context_monitor.prune_oldest_messages",
                    side_effect=lambda m, **kw: m,
                ),
                patch("core.config.settings", settings),
            ):
                await mgr.check_context_overflow(
                    "system", [{"role": "user", "content": "too much"}], "gpt-4o", "openai"
                )

        try:
            asyncio.run(_run())
        except _ContextExhaustedError:
            return
        raise AssertionError("expected _ContextExhaustedError")


def test_overflow_compaction_session_provider_reads_loop_session_id() -> None:
    """The ctx manager's session provider must resolve the loop's REAL
    session id attribute (_session_id) — a getattr on a non-existent public
    name silently disables context_artifacts persistence (writer-reader parity)."""
    from unittest.mock import MagicMock

    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor

    loop = AgenticLoop(
        ConversationContext(max_turns=2),
        ToolExecutor(action_handlers={"noop": MagicMock(return_value={})}),
        quiet=True,
    )
    provider = loop._ctx_mgr._session_id_provider
    assert provider is not None
    assert provider() == (loop._session_id or None)
    loop._session_id = "s-test123"
    assert provider() == "s-test123"
