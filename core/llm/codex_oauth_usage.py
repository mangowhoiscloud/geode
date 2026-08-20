"""ChatGPT subscription usage lookup via the WHAM HTTP endpoint.

The credential reader and fetcher provide quota evidence without owning
inference admission policy:

* Endpoint — ``GET https://chatgpt.com/backend-api/wham/usage``
* Auth — ``Authorization: Bearer <tokens.access_token>`` plus optional
  ``ChatGPT-Account-Id: <tokens.account_id>`` (multi-account
  subscribers).
* Schema —
  ``{plan_type, rate_limit:{primary_window, secondary_window},
  credits:{balance, unlimited}}`` with ``used_percent`` either in
  ``0-100`` (current) or ``0-1`` (legacy) shape.

paperclip operates two paths: ``fetchCodexRpcQuota`` (preferred,
spawns ``codex … app-server`` JSON-RPC) and ``fetchCodexQuota`` (HTTP
fallback). Option A ports ONLY the HTTP fallback so GEODE stays
stdlib-only and matches the Anthropic-side stateless pattern; the
RPC path is left for a later PR if its richer plan / refresh-aware
data turns out to be worth the subprocess + protocol cost.

Token surface
=============

paperclip's ``readCodexAuthInfo`` recognises two on-disk schemas:

* **Modern** — ``$CODEX_HOME/auth.json``::

      {"tokens": {"access_token": "...",
                  "account_id": "...",
                  "id_token": "...",
                  "refresh_token": "..."}}

* **Legacy** — top-level ``{"accessToken": "...", "accountId": "..."}``.

Both are accepted by :func:`read_codex_oauth_credentials`; the
returned :class:`CodexAuthCredentials` carries the ``account_id``
alongside the token so the WHAM call can attach the
``ChatGPT-Account-Id`` header when present.

JWT decoding (paperclip uses it to surface plan / email in the
dashboard) is out of scope here — admission control only needs
``rate_limit.primary_window.used_percent``.

Graceful degradation
====================

Every failure path returns ``None``. Usage telemetry must not block inference.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from core.llm.oauth_usage import _normalise_utilization

log = logging.getLogger(__name__)

__all__ = [
    "CODEX_WHAM_USAGE_URL",
    "CodexAuthCredentials",
    "CodexUsage",
    "CodexUsageWindow",
    "fetch_codex_usage",
    "read_codex_oauth_credentials",
    "read_codex_oauth_token",
]


CODEX_WHAM_USAGE_URL: Final[str] = "https://chatgpt.com/backend-api/wham/usage"
"""ChatGPT WHAM usage endpoint — paperclip
``packages/adapters/codex-local/src/server/quota.ts:235``.

Plain HTTP + Bearer (Path B in the LaneQueue handoff terminology).
Independent of the inference SDK path — does not count toward Codex
CLI's burst limiter per paperclip's empirical observation."""


@dataclass(frozen=True, slots=True)
class CodexAuthCredentials:
    """The two fields the WHAM call needs.

    paperclip threads ``token + account_id`` together
    (``readCodexToken`` returns ``{token, accountId}``); the
    ``account_id`` is optional — single-account subscribers don't
    have it on disk and the WHAM endpoint accepts the call without
    the ``ChatGPT-Account-Id`` header.
    """

    token: str
    account_id: str | None = None


def _codex_home_dir() -> Path:
    """Return ``$CODEX_HOME`` or ``~/.codex`` (codex CLI standard).

    Mirrors :func:`core.llm.oauth_usage._claude_config_dir` shape but
    for the Codex tree.
    """
    env = os.environ.get("CODEX_HOME", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".codex"


def _extract_credentials(parsed: object) -> CodexAuthCredentials | None:
    """Pull token + account_id from a parsed auth.json dict.

    Handles both schemas paperclip recognises:

    * Modern — ``{"tokens": {"access_token": ..., "account_id": ...}}``
    * Legacy — ``{"accessToken": ..., "accountId": ...}`` (top-level)

    Returns ``None`` when neither layout yields a non-empty token.
    The ``account_id`` field is allowed to be missing — the WHAM call
    just omits the ``ChatGPT-Account-Id`` header in that case.
    """
    if not isinstance(parsed, dict):
        return None

    # Modern layout first — codex CLI ≥ "tokens" block.
    tokens = parsed.get("tokens")
    if isinstance(tokens, dict):
        token = tokens.get("access_token")
        if isinstance(token, str) and token:
            raw_account = tokens.get("account_id")
            account_id = raw_account if isinstance(raw_account, str) and raw_account else None
            return CodexAuthCredentials(token=token, account_id=account_id)

    # Legacy top-level layout.
    token = parsed.get("accessToken")
    if isinstance(token, str) and token:
        raw_account = parsed.get("accountId")
        account_id = raw_account if isinstance(raw_account, str) and raw_account else None
        return CodexAuthCredentials(token=token, account_id=account_id)

    return None


def read_codex_oauth_credentials() -> CodexAuthCredentials | None:
    """Locate the operator's Codex CLI OAuth access token + account id.

    Walks ``$CODEX_HOME/auth.json`` and accepts both the modern
    (``tokens.access_token``) and legacy (top-level ``accessToken``)
    layouts paperclip's ``readCodexAuthInfo`` handles. Returns
    ``None`` for missing file, unreadable JSON, or empty token; the
    caller (poller / decision helper) interprets that as
    "polling unavailable, fall open".

    We deliberately walk ONLY the on-disk path (no shell-out to
    ``codex auth status`` or platform-specific keychain helpers) so
    the module stays usable on every CI runner + Linux operator.
    """
    path = _codex_home_dir() / "auth.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("codex_oauth_usage: %s exists but is not valid JSON", path)
        return None
    return _extract_credentials(parsed)


def read_codex_oauth_token() -> str | None:
    """Compatibility shim — returns only the access token string.

    Kept for callers that don't need the ``account_id``; new code
    should prefer :func:`read_codex_oauth_credentials` so the WHAM
    header can be attached.
    """
    creds = read_codex_oauth_credentials()
    return creds.token if creds is not None else None


@dataclass(frozen=True, slots=True)
class CodexUsageWindow:
    """One Codex quota window. Shape parity with
    :class:`core.llm.oauth_usage.OAuthUsageWindow` so a generic
    dashboard can render either provider without branching."""

    label: str
    utilization: float | None
    resets_at: str | None = None


@dataclass(frozen=True, slots=True)
class CodexUsage:
    """Top-level Codex usage wrapper — paperclip ``WhamUsageResponse``
    in Python form.

    Window naming choice — paperclip's WHAM payload uses
    ``primary_window`` / ``secondary_window`` while the Anthropic
    schema names them ``five_hour`` / ``seven_day``. We keep the
    semantic names (``five_hour``, ``weekly``) because:

    1. ``five_hour`` reads identically to the Anthropic-side field —
       cross-provider admission code stays uniform.
    2. Operator-facing logs / dashboards prefer the meaning
       ("5 hours") over the API codename ("primary").
    3. Phase 4's classifier already looks for ``5-hour`` in the
       throttle TimeoutError text; using the same field name makes
       that hand-off naturally readable.

    ``credits`` and ``plan_type`` ship as raw fields so dashboard
    work can surface them without a schema bump here.
    """

    five_hour: CodexUsageWindow | None = None
    weekly: CodexUsageWindow | None = None
    credits: dict[str, object] = field(default_factory=dict)
    plan_type: str | None = None


def _normalise_reset_at(raw: object) -> str | None:
    """Normalise WHAM's ``reset_at`` to an ISO-8601 string.

    paperclip ``fetchCodexQuota`` (``quota.ts:247-249``) handles
    ``number`` (unix seconds) OR ``string`` (already-ISO). Convert
    numbers to UTC ISO so downstream code (CLI dashboard, Phase 4
    quota-class router) can parse a single shape. Anything else
    returns ``None``.
    """
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=UTC).isoformat()
        except (OverflowError, ValueError, OSError):  # pragma: no cover — exotic timestamps
            return None
    if isinstance(raw, str) and raw:
        return raw
    return None


def _parse_window(label: str, body: object) -> CodexUsageWindow | None:
    """Map a WHAM rate-limit window dict to :class:`CodexUsageWindow`."""
    if not isinstance(body, dict):
        return None
    util = _normalise_utilization(body.get("used_percent"))
    resets = _normalise_reset_at(body.get("reset_at"))
    return CodexUsageWindow(label=label, utilization=util, resets_at=resets)


def _parse_wham_payload(payload: object) -> CodexUsage:
    """Build a :class:`CodexUsage` from a parsed WHAM JSON dict.

    Tolerates missing / malformed fields — each window resolves to
    ``None`` rather than raising, matching paperclip's null-tolerant
    contract (``quota.ts:241-273``).
    """
    if not isinstance(payload, dict):
        return CodexUsage()

    plan_type_raw = payload.get("plan_type")
    plan_type = plan_type_raw if isinstance(plan_type_raw, str) and plan_type_raw else None

    rate_limit = payload.get("rate_limit")
    primary: CodexUsageWindow | None = None
    secondary: CodexUsageWindow | None = None
    if isinstance(rate_limit, dict):
        primary = _parse_window("5h limit", rate_limit.get("primary_window"))
        secondary = _parse_window("Weekly limit", rate_limit.get("secondary_window"))

    credits_raw = payload.get("credits")
    credits: dict[str, object] = credits_raw if isinstance(credits_raw, dict) else {}

    return CodexUsage(
        five_hour=primary,
        weekly=secondary,
        credits=credits,
        plan_type=plan_type,
    )


def fetch_codex_usage(
    credentials: CodexAuthCredentials,
    *,
    timeout_s: float = 8.0,
) -> CodexUsage | None:
    """Make one ``GET /backend-api/wham/usage`` call.

    Mirrors paperclip ``fetchCodexQuota`` (``quota.ts:226-279``):

    * ``Authorization: Bearer <token>``
    * ``ChatGPT-Account-Id: <account_id>`` — attached only when the
      auth.json carries an account id (single-account subscribers
      omit this and the endpoint still answers).
    * Non-200, network error, malformed JSON → return ``None``
      (caller decides on fail-open vs strict per env knob).

    Uses :mod:`urllib` (stdlib) so the cold-start path stays free of
    ``httpx`` / ``requests``.
    """
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Accept": "application/json",
    }
    if credentials.account_id:
        headers["ChatGPT-Account-Id"] = credentials.account_id

    req = urllib.request.Request(  # noqa: S310
        CODEX_WHAM_USAGE_URL,
        headers=headers,
        method="GET",
    )
    # CODEX_WHAM_USAGE_URL is a hardcoded https module constant — not
    # an operator-supplied input. ruff S310 + bandit B310 both fire
    # because the rule can't statically prove the scheme; the
    # suppressions mark the constraint as enforced at module load.
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310  # nosec B310
            if resp.status != 200:
                log.debug("codex_oauth_usage: WHAM usage api returned status=%s", resp.status)
                return None
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        log.debug("codex_oauth_usage: HTTP error %s on WHAM usage api", exc.code)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.debug("codex_oauth_usage: network error on WHAM usage api — %s", exc)
        return None

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.debug("codex_oauth_usage: malformed JSON from WHAM usage api — %s", exc)
        return None

    return _parse_wham_payload(payload)
