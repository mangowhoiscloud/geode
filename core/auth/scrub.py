"""Credential scrubbing — strip secrets from error messages.

Hermes pattern: regex-based removal of API keys, bearer tokens,
and other credentials before messages reach the LLM or logs.
"""

from __future__ import annotations

import re

# Matches common credential patterns in error messages / URLs / headers.
# Hermes mcp_tool.py _CREDENTIAL_PATTERN + OpenClaw masked auth display.
_CREDENTIAL_PATTERN = re.compile(
    r"(?:"
    r"ghp_[A-Za-z0-9_]{1,255}"  # GitHub PAT
    r"|gho_[A-Za-z0-9_]{1,255}"  # GitHub OAuth token
    r"|sk-[A-Za-z0-9_-]{20,255}"  # OpenAI-style key
    r"|xoxb-[A-Za-z0-9_/-]{20,255}"  # Slack bot token
    r"|xapp-[A-Za-z0-9_/-]{20,255}"  # Slack app token
    r"|Bearer\s+\S{10,}"  # Bearer token (10+ chars)
    r"|token=[^\s&,;\"']{10,255}"  # token=...
    r"|key=[^\s&,;\"']{10,255}"  # key=...
    r"|password=[^\s&,;\"']{1,255}"  # password=...
    r"|secret=[^\s&,;\"']{1,255}"  # secret=...
    r"|api_key=[^\s&,;\"']{10,255}"  # api_key=...
    r")",
    re.IGNORECASE,
)

_REPLACEMENT = "[REDACTED]"


def scrub_credentials(text: str) -> str:
    """Remove credential patterns from text.

    Safe to call on any string — returns unchanged text if no matches.
    """
    return _CREDENTIAL_PATTERN.sub(_REPLACEMENT, text)
