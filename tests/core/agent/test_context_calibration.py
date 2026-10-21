"""In-turn context pressure is measured in provider tokens on every route.

Live evidence (2026-10-21, codex-oauth gpt-6-sol): eighteen 57,000-char hex
documents each cost ~31k provider tokens but only ~17k estimated tokens, so
requests reached 259,201 input tokens before the 4 chars/token estimate
crossed the 272K route's warning level.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from math import ceil
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.agent.context_manager import ContextWindowManager
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.tool_executor import ToolExecutor
from core.config import settings
from core.hooks import HookDecision, HookName, HookRegistry
from core.llm.adapters import bootstrap_builtins
from core.llm.adapters.base import AdapterCallRequest, AdapterCallResult, UsageSummary
from core.llm.adapters.codex_oauth import CodexOAuthAdapter
from core.llm.model_catalog import get_model_catalog_spec
from core.orchestration.context_budget import (
    MAX_OBSERVED_TOKEN_RATIO,
    TOKEN_RATIO_MIN_SAMPLE_TOKENS,
    calibrate_token_ratio,
    observed_prompt_tokens,
    resolve_request_context_budget,
)
from core.orchestration.context_monitor import CHARS_PER_TOKEN, estimate_tool_tokens

# Hex digest lines tokenize at ~1.85 chars/token (57,000 chars -> ~30,900).
_CHARS_PER_PROVIDER_TOKEN = 1.85
_ROUNDS = 18
_SYSTEM = "Offline dense-context regression."


def _codex_policy():
    return resolve_request_context_budget(
        AdapterCallRequest(model="gpt-6-sol", messages=()),
        provider=CodexOAuthAdapter.provider,
        source=CodexOAuthAdapter.source,
    )


def test_gpt_6_sol_codex_oauth_window_is_the_client_default() -> None:
    """The route resolves the Codex client window, not the 1.05M Platform window."""
    assert (CodexOAuthAdapter.provider, CodexOAuthAdapter.source) == ("openai", "subscription")
    policy = _codex_policy()
    assert (policy.context_window, policy.tier.name, policy.context_origin) == (
        272_000,
        "standard",
        "client_default",
    )
    assert policy.output_reserve_tokens == 20_000
    assert policy.effective_prompt_budget_tokens == 252_000
    assert (policy.warning_tokens, policy.critical_tokens) == (176_400, 226_800)
    assert get_model_catalog_spec(
        "gpt-6-sol", "openai", source="subscription"
    ).max_context_window == (872_000)
    platform = resolve_request_context_budget(
        AdapterCallRequest(model="gpt-6-sol", messages=(), max_tokens=32_768),
        provider="openai",
        source="payg",
    )
    assert (platform.context_window, platform.max_input_tokens) == (1_050_000, 922_000)


def test_observed_ratio_raises_estimates_and_shrinks_the_prune_budget() -> None:
    policy = _codex_policy()
    assert policy.apply_safety_margin(100_000) == 120_000
    calibrated = ContextWindowManager(hooks=None, quiet=True)
    calibrated._observed_token_ratio = 2.4
    dense = calibrated.calibrated(policy)
    assert dense.apply_safety_margin(100_000) == 240_000
    assert dense.prune_budget_tokens == int(policy.warning_tokens / 2.4)
    assert policy.prune_budget_tokens == int(policy.warning_tokens / policy.safety_margin)
    # A ratio below the static margin never lowers the estimate.
    calibrated._observed_token_ratio = 0.5
    assert calibrated.calibrated(policy).apply_safety_margin(100_000) == 120_000


def test_usage_calibration_counts_cache_and_ignores_small_or_compacted_samples() -> None:
    anthropic = UsageSummary(
        input_tokens=1_000, cached_input_tokens=40_000, cache_write_tokens=9_000
    )
    assert observed_prompt_tokens(anthropic, provider="anthropic") == 50_000
    openai = UsageSummary(input_tokens=50_000, cached_input_tokens=40_000)
    assert observed_prompt_tokens(openai, provider="openai-codex") == 50_000
    assert observed_prompt_tokens(UsageSummary(), provider="openai") is None
    assert calibrate_token_ratio(50_000, TOKEN_RATIO_MIN_SAMPLE_TOKENS - 1) is None
    assert calibrate_token_ratio(10**9, TOKEN_RATIO_MIN_SAMPLE_TOKENS) == MAX_OBSERVED_TOKEN_RATIO

    manager = ContextWindowManager(hooks=None, quiet=True)
    compacted = AdapterCallResult(
        text="",
        usage=anthropic,
        stop_reason="end_turn",
        anthropic_content=({"type": "compaction", "content": "summary"},),
    )
    manager.record_prompt_usage(compacted, raw_estimated_tokens=10_000, provider="anthropic")
    assert manager._observed_token_ratio == 0.0
    plain = AdapterCallResult(text="", usage=anthropic, stop_reason="end_turn")
    manager.record_prompt_usage(plain, raw_estimated_tokens=10_000, provider="anthropic")
    assert manager._observed_token_ratio == 5.0
    # The newest sample replaces the older one after dense history is compacted.
    lighter = AdapterCallResult(text="", usage=openai, stop_reason="end_turn")
    manager.record_prompt_usage(lighter, raw_estimated_tokens=40_000, provider="openai")
    assert manager._observed_token_ratio == 1.25


def _hex_document(index: int) -> str:
    """One 57,000-character file shaped like the live fixture."""
    return "\n".join(
        f"part{index} line {line:04d} {hashlib.sha256(f'{index}:{line}'.encode()).hexdigest()[:40]}"
        for line in range(1_000)
    )


def _provider_tokens(system: str, contents: list[Any], tools_chars: int = 0) -> int:
    chars = len(system) + tools_chars
    chars += sum(len(json.dumps(content, default=str)) for content in contents)
    return ceil(chars / _CHARS_PER_PROVIDER_TOKEN)


class _DenseCodexAdapter:
    """codex-oauth stand-in whose usage follows the dense tokenizer."""

    name = "codex-oauth"
    provider = CodexOAuthAdapter.provider
    source = CodexOAuthAdapter.source

    def __init__(self) -> None:
        self.sent: list[int] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        tokens = _provider_tokens(
            request.system_prompt,
            [message.content for message in request.messages],
            estimate_tool_tokens(request.tools) * CHARS_PER_TOKEN,
        )
        self.sent.append(tokens)
        return AdapterCallResult(
            text="Reading the next file.",
            usage=UsageSummary(input_tokens=tokens, output_tokens=88),
            stop_reason="end_turn",
        )


@pytest.mark.parametrize("scenario", ["mask", "compact", "prune"])
def test_dense_tool_rounds_on_codex_gpt_6_sol_stay_under_the_route_limit(
    scenario: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Warning maintenance fires before critical; no request exceeds the budget."""
    bootstrap_builtins()
    policy = _codex_policy()
    registry = HookRegistry()
    compactions: list[dict[str, Any]] = []

    async def observe(invocation: Any) -> HookDecision:
        compactions.append(dict(invocation.payload))
        return HookDecision()

    registry.register(HookName.PRE_COMPACT, observe, name="capture-pre")
    summary = AsyncMock(return_value="Earlier files were read; their hashes were recorded.")
    if scenario != "mask":
        monkeypatch.setattr(settings, "observation_mask_keep_rounds", 1_000)
    if scenario == "prune":
        summary.side_effect = RuntimeError("summary route unavailable")
        monkeypatch.setattr(
            "core.orchestration.context_monitor.summarize_tool_results",
            lambda _messages, _policy: (0, 0, 0),
        )
    monkeypatch.setattr("core.orchestration.compaction._call_summarize", summary)
    pruned: list[tuple[str, bool]] = []
    original_apply = ContextWindowManager._apply_overflow_strategy

    async def apply(
        self: ContextWindowManager, strategy: dict[str, Any], *args: Any, **kwargs: Any
    ):
        outcome = await original_apply(self, strategy, *args, **kwargs)
        if outcome.action == "prune" and outcome.status == "changed":
            pruned.append((str(strategy.get("trigger")), bool(strategy.get("hard"))))
        return outcome

    monkeypatch.setattr(ContextWindowManager, "_apply_overflow_strategy", apply)
    checks: list[tuple[int, int]] = []
    original_check = ContextWindowManager.check_context_overflow

    async def check(
        self: ContextWindowManager,
        system: str,
        messages: list[dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ):
        before = _provider_tokens(system, [message.get("content") for message in messages])
        await original_check(self, system, messages, *args, **kwargs)
        checks.append((before, _provider_tokens(system, [m.get("content") for m in messages])))

    monkeypatch.setattr(ContextWindowManager, "check_context_overflow", check)

    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers={}, hook_registry=registry),
        config=AgenticLoopConfig(
            source="subscription",
            allowed_tool_names=set(),
            system_prompt_override=_SYSTEM,
        ),
        model="gpt-6-sol",
        provider="openai",
        quiet=True,
    )
    adapter = _DenseCodexAdapter()
    loop._new_adapter = adapter
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Read part0..part17 one after another."}
    ]

    async def drive() -> None:
        for index in range(_ROUNDS):
            assert await loop._call_llm(_SYSTEM, messages, round_idx=index) is not None
            call_id = f"call-{index}"
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": "read_document",
                            "input": {"file_path": f"part{index}.txt"},
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": _hex_document(index),
                        }
                    ],
                }
            )
        assert await loop._call_llm(_SYSTEM, messages, round_idx=_ROUNDS) is not None

    asyncio.run(drive())

    assert len(adapter.sent) == len(checks) == _ROUNDS + 1
    # Unmaintained, this history would exceed the 272K window several times over.
    documents = [_hex_document(index) for index in range(_ROUNDS)]
    assert _provider_tokens(_SYSTEM, documents) > 2 * policy.context_window
    maintained = [before for before, after in checks if after < before]
    assert maintained, "context maintenance never ran"
    assert max(adapter.sent) <= policy.effective_prompt_budget_tokens
    if scenario == "prune":
        # Soft compaction failed at warning; the hard pass pruned at critical
        # before the request was sent.
        assert compactions[0]["trigger"] == "warning" and compactions[0]["hard"] is False
        assert pruned and all(hard for _trigger, hard in pruned)
        assert maintained[0] >= policy.critical_tokens * 0.9
        return
    # Maintenance begins near the warning level, never at critical.
    assert policy.warning_tokens * 0.9 <= maintained[0] < policy.critical_tokens
    assert max(adapter.sent) < policy.critical_tokens
    if scenario == "compact":
        assert summary.await_count >= 1
        assert compactions[0]["trigger"] == "warning" and compactions[0]["hard"] is False
