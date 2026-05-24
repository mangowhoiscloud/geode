"""Sub-agent announce-queue polling for ``AgenticLoop``.

Split out of ``_helpers.py`` in PR-HELPERS-3SPLIT (2026-05-24) per
the new Naming CANNOT row that forbids ``_helpers`` filenames once a
caller appears. The function was originally extracted into a sibling
``_announce.py`` (Tier 3 #7) and later absorbed back into
``_helpers.py`` by PR-CLEANUP-1 (2026-05-23) on the rationale that
three under-100-LOC siblings shared a single caller. This split
reverses that fold along the actual ownership line — sub-agent
announce-queue draining is its own subsystem (OpenClaw
Spawn+Announce pattern), distinct from the tool factory and the
planner dispatcher that ``_helpers.py`` also hosted.

The module surfaces exactly one symbol — ``check_announced_results``
— which ``AgenticLoop._check_announced_results`` delegates to once
per round to drain results from
:func:`core.agent.sub_agent.drain_announced_results` and inject each
completed sub-agent's summary as a system event message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.agent.sub_agent import SubAgentResult, drain_announced_results

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def check_announced_results(loop: AgenticLoop, messages: list[dict[str, Any]]) -> int:
    """Poll for sub-agent announced results and inject into conversation.

    Drains the announce queue for this parent session and adds each
    completed sub-agent's summary as a system event message.

    OpenClaw Spawn+Announce pattern: parent polls at each round start.
    """
    if not loop._parent_session_key:
        return 0
    announced: list[SubAgentResult] = drain_announced_results(loop._parent_session_key)
    if not announced:
        return 0
    for result in announced:
        status_label = "completed" if result.success else "failed"
        content = f"Sub-agent {status_label}: task_id={result.task_id}, summary={result.summary}"
        if result.error_message:
            content += f", error={result.error_message}"
        loop.context.add_system_event("subagent_completed", content)
        messages.append({"role": "user", "content": f"[system:subagent_completed] {content}"})
        log.debug("Injected announce for task_id=%s", result.task_id)
    return len(announced)
