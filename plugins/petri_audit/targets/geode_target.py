"""GEODE Custom Target for Petri (skeleton, P1).

Adapts GEODE's ``AgenticLoop`` to Petri 3.0's Custom Target protocol —
``execute(state, context: TargetContext)`` introduced in Petri v3.0.4
(see ``meridianlabs-ai/inspect_petri`` CHANGELOG).

P1 scope: stub. The real wiring lands in P2 alongside the ``[audit]``
optional extra. ``inspect_ai`` / ``inspect_petri`` are deliberately NOT
imported here so ``uv sync`` (without the audit extra) keeps working
and the v0.89.x cold-start budget is preserved.
"""

from __future__ import annotations

from typing import Any


class GeodeTarget:
    """Petri Custom Target backed by GEODE's AgenticLoop.

    Per Petri 3.0.4, a Custom Target exposes ``execute(state, context)``
    where ``context`` is a ``TargetContext`` that provides the auditor-side
    ``Channel`` and slot policy via ``expect()``.

    P1 deliberately raises ``NotImplementedError`` rather than returning
    None so a misconfigured invocation surfaces a clear failure instead
    of producing empty audit transcripts.
    """

    name: str = "geode"

    async def execute(self, state: Any, context: Any) -> None:
        raise NotImplementedError(
            "GeodeTarget.execute is a P1 stub; implementation lands in P2 "
            "with the [audit] optional extra. "
            "See docs/plans/eval-petri-integration.md."
        )
