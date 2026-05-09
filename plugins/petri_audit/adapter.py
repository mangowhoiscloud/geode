"""Adapter between GEODE AgenticLoop and Petri TargetContext (skeleton, P1).

Translates Petri's ``Stage`` / ``Slot`` / ``expect()`` commands into calls
against ``core.agent.loop.loop:AgenticLoop``, and surfaces tool-call output
back through Petri's ``TargetContext.Channel``.

P1 scope: surface declared, behavior unimplemented. P2 fills in the actual
translation once the ``[audit]`` extra is installed.
"""

from __future__ import annotations

from typing import Any


class GeodeAuditAdapter:
    """Translates Petri Stage commands into AgenticLoop turns.

    P1 deliberately raises ``NotImplementedError`` on any call — a misuse
    is loud rather than silent.
    """

    def turn(self, payload: Any) -> Any:
        raise NotImplementedError(
            "GeodeAuditAdapter.turn is a P1 stub; "
            "see docs/plans/eval-petri-integration.md (Phase P2)."
        )
