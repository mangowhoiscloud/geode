"""Secret redaction — strip API keys from text before LLM context injection.

Applies regex-based pattern matching to detect and replace known
API key formats (Anthropic, OpenAI, ZhipuAI, generic bearer tokens).
Used by BashTool.to_tool_result() and MCP tool result post-processing.
"""

from __future__ import annotations

import re

# API key patterns ordered from most specific to most general.
# More specific patterns (sk-ant-, sk-proj-) are checked first to avoid
# partial matches from the generic sk- pattern.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[a-zA-Z0-9\-_]{20,}"),  # Anthropic
    re.compile(r"sk-proj-[a-zA-Z0-9\-_]{20,}"),  # OpenAI project keys
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # Generic OpenAI
    re.compile(r"[a-f0-9]{32}\.[a-zA-Z0-9]{16,}"),  # ZhipuAI (hex.token)
    re.compile(r"ghp_[a-zA-Z0-9]{36,}"),  # GitHub PAT
    re.compile(r"gho_[a-zA-Z0-9]{36,}"),  # GitHub OAuth
    re.compile(r"xoxb-[a-zA-Z0-9\-]+"),  # Slack bot token
    re.compile(r"xoxp-[a-zA-Z0-9\-]+"),  # Slack user token
]


def redact_secrets(text: str, *, placeholder: str = "[REDACTED]") -> str:
    """Replace API key patterns in text with placeholder.

    Returns the original text unchanged if no patterns match.
    """
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(placeholder, text)
    return text
