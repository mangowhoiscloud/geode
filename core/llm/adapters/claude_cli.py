"""ClaudeCliAdapter — local ``claude`` binary subprocess path.

Layer 3 adapter for Anthropic provider, source=adapter. Spawns the local
``claude`` CLI binary (the same one operators use interactively) and pipes the
prompt through stdin. The binary uses its own OAuth subscription quota — no
GEODE-side API key, no ProfileRotator involvement.

This is the "Adapter" choice in the user-facing PAYG / Subscription / Adapter
trichotomy. Maps to paperclip's ``adapter-claude-local`` package.

The actual subprocess implementation is reused from
:mod:`plugins.petri_audit.claude_cli_provider` (``_run_claude_subprocess`` +
``build_claude_cli_argv``) — that module is the canonical Anthropic-subprocess
runner; the adapter is the public Layer 4-shaped surface around it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from core.llm.adapters._subprocess_common import build_subprocess_stdin
from core.llm.adapters.base import (
    SOURCE_ADAPTER,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    CredentialDetection,
    EnvironmentReport,
    ModelSpec,
    QuotaWindows,
    StreamEvent,
    UsageSummary,
)

log = logging.getLogger(__name__)


@dataclass
class ClaudeCliAdapter:
    """Local ``claude`` CLI subprocess adapter."""

    name: str = "claude-cli"
    provider: str = "anthropic"
    source: str = SOURCE_ADAPTER
    billing_type: AdapterBillingType = AdapterBillingType.SUBSCRIPTION_INCLUDED
    _last_error: Exception | None = field(default=None, init=False, repr=False)

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        """Single-turn ``claude --print`` invocation.

        Behaviour mirrors :func:`plugins.petri_audit.claude_cli_provider._generate_text_only`
        — the canonical Claude OAuth-subprocess path. LaneQueue
        (``core.orchestration.claude_cli_lane``) gates concurrency so multiple
        adapter callers don't burst-overload the local binary.

        The stdout is parsed via ``parse_stream_json_events`` and the
        assistant text extracted before being returned. Pre-classifier
        this method passed raw stream-json stdout as ``AdapterCallResult.text``
        so when claude-cli surfaced ``! Unexpected error. Auto-retrying.``
        as its only output the caller's AgenticLoop treated that error
        text as the LLM's reply, terminated with no tool calls, and
        the parent recorded a ghost candidate. The transient-upstream
        classifier closes that path by raising
        :class:`ClaudeCliTransientUpstreamError` instead.
        """
        from plugins.petri_audit.claude_cli_provider import (
            ClaudeCliInvocationError,
            ClaudeCliTransientUpstreamError,
            _extract_assistant_text,
            _extract_stop_reason,
            _resolve_claude_binary,
            _run_claude_subprocess,
            build_claude_cli_argv,
            is_claude_transient_upstream_error,
            parse_stream_json_events,
        )

        from core.orchestration.claude_cli_lane import acquire_claude_cli_lane_async

        binary = _resolve_claude_binary()
        argv = build_claude_cli_argv(binary=binary, model_name=req.model, max_turns=1)
        stdin_text = build_subprocess_stdin(req)
        lane_key = f"claude-cli:{req.model}"
        try:
            async with acquire_claude_cli_lane_async(lane_key):
                stdout, stderr, rc = await _run_claude_subprocess(argv, stdin_text, timeout_s=600.0)
        except ClaudeCliInvocationError as exc:
            self._last_error = exc
            raise

        events = parse_stream_json_events(stdout)
        if is_claude_transient_upstream_error(stdout=stdout, stderr=stderr, events=events):
            stderr_tail = stderr.strip().splitlines()[-1] if stderr.strip() else "<empty>"
            transient_exc = ClaudeCliTransientUpstreamError(
                f"claude-cli upstream transient error (rc={rc}, model={req.model}). "
                f"stderr_tail={stderr_tail!r}"
            )
            self._last_error = transient_exc
            raise transient_exc

        if rc != 0:
            err_excerpt = stderr.strip().splitlines()[-1] if stderr.strip() else "<no stderr>"
            raise RuntimeError(f"claude-cli subprocess exited rc={rc}: {err_excerpt}")

        # No events but rc==0 means claude-cli emitted nothing — treat
        # as a hard failure so the caller doesn't process empty text
        # as a legitimate assistant reply.
        if not events:
            raise ClaudeCliInvocationError(
                f"claude-cli rc=0 but emitted no stream-json events. "
                f"stderr={stderr.strip()[:200]!r}"
            )

        text = _extract_assistant_text(events)
        stop_reason = _extract_stop_reason(events)
        # ``_extract_stop_reason`` returns ``"unknown"`` when no
        # ``message_delta`` / ``result`` stop event was seen; coerce
        # to the adapter-canonical ``"end_turn"`` so the translator's
        # ``("tool_use" | "tool_calls")`` branch isn't tripped.
        if stop_reason == "unknown":
            stop_reason = "end_turn"
        return AdapterCallResult(
            text=text,
            usage=UsageSummary(),  # subscription path does not expose token usage
            stop_reason=stop_reason,
        )

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        """Yield a single chunk — ``claude --print`` is synchronous-only.

        The subscription-subprocess path doesn't natively stream tokens — the
        CLI buffers and emits at the end. The adapter yields a single
        ``text`` event followed by ``stop`` so callers using the streaming
        surface still get a valid event sequence.
        """
        result = await self.acomplete(req)
        if result.text:
            yield StreamEvent(kind="text", payload={"text": result.text})
        yield StreamEvent(
            kind="stop",
            payload={"stop_reason": result.stop_reason},
        )

    def test_environment(self) -> EnvironmentReport:
        from plugins.petri_audit.adapters.claude_cli_backend import is_available

        try:
            from plugins.petri_audit.claude_cli_provider import _resolve_claude_binary

            binary = _resolve_claude_binary()
        except Exception as exc:
            return EnvironmentReport(
                ok=False,
                checks=(("claude_binary", "missing"),),
                hints=(
                    f"Could not locate the ``claude`` binary: {exc}",
                    "Install the Claude CLI from https://claude.ai/code.",
                ),
            )
        if not is_available():
            return EnvironmentReport(
                ok=False,
                checks=(
                    ("claude_binary", binary),
                    ("oauth_token", "missing"),
                ),
                hints=(
                    "Claude binary found but OAuth token not resolvable.",
                    "Run ``claude /login`` to authenticate.",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(
                ("claude_binary", binary),
                ("oauth_token", "present"),
            ),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import ANTHROPIC_FALLBACK_CHAIN, ANTHROPIC_PRIMARY

        ids = [ANTHROPIC_PRIMARY, *ANTHROPIC_FALLBACK_CHAIN]
        seen: set[str] = set()
        out: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            out.append(
                ModelSpec(
                    id=mid,
                    label=f"{mid} (via claude-cli)",
                    context_tokens=200_000,
                    supports_thinking=True,
                    supports_tools=False,  # subprocess text-only path
                )
            )
        return out

    def get_quota_windows(self) -> QuotaWindows | None:
        """Read OAuth quota via the petri_audit helper.

        Returns ``None`` when the helper isn't available or quota probe fails —
        the UI then renders "unknown" instead of "zero".
        """
        try:
            from plugins.petri_audit.adapters.claude_cli_backend import metadata

            md = metadata()
        except Exception:
            return None
        if not isinstance(md, dict):
            return None
        used = md.get("used_tokens")
        total = md.get("total_tokens")
        if not isinstance(used, int) or not isinstance(total, int) or total <= 0:
            return None
        window = md.get("window_seconds")
        return QuotaWindows(
            used_tokens=used,
            total_tokens=total,
            window_seconds=int(window) if isinstance(window, int) else 0,
        )

    def detect_credential(self) -> CredentialDetection | None:
        from plugins.petri_audit.adapters.claude_cli_backend import is_available

        if not is_available():
            return None
        from core.config import ANTHROPIC_PRIMARY

        return CredentialDetection(
            model=ANTHROPIC_PRIMARY,
            provider=self.provider,
            source_path="~/.claude/oauth-token.json (via claude binary)",
        )


__all__ = ["ClaudeCliAdapter"]
