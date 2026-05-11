"""Smoke + conversion + split tests for the petri_audit plugin (P3-a).

Skeleton + helpers checks that pass without the ``[audit]`` optional
extra installed. The Custom Target factory (P1..P2-c) is gone: Petri's
standard ``target_agent`` drives the audit loop via the registered
``geode/<base-model>`` ``ModelAPI``, and our ``generate()`` is one shot.

P3-a adds ``_split_messages`` (system/history/last-user split) plus
``_default_geode_runner`` real wiring against ``AgenticLoop``. The
helpers are unit-tested here; the live runner is exercised in P3-b
with explicit user authorisation.
"""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

_AUDIT_INSTALLED = importlib.util.find_spec("inspect_ai") is not None


@dataclass
class _FakeMsg:
    """Duck-typed stand-in for ``inspect_ai`` ChatMessage variants."""

    role: str
    text: str = ""
    tool_call_id: str | None = None


# ---------------------------------------------------------------------------
# Plugin surface
# ---------------------------------------------------------------------------


def test_petri_audit_package_imports() -> None:
    """``import plugins.petri_audit`` succeeds with or without [audit]."""
    import plugins.petri_audit  # noqa: F401


def test_geode_target_module_imports_without_audit_extra() -> None:
    """Module-level surface has no ``inspect_ai`` dependency.

    Helpers + ``register()`` factory load on a default ``uv sync`` so
    cold-start stays clean. ``inspect_ai`` is imported only when
    ``register()`` is actually invoked.
    """
    from plugins.petri_audit.targets import geode_target

    assert hasattr(geode_target, "register")
    assert hasattr(geode_target, "_to_geode_messages")
    assert hasattr(geode_target, "_split_messages")
    assert hasattr(geode_target, "_default_geode_runner")
    assert hasattr(geode_target, "GeodeRunner")


@pytest.mark.skipif(
    _AUDIT_INSTALLED,
    reason="[audit] extra installed — ImportError path covers absent-extra case",
)
def test_register_raises_import_error_without_audit_extra() -> None:
    """``register()`` requires the ``[audit]`` extra installed."""
    from plugins.petri_audit.targets.geode_target import register

    with pytest.raises(ImportError):
        register()


def test_default_runner_rejects_empty_messages() -> None:
    """Empty message list fails fast before any GEODE bootstrap."""
    from plugins.petri_audit.targets.geode_target import _default_geode_runner

    with pytest.raises(ValueError, match="Empty message history"):
        asyncio.run(_default_geode_runner(messages=[]))


def test_default_runner_passes_pinned_model_to_loop_with_drift_disabled() -> None:
    """N6-followup: caller-pinned model arrives at AgenticLoop sticky.

    Source-inspect — verify the runner constructs AgenticLoop with the
    model arg and ``disable_settings_drift=True`` when ``model`` is
    pinned, and lets it fall back (no flag) when ``model is None``.
    """
    import inspect

    from plugins.petri_audit.targets import geode_target

    src = inspect.getsource(geode_target._default_geode_runner)
    code_only = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "model=model" in code_only, (
        "_default_geode_runner must pass its ``model`` argument to AgenticLoop"
    )
    assert "disable_settings_drift=(model is not None)" in code_only, (
        "_default_geode_runner must scope drift suppression to caller-pinned "
        "models — passing model=None must keep the regular drift sync active."
    )


def test_geode_model_api_routes_default_sentinel_to_none() -> None:
    """N6-followup: ``geode/default`` sentinel → runner_model=None.

    The bare ``base`` (e.g. ``claude-opus-4-7``) is forwarded; the
    ``default`` sentinel maps to ``None`` so AgenticLoop falls back to
    ANTHROPIC_PRIMARY + drift sync.
    """
    import inspect

    from plugins.petri_audit.targets import geode_target

    src = inspect.getsource(geode_target.register)
    assert 'base == "default"' in src, (
        "GeodeModelAPI.generate must treat ``geode/default`` as the no-pin sentinel."
    )


def test_default_runner_uses_async_arun_not_sync_run() -> None:
    """N3 regression guard — must not call sync ``loop.run`` inside async runner.

    inspect-petri invokes ``GeodeModelAPI.generate`` (async) inside its
    own audit event loop. ``AgenticLoop.run`` is a sync wrapper that
    calls ``asyncio.run(self.arun(...))``, which raises
    ``RuntimeError: asyncio.run() cannot be called from a running event
    loop``. v2 (#988/#989) silently failed every target invocation
    because of this — see docs/audits/2026-05-10-petri-2a-v2.md § C4.

    This test inspects the source so a future refactor doesn't
    accidentally regress.
    """
    import inspect

    from plugins.petri_audit.targets import geode_target

    src = inspect.getsource(geode_target._default_geode_runner)
    # Strip comments + docstrings before checking — those legitimately
    # mention the old call form.
    code_only = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "await loop.arun(" in code_only, (
        "_default_geode_runner must `await loop.arun(...)` to avoid the "
        "asyncio.run() nested-loop RuntimeError under inspect-petri."
    )
    assert "= loop.run(" not in code_only and "  loop.run(" not in code_only, (
        "_default_geode_runner must NOT call sync `loop.run(...)` — "
        "that path triggers asyncio.run() inside an already-running "
        "event loop."
    )


def test_geode_target_runner_invokes_token_tracker_record() -> None:
    """A (token tracker wiring guard) — `_default_geode_runner`
    eventually triggers `_track_usage` → `tracker.record(...)` →
    `~/.geode/usage/<YYYY-MM>.jsonl` append. N7'/N8 라이브에서 0
    records 였던 결함 A 의 root-cause hypothesis 검증.

    This is a *source-inspect* guard, not a runtime verification —
    instantiating ``AgenticLoop`` requires a full GEODE bootstrap
    (readiness, executor, handlers) that's much heavier than a pytest
    unit test should attempt. The wiring chain we lock in:

        _default_geode_runner
          └── AgenticLoop.arun (loop.py:761 self._track_usage(response))
                └── _response.track_usage (loop.py:1176)
                      └── get_tracker().record (token_tracker.py:260)
                            └── _persist_usage (token_tracker.py:358)
                                  └── usage_store.record (~/.geode/usage/)

    Each link below is verified by source-inspect so a future refactor
    that breaks the chain (e.g. dropping ``_track_usage`` from the
    successful-LLM-call branch in loop.py) fires a clear test failure.
    """
    import inspect

    from core.agent.loop import _response
    from core.agent.loop import loop as loop_mod
    from core.llm import token_tracker
    from plugins.petri_audit.targets import geode_target

    # Link 1: runner → AgenticLoop.arun
    runner_src = inspect.getsource(geode_target._default_geode_runner)
    assert "AgenticLoop(" in runner_src
    assert "await loop.arun(" in runner_src

    # Link 2: AgenticLoop.arun → self._track_usage(response)
    arun_src = inspect.getsource(loop_mod.AgenticLoop.arun)
    assert "_track_usage(response)" in arun_src, (
        "AgenticLoop.arun must call self._track_usage(response) on a "
        "successful LLM response. Without it the petri audit's target "
        "calls bypass the tracker."
    )

    # Link 3: _track_usage → _response.track_usage
    inner_src = inspect.getsource(loop_mod.AgenticLoop._track_usage)
    assert "_response.track_usage" in inner_src

    # Link 4: _response.track_usage → tracker.record
    track_src = inspect.getsource(_response.track_usage)
    assert "tracker = get_tracker()" in track_src
    assert "tracker.record(" in track_src

    # Link 5: tracker.record → _persist_usage → usage_store
    record_src = inspect.getsource(token_tracker.TokenTracker.record)
    assert "_persist_usage" in record_src
    persist_src = inspect.getsource(token_tracker.TokenTracker._persist_usage)
    assert "get_usage_store()" in persist_src
    assert ".record(" in persist_src


def test_token_tracker_record_appends_to_geode_usage_jsonl(tmp_path: Path) -> None:
    """A — explicit smoke that the usage_store path actually writes a
    JSONL record when the tracker fires. Decouples the test from
    ``Path.home()`` by injecting a temp dir."""
    from core.llm.token_tracker import TokenTracker
    from core.llm.usage_store import UsageStore

    store = UsageStore(usage_dir=tmp_path)
    tracker = (
        TokenTracker(usage_store=store)
        if "usage_store" in TokenTracker.__init__.__code__.co_varnames
        else TokenTracker()
    )
    # ``TokenTracker._persist_usage`` is a staticmethod that reaches for
    # ``get_usage_store()`` — patch the symbol so a fresh tracker writes
    # to the temp dir without touching ``~/.geode``.
    # ``_persist_usage`` does ``from core.llm.usage_store import get_usage_store``
    # at call time, so patch the symbol on the source module — patching
    # the importing module's namespace would miss the lazy import.
    with patch("core.llm.usage_store.get_usage_store", return_value=store):
        tracker.record("claude-haiku-4-5-20251001", input_tokens=10, output_tokens=5)

    files = list(tmp_path.glob("*.jsonl"))
    assert files, f"Expected JSONL in {tmp_path}, found {[p.name for p in tmp_path.iterdir()]}"
    body = files[0].read_text(encoding="utf-8").strip()
    assert "claude-haiku-4-5-20251001" in body
    assert '"input_tokens": 10' in body or '"input": 10' in body or "10" in body


def test_default_runner_returns_text_and_usage_tuple(monkeypatch) -> None:
    """F-A1 contract — ``_default_geode_runner`` returns ``(text,
    usage_dict)``. The Custom ModelAPI surfaces ``usage_dict`` into
    inspect_ai's ``ModelOutput.usage`` so the eval log's role_usage
    aggregation finally lists the target. Pre-F-A1 the runner returned
    bare text and the petri audit's target column was always empty
    (see ``docs/audits/2026-05-11-petri-tracker-A-live-verify.md``).

    Mock-based — exercises the runner without spinning up the full
    GEODE bootstrap (which would need readiness, handlers, executor).
    """
    if not _AUDIT_INSTALLED:
        pytest.skip("[audit] extra not installed")

    from core.llm.token_tracker import LLMUsage
    from plugins.petri_audit.targets import geode_target
    from plugins.petri_audit.targets.geode_target import _default_geode_runner

    class _FakeAgenticResult:
        text = "hi"
        usage = LLMUsage(
            model="claude-haiku-4-5-20251001",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=80,
            thinking_tokens=12,
            cost_usd=0.001,
        )

    class _FakeLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.model = kwargs.get("model") or "claude-haiku-4-5-20251001"

        async def arun(self, _user_input):
            return _FakeAgenticResult()

    monkeypatch.setattr(geode_target, "_to_geode_messages", lambda msgs: msgs)
    monkeypatch.setattr("core.wiring.startup.check_readiness", lambda: object(), raising=False)
    monkeypatch.setattr("core.cli._set_readiness", lambda r: None, raising=False)
    monkeypatch.setattr("core.cli._build_tool_handlers", lambda verbose=False: {}, raising=False)
    monkeypatch.setattr(
        "core.agent.conversation.ConversationContext", lambda: type("X", (), {"messages": []})()
    )
    monkeypatch.setattr("core.agent.tool_executor.ToolExecutor", lambda **k: None)
    monkeypatch.setattr("core.agent.loop.AgenticLoop", _FakeLoop)

    text, usage = asyncio.run(
        _default_geode_runner(
            [{"role": "user", "content": "hello"}], model="claude-haiku-4-5-20251001"
        )
    )
    assert text == "hi"
    assert usage is not None
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 50
    assert usage["cache_read_tokens"] == 80
    assert usage["thinking_tokens"] == 12
    assert usage["cost_usd"] == 0.001


def test_geode_model_api_emits_inspect_modelusage(monkeypatch) -> None:
    """F-A1 — ``GeodeModelAPI.generate`` constructs ``ModelOutput`` with
    a fully populated ``ModelUsage``. Direct construction (vs the
    simple ``from_content`` factory) is required for inspect_ai's
    log.stats.role_usage aggregation to count target tokens.

    Uses the ``runner=fake`` injection seam so no live LLM call.
    """
    if not _AUDIT_INSTALLED:
        pytest.skip("[audit] extra not installed")
    from inspect_ai.model import get_model

    async def fake_runner(_messages):
        return "hi", {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 80,
            "thinking_tokens": 12,
            "cost_usd": 0.001,
        }

    model = get_model("geode/claude-haiku-4-5-20251001", runner=fake_runner)
    out = asyncio.run(model.generate("hello"))

    assert out.usage is not None
    assert out.usage.input_tokens == 100
    assert out.usage.output_tokens == 50
    assert out.usage.input_tokens_cache_read == 80
    assert out.usage.reasoning_tokens == 12
    assert out.usage.total_tokens == 100 + 50 + 80  # cache_w + cache_r summed
    assert out.usage.total_cost == 0.001


def test_geode_model_api_back_compat_str_runner(monkeypatch) -> None:
    """D5 — pre-F-A1 test runners returned bare strings. The new
    GeodeModelAPI must still accept this shape (``usage`` stays None)
    so downstream tests on ``geode/...`` keep working."""
    if not _AUDIT_INSTALLED:
        pytest.skip("[audit] extra not installed")
    from inspect_ai.model import get_model

    async def fake_runner_str(_messages):
        return "legacy-text"

    # Different alias to dodge inspect_ai's get_model cache (the prior
    # test in this module registered a different runner on the haiku
    # alias). Same code path either way.
    model = get_model("geode/claude-opus-4-7", runner=fake_runner_str)
    out = asyncio.run(model.generate("hello"))

    assert out.choices[0].message.text == "legacy-text"
    assert out.usage is None


def test_petri_audit_does_not_register_domain() -> None:
    """petri_audit is an external evaluator, not a GEODE domain.

    Importing ``plugins.petri_audit`` must not call ``register_domain``,
    so the audit plugin stays out of the default ``geode analyze`` flow.
    """
    from core.domains.loader import list_domains

    import plugins.petri_audit  # noqa: F401

    assert "petri_audit" not in list_domains()


# ---------------------------------------------------------------------------
# Message conversion (duck typed, no [audit] extra)
# ---------------------------------------------------------------------------


def test_to_geode_messages_converts_each_role() -> None:
    """All four ChatMessage roles map to the expected GEODE shape."""
    from plugins.petri_audit.targets.geode_target import _to_geode_messages

    converted = _to_geode_messages(
        [
            _FakeMsg(role="system", text="you are a tester"),
            _FakeMsg(role="user", text="hello"),
            _FakeMsg(role="assistant", text="hi"),
            _FakeMsg(role="tool", text="result-body", tool_call_id="call-1"),
        ]
    )

    assert converted == [
        {"role": "system", "content": "you are a tester"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "result-body",
                }
            ],
        },
    ]


def test_to_geode_messages_rejects_unknown_role() -> None:
    from plugins.petri_audit.targets.geode_target import _to_geode_messages

    with pytest.raises(ValueError, match="Unsupported message role"):
        _to_geode_messages([_FakeMsg(role="orchestrator", text="x")])


def test_to_geode_messages_treats_missing_text_as_empty() -> None:
    """``text`` missing or None is normalised to empty string."""
    from plugins.petri_audit.targets.geode_target import _to_geode_messages

    class _NoText:
        role = "user"

    out = _to_geode_messages([_NoText()])
    assert out == [{"role": "user", "content": ""}]


# ---------------------------------------------------------------------------
# Message split (P3-a — system/history/last-user)
# ---------------------------------------------------------------------------


def test_split_messages_extracts_system_history_and_last_user() -> None:
    """Standard layout: system → suffix, mid turns → history, tail → prompt."""
    from plugins.petri_audit.targets.geode_target import _split_messages

    sys_text, history, last = _split_messages(
        [
            {"role": "system", "content": "you are a tester"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "follow up"},
        ]
    )

    assert sys_text == "you are a tester"
    assert history == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
    ]
    assert last == "follow up"


def test_split_messages_empty_returns_blanks() -> None:
    from plugins.petri_audit.targets.geode_target import _split_messages

    assert _split_messages([]) == ("", [], "")


def test_split_messages_concatenates_multiple_system_messages() -> None:
    from plugins.petri_audit.targets.geode_target import _split_messages

    sys_text, _, _ = _split_messages(
        [
            {"role": "system", "content": "rule 1"},
            {"role": "system", "content": "rule 2"},
            {"role": "user", "content": "ok"},
        ]
    )

    assert "rule 1" in sys_text
    assert "rule 2" in sys_text


def test_split_messages_non_user_last_falls_into_history() -> None:
    """If the tail is not a user message, ``last_user`` is blank.

    AgenticLoop should then receive an empty prompt — caller's
    responsibility to handle (Petri's target_agent always seeds with a
    user message, so this branch is defensive).
    """
    from plugins.petri_audit.targets.geode_target import _split_messages

    sys_text, history, last = _split_messages(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
    )

    assert sys_text == ""
    assert last == ""
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
