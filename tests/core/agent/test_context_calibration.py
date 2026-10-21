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
from dataclasses import replace
from math import ceil
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from core.agent.context_manager import ContextWindowManager
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig, _context
from core.agent.loop.models import _ContextExhaustedError
from core.agent.tool_executor import ToolExecutor
from core.config import settings
from core.hooks import HookDecision, HookName, HookRegistry
from core.llm.adapters import bootstrap_builtins
from core.llm.adapters.base import AdapterCallRequest, AdapterCallResult, UsageSummary
from core.llm.adapters.codex_oauth import CodexOAuthAdapter
from core.llm.model_catalog import get_model_catalog_spec
from core.orchestration.context_budget import (
    DENSE_TOKEN_RATIO_FLOOR,
    MAX_OBSERVED_TOKEN_RATIO,
    TOKEN_RATIO_MIN_SAMPLE_TOKENS,
    next_prompt_calibration,
    observed_prompt_tokens,
    resolve_request_context_budget,
)
from core.orchestration.context_monitor import CHARS_PER_TOKEN, check_context, estimate_tool_tokens
from openai import BadRequestError

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


def test_calibration_prices_measured_payloads_and_floors_unmeasured_text() -> None:
    policy = _codex_policy()
    assert policy.apply_safety_margin(100_000) == 120_000
    first = next_prompt_calibration(
        None, observed_tokens=40_000, raw_tokens=20_000, payloads=[(1, 40_000)]
    )
    assert first is not None and first.request_ratio == first.overhead_ratio == 2.0
    dense = replace(policy, calibration=first)
    assert dense.prune_budget_tokens == int(policy.warning_tokens / 2.0)
    assert policy.prune_budget_tokens == int(policy.warning_tokens / policy.safety_margin)
    # The measured payload keeps its ratio; unmeasured text never drops
    # below the dense floor; the remainder uses the shared ratio.
    estimate = dense.estimate_prompt_tokens(30_000, [(1, 40_000), (2, 40_000)])
    assert estimate == ceil(10_000 * 2.0 + 10_000 * DENSE_TOKEN_RATIO_FLOOR + 10_000 * 2.0)
    prose = next_prompt_calibration(
        None, observed_tokens=10_000, raw_tokens=10_000, payloads=[(1, 30_000)]
    )
    assert prose is not None
    light = replace(policy, calibration=prose)
    assert light.estimate_prompt_tokens(10_000, [(1, 30_000)]) == 12_000
    assert light.estimate_prompt_tokens(10_000, [(9, 30_000)]) == ceil(
        2_500 * 1.2 + 7_500 * DENSE_TOKEN_RATIO_FLOOR
    )


def test_attribution_keeps_each_payload_ratio_after_history_shrinks() -> None:
    prose = next_prompt_calibration(
        None, observed_tokens=100_000, raw_tokens=100_000, payloads=[(1, 360_000)]
    )
    # 40K heuristic tokens of dense text cost 86K provider tokens.
    mixed = next_prompt_calibration(
        prose,
        observed_tokens=186_000,
        raw_tokens=140_000,
        payloads=[(1, 360_000), (2, 160_000)],
        other_keys=[3],
    )
    assert mixed is not None
    ratios = dict(mixed.payload_ratios)
    assert ratios[1] == 1.0 and ratios[2] == pytest.approx(86_000 / 40_000)
    assert ratios[3] == mixed.request_ratio
    # Compacting the prose away leaves the dense payload at its own price,
    # not at the 1.33 whole-request average.
    policy = replace(_codex_policy(), calibration=mixed)
    assert policy.estimate_prompt_tokens(40_000, [(2, 160_000)]) >= 86_000
    assert (
        next_prompt_calibration(
            mixed, observed_tokens=9_000, raw_tokens=TOKEN_RATIO_MIN_SAMPLE_TOKENS - 1, payloads=[]
        )
        is mixed
    )


def test_usage_calibration_counts_cache_and_ignores_compacted_samples() -> None:
    anthropic = UsageSummary(
        input_tokens=1_000, cached_input_tokens=40_000, cache_write_tokens=9_000
    )
    assert observed_prompt_tokens(anthropic, provider="anthropic") == 50_000
    openai = UsageSummary(input_tokens=50_000, cached_input_tokens=40_000)
    assert observed_prompt_tokens(openai, provider="openai-codex") == 50_000
    assert observed_prompt_tokens(UsageSummary(), provider="openai") is None
    huge = next_prompt_calibration(
        None, observed_tokens=10**9, raw_tokens=TOKEN_RATIO_MIN_SAMPLE_TOKENS, payloads=[]
    )
    assert huge is not None and huge.request_ratio == MAX_OBSERVED_TOKEN_RATIO

    manager = ContextWindowManager(hooks=None, quiet=True)
    compacted = AdapterCallResult(
        text="",
        usage=anthropic,
        stop_reason="end_turn",
        anthropic_content=({"type": "compaction", "content": "summary"},),
    )
    manager.record_prompt_usage(
        compacted, raw_estimated_tokens=10_000, provider="anthropic", payloads=[]
    )
    assert manager._calibration is None
    plain = AdapterCallResult(text="", usage=anthropic, stop_reason="end_turn")
    manager.record_prompt_usage(
        plain, raw_estimated_tokens=10_000, provider="anthropic", payloads=[]
    )
    assert manager._calibration is not None and manager._calibration.request_ratio == 5.0
    policy = _codex_policy()
    assert manager.calibrated(policy).calibration is manager._calibration


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


_HEX = set("0123456789abcdef")
_WINDOW = 272_000


def _leaf_tokens(text: str) -> float:
    """Hex-heavy text costs ~1.85 chars/token; prose ~4."""
    hex_share = sum(char in _HEX for char in text) / max(len(text), 1)
    return len(text) / (_CHARS_PER_PROVIDER_TOKEN if hex_share > 0.6 else CHARS_PER_TOKEN)


def _mixed_provider_tokens(request: AdapterCallRequest) -> int:
    leaves: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            leaves.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    for message in request.messages:
        walk(message.content)
    chars = len(request.system_prompt) + estimate_tool_tokens(request.tools) * CHARS_PER_TOKEN
    chars += sum(len(json.dumps(message.content, default=str)) for message in request.messages)
    framing = chars - sum(len(leaf) for leaf in leaves)
    return ceil(framing / CHARS_PER_TOKEN + sum(_leaf_tokens(leaf) for leaf in leaves))


class _WindowedAdapter:
    """codex-oauth stand-in that rejects requests over the 272K window."""

    name = "codex-oauth"
    provider = CodexOAuthAdapter.provider
    source = CodexOAuthAdapter.source

    def __init__(self) -> None:
        self.sent: list[int] = []
        self.rejected: list[int] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        tokens = _mixed_provider_tokens(request)
        if tokens > _WINDOW:
            self.rejected.append(tokens)
            raise BadRequestError(
                "maximum context length exceeded",
                response=httpx.Response(
                    400, request=httpx.Request("POST", "https://offline.invalid")
                ),
                body={"error": {"code": "context_length_exceeded"}},
            )
        self.sent.append(tokens)
        return AdapterCallResult(
            text="Next.",
            usage=UsageSummary(input_tokens=tokens, output_tokens=40),
            stop_reason="end_turn",
        )


def _windowed_loop(monkeypatch: pytest.MonkeyPatch) -> tuple[AgenticLoop, _WindowedAdapter]:
    bootstrap_builtins()
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    summary = AsyncMock(side_effect=AssertionError("a 3-message history has nothing to compact"))
    monkeypatch.setattr("core.orchestration.compaction._call_summarize", summary)
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers={}),
        config=AgenticLoopConfig(
            source="subscription", allowed_tool_names=set(), system_prompt_override=_SYSTEM
        ),
        model="gpt-6-sol",
        provider="openai",
        quiet=True,
    )
    adapter = _WindowedAdapter()
    loop._new_adapter = adapter
    return loop, adapter


def _prose_prompt() -> str:
    """About 100K provider tokens of ordinary text (ratio ~1.0)."""
    words = "the quarterly review covers planning, staffing and travel for every region "
    return (words * (400_000 // len(words) + 1))[:400_000]


def _dense_batch(policy: Any) -> list[dict[str, Any]]:
    """Seventeen hex results, each just under the summary and offload limits."""
    calls, results = [], []
    for index in range(17):
        call_id = f"call-{index}"
        lines = " ".join(
            hashlib.sha256(f"{index}:{line}".encode()).hexdigest()[:40] for line in range(600)
        )
        result: dict[str, Any] = {"file_path": f"part{index}.txt"}
        if index == 3:
            result |= {
                "error": "read stopped after partial output",
                "recoverable": True,
                "effect_applied": False,
                "error_type": "io",
            }
        result["content"] = lines
        content = json.dumps(result)
        content = json.dumps({**result, "content": lines[: len(lines) - (len(content) - 19_700)]})
        block = {"type": "tool_result", "tool_use_id": call_id, "content": content}
        assert len(content) <= 19_754
        assert len(json.dumps(block)) // CHARS_PER_TOKEN <= policy.tool_summary_threshold_tokens
        calls.append({"type": "tool_use", "id": call_id, "name": "read_document", "input": {}})
        results.append(block)
    return [{"role": "assistant", "content": calls}, {"role": "user", "content": results}]


def _assert_bounded_batch(messages: list[dict[str, Any]]) -> None:
    assert len(messages) == 3
    results = [json.loads(block["content"]) for block in messages[2]["content"]]
    assert all(result.get("_truncated") for result in results)
    failed = [result for result in results if "error" in result]
    assert len(failed) == 1 and failed[0]["error"].startswith("read stopped")
    assert (failed[0]["recoverable"], failed[0]["effect_applied"], failed[0]["error_type"]) == (
        True,
        False,
        "io",
    )


def test_unmeasured_dense_batch_after_prose_is_bounded_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ratio of ~1.0 never prices a new dense batch; the batch itself is bounded."""
    loop, adapter = _windowed_loop(monkeypatch)
    policy = _codex_policy()
    messages: list[dict[str, Any]] = [{"role": "user", "content": _prose_prompt()}]

    async def drive() -> None:
        assert await loop._call_llm(_SYSTEM, messages) is not None
        calibration = loop._ctx_mgr._calibration
        assert calibration is not None and 0.9 < calibration.request_ratio < 1.1
        messages.extend(_dense_batch(policy))
        # Unbounded, this request would cost more than the 272K window.
        assert await loop._call_llm(_SYSTEM, messages) is not None

    asyncio.run(drive())
    assert adapter.rejected == [] and len(adapter.sent) == 2
    assert adapter.sent[-1] <= policy.effective_prompt_budget_tokens
    _assert_bounded_batch(messages)


def test_provider_rejection_of_the_latest_batch_recovers_by_bounding_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery shrinks the batch compaction and pruning must keep."""
    loop, adapter = _windowed_loop(monkeypatch)
    policy = _codex_policy()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _prose_prompt()},
        *_dense_batch(policy),
    ]

    async def drive() -> None:
        with pytest.raises(_ContextExhaustedError) as caught:
            await loop._call_llm(_SYSTEM, messages)
        exc = caught.value
        assert exc.provider_rejected and exc.can_recover_history
        outcome = await _context.aggressive_context_recovery(
            loop,
            exc.system_prompt or _SYSTEM,
            messages,
            provider_rejected=True,
            policy=exc.policy,
            tools_tokens=exc.tools_tokens,
        )
        assert outcome.status == "changed"
        assert await loop._call_llm(_SYSTEM, messages) is not None

    asyncio.run(drive())
    assert len(adapter.rejected) == 1 and adapter.rejected[0] > _WINDOW
    assert adapter.sent[-1] <= policy.effective_prompt_budget_tokens
    _assert_bounded_batch(messages)


def test_remeasurement_raises_provisional_ratios_of_retained_dense_payloads() -> None:
    """A mixed first request prices dense text at its average until re-measured."""
    # 100K prose (1.0) + 80K dense (2.15) heuristic tokens share one request.
    mixed = next_prompt_calibration(
        None,
        observed_tokens=100_000 + 172_000,
        raw_tokens=180_000,
        payloads=[(1, 400_000), (2, 320_000)],
    )
    assert mixed is not None and dict(mixed.payload_ratios)[2] == pytest.approx(272 / 180)
    # The prose is pruned; the dense payload returns with a 10K new batch.
    observed = round(2.1535 * 90_000)
    remeasured = next_prompt_calibration(
        mixed, observed_tokens=observed, raw_tokens=90_000, payloads=[(2, 320_000), (3, 40_000)]
    )
    assert remeasured is not None and remeasured.request_ratio == pytest.approx(2.1535)
    ratios = dict(remeasured.payload_ratios)
    assert ratios[2] > 2.1 and ratios[3] == DENSE_TOKEN_RATIO_FLOOR
    policy = replace(_codex_policy(), calibration=remeasured)
    assert policy.estimate_prompt_tokens(90_000, [(2, 320_000), (3, 40_000)]) >= observed


def _hex_batch(tag: str, count: int, chars: int) -> list[dict[str, Any]]:
    calls, results = [], []
    for index in range(count):
        call_id = f"{tag}-{index}"
        text = " ".join(
            hashlib.sha256(f"{tag}{index}:{line}".encode()).hexdigest()[:40]
            for line in range(chars // 41 + 1)
        )[:chars]
        calls.append({"type": "tool_use", "id": call_id, "name": "read_document", "input": {}})
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": json.dumps({"file_path": call_id, "content": text}),
            }
        )
    return [{"role": "assistant", "content": calls}, {"role": "user", "content": results}]


def test_pruned_prose_scenario_rejects_at_most_once_then_estimates_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a prune the first request may be rejected once; estimates then hold."""
    loop, adapter = _windowed_loop(monkeypatch)
    policy = _codex_policy()
    prose = (_prose_prompt() * 2)[:460_000]
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Summarize the files."},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "p", "name": "read_document", "input": {}}],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "p",
                    "content": json.dumps({"content": prose}),
                }
            ],
        },
        *_hex_batch("d", 14, 19_700),
    ]

    def estimate() -> int:
        return check_context(
            messages,
            "gpt-6-sol",
            system_prompt=_SYSTEM,
            tools_tokens=0,
            policy=loop._ctx_mgr.calibrated(policy),
        ).estimated_tokens

    async def drive() -> None:
        assert await loop._call_llm(_SYSTEM, messages) is not None
        calibration = loop._ctx_mgr._calibration
        assert calibration is not None and calibration.request_ratio < 1.6
        await loop._ctx_mgr.compact(messages, "gpt-6-sol", "openai", prune=True, keep_recent=2)
        assert len(messages) == 3  # task + the dense batch; the prose is gone
        messages.extend(_hex_batch("e", 11, 20_600))
        try:
            await loop._call_llm(_SYSTEM, messages)
        except _ContextExhaustedError as exc:
            assert exc.provider_rejected
            outcome = await _context.aggressive_context_recovery(
                loop,
                exc.system_prompt or _SYSTEM,
                messages,
                provider_rejected=True,
                policy=exc.policy,
                tools_tokens=exc.tools_tokens,
            )
            assert outcome.status == "changed"
            assert await loop._call_llm(_SYSTEM, messages) is not None
        retained = {hash(block["content"]) for block in messages[2]["content"]}
        ratios = dict(loop._ctx_mgr._calibration.payload_ratios)
        assert retained <= set(ratios) and min(ratios[key] for key in retained) > 2.0
        for round_index in range(4):
            messages.extend(_hex_batch(f"f{round_index}", 2, 19_700))
            predicted = estimate()
            assert await loop._call_llm(_SYSTEM, messages) is not None
            # Maintenance before sending only lowers the request further.
            assert predicted >= adapter.sent[-1]

    asyncio.run(drive())
    assert len(adapter.rejected) <= 1
    assert adapter.sent[-1] <= policy.effective_prompt_budget_tokens
