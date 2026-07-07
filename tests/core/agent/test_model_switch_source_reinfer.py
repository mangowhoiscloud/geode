"""PR-MODEL-SWITCH-SOURCE (2026-06-12) — cross-provider /model re-infers
the source axis.

Incident (serve.log 2026-06-12 02:34): an anthropic session (inferred
source=payg) switched to gpt-5.5 via /model right after the operator
completed ``/login codex`` (ChatGPT Pro Lite OAuth registered, daemon
auth.toml reload confirmed). The old rule "loop._source stays constant
across the switch" carried anthropic's ``payg`` onto openai, so the call
routed through openai-payg's stale API key and 401-ed in 0.6s — while
``infer_source("openai")`` resolved to ``subscription`` the whole time.

Contract pinned here:
1. Provider-changing switch with an INFERRED source → re-infer for the
   new provider (payg → subscription when the OAuth profile exists).
2. Provider-changing switch with an EXPLICIT caller-pinned source →
   source survives (operators' explicit pins are never overridden).
3. Same-provider switch → source untouched (no spurious re-inference).
"""

from __future__ import annotations

from typing import Any

import pytest
from core.agent.loop import _model_switching


class _FakeToolProcessor:
    _model = ""
    _provider = ""
    _source = ""
    _adapter_name = ""


class _FakeLoop:
    """Minimal attribute surface for _apply_model_update."""

    def __init__(self, *, provider: str, source: str, explicit: bool) -> None:
        self.model = "claude-fable-5"
        self._provider = provider
        self._source = source
        self._source_explicit = explicit
        self._new_adapter = None
        self._tool_processor = _FakeToolProcessor()
        self._prompt_dirty = False


@pytest.fixture
def _patched_resolution(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {"resolved": []}
    monkeypatch.setattr(
        _model_switching, "_resolve_provider", lambda model: "openai", raising=False
    )
    monkeypatch.setattr(
        _model_switching,
        "_resolve_path_b_adapter",
        lambda provider, source: (
            calls["resolved"].append((provider, source))
            or type(
                "Adapter",
                (),
                {"provider": provider, "source": source, "name": f"{provider}-{source}"},
            )()
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source",
        lambda provider: "subscription",
    )
    monkeypatch.setattr("core.ui.agentic_ui.update_session_model", lambda model: None)
    return calls


def test_cross_provider_switch_reinfers_inferred_source(
    _patched_resolution: dict[str, Any],
) -> None:
    loop = _FakeLoop(provider="anthropic", source="payg", explicit=False)

    _model_switching._apply_model_update(loop, "gpt-5.5")  # type: ignore[arg-type]

    assert loop._source == "subscription", (
        "inferred source must be re-inferred for the new provider — "
        "carrying anthropic's payg onto openai reproduced the 2026-06-12 401"
    )
    assert _patched_resolution["resolved"] == [("openai", "subscription")], (
        "the Path-B adapter must be resolved with the RE-INFERRED source"
    )
    assert loop._tool_processor._model == "gpt-5.5"
    assert loop._tool_processor._provider == "openai"
    assert loop._tool_processor._source == "subscription"
    assert loop._tool_processor._adapter_name == "openai-subscription"


def test_cross_provider_switch_keeps_explicit_source(
    _patched_resolution: dict[str, Any],
) -> None:
    loop = _FakeLoop(provider="anthropic", source="payg", explicit=True)

    _model_switching._apply_model_update(loop, "gpt-5.5")  # type: ignore[arg-type]

    assert loop._source == "payg", "explicit caller pin must survive the switch"
    assert _patched_resolution["resolved"] == [("openai", "payg")]
    assert loop._tool_processor._provider == "openai"
    assert loop._tool_processor._source == "payg"


def test_same_provider_switch_does_not_touch_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _model_switching, "_resolve_provider", lambda model: "anthropic", raising=False
    )
    monkeypatch.setattr("core.ui.agentic_ui.update_session_model", lambda model: None)

    def _boom(provider: str) -> str:
        raise AssertionError("infer_source must not run on a same-provider switch")

    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", _boom)
    loop = _FakeLoop(provider="anthropic", source="payg", explicit=False)

    _model_switching._apply_model_update(loop, "claude-haiku-4-5-20251001")  # type: ignore[arg-type]

    assert loop._source == "payg"


def test_agentic_loop_records_source_explicitness() -> None:
    """Source pin — the loop constructor must record whether the source was
    caller-pinned (the re-inference gate reads ``_source_explicit``)."""
    import inspect

    from core.agent.loop import agent_loop

    src = inspect.getsource(agent_loop.AgenticLoop.__init__)
    assert "_source_explicit" in src
