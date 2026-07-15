"""Slack transport — direct Web API client (no MCP subprocess).

Replaces the ``@modelcontextprotocol/server-slack`` MCP dependency
(PR-SLACK-TRANSPORT, 2026-07-15). The MCP path lost a startup race on
every daemon boot — ``StdioMCPClient.connect`` waits at most 10s while a
warm-cache ``npx`` spawn measures 10.1s — so the health gate silently
disabled ALL Slack inbound and outbound. A direct httpx client removes
the subprocess, the deprecated npm package, and the race entirely.

Scope: bot-token Web API calls only (``auth.test``, ``chat.postMessage``,
``conversations.history``, ``reactions.add``). Socket Mode (push inbound)
requires an app-level ``xapp-`` token the deployment does not have yet;
inbound stays polling-based (``SlackPoller``) until the operator
provisions one — documented follow-up, not a silent assumption.

Token resolution order: explicit constructor arg, then ``SLACK_BOT_TOKEN``
from ``os.environ``, then the global ``~/.geode/.env`` (the daemon may not
have promoted dotenv into its environment at import time). The resolved
token never appears in logs or errors.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)

_API_BASE = "https://slack.com/api"
# Slack rejects >40,000-char message text; chunk under it (hermes-aligned).
MAX_MESSAGE_CHARS = 39_000
_MAX_RATE_LIMIT_RETRIES = 3
# auth.test result cache — availability probes must not hit the API on
# every send.
_AUTH_CACHE_TTL_S = 300.0


def resolve_bot_token(explicit: str | None = None) -> str:
    """Resolve the bot token without logging it. Empty string when absent."""
    if explicit:
        return explicit
    env_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if env_token:
        return env_token
    try:
        from dotenv import dotenv_values

        from core.paths import GLOBAL_ENV_FILE

        if GLOBAL_ENV_FILE.exists():
            return dotenv_values(str(GLOBAL_ENV_FILE)).get("SLACK_BOT_TOKEN") or ""
    except Exception:
        log.debug("Global .env token fallback failed", exc_info=True)
    return ""


class SlackTransportError(Exception):
    """A Slack Web API call failed (``error`` field or HTTP failure)."""


class SlackTransport:
    """Minimal async Slack Web API client for GEODE's gateway surfaces.

    One instance per process is enough; methods are stateless besides the
    cached ``auth.test`` verdict. All methods raise
    :class:`SlackTransportError` on API-level errors so callers decide
    their own degradation (the notification adapter maps to
    ``NotificationResult``; the poller logs and retries next cycle).
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = resolve_bot_token(token)
        self._auth_ok: bool | None = None
        self._auth_checked_at = 0.0

    @property
    def configured(self) -> bool:
        """Token present (no network)."""
        return bool(self._token)

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST one Web API method with 429 retry; return the parsed body."""
        if not self._token:
            raise SlackTransportError("SLACK_BOT_TOKEN not configured")
        import httpx

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
                resp = await client.post(f"{_API_BASE}/{method}", json=payload, headers=headers)
                if resp.status_code == 429 and attempt < _MAX_RATE_LIMIT_RETRIES:
                    delay = float(resp.headers.get("Retry-After", "1"))
                    log.info("Slack 429 on %s — retrying in %.0fs", method, delay)
                    await asyncio.sleep(min(delay, 30.0))
                    continue
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                if not data.get("ok", False):
                    raise SlackTransportError(f"{method}: {data.get('error', 'unknown')}")
                return data
        raise SlackTransportError(f"{method}: rate-limited after retries")

    async def auth_test(self) -> dict[str, Any]:
        """``auth.test`` — identity probe (also refreshes the availability cache)."""
        try:
            data = await self._call("auth.test", {})
            self._auth_ok = True
        except Exception:
            self._auth_ok = False
            raise
        finally:
            self._auth_checked_at = time.monotonic()
        return data

    async def ais_available(self) -> bool:
        """Cached availability: token present AND auth.test passed recently."""
        if not self.configured:
            return False
        if (
            self._auth_ok is not None
            and time.monotonic() - self._auth_checked_at < _AUTH_CACHE_TTL_S
        ):
            return self._auth_ok
        try:
            await self.auth_test()
        except Exception:
            log.warning("Slack auth.test failed — transport unavailable")
        return bool(self._auth_ok)

    async def post_message(
        self,
        channel_id: str,
        text: str,
        *,
        thread_ts: str = "",
        mrkdwn: bool = True,
    ) -> dict[str, Any]:
        """``chat.postMessage`` with mrkdwn conversion + over-length chunking.

        Standard markdown converts to Slack mrkdwn here (single owner —
        callers pass plain markdown). Returns the API response of the
        FIRST chunk (its ``ts`` anchors threads); follow-up chunks post
        into the same thread.
        """
        if mrkdwn:
            from core.messaging.slack_formatter import markdown_to_slack_mrkdwn

            text = markdown_to_slack_mrkdwn(text)
        chunks = self._chunk(text)
        first: dict[str, Any] | None = None
        anchor_ts = thread_ts
        for i, chunk in enumerate(chunks):
            body = f"({i + 1}/{len(chunks)})\n{chunk}" if len(chunks) > 1 else chunk
            payload: dict[str, Any] = {
                "channel": channel_id,
                "text": body,
                "mrkdwn": mrkdwn,
            }
            if anchor_ts:
                payload["thread_ts"] = anchor_ts
            data = await self._call("chat.postMessage", payload)
            if first is None:
                first = data
                # Follow-up chunks thread under the first if not already
                # threading somewhere.
                anchor_ts = anchor_ts or str(data.get("ts", ""))
        assert first is not None  # chunks is never empty
        return first

    async def channel_history(
        self,
        channel_id: str,
        *,
        oldest: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """``conversations.history`` — newest-first message dicts."""
        payload: dict[str, Any] = {"channel": channel_id, "limit": limit}
        if oldest:
            payload["oldest"] = oldest
        data = await self._call("conversations.history", payload)
        messages = data.get("messages", [])
        return messages if isinstance(messages, list) else []

    async def add_reaction(self, channel_id: str, message_ts: str, emoji: str) -> None:
        """``reactions.add`` — best-effort feedback marker.

        ``already_reacted`` is success for our purposes; other errors raise.
        """
        try:
            await self._call(
                "reactions.add",
                {"channel": channel_id, "timestamp": message_ts, "name": emoji},
            )
        except SlackTransportError as exc:
            if "already_reacted" not in str(exc):
                raise

    @staticmethod
    def _chunk(text: str) -> list[str]:
        """Split at MAX_MESSAGE_CHARS, preferring newline boundaries."""
        if len(text) <= MAX_MESSAGE_CHARS:
            return [text]
        chunks: list[str] = []
        rest = text
        while rest:
            if len(rest) <= MAX_MESSAGE_CHARS:
                chunks.append(rest)
                break
            cut = rest.rfind("\n", 0, MAX_MESSAGE_CHARS)
            if cut <= 0:
                cut = MAX_MESSAGE_CHARS
            chunks.append(rest[:cut])
            rest = rest[cut:].lstrip("\n")
        return chunks


# Process-wide default instance (lazy) — pollers and adapters share the
# auth cache instead of re-probing per surface.
_default_transport: SlackTransport | None = None


def get_slack_transport() -> SlackTransport:
    """Return the process-default transport (created on first use)."""
    global _default_transport
    if _default_transport is None:
        _default_transport = SlackTransport()
    return _default_transport


def reset_slack_transport() -> None:
    """Drop the default instance (tests / credential rotation)."""
    global _default_transport
    _default_transport = None
