"""GEODE Custom Model API for Petri (P3-a).

Registers GEODE as an ``inspect_ai`` model provider so any Petri (or
other ``inspect_ai``) evaluation can target it via
``--model-role target=geode/<base-model>``. The whole GEODE stack —
agentic loop, tools, hooks, memory, scheduler — is exposed as a single
``generate(messages, ...) -> ModelOutput`` interface.

Conceptually GEODE is "an LLM with tools and memory bolted on", so
representing it as a model rather than as a custom target lets Petri's
standard ``target_agent`` handle prefill / cache / replayable / tool_calls
flow without us re-implementing the outer audit loop.

Phasing:
- P1 / P2-a / P2-b / P2-c: Custom Target factory + scaffold (replaced).
- P2-d: switch to Custom Model API. ``GeodeModelAPI`` registered with
  ``@modelapi(name="geode")`` via ``register()``. Petri's standard
  ``target_agent`` drives the outer audit loop; our ``generate()`` is
  one shot.
- P3-a (this commit): ``_default_geode_runner`` real implementation
  against ``core.agent.loop.loop:AgenticLoop`` + ``_split_messages``
  helper (system → ``system_suffix``, history → ``ConversationContext``,
  last user → ``loop.run`` prompt). Live LLM call still requires user
  authorisation; coverage limited to unit tests on the helpers.
- P3-b: first authorised live audit run (3 seeds × 10 turns × Haiku
  judge, ``< 5,000 KRW`` cost gate).

Cold-start protection: the module-level surface (``_to_geode_messages``,
``_default_geode_runner``, ``GeodeRunner``) has no ``inspect_ai``
dependency, so this file is importable on a default ``uv sync``. The
``inspect_ai`` import lives inside ``register()``, which is invoked from
``plugins/petri_audit/__init__.py`` under a try/except — present-extra
installs trigger registration, absent-extra installs silently skip.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# Single-turn GEODE runner. Caller owns AgenticLoop bootstrap; we hand
# it the converted GEODE-format message history and receive the assistant
# text. Injection seam keeps unit tests free of a live LLM call.
GeodeRunner = Callable[[list[dict[str, Any]]], Awaitable[str]]


def _to_geode_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert ``inspect_ai`` ChatMessages to GEODE ``ConversationContext`` form.

    Uses duck typing on ``role`` / ``text`` / ``tool_call_id`` so the helper
    works without ``inspect_ai`` actually installed (unit-test friendliness).
    The expected input is a sequence whose elements expose:

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


def _split_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], str]:
    """Split GEODE-format messages into ``(system_suffix, history, last_user)``.

    Petri stages a sequence ``[system, user, (assistant, user)*]`` per
    turn. We split it so:

    - The auditor's system message(s) become ``AgenticLoop.system_suffix``.
      That places the audit-scenario sysprompt alongside GEODE's own
      identity prompt, which is exactly what ``cooperation_with_harmful_
      sysprompt`` is supposed to evaluate (GEODE's response to a hostile
      sysprompt, not a raw LLM's).
    - The user/assistant pairs prior to the final user become the
      ``ConversationContext`` history.
    - The final user message becomes the ``loop.run(prompt)`` argument.

    Tool-result messages (which ``_to_geode_messages`` wraps as user-role
    with a ``[{"type": "tool_result", ...}]`` content list) are passed
    through untouched in the history slot.

    Edge cases:
    - Empty input → ``("", [], "")``.
    - Last message non-user → it joins ``history`` and ``last_user`` is
      blank; the caller (or AgenticLoop) decides how to handle that.
    """
    if not messages:
        return "", [], ""

    last = messages[-1]
    last_role = last.get("role")
    if last_role == "user":
        last_content = last.get("content", "")
        last_user = last_content if isinstance(last_content, str) else str(last_content)
        body = messages[:-1]
    else:
        last_user = ""
        body = messages

    system_parts: list[str] = []
    history: list[dict[str, Any]] = []
    for msg in body:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            text = content if isinstance(content, str) else str(content)
            if text:
                system_parts.append(text)
        else:
            history.append(msg)

    return "\n\n".join(system_parts).strip(), history, last_user


async def _default_geode_runner(messages: list[dict[str, Any]]) -> str:
    """Default GEODE runner — bootstrap + ``AgenticLoop`` one-shot.

    Imports GEODE core lazily so the module-level surface stays free of
    GEODE-bootstrap dependencies. Each call performs a fresh bootstrap;
    persistent ``GeodeModelAPI``-instance bootstrap is a P3-b polish.

    The conversation layout is described in ``_split_messages``: the
    auditor's system message rides on ``AgenticLoop.system_suffix``,
    prior turns seed ``ConversationContext.messages``, and the final
    user message is the ``loop.run`` prompt.

    Live LLM authorisation: this function will trigger live API calls
    when the bootstrapped readiness lacks ``force_dry_run``. Callers
    embedding it in a ``geode/<base>`` audit MUST have explicit user
    authorisation per CLAUDE.md L99.
    """
    if not messages:
        raise ValueError(
            "Empty message history — Petri target_agent should have seeded "
            "at least the initial user message before calling generate()."
        )

    # Lazy imports — keep the module-level surface bootstrap-free.
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.cli import _build_tool_handlers, _set_readiness
    from core.wiring.startup import check_readiness

    system_text, history, last_user = _split_messages(messages)

    readiness = check_readiness()
    _set_readiness(readiness)
    handlers = _build_tool_handlers(verbose=False)

    ctx = ConversationContext()
    ctx.messages.extend(history)

    executor = ToolExecutor(action_handlers=handlers, auto_approve=True)
    # max_rounds=4 — per-turn tool-loop cap. Petri's outer max_turns
    # controls the whole audit length; this caps within a single turn so
    # a runaway agent does not eat the audit budget.
    loop = AgenticLoop(
        ctx,
        executor,
        max_rounds=4,
        system_suffix=system_text,
    )

    result = loop.run(last_user)
    return result.text or ""


def register() -> None:
    """Register ``GeodeModelAPI`` with ``inspect_ai``.

    Imports ``inspect_ai`` lazily; raises ``ImportError`` if the
    ``[audit]`` optional extra is not installed. ``plugins/petri_audit/
    __init__.py`` wraps the call in try/except so the plugin remains
    importable on the default ``uv sync``.

    Calling ``register()`` more than once is safe — ``inspect_ai``'s
    registry replaces an existing entry of the same name.

    Model name format: ``geode/<base-model>`` — e.g. ``geode/opus-4-7``,
    ``geode/sonnet-4-6``. ``<base-model>`` selects the underlying LLM
    GEODE will use internally; the live runner (P3) interprets it.

    Tests can register a custom runner via the ``runner`` model arg:

        from inspect_ai.model import get_model
        model = get_model("geode/opus-4-7", runner=fake_runner)
    """
    from inspect_ai.model import (
        ChatMessage,
        GenerateConfig,
        ModelAPI,
        ModelOutput,
        modelapi,
    )
    from inspect_ai.tool import ToolChoice, ToolInfo

    @modelapi(name="geode")
    class GeodeModelAPI(ModelAPI):  # type: ignore[misc, unused-ignore]
        """GEODE-as-a-Model — ``inspect_ai.ModelAPI`` adapter.

        Encapsulates GEODE's full agentic stack as a one-shot
        ``generate(messages) -> ModelOutput`` so Petri's standard
        ``target_agent`` (and any other ``inspect_ai`` evaluation
        harness) can target GEODE the way it targets a regular LLM.

        ``# type: ignore[misc]`` on the subclass: ``inspect_ai`` ships
        without type stubs, so ``ModelAPI`` resolves to ``Any`` under
        ``ignore_missing_imports``; mypy flags ``Any`` subclassing
        defensively. The ignore is scoped to that one defensive lint.
        """

        def __init__(
            self,
            model_name: str,
            base_url: str | None = None,
            api_key: str | None = None,
            config: GenerateConfig | None = None,
            **model_args: Any,
        ) -> None:
            super().__init__(model_name, base_url, api_key, [], config or GenerateConfig())
            runner = model_args.get("runner")
            self._runner: GeodeRunner | None = runner if callable(runner) else None

        async def generate(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> ModelOutput:
            # GEODE owns its own tool registry. The ``tools`` and
            # ``tool_choice`` arguments are intentionally ignored —
            # callers should pass ``target_tools="none"`` to audit() so
            # the auditor does not try to fabricate tool results.
            _ = tools, tool_choice, config

            geode_messages = _to_geode_messages(input)
            runner = self._runner if self._runner is not None else _default_geode_runner
            text = await runner(geode_messages)
            return ModelOutput.from_content(model=self.model_name, content=text)

    _ = GeodeModelAPI  # decorator return is unused at module level
