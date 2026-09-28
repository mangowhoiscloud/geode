"""Secret redaction — strip API keys from text before LLM context injection.

Applies regex-based pattern matching to detect and replace known
API key formats (Anthropic, OpenAI, ZhipuAI, generic bearer tokens).
Used by BashTool.to_tool_result() and MCP tool result post-processing.
"""

from __future__ import annotations

import re
from typing import Any

TYPESAFE_API_KEY_PATTERN = re.compile(r"\bapikey_[A-Za-z0-9_-]{20,}\b")

# API key patterns ordered from most specific to most general.
# More specific patterns (sk-ant-, sk-proj-) are checked first to avoid
# partial matches from the generic sk- pattern.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[a-zA-Z0-9\-_]{20,}"),  # Anthropic
    re.compile(r"sk-proj-[a-zA-Z0-9\-_]{20,}"),  # OpenAI project keys
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),  # OpenAI / OpenRouter
    TYPESAFE_API_KEY_PATTERN,
    re.compile(r"[a-f0-9]{32}\.[a-zA-Z0-9]{16,}"),  # ZhipuAI (hex.token)
    re.compile(r"ghp_[a-zA-Z0-9_]+"),  # GitHub PAT, including truncated values
    re.compile(r"gho_[a-zA-Z0-9_]+"),  # GitHub OAuth
    re.compile(
        r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"
    ),  # OAuth/JWT bearer token
    re.compile(r"xoxb-[a-zA-Z0-9_/\-]+"),  # Slack bot token
    re.compile(r"xoxp-[a-zA-Z0-9\-]+"),  # Slack user token
    re.compile(r"xapp-[a-zA-Z0-9_/\-]+"),  # Slack app-level token
    re.compile(r"\bBearer\s+[^\s\"',;\]}]{10,}", re.IGNORECASE),
]

# Opaque credentials need their field/header context; vendor prefixes alone
# cannot cover a custom endpoint's API key or an OAuth refresh token.
_AUTHORIZATION_PATTERN = re.compile(
    r"(\bauthorization[\"']?\s*[:=]\s*[\"']?(?:Bearer|Basic)\s+)"
    r"(?:\[REDACTED\]|[^\s\"',;\]}]+)",
    re.IGNORECASE,
)
_CREDENTIAL_FIELD_PATTERN = re.compile(
    r"(\b(?:[a-z0-9_]*api[_-]?key|access_token|refresh_token|id_token|client_secret|password|token|key|secret)"
    r"[\"']?\s*[:=]\s*)"
    r"(\[REDACTED\]|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s&,;\]}\"']+)",
    re.IGNORECASE,
)


def redact_secrets(text: str, *, placeholder: str = "[REDACTED]") -> str:
    """Replace known key formats and explicitly labelled credentials.

    Unlabelled opaque values cannot be identified by this text scrubber.
    """
    text = _AUTHORIZATION_PATTERN.sub(lambda match: match[1] + placeholder, text)

    def mask_field(match: re.Match[str]) -> str:
        value = match[2]
        quote = value[0] if value[0] in "\"'" else ""
        return match[1] + quote + placeholder + quote

    text = _CREDENTIAL_FIELD_PATTERN.sub(mask_field, text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


def redact_and_bound_text(value: Any, max_chars: int) -> str:
    """Redact one value, then append an explicit truncation marker if needed."""
    text = redact_secrets(str(value or ""))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"…[truncated:{len(text) - max_chars}]"


def payload_changed(before: Any, after: Any) -> bool:
    """Compare capture inputs conservatively, including opaque ``Any`` values.

    Sanitizers own conversion errors. Only an equality failure is treated as
    unknown reduction; it must not turn an omitted opaque value into full capture.
    """
    try:
        return bool(after != before)
    except Exception:
        return True
