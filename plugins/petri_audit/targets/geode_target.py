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
  against ``core.agent.loop.agent_loop:AgenticLoop`` + ``_split_messages``
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

import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

# Single-turn GEODE runner. Caller owns AgenticLoop bootstrap; we hand
# it the converted GEODE-format message history and receive the assistant
# text PLUS an optional usage dict.
#
# F-A1 (2026-05-11) — runner contract widened from ``Awaitable[str]`` to
# ``Awaitable[str | tuple[str, dict | None]]``. ``GeodeModelAPI.generate``
# unpacks both forms so existing test runners (``runner=fake`` returning
# a bare string) keep working — the new tuple form lets the runner
# surface the underlying loop's aggregate usage into
# ``inspect_ai.model.ModelOutput.usage`` (and therefore into the eval
# log's ``role_usage`` aggregation, which scoped on usage presence).
GeodeRunner = Callable[
    [list[dict[str, Any]]],
    Awaitable["str | tuple[str, dict[str, Any] | None]"],
]


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
    - The final user message becomes the ``await loop.arun(prompt)`` argument.

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


async def _default_geode_runner(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Default GEODE runner — bootstrap + ``AgenticLoop`` one-shot.

    Imports GEODE core lazily so the module-level surface stays free of
    GEODE-bootstrap dependencies. Each call performs a fresh bootstrap;
    persistent ``GeodeModelAPI``-instance bootstrap is a P3-b polish.

    The conversation layout is described in ``_split_messages``: the
    auditor's system message rides on ``AgenticLoop.system_suffix``,
    prior turns seed ``ConversationContext.messages``, and the final
    user message is the ``loop.run`` prompt.

    **Model priority** (N6-followup):

    - ``model`` argument set (= caller-explicit, e.g.
      ``geode/claude-opus-4-7``) → that model is sticky for the lifetime
      of the loop and ``AgenticLoop`` is constructed with
      ``disable_settings_drift=True`` so a divergent ``settings.model``
      never silently swaps it mid-audit.
    - ``model=None`` (= caller did not pin a base; the registered
      ``GeodeModelAPI`` is using the default sentinel) → ``AgenticLoop``
      falls back to ``ANTHROPIC_PRIMARY`` and the regular drift sync
      stays active so the user's GEODE ``settings.model`` (e.g.
      whatever ``/model`` last selected) wins.

    Live LLM authorisation: this function will trigger live API calls
    when the bootstrapped readiness lacks ``force_dry_run``. Callers
    embedding it in a ``geode/<base>`` audit MUST have explicit user
    authorisation per `CLAUDE.md` → CANNOT → Quality:
    "No unauthorized live test execution".
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
    from core.audit.diagnostics import diag
    from core.wiring.startup import check_readiness

    from core.cli import _build_tool_handlers, _set_readiness
    from plugins.petri_audit.audit_mode import (
        apply_to_profile_policy,
        apply_to_readiness,
        resolve,
    )

    # Audit-mode resolves from .geode/audit-mode.toml + env var. CLI
    # ``--unrestricted`` sets the env var before subprocess launch so
    # the inspect_ai child sees it. When enabled, lifts ProfilePolicy
    # / Readiness guardrails for this one petri run only.
    audit_mode = resolve()

    system_text, history, last_user = _split_messages(messages)

    # Defect A F-A3 (2026-05-11) — entry observability. This INFO line is
    # the runner's confirmed entry signal: PR-AUDIT-SCAFFOLD-WIRE
    # (v0.99.100, #1938) verified the closed loop's audit DOES route
    # ``geode/gpt-5.5 → GeodeModelAPI.generate → _default_geode_runner →
    # AgenticLoop`` and reach here, so the mutated scaffold is what Petri
    # audits. The line stays as a live entry trace (paired with the diag()
    # below) for per-run post-mortems; DEBUG once AgenticLoop is up.
    log.info(
        "petri runner entry: msg_count=%d last_user_chars=%d model=%s",
        len(messages),
        len(last_user),
        model,
    )
    # Booster E (2026-05-12) — diag() emission so the inspect_ai subprocess'
    # logs are also captured to ``~/.geode/diagnostics/<YYYY-MM>.log`` for
    # cross-session post-mortem. Booster C — the runner's RunLog binding
    # is documented here even though no RunLog session_key is wired yet;
    # the timestamp + pid in each diag line lets us pair entry / exit
    # with the inspect archive's timestamp. Live RunLog cross-link is a
    # follow-up PR.
    diag(
        "petri.runner.entry",
        f"msg_count={len(messages)} last_user_chars={len(last_user)} "
        f"model={model} audit_mode={'on' if audit_mode.enabled else 'off'}",
    )

    readiness = check_readiness()
    readiness = apply_to_readiness(readiness, audit_mode)
    _set_readiness(readiness)
    handlers = _build_tool_handlers(verbose=False)
    if audit_mode.enabled:
        try:
            from core.tools.policy import load_profile_policy

            original_policy = load_profile_policy()
            patched_policy = apply_to_profile_policy(original_policy, audit_mode)
            for handler in handlers.values() if isinstance(handlers, dict) else handlers:
                if hasattr(handler, "policy"):
                    handler.policy = patched_policy
            log.info("petri runner: audit-mode active (%s)", audit_mode)
            diag(
                "petri.runner.policy",
                f"audit_mode applied: allow_dangerous={audit_mode.allow_dangerous} "
                f"allow_write={audit_mode.allow_write} "
                f"force_dry_run={audit_mode.force_dry_run} "
                f"auto_approve={audit_mode.auto_approve}",
            )
        except Exception as exc:
            log.warning("petri runner: audit-mode policy apply failed", exc_info=True)
            diag("petri.runner.policy", f"audit_mode apply FAILED: {exc!r}")

    ctx = ConversationContext()
    ctx.messages.extend(history)

    executor = ToolExecutor(action_handlers=handlers, auto_approve=True)
    # G2 (2026-05-12) — max_rounds cap removed. Prior `max_rounds=4`
    # hardcode caused the `long_running_loop` audit's GEODE admirable
    # = 2 vs vanilla 8 (budget self-monitoring weakness). Petri's outer
    # `max_turns` already controls the whole audit length; an inner cap
    # was double-bounding and stripped the agent's budget self-awareness
    # signal. AgenticLoop's `DEFAULT_MAX_ROUNDS = 0` (unlimited, time-
    # budget based) is the right default for an audit target.
    #
    # ``disable_settings_drift`` is True iff the caller explicitly pinned
    # a target model — see N6-followup priority docstring above.
    # The inspect-ai audit subprocess (``uv run inspect eval inspect_petri/audit``)
    # does not go through ``core.runtime.GeodeRuntime._build_core``, the
    # parent's bootstrap path. Without an explicit ``bootstrap_builtins()``
    # here the registry is empty (``Known pairs: []``) and every target
    # ``generate`` call inside this runner fails with
    # ``AdapterNotFoundError: provider='openai' source='payg'``. Mirrors the
    # ``core/agent/worker.py:817-823`` pattern for the sub-agent worker
    # subprocess, which has the identical wiring gap. Idempotent — safe to
    # re-call when the parent already populated the registry.
    from core.llm.adapters.registry import bootstrap_builtins

    from core.llm.adapters import infer_provider_from_model

    bootstrap_builtins()

    # Resolve (provider, source) via ``get_binding`` — the same path
    # the manual ``geode audit`` CLI uses — so the audit subprocess,
    # the CLI, and the closed-loop all share one source SoT
    # (``[petri.target]`` / ``[self_improving_loop.petri.target]``).
    resolved_provider = infer_provider_from_model(model) if model else "anthropic"
    resolved_source = ""
    if model:
        try:
            from plugins.petri_audit.registry import get_binding

            binding = get_binding("target", model=model)
            resolved_provider = binding.provider
            resolved_source = binding.source
            # Translate Petri-surface source names to the GEODE
            # adapter-registry namespace so AgenticLoop's
            # ``get_adapter(name)`` / ``resolve_for(provider, category)``
            # lookups hit. Only two pairs diverge:
            #   ``openai-codex`` (Petri name) → ``codex-oauth`` (registry name)
            #   ``api_key`` (Petri PAYG, provider-generic) → ``payg``
            #     (registry category; the fallback ``resolve_for(provider,
            #     "payg")`` selects the provider-specific ``*-payg`` adapter)
            # The other concrete sources (``claude-cli`` / ``codex-cli`` /
            # ``anthropic-oauth``) are identical across both namespaces.
            _PETRI_TO_REGISTRY = {
                "openai-codex": "codex-oauth",
                "api_key": "payg",
            }
            resolved_source = _PETRI_TO_REGISTRY.get(resolved_source, resolved_source)
        except Exception:
            # get_binding can raise if the model is not in the role
            # manifest's allowed_models list (manual override / custom
            # model). Fall through to provider inference + AgenticLoop
            # default source — preserves legacy behaviour for callers
            # that have not migrated their config to the [petri.target]
            # section yet. Logged at DEBUG so production noise stays
            # quiet but post-mortems can trace the fallback.
            log.debug(
                "geode_target: get_binding('target', model=%s) failed; "
                "falling back to inferred provider + default source",
                model,
                exc_info=True,
            )

    loop = AgenticLoop(
        ctx,
        executor,
        system_suffix=system_text,
        model=model,
        provider=resolved_provider,
        source=resolved_source,
        disable_settings_drift=(model is not None),
    )
    log.debug(
        "AgenticLoop constructed: model=%s drift_disabled=%s system_chars=%d history=%d",
        loop.model,
        model is not None,
        len(system_text),
        len(history),
    )

    # inspect-petri always invokes ``GeodeModelAPI.generate`` (async) inside
    # the audit event loop. Calling the async ``arun`` directly avoids nested
    # loop and fixes the v2 N3 silent target-invocation failure
    # (``docs/audits/2026-05-10-petri-2a-v2.md`` § C4).
    result = await loop.arun(last_user)
    text = result.text or ""
    usage_dict = result.usage.to_dict() if result.usage is not None else None
    log.info(
        "petri runner exit: text_chars=%d usage=%s",
        len(text),
        usage_dict,
    )
    diag(
        "petri.runner.exit",
        f"text_chars={len(text)} usage={usage_dict}",
    )
    return text, usage_dict


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
        ChatCompletionChoice,
        ChatMessage,
        ChatMessageAssistant,
        GenerateConfig,
        ModelAPI,
        ModelOutput,
        ModelUsage,
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
            usage_dict: dict[str, Any] | None = None
            if self._runner is not None:
                # Custom runner (used by tests via the ``runner=`` model
                # arg). Receives messages only — ``model_name`` is
                # already on ``self`` for any introspection the test
                # wants to do. F-A1 back-compat — accept either bare str
                # or ``(text, usage_dict)`` tuple.
                raw = await self._runner(geode_messages)
                if isinstance(raw, tuple):
                    text, usage_dict = raw
                else:
                    text = raw
            else:
                # N6-followup priority: pass the caller-pinned base
                # model down to the runner. ``model_name`` is shaped
                # ``geode/<base>``; the ``geode/default`` sentinel
                # means "no caller pin — fall back to settings.model".
                base = self.model_name.rsplit("/", 1)[-1]
                runner_model: str | None = None if base == "default" else base
                text, usage_dict = await _default_geode_runner(geode_messages, model=runner_model)
            # Defect A F-A1 — emit a fully populated ``ModelUsage`` so
            # inspect_ai's ``log.stats.role_usage["target"]`` is non-
            # empty. ``ModelOutput.from_content`` would leave it None
            # and the petri eval log would have the target column
            # silently missing (the symptom of #1020).
            #
            # Defect B-1 follow-up (2026-05-11) — always emit a
            # ModelUsage, even when ``usage_dict is None``. The old
            # path skipped the entry whenever ``_default_geode_runner``
            # returned ``(text, None)`` (anthropic call failed inside
            # the AgenticLoop, leaving ``result.usage = None`` because
            # ``_response.track_usage`` never fired). The result was
            # ``output.usage = None`` on the ModelEvent, which inspect_
            # ai then drops from ``role_usage`` — the same "target
            # column silently disappears" symptom F-A1 was meant to
            # fix. Zero-valued ModelUsage keeps the role present and
            # makes the failure visible (``target: 0 tokens``) instead
            # of invisible.
            usage_src: dict[str, Any] = usage_dict or {}
            cache_w = int(usage_src.get("cache_creation_tokens", 0) or 0)
            cache_r = int(usage_src.get("cache_read_tokens", 0) or 0)
            in_tok = int(usage_src.get("input_tokens", 0) or 0)
            out_tok = int(usage_src.get("output_tokens", 0) or 0)
            inspect_usage = ModelUsage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=in_tok + out_tok + cache_w + cache_r,
                input_tokens_cache_write=cache_w or None,
                input_tokens_cache_read=cache_r or None,
                reasoning_tokens=(int(usage_src.get("thinking_tokens", 0) or 0) or None),
                total_cost=usage_src.get("cost_usd"),
            )
            return ModelOutput(
                model=self.model_name,
                choices=[
                    ChatCompletionChoice(
                        message=ChatMessageAssistant(
                            content=text,
                            model=self.model_name,
                            source="generate",
                        ),
                        stop_reason="stop",
                    )
                ],
                usage=inspect_usage,
            )

    _ = GeodeModelAPI  # decorator return is unused at module level
