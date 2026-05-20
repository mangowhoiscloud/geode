"""ContextVar-scoped accessor for the active :class:`CognitiveState`.

PR-4 C-3 of the cognitive-loop-uplift sprint
(``docs/plans/2026-05-21-cognitive-loop-uplift.md``).

Hooks fired from inside the agentic loop (TOOL_EXEC_ENDED in
particular) need to embed a ``cognitive_state`` snapshot in the
episode they record, but the tool executor — which constructs the
TOOL_EXEC_ENDED payload — has no reference to the surrounding
:class:`AgenticLoop`. A ContextVar bridges the two without coupling
the executor's API to a new positional argument.

Contract:
  - :class:`AgenticLoop` calls :func:`set_cognitive_state` once at
    session start with its ``self.cognitive_state``.
  - Hook handlers and any cross-cutting observer can read it via
    :func:`get_cognitive_state`. Returns ``None`` if no loop is
    active (test harnesses, standalone tool invocations).

Read-Write parity (CLAUDE.md): every reader pairs with a writer.
Both live in this module so the bilateral wiring stays grep-visible.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent.cognitive_state import CognitiveState


_active_state: ContextVar[CognitiveState | None] = ContextVar(
    "geode_active_cognitive_state", default=None
)
_active_session_id: ContextVar[str] = ContextVar("geode_active_session_id", default="")
# PR-F (2026-05-21) — sub-agent lineage. When the active loop is a
# child spawned via the OpenClaw spawn pattern, this carries the
# parent loop's ``_parent_session_key`` (the OpenClaw routing key,
# e.g. ``"subject:foo:bar"``, NOT the parent's ``_session_id`` uuid
# format). Naming matches the AgenticLoop constructor kwarg so the
# data shape is unambiguous. Empty string = top-level loop.
# Future-PR scope: a separate ContextVar ``parent_session_id`` can
# be added when the sub-agent spawner is plumbed to forward the
# parent's actual ``_session_id`` through WorkerRequest.
_active_parent_session_key: ContextVar[str] = ContextVar(
    "geode_active_parent_session_key", default=""
)


def get_cognitive_state() -> CognitiveState | None:
    """Return the active :class:`CognitiveState`, or ``None`` if no
    agentic loop is bound to this context."""
    return _active_state.get()


def set_cognitive_state(state: CognitiveState | None) -> None:
    """Bind ``state`` to the current context. ``None`` clears the
    binding (useful for test isolation)."""
    _active_state.set(state)


def get_session_id() -> str:
    """Return the active agentic loop's session id, or ``""`` if no
    loop is bound to this context. Paired with the cognitive-state
    ContextVar so episodic memory rows can carry both without the
    tool executor knowing about either."""
    return _active_session_id.get()


def set_session_id(session_id: str) -> None:
    """Bind ``session_id`` to the current context."""
    _active_session_id.set(session_id)


def get_parent_session_key() -> str:
    """PR-F (2026-05-21) — return the active loop's parent
    ``_parent_session_key`` (OpenClaw routing-key format like
    ``"subject:foo:bar"``), or ``""`` for a top-level loop. Read by
    the episodic recorder so cross-session attribution can group
    child Episode rows by spawning parent.

    NOTE: this is the *routing key*, NOT the parent's ``_session_id``
    uuid. A future PR can add a separate ``parent_session_id``
    ContextVar when the sub-agent spawner is plumbed to forward
    the parent's actual session id through WorkerRequest."""
    return _active_parent_session_key.get()


def set_parent_session_key(parent_session_key: str) -> None:
    """Bind ``parent_session_key`` to the current context. Empty
    string clears the binding (top-level loop)."""
    _active_parent_session_key.set(parent_session_key)


__all__ = [
    "get_cognitive_state",
    "get_parent_session_key",
    "get_session_id",
    "set_cognitive_state",
    "set_parent_session_key",
    "set_session_id",
]
