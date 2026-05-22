"""Codex CLI OAuth usage polling — Phase 3 Codex parity.

Sibling of :mod:`core.llm.oauth_usage` for ``codex exec`` subprocess
spawn paths. Same shape (token reader, fetch, TTL poller, decision
helper) so callers can swap providers via the lane wiring without
re-deriving the polling pattern.

Endpoint status
===============

paperclip's port covers Anthropic (``GET /api/oauth/usage``); the
ChatGPT-Plus / Codex-CLI OAuth bucket does **not** currently
advertise an equivalent public endpoint. The token surface
(``$CODEX_HOME/auth.json``'s ``tokens.access_token``, mirroring
codex CLI's keychain output) is real and stable, but the quota
metadata URL is not — operators who want quota-aware admission must
inject a verified fetch function via
:class:`CodexUsagePoller(fetch_fn=…)`.

Until that endpoint lands or an operator wires their own, the
default :func:`fetch_codex_usage` returns ``None`` so the lane falls
open (same fail-open contract as the Anthropic poller — see
:data:`CODEX_OAUTH_POLL_REQUIRED_ENV` for strict mode). The
acquire-site wiring is in place, which means a future PR that
discovers / verifies the endpoint only needs to flip the constants +
the fetch body, not re-thread the call graph.

Module surface
==============

Mirrors :mod:`core.llm.oauth_usage` field-for-field:

* :class:`CodexUsageWindow` / :class:`CodexUsage` (with
  :meth:`is_throttled`).
* :func:`read_codex_oauth_token` — locate
  ``$CODEX_HOME/auth.json``'s ``tokens.access_token`` (Codex CLI's
  standard location, mirrors paperclip's ``readClaudeToken`` pattern).
* :func:`fetch_codex_usage` — placeholder returning ``None`` until
  the endpoint is verified; signature pinned so swap-in is local.
* :class:`CodexUsagePoller` — TTL-cached wrapper, dependency-injected
  fetch + token resolvers so a future verified endpoint plugs in
  without touching the lane.
* :func:`should_block_codex_lane_acquisition` — decision helper for
  the Codex lane's acquire site.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from core.llm.oauth_usage import _truthy

log = logging.getLogger(__name__)

__all__ = [
    "CODEX_OAUTH_POLL_DISABLED_ENV",
    "CODEX_OAUTH_POLL_REQUIRED_ENV",
    "DEFAULT_CODEX_BLOCK_THRESHOLD",
    "DEFAULT_CODEX_TTL_S",
    "CodexUsage",
    "CodexUsagePoller",
    "CodexUsageWindow",
    "fetch_codex_usage",
    "read_codex_oauth_token",
    "should_block_codex_lane_acquisition",
]


DEFAULT_CODEX_TTL_S: Final[float] = 30.0
"""TTL parity with the Anthropic poller — 30 s cache window per
acquire so concurrent fan-out doesn't multiply the metadata-endpoint
load."""

DEFAULT_CODEX_BLOCK_THRESHOLD: Final[float] = 0.8
"""5-hour bucket threshold mirror — same value as Anthropic; revisit
once Codex side measurements land."""

CODEX_OAUTH_POLL_DISABLED_ENV: Final[str] = "GEODE_CODEX_OAUTH_POLL_DISABLED"
"""Operator escape hatch — set to truthy to skip Codex polling. Until
the endpoint is verified this knob is effectively dormant (the
default fetch returns ``None`` regardless), but it exists so future
wiring is one-line."""

CODEX_OAUTH_POLL_REQUIRED_ENV: Final[str] = "GEODE_CODEX_OAUTH_POLL_REQUIRED"
"""Strict-mode flip — fail closed on polling errors. Symmetric with
:data:`core.llm.oauth_usage.OAUTH_POLL_REQUIRED_ENV`."""


def _codex_home_dir() -> Path:
    """Return ``$CODEX_HOME`` or ``~/.codex`` (codex CLI standard).

    Mirrors :func:`core.llm.oauth_usage._claude_config_dir` shape but
    for the Codex tree.
    """
    env = os.environ.get("CODEX_HOME", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".codex"


def read_codex_oauth_token() -> str | None:
    """Locate the operator's Codex CLI OAuth access token on disk.

    Codex CLI writes ``$CODEX_HOME/auth.json`` with structure
    ``{"tokens": {"access_token": "..."}}`` (verified against
    operator install 2026-05-22). Returns the token string when the
    file parses and the field is non-empty; ``None`` otherwise.

    We deliberately walk ONLY the on-disk path (no shell-out to
    ``codex auth status`` or platform-specific keychain helpers) so
    the module stays usable on every CI runner + Linux operator,
    same as the Anthropic-side helper.
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
    if not isinstance(parsed, dict):
        return None
    tokens = parsed.get("tokens")
    if not isinstance(tokens, dict):
        return None
    token = tokens.get("access_token")
    if isinstance(token, str) and token:
        return token
    return None


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
    """Top-level Codex usage wrapper.

    ``five_hour`` is the only window the lane consults for admission;
    ``extra`` carries the rest of the payload as raw dict so future
    dashboard work can inspect tier-specific fields without a schema
    bump here.
    """

    five_hour: CodexUsageWindow | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def is_throttled(self, threshold: float = DEFAULT_CODEX_BLOCK_THRESHOLD) -> bool:
        """Throttled when ``five_hour.utilization >= threshold``.

        Mirrors :meth:`OAuthUsage.is_throttled` so the two providers
        agree on the precedence rule (only 5-hour bucket gates
        admission; weekly windows are too long to wait out in-band).
        """
        if self.five_hour is None or self.five_hour.utilization is None:
            return False
        return self.five_hour.utilization >= threshold


def fetch_codex_usage(token: str, *, timeout_s: float = 8.0) -> CodexUsage | None:
    """Codex usage probe — current default returns ``None``.

    The ChatGPT-Plus / Codex-CLI OAuth bucket does not expose an
    equivalent of Anthropic's ``GET /api/oauth/usage`` at the time
    of writing (2026-05-22). Rather than guess at the URL or scrape
    a TUI like paperclip's ``captureClaudeCliUsageText``, this module
    ships the no-op default + a clearly-documented injection seam:

    * :class:`CodexUsagePoller(fetch_fn=...)` — operators / a future
      PR can pin a real implementation without touching the lane
      wiring.
    * :data:`CODEX_OAUTH_POLL_DISABLED_ENV` /
      :data:`CODEX_OAUTH_POLL_REQUIRED_ENV` — environment knobs are
      already wired so flipping the default is a one-line change
      once the endpoint contract is known.

    Until the endpoint lands, ``should_block_codex_lane_acquisition``
    will always fall open (i.e. proceed with the acquire) unless
    strict mode is on, in which case it always blocks — matching the
    Anthropic-side contract exactly.

    The ``token`` and ``timeout_s`` parameters are accepted (and
    ignored) so the signature is locked in — a future implementation
    can drop into place without breaking call sites that already
    pass a token through the lane.
    """
    _ = token, timeout_s  # placeholder — see docstring
    log.debug(
        "codex_oauth_usage: fetch_codex_usage is a placeholder — "
        "no public Codex /api/oauth/usage endpoint verified yet"
    )
    return None


class CodexUsagePoller:
    """TTL-cached Codex usage poller — sibling of
    :class:`core.llm.oauth_usage.OAuthUsagePoller`.

    Behaviour matches the Anthropic poller exactly so a generic
    "block on either provider" helper can be written later without
    branching on provider type. Operators inject ``fetch_fn`` to
    plug in a verified Codex endpoint.
    """

    def __init__(
        self,
        *,
        ttl_s: float = DEFAULT_CODEX_TTL_S,
        fetch_fn: object | None = None,
        token_fn: object | None = None,
    ) -> None:
        self._ttl_s = ttl_s
        self._fetch_fn = fetch_fn or fetch_codex_usage
        self._token_fn = token_fn or read_codex_oauth_token
        self._lock = threading.Lock()
        self._cached: CodexUsage | None = None
        self._cached_at: float = 0.0

    def current(self, *, force: bool = False) -> CodexUsage | None:
        """Return cached usage, refreshing past TTL. Returns stale
        value on refresh failure (parity with Anthropic poller)."""
        now = time.time()
        with self._lock:
            if not force and self._cached is not None and now - self._cached_at < self._ttl_s:
                return self._cached

        token = self._token_fn()  # type: ignore[operator]
        if not token:
            return self._cached
        fresh = self._fetch_fn(token)  # type: ignore[operator]
        if fresh is None:
            return self._cached

        with self._lock:
            self._cached = fresh
            self._cached_at = now
            return self._cached

    def invalidate(self) -> None:
        """Drop the cache slot — tests use this to force re-fetch."""
        with self._lock:
            self._cached = None
            self._cached_at = 0.0


_DEFAULT_CODEX_POLLER: CodexUsagePoller | None = None
_DEFAULT_CODEX_POLLER_LOCK = threading.Lock()


def _default_codex_poller() -> CodexUsagePoller:
    """Module-level singleton — same lazy-init pattern as
    :func:`core.llm.oauth_usage._default_poller`."""
    global _DEFAULT_CODEX_POLLER
    if _DEFAULT_CODEX_POLLER is None:
        with _DEFAULT_CODEX_POLLER_LOCK:
            if _DEFAULT_CODEX_POLLER is None:
                _DEFAULT_CODEX_POLLER = CodexUsagePoller()
    return _DEFAULT_CODEX_POLLER


def _reset_default_codex_poller_for_tests() -> None:
    """Drop the singleton — tests use this to flip env knobs + re-init."""
    global _DEFAULT_CODEX_POLLER
    with _DEFAULT_CODEX_POLLER_LOCK:
        _DEFAULT_CODEX_POLLER = None


def should_block_codex_lane_acquisition(
    *,
    threshold: float = DEFAULT_CODEX_BLOCK_THRESHOLD,
    poller: CodexUsagePoller | None = None,
) -> bool:
    """Decide whether to block a ``codex exec`` lane acquire.

    Strictly parallel to
    :func:`core.llm.oauth_usage.should_block_lane_acquisition`:

    * ``False`` when polling is disabled, no token is available, the
      poller fails, OR the 5-hour utilisation is below threshold.
    * ``True`` when ``five_hour.utilization >= threshold`` AND the
      poller returned fresh data.
    * Strict mode (:data:`CODEX_OAUTH_POLL_REQUIRED_ENV` truthy)
      flips "poll failed" to True so silent endpoint outages surface.

    Since :func:`fetch_codex_usage` is currently a placeholder that
    always returns ``None``, this helper currently always returns
    ``False`` (fail-open default) unless strict mode is on. The
    wiring stays in place so the future verified-endpoint PR is a
    single-file change.
    """
    if _truthy(os.environ.get(CODEX_OAUTH_POLL_DISABLED_ENV)):
        return False

    poller = poller if poller is not None else _default_codex_poller()
    usage = poller.current()
    if usage is None:
        return _truthy(os.environ.get(CODEX_OAUTH_POLL_REQUIRED_ENV))
    return usage.is_throttled(threshold)
