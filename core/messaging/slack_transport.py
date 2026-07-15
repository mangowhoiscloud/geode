"""Slack transport — direct Web API client (no MCP subprocess).

Replaces the ``@modelcontextprotocol/server-slack`` MCP dependency
(PR-SLACK-TRANSPORT, 2026-07-15). The MCP path lost a startup race on
every daemon boot — ``StdioMCPClient.connect`` waits at most 10s while a
warm-cache ``npx`` spawn measures 10.1s — so the health gate silently
disabled ALL Slack inbound and outbound. A direct httpx client removes
the subprocess, the deprecated npm package, and the race entirely.

Scope: bot-token Web API calls only (``auth.test``, ``chat.postMessage``,
``conversations.history``, ``conversations.info``, ``reactions.add``).
Push inbound lives in :mod:`core.messaging.slack_socket_mode`; the legacy
history poll remains an explicit compatibility fallback when no app-level
``xapp-`` token is configured.

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
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_API_BASE = "https://slack.com/api"
_SOCKET_OPEN_URL = f"{_API_BASE}/apps.connections.open"
# Slack rejects >40,000-char message text; chunk under it (hermes-aligned).
MAX_MESSAGE_CHARS = 39_000
_MAX_RATE_LIMIT_RETRIES = 3
# auth.test result cache — availability probes must not hit the API on
# every send.
_AUTH_CACHE_TTL_S = 300.0
# Failed verdicts expire quickly — a Slack outage must not disable the
# poller for the full positive-cache window.
_AUTH_FAIL_CACHE_TTL_S = 30.0


def _resolve_slack_token(name: str, explicit: str | None = None) -> str:
    """Resolve one Slack token without logging it. Empty string when absent."""
    if explicit:
        return explicit
    env_token = os.environ.get(name, "")
    if env_token:
        return env_token
    try:
        from dotenv import dotenv_values

        from core.paths import GLOBAL_ENV_FILE

        if GLOBAL_ENV_FILE.exists():
            return dotenv_values(str(GLOBAL_ENV_FILE)).get(name) or ""
    except Exception:
        log.debug("Global .env Slack token fallback failed for %s", name, exc_info=True)
    return ""


def resolve_bot_token(explicit: str | None = None) -> str:
    """Resolve the ``xoxb-`` bot token without logging it."""
    return _resolve_slack_token("SLACK_BOT_TOKEN", explicit)


def resolve_app_token(explicit: str | None = None) -> str:
    """Resolve the ``xapp-`` Socket Mode token without logging it."""
    return _resolve_slack_token("SLACK_APP_TOKEN", explicit)


class SlackTransportError(Exception):
    """A Slack Web API call failed (``error`` field or HTTP failure)."""


async def open_socket_mode_url(app_token: str | None = None) -> str:
    """Issue a validated temporary Socket Mode URL with an app-level token.

    The returned URL contains a short-lived ticket. This function never logs
    or persists it; the Socket Mode client consumes it immediately.
    """
    token = resolve_app_token(app_token)
    if not token:
        raise SlackTransportError("SLACK_APP_TOKEN not configured")

    import httpx

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            response = await client.post(_SOCKET_OPEN_URL, json={}, headers=headers)
            if response.status_code == 429 and attempt < _MAX_RATE_LIMIT_RETRIES:
                delay = max(float(response.headers.get("Retry-After", "1")), 0.0)
                log.info("Slack Socket Mode URL rate-limited — retrying in %.0fs", delay)
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            if not data.get("ok", False):
                raise SlackTransportError(f"apps.connections.open: {data.get('error', 'unknown')}")
            url = str(data.get("url", ""))
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            if parsed.scheme != "wss" or not (
                hostname == "slack.com" or hostname.endswith(".slack.com")
            ):
                raise SlackTransportError("apps.connections.open returned an invalid WebSocket URL")
            return url

    raise SlackTransportError("apps.connections.open: rate-limited after retries")


class SlackTransport:
    """Minimal async Slack Web API client for GEODE's gateway surfaces.

    One instance per process is enough; methods are stateless besides the
    cached ``auth.test`` verdict. All methods raise
    :class:`SlackTransportError` on API-level errors so callers decide
    their own degradation (the notification adapter maps to
    ``NotificationResult``; inbound receivers log their own degradation).
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = resolve_bot_token(token)
        self._auth_ok: bool | None = None
        self._auth_checked_at = 0.0

    @property
    def configured(self) -> bool:
        """Token present (no network)."""
        return bool(self._token)

    async def _call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        form_encoded: bool = False,
    ) -> dict[str, Any]:
        """POST one Web API method with 429 retry; return the parsed body.

        Slack accepts JSON for the mutation/history methods GEODE uses, but
        ``conversations.info`` still requires form encoding in some
        workspaces (a JSON request returns ``missing required field:
        channel``). Keep that wire-format exception explicit at the call site.
        """
        if not self._token:
            raise SlackTransportError("SLACK_BOT_TOKEN not configured")
        import httpx

        headers = {"Authorization": f"Bearer {self._token}"}
        if not form_encoded:
            headers["Content-Type"] = "application/json; charset=utf-8"
        # Per-call client, deliberately: the singleton transport is shared
        # across event loops (main-thread adapter vs poller-thread Runner),
        # and httpx.AsyncClient is loop-affine. Connection reuse would need
        # per-loop clients — revisit only if poll volume makes TLS setup
        # measurable.
        async with httpx.AsyncClient(timeout=15.0) as client:
            for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
                if form_encoded:
                    resp = await client.post(f"{_API_BASE}/{method}", data=payload, headers=headers)
                else:
                    resp = await client.post(f"{_API_BASE}/{method}", json=payload, headers=headers)
                if resp.status_code == 429 and attempt < _MAX_RATE_LIMIT_RETRIES:
                    delay = float(resp.headers.get("Retry-After", "1"))
                    log.info("Slack 429 on %s — retrying in %.0fs", method, delay)
                    # Slack's Retry-After value is the contract. Capping it
                    # below the requested delay simply causes another 429.
                    await asyncio.sleep(max(delay, 0.0))
                    continue
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                if not data.get("ok", False):
                    raise SlackTransportError(f"{method}: {data.get('error', 'unknown')}")
                return data
        raise SlackTransportError(f"{method}: rate-limited after retries")

    async def auth_test(self) -> dict[str, Any]:
        """``auth.test`` — identity probe (also refreshes the availability cache).

        Only an API-level rejection (``SlackTransportError``, e.g.
        ``invalid_auth``) caches a negative verdict; transient transport
        failures (DNS, timeout, 5xx) leave the verdict UNKNOWN so the next
        cycle retries instead of parking the poller for the cache window.
        """
        try:
            data = await self._call("auth.test", {})
            self._auth_ok = True
        except SlackTransportError:
            self._auth_ok = False
            raise
        except Exception:
            self._auth_ok = None
            raise
        finally:
            self._auth_checked_at = time.monotonic()
        return data

    def _cached_verdict(self) -> bool | None:
        """Return the cached availability verdict if still fresh."""
        if self._auth_ok is None:
            return None
        ttl = _AUTH_CACHE_TTL_S if self._auth_ok else _AUTH_FAIL_CACHE_TTL_S
        if time.monotonic() - self._auth_checked_at < ttl:
            return self._auth_ok
        return None

    async def ais_available(self) -> bool:
        """Cached availability: token present AND auth.test passed recently."""
        if not self.configured:
            return False
        cached = self._cached_verdict()
        if cached is not None:
            return cached
        try:
            await self.auth_test()
        except Exception:
            log.warning("Slack auth.test failed — transport unavailable this cycle")
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

    async def channel_info(self, channel_id: str) -> dict[str, Any]:
        """``conversations.info`` — metadata used by binding diagnostics."""
        data = await self._call("conversations.info", {"channel": channel_id}, form_encoded=True)
        channel = data.get("channel", {})
        return channel if isinstance(channel, dict) else {}

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
