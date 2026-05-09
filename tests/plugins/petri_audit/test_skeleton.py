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
