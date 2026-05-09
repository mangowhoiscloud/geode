"""GEODE Custom Model API for Petri (P2-d).

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
- P2-d (this commit): switch to Custom Model API. ``GeodeModelAPI``
  registered with ``@modelapi(name="geode")`` via ``register()``.
  Petri's standard ``target_agent`` drives the outer audit loop; our
  ``generate()`` is one shot.
- P3: ``_default_geode_runner`` real implementation against
  ``core.agent.loop.loop:AgenticLoop`` + first authorised live audit run
  (3 seeds × 10 turns × Haiku judge, ``< 5,000 KRW`` cost gate).

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


async def _default_geode_runner(messages: list[dict[str, Any]]) -> str:
    """Default GEODE runner — bootstrap + ``AgenticLoop`` one-shot.

    Not implemented in P2-d: live ``AgenticLoop`` bootstrap pulls in
    ``HookSystem``, ``ToolRegistry``, and provider credentials, all of
    which only make sense alongside the first authorised P3 audit run.
    """
    _ = messages  # silence unused-arg lint until P3 wires this up
    raise NotImplementedError(
        "_default_geode_runner is a P2-d stub; live AgenticLoop bootstrap "
        "lands in P3 with the first authorised audit run. "
        "See docs/plans/eval-petri-integration.md."
    )


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
    class GeodeModelAPI(ModelAPI):  # type: ignore[misc]
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
            super().__init__(
                model_name, base_url, api_key, [], config or GenerateConfig()
            )
            runner = model_args.get("runner")
            self._runner: GeodeRunner | None = (
                runner if callable(runner) else None
            )

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
            runner = (
                self._runner
                if self._runner is not None
                else _default_geode_runner
            )
            text = await runner(geode_messages)
            return ModelOutput.from_content(
                model=self.model_name, content=text
            )

    _ = GeodeModelAPI  # decorator return is unused at module level
