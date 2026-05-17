"""Sub-agent announce-queue polling helper.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). The
function takes the ``AgenticLoop`` as the first parameter (``loop``).
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
