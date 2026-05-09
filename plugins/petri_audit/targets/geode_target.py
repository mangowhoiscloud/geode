"""GEODE Custom Target for Petri (P2-a: factory + scaffold).

The factory ``make_geode_target_agent()`` returns an ``inspect_ai.Agent``
when called, conforming to Petri 3.0.4's Custom Target protocol —
``execute(state, context: TargetContext, metadata: dict) -> AgentState``.

inspect_ai / inspect_petri imports are deferred to factory call time so
this module is importable without the ``[audit]`` optional extra installed
and the v0.89.x cold-start budget is preserved.

Phasing:
- P2-a (this commit): factory + outer audit-loop scaffold + lazy imports.
  ``_run_geode_loop()`` is a stub — calling the factory's returned Agent
  in a real audit will fail at the first turn with NotImplementedError.
- P2-b: ``_run_geode_loop()`` real implementation against
  ``core.agent.loop.loop:AgenticLoop``.
- P3: first live audit run (3 seeds × 10 turns × Haiku judge),
  ``< 5,000 KRW`` cost gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inspect_ai.agent import Agent
    from inspect_ai.model import CachePolicy, ChatMessage


def make_geode_target_agent(*, cache: bool | CachePolicy = False) -> Agent:
    """Build a Petri-compatible target ``Agent`` backed by GEODE's AgenticLoop.

    Args:
        cache: Forwarded to ``TargetContext.scoped_cache`` for trajectory-
            scoped response caching (Petri 3.0.6).

    Returns:
        An ``@agent``-decorated Inspect AI ``Agent`` callable.

    Raises:
        ImportError: If the ``[audit]`` optional extra is not installed
            (``inspect_ai`` / ``inspect_petri`` missing).

    The returned agent will raise ``NotImplementedError`` at runtime in
    P2-a because ``_run_geode_loop`` is a stub. Wiring lands in P2-b.
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
            # Mirrors inspect_petri.target._agent.target_agent's outer loop
            # (resume → seed messages → generate → send_output → next user)
            # but swaps Petri's `model.generate` call for GEODE's AgenticLoop
            # via _run_geode_loop. Tool simulation is bypassed: callers must
            # invoke audit() with target_tools="none" so GEODE's own tools
            # remain authoritative.
            try:
                await context.wait_for_resume()
                state.messages[:] = [
                    await context.system_message(),
                    await context.user_message(),
                ]

                while True:
                    output_text = await _run_geode_loop(state.messages)

                    assistant = ChatMessageAssistant(content=output_text)
                    state.messages.append(assistant)
                    state.output = ModelOutput.from_message(assistant)

                    # No tool-call surface in P2-a; auditor must drive the
                    # next user turn explicitly.
                    context.expect({TOOL_RESULT: set()})
                    await context.send_output(state.output)

                    state.messages.append(await context.user_message())
            except ExitSignal:
                return state

        return execute

    # `cache` will be wired into _run_geode_loop in P2-b via context.scoped_cache.
    _ = cache
    return _factory()


async def _run_geode_loop(messages: list[ChatMessage]) -> str:
    """Drive one GEODE AgenticLoop turn from a Petri conversation history.

    P2-a stub. P2-b plumbs ``messages`` into
    ``core.agent.loop.loop:AgenticLoop`` and extracts the assistant text.
    """
    raise NotImplementedError(
        "_run_geode_loop is a P2-a stub; AgenticLoop wiring lands in P2-b. "
        "See docs/plans/eval-petri-integration.md."
    )
