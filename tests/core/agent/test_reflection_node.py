"""PR-3 C-2 — Reflection node invariants.

PR-B (2026-05-21) — migrated to Anthropic ``tool_use`` structured
output. The free-form-JSON fence/brace parser is gone; the LLM
invokes the ``record_reflection`` tool and we read ``input``
directly off the ``ToolUseBlock``. Schema-typed casts in
``_apply_reflection`` survive so a non-Anthropic provider (which
may not enforce the schema server-side) can't poison state.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.cognitive_state import CognitiveState
from core.agent.loop import _reflection
from core.agent.loop._reflection import REFLECTION_TOOL_NAME

# ---------------------------------------------------------------------------
# Pure-function invariants (no LLM)
# ---------------------------------------------------------------------------


def test_summarise_tool_results_empty() -> None:
    assert _reflection._summarise_tool_results([]) == "(no tool results — text-only round)"


def test_summarise_tool_results_str_content() -> None:
    out = _reflection._summarise_tool_results([{"tool_use_id": "t1", "content": "hello world"}])
    assert "t1" in out
    assert "hello world" in out


def test_summarise_tool_results_list_content() -> None:
    out = _reflection._summarise_tool_results(
        [{"tool_use_id": "t1", "content": [{"type": "text", "text": "deep result"}]}]
    )
    assert "deep result" in out


def test_summarise_tool_results_caps_long_text() -> None:
    long = "x" * 500
    out = _reflection._summarise_tool_results([{"tool_use_id": "t1", "content": long}])
    # 200 head + ellipsis — never the full 500
    assert "x" * 500 not in out
    assert "…" in out


def test_summarise_tool_results_caps_entries() -> None:
    rows = [{"tool_use_id": f"t{i}", "content": f"r{i}"} for i in range(20)]
    out = _reflection._summarise_tool_results(rows, cap=8)
    assert "truncated" in out
    assert "t0" in out and "t7" in out
    assert "t8" not in out


# ---------------------------------------------------------------------------
# Tool schema declaration — pinned so a refactor that drops fields surfaces here
# ---------------------------------------------------------------------------


def test_reflection_tool_schema_declares_required_shape() -> None:
    """Pin the tool schema. The Anthropic SDK enforces this server-
    side, so dropping a property or required field would silently
    change the contract."""
    tool = _reflection._REFLECTION_TOOL
    assert tool["name"] == REFLECTION_TOOL_NAME == "record_reflection"
    schema = tool["input_schema"]
    assert schema["type"] == "object"
    props = schema["properties"]
    assert set(props.keys()) == {"hypotheses", "confidence", "next_action_hint"}
    assert props["hypotheses"]["type"] == "array"
    assert props["hypotheses"]["maxItems"] == 5
    assert props["confidence"]["type"] == "number"
    assert props["confidence"]["minimum"] == 0.0
    assert props["confidence"]["maximum"] == 1.0
    # hypotheses + confidence are required; next_action_hint optional
    assert set(schema["required"]) == {"hypotheses", "confidence"}


def test_anthropic_adapter_passes_strict_flag_through() -> None:
    """Codex MCP review #2 catch — ``strict: True`` was being stripped
    by ``_API_ALLOWED_KEYS`` filter on the Anthropic adapter so the
    schema flag never reached the API. Pin that ``strict`` is in the
    allowlist."""
    from core.llm.providers.anthropic import _API_ALLOWED_KEYS

    assert "strict" in _API_ALLOWED_KEYS


def test_reflection_module_exports_tool_name_for_other_callers() -> None:
    """Re-exported so downstream (transcript renderer, debug tools) can
    grep for the tool name without importing the private dict."""
    assert "REFLECTION_TOOL_NAME" in _reflection.__all__
    assert REFLECTION_TOOL_NAME == "record_reflection"


# ---------------------------------------------------------------------------
# _apply_reflection — schema-typed casts
# ---------------------------------------------------------------------------


def test_apply_reflection_populates_hypotheses() -> None:
    state = CognitiveState(goal="x")
    _reflection._apply_reflection(state, {"hypotheses": ["h1", "h2"]})
    assert state.hypotheses == ["h1", "h2"]


def test_apply_reflection_caps_hypotheses_at_five() -> None:
    state = CognitiveState()
    _reflection._apply_reflection(state, {"hypotheses": [f"h{i}" for i in range(10)]})
    assert len(state.hypotheses) == 5
    assert state.hypotheses[0] == "h0"
    assert state.hypotheses[-1] == "h4"


def test_apply_reflection_truncates_hypotheses_at_120_chars() -> None:
    state = CognitiveState()
    long = "x" * 500
    _reflection._apply_reflection(state, {"hypotheses": [long]})
    assert len(state.hypotheses[0]) == 120


def test_apply_reflection_clamps_confidence() -> None:
    state = CognitiveState()
    _reflection._apply_reflection(state, {"confidence": 1.5})
    assert state.confidence == 1.0
    _reflection._apply_reflection(state, {"confidence": -0.3})
    assert state.confidence == 0.0


def test_apply_reflection_rejects_bool_confidence() -> None:
    """``bool`` is an ``int`` subclass — must be excluded so the LLM
    can't accidentally collapse confidence to 0/1 by returning
    True/False. Mirrors PR-5 fix-up on the mutator schema."""
    state = CognitiveState(confidence=0.5)
    _reflection._apply_reflection(state, {"confidence": True})
    # True would have flipped confidence to 1.0; the guard preserves 0.5
    assert state.confidence == 0.5


def test_apply_reflection_pushes_hint_into_subgoals() -> None:
    state = CognitiveState()
    _reflection._apply_reflection(state, {"next_action_hint": "try X"})
    _reflection._apply_reflection(state, {"next_action_hint": "try Y"})
    assert state.subgoals == ["try X", "try Y"]


def test_apply_reflection_caps_subgoals_at_five() -> None:
    state = CognitiveState()
    for i in range(8):
        _reflection._apply_reflection(state, {"next_action_hint": f"hint{i}"})
    assert len(state.subgoals) == 5
    assert state.subgoals[0] == "hint3"
    assert state.subgoals[-1] == "hint7"


def test_apply_reflection_ignores_wrong_types() -> None:
    """Schema-typed casts — bad types silently drop the field, not
    poison the whole state. Even though the Anthropic SDK enforces
    types server-side, non-Anthropic providers don't, so this guard
    protects the dispatcher fork."""
    state = CognitiveState(goal="x", confidence=0.5, hypotheses=["keep"])
    _reflection._apply_reflection(
        state,
        {"hypotheses": "not-a-list", "confidence": "high", "next_action_hint": 123},
    )
    # all dropped — original state preserved
    assert state.hypotheses == ["keep"]
    assert state.confidence == 0.5
    assert state.subgoals == []


# ---------------------------------------------------------------------------
# _extract_reflection_input — tool_use block resolver
# ---------------------------------------------------------------------------


def _tool_use_block(name: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def test_extract_reflection_input_finds_named_tool_block() -> None:
    response = SimpleNamespace(
        content=[
            _text_block("thinking..."),
            _tool_use_block(
                REFLECTION_TOOL_NAME,
                {"hypotheses": ["h1"], "confidence": 0.5},
            ),
        ]
    )
    out = _reflection._extract_reflection_input(response)
    assert out == {"hypotheses": ["h1"], "confidence": 0.5}


def test_extract_reflection_input_ignores_other_tools() -> None:
    response = SimpleNamespace(
        content=[
            _tool_use_block("some_other_tool", {"junk": True}),
            _text_block("no reflection here"),
        ]
    )
    assert _reflection._extract_reflection_input(response) is None


def test_extract_reflection_input_handles_empty_content() -> None:
    response = SimpleNamespace(content=[])
    assert _reflection._extract_reflection_input(response) is None


def test_extract_reflection_input_handles_none_content() -> None:
    """Defensive — adapters that return a response without a content
    attribute (or with content=None) must not crash the helper."""
    response = SimpleNamespace(content=None)
    assert _reflection._extract_reflection_input(response) is None


# ---------------------------------------------------------------------------
# Settings knobs
# ---------------------------------------------------------------------------


def test_settings_carries_cognitive_reflection_fields() -> None:
    from core.config._settings import Settings

    fields = Settings.model_fields
    assert "cognitive_reflection_enabled" in fields
    assert fields["cognitive_reflection_enabled"].default is True
    assert "cognitive_reflection_model" in fields
    assert fields["cognitive_reflection_model"].default == ""
    assert "cognitive_reflection_max_tokens" in fields
    assert fields["cognitive_reflection_max_tokens"].default == 512


def test_toml_map_carries_cognitive_reflection_keys() -> None:
    from core.config import _TOML_TO_SETTINGS

    assert _TOML_TO_SETTINGS["cognitive.reflection_enabled"] == "cognitive_reflection_enabled"
    assert _TOML_TO_SETTINGS["cognitive.reflection_model"] == "cognitive_reflection_model"
    assert _TOML_TO_SETTINGS["cognitive.reflection_max_tokens"] == "cognitive_reflection_max_tokens"


# ---------------------------------------------------------------------------
# AgenticLoop wiring
# ---------------------------------------------------------------------------


def test_agentic_loop_has_maybe_reflect() -> None:
    """The AgenticLoop must own the toggle check, not _reflection.py —
    so the LLM module stays pure. Pin the wiring."""
    from core.agent.loop.agent_loop import AgenticLoop

    assert hasattr(AgenticLoop, "_maybe_reflect")
    src = inspect.getsource(AgenticLoop._maybe_reflect)
    assert "cognitive_reflection_enabled" in src
    assert "reflect_async" in src


def test_run_cognitive_act_observe_cycle_calls_maybe_reflect() -> None:
    """The reflection node must fire between ``record_round`` and
    the REFLECT hook event — otherwise downstream listeners see the
    deterministic snapshot, not the LLM-derived belief update."""
    from core.agent.loop.agent_loop import AgenticLoop

    src = inspect.getsource(AgenticLoop._run_cognitive_act_observe_cycle)
    # ordering: record_round → _maybe_reflect → COGNITIVE_REFLECT
    record_pos = src.index("self.cognitive_state.record_round(")
    reflect_call_pos = src.index("self._maybe_reflect(")
    reflect_event_pos = src.index("HookEvent.COGNITIVE_REFLECT")
    assert record_pos < reflect_call_pos < reflect_event_pos, (
        "Cognitive cycle ordering broken: record_round must precede "
        "_maybe_reflect must precede COGNITIVE_REFLECT event emission."
    )


def test_maybe_reflect_inherits_loop_model_provider_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty ``cognitive_reflection_model`` means reflection follows the
    active AgenticLoop route, including subscription/PAYG source."""
    from core.agent.loop.agent_loop import AgenticLoop
    from core.config import settings

    captured: dict[str, Any] = {}

    async def _fake_reflect_async(
        _state: CognitiveState,
        _tool_results: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        provider: str | None = None,
        source: str | None = None,
    ) -> None:
        captured.update(
            model=model,
            max_tokens=max_tokens,
            provider=provider,
            source=source,
        )

    monkeypatch.setattr(_reflection, "reflect_async", _fake_reflect_async)
    old_model = getattr(settings, "cognitive_reflection_model", "")
    old_tokens = getattr(settings, "cognitive_reflection_max_tokens", 512)
    old_enabled = getattr(settings, "cognitive_reflection_enabled", True)
    old_interval = getattr(settings, "cognitive_reflection_interval", 1)
    try:
        object.__setattr__(settings, "cognitive_reflection_enabled", True)
        object.__setattr__(settings, "cognitive_reflection_interval", 1)
        object.__setattr__(settings, "cognitive_reflection_model", "")
        object.__setattr__(settings, "cognitive_reflection_max_tokens", 321)

        class _Adapter:
            source = "subscription"

        class _StubSelf:
            cognitive_state = CognitiveState(round_count=1)
            model = "gpt-5.5"
            _provider = "openai-codex"
            _source = "api_key"
            _new_adapter = _Adapter()

        bound = AgenticLoop._maybe_reflect.__get__(_StubSelf(), _StubSelf)
        asyncio.run(bound([]))
    finally:
        object.__setattr__(settings, "cognitive_reflection_model", old_model)
        object.__setattr__(settings, "cognitive_reflection_max_tokens", old_tokens)
        object.__setattr__(settings, "cognitive_reflection_enabled", old_enabled)
        object.__setattr__(settings, "cognitive_reflection_interval", old_interval)

    assert captured == {
        "model": "gpt-5.5",
        "max_tokens": 321,
        "provider": "openai-codex",
        "source": "subscription",
    }


def test_maybe_reflect_configured_model_stays_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured reflection model remains an override and lets
    ``reflect_async`` resolve provider/source from that model."""
    from core.agent.loop.agent_loop import AgenticLoop
    from core.config import settings

    captured: dict[str, Any] = {}

    async def _fake_reflect_async(
        _state: CognitiveState,
        _tool_results: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        provider: str | None = None,
        source: str | None = None,
    ) -> None:
        captured.update(model=model, provider=provider, source=source)

    monkeypatch.setattr(_reflection, "reflect_async", _fake_reflect_async)
    old_model = getattr(settings, "cognitive_reflection_model", "")
    old_enabled = getattr(settings, "cognitive_reflection_enabled", True)
    old_interval = getattr(settings, "cognitive_reflection_interval", 1)
    try:
        object.__setattr__(settings, "cognitive_reflection_enabled", True)
        object.__setattr__(settings, "cognitive_reflection_interval", 1)
        object.__setattr__(settings, "cognitive_reflection_model", "claude-haiku-4-5-20251001")

        class _StubSelf:
            cognitive_state = CognitiveState(round_count=1)
            model = "gpt-5.5"
            _provider = "openai-codex"
            _source = "subscription"
            _new_adapter = object()

        bound = AgenticLoop._maybe_reflect.__get__(_StubSelf(), _StubSelf)
        asyncio.run(bound([]))
    finally:
        object.__setattr__(settings, "cognitive_reflection_model", old_model)
        object.__setattr__(settings, "cognitive_reflection_enabled", old_enabled)
        object.__setattr__(settings, "cognitive_reflection_interval", old_interval)

    assert captured == {
        "model": "claude-haiku-4-5-20251001",
        "provider": None,
        "source": None,
    }


# ---------------------------------------------------------------------------
# reflect_async — error tolerance + tool_use roundtrip
# ---------------------------------------------------------------------------


class _StubAdapter:
    """Step J-b.3 (2026-05-23) — stub matches the
    :class:`~core.llm.adapters.base.LLMAdapter` Protocol surface
    (``acomplete(AdapterCallRequest)``) instead of the legacy
    ``AgenticLLMPort.agentic_call(**kwargs)``. ``last_kwargs`` is
    rebuilt from the request dataclass so existing assertions
    (``tools``, ``tool_choice``, …) keep working as a wire-up invariant
    without leaking the dataclass type into the test body.
    """

    def __init__(
        self,
        response: Any = None,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._response = response
        self._raise = raise_exc
        self.last_kwargs: dict[str, Any] = {}

    async def acomplete(self, req: Any) -> Any:
        self.last_kwargs = {
            "model": getattr(req, "model", None),
            "system": getattr(req, "system_prompt", None),
            "messages": list(getattr(req, "messages", ())),
            "tools": list(getattr(req, "tools", ())),
            "tool_choice": getattr(req, "tool_choice", None),
            "max_tokens": getattr(req, "max_tokens", None),
            "temperature": getattr(req, "temperature", None),
        }
        if self._raise is not None:
            raise self._raise
        return self._response


def _install_reflection_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapter: _StubAdapter,
) -> None:
    """Wire deterministic fakes into the reflection module so tests
    never touch a real LLM provider."""

    async def _fake_call_with_failover(_models: list[str], do_call: Any) -> tuple[Any, str]:
        result = await do_call(_models[0])
        return result, _models[0]

    monkeypatch.setattr(_reflection, "call_with_failover", _fake_call_with_failover, raising=False)
    # Step J-b.3 — Path-B resolver. ``resolve_for(provider, source)``
    # replaces the legacy ``resolve_agentic_adapter(provider)``.
    monkeypatch.setattr(_reflection, "resolve_for", lambda _p, _src="payg": adapter, raising=False)
    monkeypatch.setattr(_reflection, "_resolve_provider", lambda _m: "anthropic", raising=False)


def test_reflect_async_uses_supplied_provider_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inherited reflection routing must use the parent loop's provider/source
    instead of re-inferring a possibly different credential path."""
    state = CognitiveState()
    adapter = _StubAdapter(
        response=SimpleNamespace(
            tool_uses=(
                {
                    "id": "tu_1",
                    "name": REFLECTION_TOOL_NAME,
                    "input": {"hypotheses": [], "confidence": 0.5},
                },
            ),
        )
    )
    resolve_calls: list[tuple[str, str]] = []

    async def _fake_call_with_failover(_models: list[str], do_call: Any) -> tuple[Any, str]:
        result = await do_call(_models[0])
        return result, _models[0]

    def _fake_resolve_for(provider: str, source: str) -> _StubAdapter:
        resolve_calls.append((provider, source))
        return adapter

    def _unexpected_model_resolve(_model: str) -> str:
        raise AssertionError("_resolve_provider should not run when provider is supplied")

    monkeypatch.setattr(_reflection, "call_with_failover", _fake_call_with_failover, raising=False)
    monkeypatch.setattr(_reflection, "resolve_for", _fake_resolve_for, raising=False)
    monkeypatch.setattr(_reflection, "_resolve_provider", _unexpected_model_resolve, raising=False)

    asyncio.run(
        _reflection.reflect_async(
            state,
            [],
            model="gpt-5.5",
            max_tokens=128,
            provider="openai-codex",
            source="subscription",
        )
    )

    assert resolve_calls == [("openai", "subscription")]


def test_reflect_async_swallows_llm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the LLM raises, the loop must continue with previous state."""
    state = CognitiveState(hypotheses=["keep"], confidence=0.4)
    _install_reflection_stubs(monkeypatch, adapter=_StubAdapter(raise_exc=RuntimeError("boom")))

    asyncio.run(
        _reflection.reflect_async(
            state, [{"tool_use_id": "t1", "content": "x"}], model="m", max_tokens=128
        )
    )
    assert state.hypotheses == ["keep"]
    assert state.confidence == 0.4


def test_reflect_async_swallows_response_without_tool_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the LLM ignores the forced tool_choice and returns only
    text (or some other tool), keep previous state.

    Step J-b.3 (2026-05-23) — empty ``tool_uses`` tuple on
    :class:`AdapterCallResult` is how the Path-B Protocol surfaces
    "model returned only text". The extractor must fall through to
    ``None`` and the caller must preserve previous state.
    """
    state = CognitiveState(hypotheses=["keep"], confidence=0.4)
    response = SimpleNamespace(tool_uses=(), text="I have nothing to say")
    _install_reflection_stubs(monkeypatch, adapter=_StubAdapter(response=response))

    asyncio.run(_reflection.reflect_async(state, [], model="m", max_tokens=128))
    assert state.hypotheses == ["keep"]
    assert state.confidence == 0.4


def test_reflect_async_applies_tool_use_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path — adapter returns an :class:`AdapterCallResult` with a
    ``tool_uses`` tuple containing the parsed payload; reflect_async
    applies it to state.

    Step J-b.3 (2026-05-23) — moved from the legacy
    ``AgenticResponse.content`` shape to the Path-B
    ``AdapterCallResult.tool_uses`` shape that ``adapter.acomplete``
    actually returns.
    """
    state = CognitiveState(goal="x")
    response = SimpleNamespace(
        tool_uses=(
            {
                "id": "tu_1",
                "name": REFLECTION_TOOL_NAME,
                "input": {
                    "hypotheses": ["h1", "h2"],
                    "confidence": 0.7,
                    "next_action_hint": "do it",
                },
            },
        ),
    )
    _install_reflection_stubs(monkeypatch, adapter=_StubAdapter(response=response))

    asyncio.run(_reflection.reflect_async(state, [], model="m", max_tokens=128))
    assert state.hypotheses == ["h1", "h2"]
    assert state.confidence == 0.7
    assert state.subgoals == ["do it"]


def test_reflect_async_passes_tool_schema_to_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire-up invariant — reflect_async must call the adapter with
    the reflection tool declared and tool_choice forced. Pin via
    captured adapter kwargs so a refactor that drops tools=[]
    surfaces here, not at runtime."""
    state = CognitiveState()
    adapter = _StubAdapter(
        response=SimpleNamespace(
            tool_uses=(
                {
                    "id": "tu_1",
                    "name": REFLECTION_TOOL_NAME,
                    "input": {"hypotheses": [], "confidence": 0.5},
                },
            ),
        )
    )
    _install_reflection_stubs(monkeypatch, adapter=adapter)

    asyncio.run(_reflection.reflect_async(state, [], model="m", max_tokens=128))

    tools = adapter.last_kwargs.get("tools")
    assert isinstance(tools, list) and len(tools) == 1
    # Step J-b.3 (2026-05-23) — ``tools`` is now a tuple of
    # :class:`~core.llm.adapters.base.ToolSpec` instances, not raw
    # dicts. The ``strict`` field that the reflection module's
    # in-source ``_REFLECTION_TOOL`` dict carries is intentionally
    # dropped at the dict→ToolSpec translation (documented in
    # ``_reflection.py``); the contract degrades to client-side
    # coercion via ``_apply_reflection``'s isinstance checks. That
    # narrowing is a tracked follow-up — see CHANGELOG.
    assert tools[0].name == REFLECTION_TOOL_NAME
    # PR-B fix-up #2 — ``tool_choice="auto"``. Anthropic docs mark
    # both ``"any"`` and named-tool forcing as incompatible with
    # adaptive/extended thinking, so only ``"auto"`` is safe across
    # every reflection-model setting.
    assert adapter.last_kwargs.get("tool_choice") == "auto"


def test_reflect_async_swallows_setup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex MCP review (PR-3 #1) catch — provider / adapter
    resolution used to escape the try block, breaking the agentic
    loop. Pin that even setup-time errors (unknown model, missing
    adapter, importable chain) keep the loop alive."""
    state = CognitiveState(hypotheses=["keep"], confidence=0.4)

    def _boom_resolve(_model: str) -> str:
        raise RuntimeError("unknown model")

    monkeypatch.setattr(_reflection, "_resolve_provider", _boom_resolve, raising=False)
    asyncio.run(_reflection.reflect_async(state, [], model="m", max_tokens=128))
    # state preserved
    assert state.hypotheses == ["keep"]
    assert state.confidence == 0.4
