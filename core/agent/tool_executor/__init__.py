"""ToolExecutor — route tool calls to handlers with HITL safety checks.

Central dispatch for all tools available to the AgenticLoop.
Classifies tools by safety level and gates dangerous operations
behind user approval.

Also contains ToolCallProcessor — orchestrates parallel/sequential
execution of tool_use blocks returned by the LLM.
"""

from __future__ import annotations

from core.agent.approval import (
    _write_denial_with_fallback as _write_denial_with_fallback,
)
from core.agent.safety import AUTO_APPROVED_MCP_SERVERS as AUTO_APPROVED_MCP_SERVERS
from core.agent.safety import DANGEROUS_TOOLS as DANGEROUS_TOOLS
from core.agent.safety import EXPENSIVE_TOOLS as EXPENSIVE_TOOLS
from core.agent.safety import SAFE_BASH_PREFIXES as SAFE_BASH_PREFIXES
from core.agent.safety import SAFE_TOOLS as SAFE_TOOLS
from core.agent.safety import WRITE_TOOLS as WRITE_TOOLS
from core.ui.console import console as console

from ._helpers import _compute_model_tool_limit, _guard_tool_result
from ._spinner import _tool_spinner
from .executor import ToolExecutor
from .processor import ToolCallProcessor

__all__ = [
    "AUTO_APPROVED_MCP_SERVERS",
    "DANGEROUS_TOOLS",
    "EXPENSIVE_TOOLS",
    "SAFE_BASH_PREFIXES",
    "SAFE_TOOLS",
    "WRITE_TOOLS",
    "ToolCallProcessor",
    "ToolExecutor",
    "_compute_model_tool_limit",
    "_guard_tool_result",
    "_tool_spinner",
    "_write_denial_with_fallback",
]
