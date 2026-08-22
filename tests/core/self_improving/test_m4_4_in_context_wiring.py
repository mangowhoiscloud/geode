"""ADR-012 M4.4 — In-context slot wiring invariants.

Pins:
- ``apply_in_context_slots`` takes ``(messages, system=)`` and returns
  ``(new_messages, new_system)``.
- No-op fast path: when no SoT is configured, returns *identity*
  (same objects, not just equal values) so per-call cost is zero.
- exemplars slot wired: reads M3 few-shot pool, prepends top-K
  ``(user, assistant)`` pairs at head of messages.
- Per-slot graceful: a reader / apply failure on one slot doesn't
  break the LLM call.
- Product composition installs one request middleware for Anthropic PAYG/OAuth.
- The kernel Anthropic request builder has no product import or direct call.
- Claude CLI and non-Anthropic adapters are outside this contribution.
"""

from __future__ import annotations

import asyncio
import builtins
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
from core.config.policy_source import EMPTY_POLICY_SOURCES, PolicySourceBundle, PolicySourcePaths
from core.hooks import DuplicateMiddlewareError, LlmCallRequest, MiddlewareRegistry
from core.llm.adapters._anthropic_common import build_create_kwargs, build_stream_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message
from core.wiring.bootstrap import build_middleware_registry as build_core_middleware_registry
from geode_product.self_improving.loop.inject.in_context_wiring import (
    apply_in_context_slots,
    register_in_context_middleware,
)
from geode_product.wiring import build_middleware_registry

# No-op fast path ------------------------------------------------------------


def test_no_sot_configured_returns_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """No SoT → identical objects returned (zero allocation)."""
    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda **_kwargs: None,
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, new_sys = apply_in_context_slots(msgs, system="SYS")
    assert new_msgs is msgs  # identity, not just equality
    assert new_sys == "SYS"


def test_empty_dict_slots_returns_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty dict from the reader → identity (truthiness check)."""
    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda **_kwargs: {},
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs is msgs


def test_load_failure_returns_identity_and_swallows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader exception → identity, no propagation (defensive)."""

    def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        _boom,
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs is msgs


# exemplars slot — M3 substrate wired ---------------------------------------


def test_exemplars_slot_prepends_few_shot_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """When exemplars slot active + pool has entries → ``(user, assistant)``
    pairs land at head of messages."""
    from core.llm.few_shot_pool import FewShotExemplar
    from geode_product.self_improving.loop.inject.in_context_slots import (
        SLOT_EXEMPLARS,
        InContextSlot,
    )

    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda **_kwargs: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=2,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.llm.few_shot_pool._load_few_shot_pool_override",
        lambda **_kwargs: [
            FewShotExemplar(
                user_msg="ex1_user",
                assistant_msg="ex1_assistant",
                fitness_delta=0.9,
                source="petri",
            ),
            FewShotExemplar(
                user_msg="ex2_user",
                assistant_msg="ex2_assistant",
                fitness_delta=0.7,
                source="petri",
            ),
        ],
    )
    msgs = [{"role": "user", "content": "real"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    # 2 exemplar pairs (4 messages) + the 1 real message = 5
    assert len(new_msgs) == 5
    assert new_msgs[0]["content"] == "ex1_user"
    assert new_msgs[1]["content"] == "ex1_assistant"
    assert new_msgs[2]["content"] == "ex2_user"
    assert new_msgs[3]["content"] == "ex2_assistant"
    assert new_msgs[4]["content"] == "real"


def test_exemplars_slot_empty_pool_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """exemplars slot configured but pool empty → messages unchanged."""
    from geode_product.self_improving.loop.inject.in_context_slots import (
        SLOT_EXEMPLARS,
        InContextSlot,
    )

    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda **_kwargs: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=3,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.llm.few_shot_pool._load_few_shot_pool_override",
        lambda **_kwargs: None,
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs == msgs


def test_exemplars_slot_pool_failure_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """exemplars reader exception → swallowed; other slots / call proceed."""
    from geode_product.self_improving.loop.inject.in_context_slots import (
        SLOT_EXEMPLARS,
        InContextSlot,
    )

    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda **_kwargs: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=2,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )

    def _pool_boom(**_kwargs: Any) -> Any:
        raise RuntimeError("synthetic pool failure")

    monkeypatch.setattr("core.llm.few_shot_pool._load_few_shot_pool_override", _pool_boom)
    msgs = [{"role": "user", "content": "real"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs == msgs  # unchanged after failure


# System prompt passthrough --------------------------------------------------


def test_system_passthrough_when_no_slot_targets_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """exemplars only mutates messages, never system."""
    from core.llm.few_shot_pool import FewShotExemplar
    from geode_product.self_improving.loop.inject.in_context_slots import (
        SLOT_EXEMPLARS,
        InContextSlot,
    )

    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda **_kwargs: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=1,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.llm.few_shot_pool._load_few_shot_pool_override",
        lambda **_kwargs: [
            FewShotExemplar(user_msg="u", assistant_msg="a", fitness_delta=0.5, source="t")
        ],
    )
    _, new_sys = apply_in_context_slots([], system="ORIG_SYSTEM")
    assert new_sys == "ORIG_SYSTEM"


# Neutral request-middleware wiring -----------------------------------------


def _apply_registered(
    registry: MiddlewareRegistry,
    *,
    adapter_name: str,
    request: AdapterCallRequest,
) -> LlmCallRequest:
    adapter: Any = SimpleNamespace(name=adapter_name)
    return asyncio.run(
        registry.llm_request(
            LlmCallRequest(
                adapter=adapter,
                request=request,
            )
        )
    )


class _CaptureRequest:
    def __init__(self) -> None:
        self.system_prompt = ""

    async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
        self.system_prompt = request.request.system_prompt
        return request


def test_anthropic_api_middleware_preserves_wire_shape_and_dynamic_cache_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Anthropic API lane gets contributions immediately before adaptation."""
    import geode_product.self_improving.loop.inject.in_context_wiring as wiring

    adapter_name = "anthropic-payg"
    calls: list[tuple[list[dict[str, Any]], str]] = []

    def _inject(
        messages: list[dict[str, Any]],
        *,
        system: str,
        **_kwargs: Any,
    ) -> tuple[list[dict[str, Any]], str]:
        calls.append((messages, system))
        exemplars = [
            {"role": "user", "content": "example question"},
            {"role": "assistant", "content": "example answer"},
        ]
        return exemplars + messages, "<memory-recall>memo</memory-recall>\n" + system

    monkeypatch.setattr(wiring, "apply_in_context_slots", _inject)

    registry = build_middleware_registry()
    capture = _CaptureRequest()
    registry.register_llm_request(capture, name="pre-injection-capture")

    static = "STATIC RULES\n\n"
    dynamic = "\n\n<dynamic_context>\nvolatile\n</dynamic_context>"
    system = static + PROMPT_CACHE_BOUNDARY + dynamic
    request = AdapterCallRequest(
        model="claude-sonnet-5",
        messages=(
            Message(
                role="assistant",
                content="prior",
                codex_reasoning_items=({"id": "reasoning"},),
                phase="commentary",
            ),
            Message(role="tool", content="tool output", tool_use_id="tool-1"),
        ),
        system_prompt=system,
        metadata={"trace": "kept"},
    )

    transformed = _apply_registered(
        registry,
        adapter_name=adapter_name,
        request=request,
    ).request

    assert capture.system_prompt == system
    assert len(calls) == 1
    assert calls[0][1].endswith("volatile\n")
    assert "</dynamic_context>" not in calls[0][1]
    before_boundary, after_boundary = transformed.system_prompt.split(
        PROMPT_CACHE_BOUNDARY,
        1,
    )
    assert before_boundary == static
    assert after_boundary.endswith("</dynamic_context>")
    assert "<memory-recall>memo</memory-recall>" in after_boundary

    assert [message.content for message in transformed.messages[:2]] == [
        "example question",
        "example answer",
    ]
    assert transformed.messages[2].codex_reasoning_items == ({"id": "reasoning"},)
    assert transformed.messages[2].phase == "commentary"
    assert transformed.messages[3].tool_use_id == "tool-1"
    create_kwargs = build_create_kwargs(transformed)
    stream_kwargs = build_stream_kwargs(transformed)
    assert create_kwargs["system"] == stream_kwargs["system"]
    assert create_kwargs["messages"] == stream_kwargs["messages"]
    tool_result = create_kwargs["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "tool-1"
    assert tool_result["content"] == "tool output"
    assert transformed.metadata == {
        "trace": "kept",
        "cache_invalidation_reason": "self-improving in-context contribution",
    }


@pytest.mark.parametrize("adapter_name", ["claude-cli", "openai-payg"])
def test_non_anthropic_api_adapters_are_not_modified(
    monkeypatch: pytest.MonkeyPatch,
    adapter_name: str,
) -> None:
    import geode_product.self_improving.loop.inject.in_context_wiring as wiring

    def _unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("in-context contribution must not run")

    monkeypatch.setattr(wiring, "apply_in_context_slots", _unexpected)
    registry = build_middleware_registry()
    request = AdapterCallRequest(
        model="model",
        messages=(Message(role="user", content="hello"),),
        system_prompt="system",
    )

    transformed = _apply_registered(
        registry,
        adapter_name=adapter_name,
        request=request,
    ).request

    assert transformed == request


def test_registration_is_once_only_and_fail_loud() -> None:
    registry = MiddlewareRegistry()
    register_in_context_middleware(registry)

    with pytest.raises(DuplicateMiddlewareError, match="self_improving_in_context"):
        register_in_context_middleware(registry)


@pytest.mark.parametrize(
    "policy_sources",
    [
        EMPTY_POLICY_SOURCES,
        {"cache_policy": PolicySourcePaths("GEODE_TEST_CACHE_POLICY_OVERRIDE")},
    ],
)
def test_missing_slot_policy_keeps_anthropic_request_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    policy_sources: PolicySourceBundle,
) -> None:
    import geode_product.self_improving.loop.inject.in_context_wiring as wiring

    def _unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("explicit empty policy must not load product slots")

    monkeypatch.setattr(wiring, "apply_in_context_slots", _unexpected)
    registry = build_middleware_registry(policy_sources=policy_sources)
    request = AdapterCallRequest(
        model="claude-sonnet-5",
        messages=(Message(role="user", content="hello"),),
        system_prompt="system",
    )

    transformed = _apply_registered(
        registry,
        adapter_name="anthropic-payg",
        request=request,
    ).request

    assert transformed == request


def test_neutral_bootstrap_tolerates_absent_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _without_product(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("geode_product.self_improving"):
            raise ModuleNotFoundError(
                "No module named 'geode_product.self_improving'",
                name="geode_product.self_improving",
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _without_product)
    assert isinstance(build_core_middleware_registry(), MiddlewareRegistry)


def test_neutral_bootstrap_does_not_hide_broken_product_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _broken_product(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("geode_product.self_improving"):
            raise ModuleNotFoundError(
                "No module named 'missing_product_dependency'",
                name="missing_product_dependency",
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_product)
    with pytest.raises(ModuleNotFoundError, match="missing_product_dependency"):
        build_middleware_registry()


def test_neutral_bootstrap_does_not_hide_partial_product_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _partial_product(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("geode_product.self_improving"):
            raise ModuleNotFoundError(
                "No module named 'geode_product.self_improving.policy_sources'",
                name="geode_product.self_improving.policy_sources",
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _partial_product)
    with pytest.raises(ModuleNotFoundError, match="policy_sources"):
        build_middleware_registry()


# Stub slots behave as no-ops ----------------------------------------------


def test_stub_slots_do_not_break_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """memory_recall / rubric_excerpts active → no-op; tool_hints reader isolated.

    Verifies the orchestrator's iteration over the slots doesn't raise or mutate
    output. ``tool_hints`` DOES now have a reader (``load_recent_episodes`` over
    ``~/.geode/memory/episodes.jsonl``); we pin it to empty so the no-op
    assertion is hermetic and never leaks the dev machine's real episodic store
    (which would inject a ``<tool-hints>`` block and fail the ``== "S"`` check).
    """
    from geode_product.self_improving.loop.inject.in_context_slots import (
        SLOT_MEMORY_RECALL,
        SLOT_RUBRIC_EXCERPTS,
        SLOT_TOOL_HINTS,
        InContextSlot,
    )

    # tool_hints is imported lazily inside apply_in_context_slots from the
    # source module, so patch the source (not the wiring namespace).
    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.tool_hints.load_recent_episodes",
        lambda *a, **k: [],
    )

    monkeypatch.setattr(
        "geode_product.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda **_kwargs: {
            SLOT_MEMORY_RECALL: InContextSlot(
                name=SLOT_MEMORY_RECALL,
                max_entries=5,
                rank_by="recency",
                injection_point="system_prompt",
            ),
            SLOT_RUBRIC_EXCERPTS: InContextSlot(
                name=SLOT_RUBRIC_EXCERPTS,
                max_entries=3,
                rank_by="regression_severity",
                injection_point="system_prompt",
            ),
            SLOT_TOOL_HINTS: InContextSlot(
                name=SLOT_TOOL_HINTS,
                max_entries=5,
                rank_by="success_rate",
                injection_point="tool_descriptions",
            ),
        },
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, new_sys = apply_in_context_slots(msgs, system="S")
    assert new_msgs == msgs
    assert new_sys == "S"
