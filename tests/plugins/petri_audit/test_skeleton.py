"""Smoke + conversion tests for the petri_audit plugin (P2-b).

Two tiers:

1. Skeleton checks that pass without the ``[audit]`` optional extra
   installed — package importability, factory ``ImportError`` when the
   extra is missing, ``_default_geode_runner`` stub.
2. Conversion + runner-injection tests that use duck-typed fake messages
   so they also run extra-less.

The factory's outer loop wiring (which does require ``[audit]``) is
covered indirectly: the runner-injection seam means the same
``_run_geode_loop`` is exercised here with a mock runner, so the inner
generate path is tested without a live LLM.
"""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass

import pytest

_AUDIT_INSTALLED = importlib.util.find_spec("inspect_ai") is not None


@dataclass
class _FakeMsg:
    """Duck-typed stand-in for inspect_ai ChatMessage variants."""

    role: str
    text: str = ""
    tool_call_id: str | None = None


# ---------------------------------------------------------------------------
# Tier 1 — skeleton (no [audit] extra required)
# ---------------------------------------------------------------------------


def test_petri_audit_package_imports() -> None:
    import plugins.petri_audit  # noqa: F401


def test_geode_target_module_imports_without_audit_extra() -> None:
    """Importing the target module must NOT trigger inspect_ai import.

    Module-level surface only references ``inspect_ai`` / ``inspect_petri``
    under ``TYPE_CHECKING``, so the module is loadable on a default
    ``uv sync`` without the ``[audit]`` extra installed.
    """
    from plugins.petri_audit.targets import geode_target

    assert hasattr(geode_target, "make_geode_target_agent")
    assert hasattr(geode_target, "_run_geode_loop")
    assert hasattr(geode_target, "_to_geode_messages")
    assert hasattr(geode_target, "_default_geode_runner")


@pytest.mark.skipif(
    _AUDIT_INSTALLED,
    reason="[audit] extra installed — ImportError path covers absent-extra case",
)
def test_factory_raises_import_error_without_audit_extra() -> None:
    """``make_geode_target_agent()`` requires the ``[audit]`` extra installed."""
    from plugins.petri_audit.targets.geode_target import make_geode_target_agent

    with pytest.raises(ImportError):
        make_geode_target_agent()


def test_default_runner_is_p3_stub() -> None:
    """Default runner is intentionally not implemented before P3."""
    from plugins.petri_audit.targets.geode_target import _default_geode_runner

    with pytest.raises(NotImplementedError, match="P2-b stub"):
        asyncio.run(_default_geode_runner(messages=[]))


def test_petri_audit_does_not_register_domain() -> None:
    """petri_audit is an external evaluator, not a GEODE domain.

    Importing ``plugins.petri_audit`` must not call ``register_domain``,
    so the audit plugin stays out of the default ``geode analyze`` flow.
    """
    from core.domains.loader import list_domains

    import plugins.petri_audit  # noqa: F401

    assert "petri_audit" not in list_domains()


# ---------------------------------------------------------------------------
# Tier 2 — conversion + runner injection (duck typed, no [audit] extra)
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


def test_run_geode_loop_calls_injected_runner_with_converted_messages() -> None:
    """``_run_geode_loop`` converts then forwards to the injected runner."""
    from plugins.petri_audit.targets.geode_target import _run_geode_loop

    captured: list[list[dict]] = []

    async def fake_runner(messages: list[dict]) -> str:
        captured.append(messages)
        return "mock-response"

    out = asyncio.run(
        _run_geode_loop(
            [_FakeMsg(role="user", text="probe")],
            runner=fake_runner,
        )
    )

    assert out == "mock-response"
    assert captured == [[{"role": "user", "content": "probe"}]]


def test_run_geode_loop_falls_back_to_default_runner_when_none() -> None:
    """No runner injected → default runner runs (and currently raises)."""
    from plugins.petri_audit.targets.geode_target import _run_geode_loop

    with pytest.raises(NotImplementedError, match="P2-b stub"):
        asyncio.run(_run_geode_loop([_FakeMsg(role="user", text="x")]))
