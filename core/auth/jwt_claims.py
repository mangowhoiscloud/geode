"""Unverified JWT payload decode — shared OAuth-claim reader.

Four sites (``oauth_login``, ``codex_cli_oauth``, ``llm.providers.codex``,
``petri_audit.codex_provider``) carried byte-identical "split on ``.`` → pad
base64url → ``json.loads`` → swallow decode errors" blocks, each then pulling a
different claim out of the payload (PR-DEDUP-2). One decoder now; callers keep
their thin field extraction on top.

No signature verification — the OAuth provider owns the signature; GEODE only
needs the public claims (``chatgpt_plan_type`` / ``chatgpt_account_id`` /
``exp`` / ``email``) for routing + display.
"""

from __future__ import annotations

import base64
import json
from typing import Any


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Return the decoded payload dict of a JWT, or ``{}`` on any malformed input.

    Tolerates a non-JWT / empty / truncated token (returns ``{}``) so callers can
    treat "no claims" uniformly. Never raises.
    """
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
