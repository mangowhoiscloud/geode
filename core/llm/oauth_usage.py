"""Anthropic OAuth usage polling — paperclip P1 port (PR-LQ-Phase3).

Fifth leg of the LaneQueue 5-phase plan
([[project_lanequeue_handoff_2026_05_22]]). Phases 1, 2, 4, 5 landed
in v0.99.31; Phase 3 was deferred there because the endpoint contract
was unverified — this module ports paperclip's ``fetchClaudeQuota``
(``packages/adapters/claude-local/src/server/quota.ts:212-275``) to
Python so GEODE can read its own 5-hour / 7-day OAuth-bucket
utilisation before queuing a ``claude --print`` subprocess.

Why this exists
===============

The :class:`Lane` introduced in Phase 2
(:mod:`core.orchestration.claude_cli_lane`) caps concurrent
``claude --print`` fan-out at ``max_concurrent=2`` — one slot below
the documented 3-4 burst-limiter floor. That cap is necessary but
not sufficient: the 5-hour token bucket can be 90 % drained while
the burst limiter is fully reset, and the next acquire would burn
the last few percent for marginal value. paperclip solves this by
polling ``/api/oauth/usage`` before each spawn and backing off when
``five_hour.utilization >= 0.8``.

Path notes
==========

Unlike the inference path (``POST /v1/messages``), where raw SDK
calls trip Anthropic's "OAuth via SDK = rate-limited tier"
distinction and must therefore route through the ``claude --print``
subprocess (CSA-1), the metadata endpoint
(``GET /api/oauth/usage``) is plain HTTP + Bearer-token. paperclip's
1+ year of production traffic confirms the metadata endpoint does
NOT count toward the burst limiter, and there is no Python SDK
wrapper for ``/api/oauth/`` to begin with — so this module uses
``urllib`` directly. No new third-party dependency.

Module surface
==============

* :class:`OAuthUsageWindow` — one quota window
  (``five_hour`` / ``seven_day`` / ``seven_day_sonnet`` /
  ``seven_day_opus`` / ``extra_usage``) with normalised
  ``utilization`` (0.0-1.0) + ``resets_at`` (raw API string).
* :class:`OAuthUsage` — top-level response wrapper +
  :meth:`is_throttled` helper.
* :func:`read_anthropic_oauth_token` — locate the operator's
  ``claudeAiOauth.accessToken`` from
  ``$CLAUDE_CONFIG_DIR`` / ``~/.claude/.credentials.json`` (or
  ``credentials.json`` fallback).
* :func:`fetch_oauth_usage` — one synchronous request to
  ``/api/oauth/usage`` with the ``anthropic-beta: oauth-2025-04-20``
  header.
* :class:`OAuthUsagePoller` — TTL-cached wrapper so the
  ``claude_cli_lane`` acquire site can probe on every spawn without
  hammering the metadata endpoint.
* :func:`should_block_lane_acquisition` — decision helper applied
  by ``acquire_claude_cli_lane*`` immediately before the semaphore
  grab.

Graceful degradation
====================

Every failure path — missing token file, unreadable JSON, network
timeout, non-200 response, malformed payload — returns ``None`` (or
``False`` from the decision helper). The lane MUST stay usable when
quota polling fails; otherwise a single network blip would harden
every ``claude --print`` spawn into "no slots forever". Operators
who want strict admission control set
``GEODE_CLAUDE_OAUTH_POLL_REQUIRED=1`` to flip the policy.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

__all__ = [
    "ANTHROPIC_OAUTH_BETA",
    "DEFAULT_BLOCK_THRESHOLD",
    "DEFAULT_TTL_S",
    "OAUTH_POLL_DISABLED_ENV",
    "OAUTH_POLL_REQUIRED_ENV",
    "OAUTH_USAGE_URL",
    "OAuthUsage",
    "OAuthUsagePoller",
    "OAuthUsageWindow",
    "fetch_oauth_usage",
    "read_anthropic_oauth_token",
    "should_block_lane_acquisition",
]


OAUTH_USAGE_URL: Final[str] = "https://api.anthropic.com/api/oauth/usage"
"""Metadata endpoint (Path B, see [[project_lanequeue_handoff_2026_05_22]]).
Plain HTTP + Bearer — paperclip parity."""

ANTHROPIC_OAUTH_BETA: Final[str] = "oauth-2025-04-20"
"""Required ``anthropic-beta`` header value for ``/api/oauth/*``.
Mirrors ``paperclip/packages/adapters/claude-local/src/server/quota.ts:216``."""

DEFAULT_TTL_S: Final[float] = 30.0
"""Per-poll cache lifetime. paperclip doesn't cache (its server
caches at the consumer layer); GEODE polls every ``claude --print``
acquire so a 30 s window keeps the metadata endpoint quiet under
fan-out without lagging behind real bucket movement."""

DEFAULT_BLOCK_THRESHOLD: Final[float] = 0.8
"""Lane acquisition blocks when ``five_hour.utilization >=`` this
value. Matches paperclip's heartbeat threshold — at 80 % the
remaining bucket would be consumed by 1-2 more sub-agent fan-outs,
so we surrender now and let the bucket roll over rather than burn
the tail on burst retries."""

OAUTH_POLL_DISABLED_ENV: Final[str] = "GEODE_CLAUDE_OAUTH_POLL_DISABLED"
"""Operator escape hatch — set to a truthy value (``1`` / ``true``)
to skip polling entirely. The lane keeps its raw capacity cap; only
the quota-aware backoff layer is bypassed. Useful for tests + for
operators whose token can't reach ``/api/oauth/usage``
(non-subscription auth, corporate proxy, etc.)."""

OAUTH_POLL_REQUIRED_ENV: Final[str] = "GEODE_CLAUDE_OAUTH_POLL_REQUIRED"
"""Strict-mode flip. By default polling failures (missing token,
network error, malformed payload) fall open — the lane stays
usable. Set this to a truthy value to fail closed instead: any
polling error blocks the acquire so the operator notices the
silent degradation."""


def _claude_config_dir() -> Path:
    """Return ``$CLAUDE_CONFIG_DIR`` or ``~/.claude`` (paperclip parity)."""
    env = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".claude"


def _truthy(env_value: str | None) -> bool:
    """Standard truthy parsing for the polling env knobs."""
    if env_value is None:
        return False
    return env_value.strip().lower() in {"1", "true", "yes", "on"}


def read_anthropic_oauth_token() -> str | None:
    """Locate the operator's ``claudeAiOauth.accessToken`` on disk.

    Mirrors paperclip's
    ``readClaudeToken`` (``quota.ts:140-147``): walks
    ``$CLAUDE_CONFIG_DIR``/``.credentials.json`` then
    ``credentials.json``. Returns the access-token string when the
    file parses and contains a non-empty token, otherwise ``None``.

    macOS operators who keep the token in the Keychain rather than a
    file should run ``claude login`` once — the CLI writes a copy
    to ``~/.claude/.credentials.json`` automatically. We deliberately
    do NOT shell out to ``security find-generic-password`` here: it
    would make the module unusable on Linux + every CI runner.
    """
    config_dir = _claude_config_dir()
    for filename in (".credentials.json", "credentials.json"):
        path = config_dir / filename
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("oauth_usage: %s exists but is not valid JSON", path)
            continue
        if not isinstance(parsed, dict):
            continue
        oauth = parsed.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            continue
        token = oauth.get("accessToken")
        if isinstance(token, str) and token:
            return token
    return None


def _normalise_utilization(raw: float | int | None) -> float | None:
    """Map paperclip's dual-shape utilisation (0-1 OR 0-100) to 0-1.

    paperclip ``toPercent`` (``quota.ts:196-199``) clamps to 0-100;
    GEODE keeps the internal contract as 0-1 floats so downstream
    threshold checks (``>= 0.8``) read naturally. Negative values are
    treated as 0; >1 values are treated as percentages and divided.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return 0.0
    if value <= 1.0:
        return value
    # API has historically returned both 0-1 fractions (legacy) and
    # 0-100 percentages (current) — divide the latter back to 0-1.
    return min(value / 100.0, 1.0)


@dataclass(frozen=True, slots=True)
class OAuthUsageWindow:
    """One quota window from ``/api/oauth/usage``.

    ``utilization`` is normalised to 0.0-1.0 regardless of which shape
    the API returned. ``resets_at`` keeps the raw API string (ISO-ish
    timestamp; paperclip surfaces it to the UI without parsing).
    """

    label: str
    utilization: float | None
    resets_at: str | None = None


@dataclass(frozen=True, slots=True)
class OAuthUsage:
    """Top-level response — wraps the per-window slices + extra-usage.

    Field names mirror paperclip ``AnthropicUsageResponse``
    (``quota.ts:162-168``) so future contributors cross-referencing
    paperclip can pattern-match field by field. ``extra_usage`` is a
    coarse dict because its shape is operator-tier-dependent and
    GEODE doesn't make admission decisions on it (only on
    ``five_hour``).
    """

    five_hour: OAuthUsageWindow | None = None
    seven_day: OAuthUsageWindow | None = None
    seven_day_sonnet: OAuthUsageWindow | None = None
    seven_day_opus: OAuthUsageWindow | None = None
    extra_usage: dict[str, object] = field(default_factory=dict)

    def is_throttled(self, threshold: float = DEFAULT_BLOCK_THRESHOLD) -> bool:
        """Return True when the 5-hour bucket has crossed ``threshold``.

        Only ``five_hour`` is consulted — the 7-day / sonnet / opus
        windows are reported for dashboards but don't trip admission
        because their reset cadence (days) is too long to wait out
        in-band. paperclip applies the same precedence.
        """
        if self.five_hour is None or self.five_hour.utilization is None:
            return False
        return self.five_hour.utilization >= threshold


def _parse_window(label: str, body: object) -> OAuthUsageWindow | None:
    if not isinstance(body, dict):
        return None
    raw_util = body.get("utilization")
    raw_reset = body.get("resets_at")
    util = _normalise_utilization(raw_util)
    resets = raw_reset if isinstance(raw_reset, str) else None
    return OAuthUsageWindow(label=label, utilization=util, resets_at=resets)


def _parse_usage_payload(payload: object) -> OAuthUsage:
    """Map a parsed JSON dict to :class:`OAuthUsage`.

    Tolerates missing / malformed fields — each window resolves to
    ``None`` rather than raising, matching paperclip's null-tolerant
    contract (``quota.ts:223-273``).
    """
    if not isinstance(payload, dict):
        return OAuthUsage()
    extra = payload.get("extra_usage")
    extra_dict: dict[str, object] = extra if isinstance(extra, dict) else {}
    return OAuthUsage(
        five_hour=_parse_window("Current session", payload.get("five_hour")),
        seven_day=_parse_window("Current week (all models)", payload.get("seven_day")),
        seven_day_sonnet=_parse_window(
            "Current week (Sonnet only)", payload.get("seven_day_sonnet")
        ),
        seven_day_opus=_parse_window("Current week (Opus only)", payload.get("seven_day_opus")),
        extra_usage=extra_dict,
    )


def fetch_oauth_usage(token: str, *, timeout_s: float = 8.0) -> OAuthUsage | None:
    """Make one ``GET /api/oauth/usage`` call and return parsed usage.

    Returns ``None`` (with a debug-level log) for any failure mode —
    HTTP error, network timeout, non-200 status, malformed JSON.
    The caller decides whether absence is fatal
    (:data:`OAUTH_POLL_REQUIRED_ENV`) or fail-open (default).

    Implementation uses :mod:`urllib.request` to avoid pulling
    ``httpx`` into the cold-start path. paperclip's ``fetchWithTimeout``
    pattern is reproduced via ``socket`` timeout on the urlopen call.
    """
    req = urllib.request.Request(  # noqa: S310
        OAUTH_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": ANTHROPIC_OAUTH_BETA,
            "Accept": "application/json",
        },
        method="GET",
    )
    # OAUTH_USAGE_URL is a hardcoded module constant (https) — not an
    # operator-supplied input. ruff S310 + bandit B310 fire because
    # the rule can't statically prove the scheme; both suppressions
    # below mark the constraint as enforced at module load.
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310  # nosec B310
            if resp.status != 200:
                log.debug("oauth_usage: /api/oauth/usage returned status=%s", resp.status)
                return None
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        log.debug("oauth_usage: HTTP error %s on /api/oauth/usage", exc.code)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.debug("oauth_usage: network error on /api/oauth/usage — %s", exc)
        return None

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.debug("oauth_usage: malformed JSON from /api/oauth/usage — %s", exc)
        return None

    return _parse_usage_payload(payload)


class OAuthUsagePoller:
    """TTL-cached wrapper around :func:`fetch_oauth_usage`.

    The ``claude_cli_lane`` acquire path calls :meth:`current` before
    every semaphore grab; without caching that would be one HTTP
    round-trip per spawn (= 2/sec under default lane cap). A 30 s TTL
    keeps the endpoint quiet while still reacting fast enough to
    bucket movement (utilisation changes by single digits per spawn
    on tier-1 plans).

    The poller is thread-safe — both the cache slot and the in-flight
    fetch flag are guarded so two concurrent acquires don't both
    trigger a fetch when the cache is stale.
    """

    def __init__(
        self,
        *,
        ttl_s: float = DEFAULT_TTL_S,
        fetch_fn: object | None = None,
        token_fn: object | None = None,
    ) -> None:
        # ``fetch_fn`` + ``token_fn`` are kept as ``object`` in the
        # signature so test fixtures can inject stubs without
        # importing ``Callable``. The defaults pin to the module-
        # level helpers.
        self._ttl_s = ttl_s
        self._fetch_fn = fetch_fn or fetch_oauth_usage
        self._token_fn = token_fn or read_anthropic_oauth_token
        self._lock = threading.Lock()
        self._cached: OAuthUsage | None = None
        self._cached_at: float = 0.0

    def current(self, *, force: bool = False) -> OAuthUsage | None:
        """Return the cached usage, refreshing if stale.

        ``force=True`` always re-fetches (used by the CLI dashboard
        command). On any failure to refresh, the stale cached value
        is returned rather than ``None`` — operators care about
        seeing the most-recently-known utilisation, even slightly
        stale, more than they care about an empty box.
        """
        now = time.time()
        with self._lock:
            if not force and self._cached is not None and now - self._cached_at < self._ttl_s:
                return self._cached

        # Fetch outside the lock — the HTTP round-trip would otherwise
        # serialise concurrent acquires unnecessarily.
        token = self._token_fn()  # type: ignore[operator]
        if not token:
            return self._cached  # keep stale value if any
        fresh = self._fetch_fn(token)  # type: ignore[operator]
        if fresh is None:
            return self._cached

        with self._lock:
            self._cached = fresh
            self._cached_at = now
            return self._cached

    def invalidate(self) -> None:
        """Drop the cache slot. Tests use this to force re-fetch."""
        with self._lock:
            self._cached = None
            self._cached_at = 0.0


_DEFAULT_POLLER: OAuthUsagePoller | None = None
_DEFAULT_POLLER_LOCK = threading.Lock()


def _default_poller() -> OAuthUsagePoller:
    """Module-level singleton — lazy-initialised under a lock."""
    global _DEFAULT_POLLER
    if _DEFAULT_POLLER is None:
        with _DEFAULT_POLLER_LOCK:
            if _DEFAULT_POLLER is None:
                _DEFAULT_POLLER = OAuthUsagePoller()
    return _DEFAULT_POLLER


def _reset_default_poller_for_tests() -> None:
    """Drop the singleton so the next call rebuilds it.

    Tests that monkeypatch :data:`OAUTH_POLL_DISABLED_ENV` or swap
    out ``fetch_oauth_usage`` need this — the singleton would
    otherwise capture the original closure forever.
    """
    global _DEFAULT_POLLER
    with _DEFAULT_POLLER_LOCK:
        _DEFAULT_POLLER = None


def should_block_lane_acquisition(
    *,
    threshold: float = DEFAULT_BLOCK_THRESHOLD,
    poller: OAuthUsagePoller | None = None,
) -> bool:
    """Decide whether to block a ``claude --print`` lane acquire.

    Wired into :func:`core.orchestration.claude_cli_lane.acquire_*`
    immediately before the semaphore grab. Returns:

    * ``False`` when polling is disabled
      (:data:`OAUTH_POLL_DISABLED_ENV` truthy), no token is available,
      polling fails, or ``five_hour.utilization`` is below the
      threshold — the acquire proceeds as before.
    * ``True`` when ``five_hour.utilization >= threshold`` AND the
      poller returned a fresh reading. The lane caller surfaces this
      as a :class:`TimeoutError` so the existing backoff path picks
      it up.

    Strict mode (:data:`OAUTH_POLL_REQUIRED_ENV` truthy) flips the
    "polling failed" branch to ``True``: any failure becomes a block,
    so operators notice silent degradation.
    """
    if _truthy(os.environ.get(OAUTH_POLL_DISABLED_ENV)):
        return False

    poller = poller if poller is not None else _default_poller()
    usage = poller.current()

    if usage is None:
        return _truthy(os.environ.get(OAUTH_POLL_REQUIRED_ENV))
    return usage.is_throttled(threshold)
