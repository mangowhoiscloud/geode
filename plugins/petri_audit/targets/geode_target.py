"""GEODE Custom Target for Petri (P2-b: conversion + runner-injection seam).

The factory ``make_geode_target_agent()`` returns an ``inspect_ai.Agent``
when called, conforming to Petri 3.0.4's Custom Target protocol —
``execute(state, context: TargetContext, metadata: dict) -> AgentState``.

inspect_ai / inspect_petri imports are deferred to factory call time so
this module is importable without the ``[audit]`` optional extra installed
and the v0.89.x cold-start budget is preserved.

Phasing:
- P2-a: factory + outer audit-loop scaffold + lazy imports.
- P2-b (this commit): ``_to_geode_messages`` real conversion +
  ``GeodeRunner`` injection seam in ``_run_geode_loop``. Default runner
  is still a stub — live AgenticLoop bootstrap lands in P3.
- P3: ``_default_geode_runner`` real implementation + first authorised
  live audit run (3 seeds × 10 turns × Haiku judge, ``< 5,000 KRW`` gate).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inspect_ai.agent import Agent
    from inspect_ai.model import CachePolicy


# Single-turn GEODE runner. Caller owns AgenticLoop bootstrap; we hand it
# the converted GEODE-format message history and receive the assistant
# text. Injection seam keeps unit tests free of a live LLM call.
GeodeRunner = Callable[[list[dict[str, Any]]], Awaitable[str]]


def _to_geode_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert ``inspect_ai`` ChatMessages to GEODE ``ConversationContext`` form.

    Uses duck typing on ``role`` / ``text`` / ``tool_call_id`` so the helper
    works without ``inspect_ai`` installed (unit-test friendliness). The
    expected input is a sequence whose elements expose:

    - ``role: Literal["system", "user", "assistant", "tool"]``
    - ``text: str`` (or empty)
    - ``tool_call_id: str | None`` (only for ``role == "tool"``)

    GEODE's ``ConversationContext`` (``core/agent/conversation.py``) uses
    Anthropic convention: assistant tool calls live on the assistant
    message, and tool results are user-role messages with a structured
    ``[{"type": "tool_result", ...}]`` content list.
    """
    converted: list[dict[str, Any]] = []
    for m in messages:
        role = getattr(m, "role", None)
        text = getattr(m, "text", "") or ""

        if role == "system":
            converted.append({"role": "system", "content": text})
        elif role == "user":
            converted.append({"role": "user", "content": text})
        elif role == "assistant":
            converted.append({"role": "assistant", "content": text})
        elif role == "tool":
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(m, "tool_call_id", None),
                            "content": text,
                        }
                    ],
                }
            )
        else:
            raise ValueError(f"Unsupported message role: {role!r}")
    return converted


async def _run_geode_loop(
    messages: list[Any],
    *,
    runner: GeodeRunner | None = None,
) -> str:
    """Drive one GEODE turn from a Petri conversation history.

    Args:
        messages: ``inspect_ai`` ChatMessage list from ``TargetContext``,
            or any duck-typed equivalent.
        runner: Single-turn GEODE runner. Defaults to
            ``_default_geode_runner`` (P3 stub). Tests inject a mock to
            cover the conversion + outer-loop interaction without spinning
            up a real LLM.

    Returns:
        The assistant text from one GEODE turn.
    """
    geode_messages = _to_geode_messages(messages)
    if runner is None:
        runner = _default_geode_runner
    return await runner(geode_messages)


async def _default_geode_runner(messages: list[dict[str, Any]]) -> str:
    """Default GEODE runner — bootstrap + ``AgenticLoop`` one-shot.

    Not implemented in P2-b: live ``AgenticLoop`` bootstrap pulls in
    ``HookSystem``, ``ToolRegistry``, and provider credentials, all of
    which only make sense alongside the first authorised P3 audit run.
    """
    _ = messages  # silence unused-arg lint until P3 wires this up
    raise NotImplementedError(
        "_default_geode_runner is a P2-b stub; live AgenticLoop bootstrap "
        "lands in P3 with the first authorised audit run. "
        "See docs/plans/eval-petri-integration.md."
    )


def make_geode_target_agent(
    *,
    cache: bool | CachePolicy = False,
    runner: GeodeRunner | None = None,
) -> Agent:
    """Build a Petri-compatible target ``Agent`` backed by GEODE's AgenticLoop.

    Args:
        cache: Forwarded to ``TargetContext.scoped_cache`` for trajectory-
            scoped response caching (Petri 3.0.6).
        runner: Optional single-turn GEODE runner. ``None`` selects the
            P3-pending default. Tests pass a mock so the audit loop runs
            end-to-end without a live LLM.

    Returns:
        An ``@agent``-decorated Inspect AI ``Agent`` callable.

    Raises:
        ImportError: If the ``[audit]`` optional extra is not installed.
    """
    # Lazy imports — only triggered when the factory is invoked, so plain
    # `import plugins.petri_audit.targets.geode_target` keeps working
    # without the [audit] extra installed.
    from inspect_ai.agent import AgentState, agent
    from inspect_ai.model import ChatMessageAssistant, ModelOutput
    from inspect_petri.target import (
        TOOL_RESULT,
        ExitSignal,
        TargetContext,
    )

    @agent(name="geode")
    def _factory() -> Any:
        async def execute(
            state: AgentState,
            context: TargetContext,
            metadata: dict[str, Any],
        ) -> AgentState:
            # Mirrors inspect_petri.target._agent.target_agent's outer
            # loop (resume → seed messages → generate → send_output →
            # next user) but swaps Petri's `model.generate` for GEODE's
            # AgenticLoop via _run_geode_loop. Tool simulation must be
            # disabled at audit() level via target_tools="none" so GEODE's
            # own tool registry remains authoritative.
            try:
                await context.wait_for_resume()
                state.messages[:] = [
                    await context.system_message(),
                    await context.user_message(),
                ]

                while True:
                    output_text = await _run_geode_loop(
                        state.messages, runner=runner
                    )

                    assistant = ChatMessageAssistant(content=output_text)
                    state.messages.append(assistant)
                    state.output = ModelOutput.from_message(assistant)

                    # No tool-call surface in P2-b; auditor must drive
                    # the next user turn explicitly.
                    context.expect({TOOL_RESULT: set()})
                    await context.send_output(state.output)

                    state.messages.append(await context.user_message())
            except ExitSignal:
                return state

        return execute

    # `cache` will be wired into _default_geode_runner in P3 via
    # context.scoped_cache. Held inert for now to keep the public
    # signature stable.
    _ = cache
    return _factory()
