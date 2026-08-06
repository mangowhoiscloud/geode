"""Sub-agent completion delivery for ``AgenticLoop``.

Split out of ``_helpers.py`` in PR-HELPERS-3SPLIT (2026-05-24) per
the new Naming CANNOT row that forbids ``_helpers`` filenames once a
caller appears. The function was originally extracted into a sibling
``_announce.py`` (Tier 3 #7) and later absorbed back into
``_helpers.py`` by PR-CLEANUP-1 (2026-05-23) on the rationale that
three under-100-LOC siblings shared a single caller. This split
reverses that fold along the actual ownership line — sub-agent completion
delivery is its own subsystem, distinct from the tool factory and planner
dispatcher that ``_helpers.py`` also hosted.

The module surfaces exactly one symbol — ``check_announced_results``
— which ``AgenticLoop._check_announced_results`` delegates to once
per round to drain both the legacy in-process announce queue and the durable
collaboration mailbox, then inject each item as a system event message.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def check_announced_results(loop: AgenticLoop, messages: list[dict[str, Any]]) -> int:
    """Poll for sub-agent announced results and inject into conversation.

    Drain legacy announces and durable mailbox items at a legal loop boundary.

    OpenClaw Spawn+Announce pattern: parent polls at each round start.
    """
    injected = 0
    if loop._parent_session_key:
        # Local import avoids sub_agent -> worker -> loop.__init__ -> this
        # module -> sub_agent during direct imports.
        from core.agent.sub_agent import drain_announced_results

        for result in drain_announced_results(loop._parent_session_key):
            status_label = "completed" if result.success else "failed"
            content = (
                f"Sub-agent {status_label}: task_id={result.task_id}, summary={result.summary}"
            )
            if result.error_message:
                content += f", error={result.error_message}"
            loop.context.add_system_event("subagent_completed", content)
            messages.append({"role": "user", "content": f"[system:subagent_completed] {content}"})
            injected += 1

    try:
        from core.memory.collaboration import CollaborationStore

        mailbox = CollaborationStore().drain_mailbox(loop._session_id)
    except Exception:
        log.warning("Collaboration mailbox drain failed", exc_info=True)
        mailbox = []
    for item in mailbox:
        if item.kind == "message":
            event = "subagent_message"
            content = (
                f"Parent follow-up: {item.payload.get('message', '')} "
                f"(generation={item.payload.get('generation', '')})"
            )
        else:
            event = "subagent_completed"
            content = "Sub-agent completion: " + json.dumps(
                item.payload, ensure_ascii=False, sort_keys=True
            )
        loop.context.add_system_event(event, content)
        messages.append({"role": "user", "content": f"[system:{event}] {content}"})
        injected += 1
    return injected
