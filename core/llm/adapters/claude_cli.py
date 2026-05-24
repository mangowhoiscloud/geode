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
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from plugins.petri_audit.claude_cli_provider import StreamJsonEvent, TransientSignal

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
            classify_transient_signal,
            parse_stream_json_events,
        )

        from core.orchestration.claude_cli_lane import acquire_claude_cli_lane_async

        binary = _resolve_claude_binary()
        # PR-V (2026-05-24) — paperclip `--resume <sessionId>` parity.
        # ``req.resume_session_id`` is non-empty when the caller has a
        # prior session from this sub-agent's previous turn (or a
        # cross-cycle continuity slot like
        # ``<run_dir>/sub_agents/<task_id>/session.json``); claude-cli
        # then reuses the cached system prompt + conversation context,
        # dropping input billing to the cached-marker tier.
        argv = build_claude_cli_argv(
            binary=binary,
            model_name=req.model,
            # GEODE policy: no turn-cap, run on time-cap. claude-cli's
            # ``--max-turns`` flag still requires a positive integer, so
            # set it high enough that the 30-minute time-cap on
            # ``_run_claude_subprocess`` (matched to the
            # ``SubAgentManager.timeout_s=1800.0`` ceiling) always
            # trips first. 100 turns × claude-cli's typical 5-10s per
            # turn ≫ 1800s — the option becomes a safety ceiling, not
            # the operational limit. The previous ``max_turns=1`` was
            # an inspect_ai contract leak (that path owns its own
            # iteration loop); AgenticLoop's adapter call does the
            # opposite, letting claude-cli run its internal tool-loop
            # until it produces a terminal ``stop_reason``.
            max_turns=100,
            resume_session_id=req.resume_session_id or None,
        )
        stdin_text = build_subprocess_stdin(req)
        lane_key = f"claude-cli:{req.model}"
        try:
            async with acquire_claude_cli_lane_async(lane_key):
                # GEODE policy: 30-minute time-cap. Matches the
                # ``SubAgentManager.timeout_s=1800.0`` ceiling so the
                # subprocess and the parent-process wall-clock gates
                # trip together rather than producing a 1200s window
                # where the parent gives up before the subprocess does.
                stdout, stderr, rc = await _run_claude_subprocess(
                    argv, stdin_text, timeout_s=1800.0
                )
        except ClaudeCliInvocationError as exc:
            self._last_error = exc
            raise

        # ``stream_events`` is the parsed stream-json sequence — used for
        # both the transient classifier walk and (on the happy path) the
        # assistant-text + stop_reason extractors. Renamed from the
        # naive ``events`` to make the lifecycle (parse once, consume
        # in two branches) obvious to the next reader.
        stream_events = parse_stream_json_events(stdout)
        # ``transient_signal`` is non-None when ``stdout``/``stderr``/
        # any parsed event carried an upstream rate-limit / overload /
        # quota / retry-failure signature (see classifier docstring).
        # ``None`` = healthy call, continue to text extraction below.
        transient_signal = classify_transient_signal(
            stdout=stdout, stderr=stderr, events=stream_events
        )
        if transient_signal is not None:
            # ``postmortem_path`` is the on-disk JSON dump under
            # ``~/.geode/diagnostics/claude-cli-transient/`` carrying
            # the full ``(stdout, stderr, parsed events, classifier
            # signal, rc)`` — the four diagnostic dimensions the
            # pre-PR-T ``stderr_tail`` log line discarded. ``None``
            # when the dump write itself failed (disk full / permission
            # denied) — diagnostic is best-effort, never blocks the
            # raise below.
            postmortem_path = _dump_transient_postmortem(
                model=req.model,
                rc=rc,
                stdout=stdout,
                stderr=stderr,
                events=stream_events,
                signal=transient_signal,
            )
            transient_exc = ClaudeCliTransientUpstreamError(
                f"claude-cli upstream transient (rc={rc}, model={req.model}, "
                f"source={transient_signal.source}"
                + (
                    f"/{transient_signal.event_type}"
                    + (f".{transient_signal.event_field}" if transient_signal.event_field else "")
                    if transient_signal.event_type
                    else ""
                )
                + f", matched={transient_signal.matched_text!r}"
                + (f", dump={postmortem_path}" if postmortem_path else "")
                + ")",
                signal=transient_signal,
                dump_path=str(postmortem_path) if postmortem_path else None,
            )
            self._last_error = transient_exc
            raise transient_exc

        if rc != 0:
            err_excerpt = stderr.strip().splitlines()[-1] if stderr.strip() else "<no stderr>"
            raise RuntimeError(f"claude-cli subprocess exited rc={rc}: {err_excerpt}")

        # No events but rc==0 means claude-cli emitted nothing — treat
        # as a hard failure so the caller doesn't process empty text
        # as a legitimate assistant reply.
        if not stream_events:
            raise ClaudeCliInvocationError(
                f"claude-cli rc=0 but emitted no stream-json events. "
                f"stderr={stderr.strip()[:200]!r}"
            )

        assistant_text = _extract_assistant_text(stream_events)
        stop_reason = _extract_stop_reason(stream_events)
        # ``_extract_stop_reason`` returns ``"unknown"`` when no
        # ``message_delta`` / ``result`` stop event was seen; coerce
        # to the adapter-canonical ``"end_turn"`` so the translator's
        # ``("tool_use" | "tool_calls")`` branch isn't tripped.
        if stop_reason == "unknown":
            stop_reason = "end_turn"
        # PR-V (2026-05-24) — paperclip ``parse.ts:30`` parity.
        # Capture the session_id claude-cli emitted in its
        # ``system.init`` event so the caller can persist it for the
        # next turn's ``resume_session_id`` (cross-call cache hit).
        from plugins.petri_audit.claude_cli_provider import (
            extract_session_id_from_events,
        )

        emitted_session_id = extract_session_id_from_events(stream_events)
        return AdapterCallResult(
            text=assistant_text,
            usage=UsageSummary(),  # subscription path does not expose token usage
            stop_reason=stop_reason,
            session_id=emitted_session_id,
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


def _dump_transient_postmortem(
    *,
    model: str,
    rc: int,
    stdout: str,
    stderr: str,
    events: list[StreamJsonEvent],
    signal: TransientSignal,
) -> Path | None:
    """Persist a full post-mortem for every claude-cli transient hit so
    operators can recover the upstream error message the classifier
    matched on (which is otherwise discarded). Returns the dump path on
    success, ``None`` on any I/O error (best-effort — diagnostic, not
    correctness-critical).

    Pre-PR-T the adapter discarded stdout / parsed events after the
    classifier hit, surfacing only ``stderr_tail`` in the log line —
    but claude-cli writes its errors to stdout, not stderr, so the
    tail was invariably ``<empty>``. The dump records everything the
    classifier saw so operators can identify the actual upstream
    signature (5-hour quota vs RPM cap vs backend 5xx vs OAuth slot
    cap) without re-running the cycle.
    """
    import json
    import time

    from core.paths import GLOBAL_DIAGNOSTICS_DIR

    try:
        # ``postmortem_dir`` is the parent of every transient dump.
        # Co-located under ``~/.geode/diagnostics/`` with the existing
        # smoke/oauth diagnostic outputs (see ``core.paths.GLOBAL_DIAGNOSTICS_DIR``)
        # so the operator's "diagnostics tar-up" command catches it
        # without a separate registration.
        postmortem_dir = GLOBAL_DIAGNOSTICS_DIR / "claude-cli-transient"
        postmortem_dir.mkdir(parents=True, exist_ok=True)
        # ``hit_ts`` = wall-clock seconds of the transient hit. Used as
        # the filename prefix so directory listing sorts chronologically
        # (newest last), and as the ``ts`` field in the payload so a
        # consumer reading multiple dumps can reconstruct the cycle's
        # transient timeline without filesystem mtime ambiguity.
        hit_ts = int(time.time())
        # ``postmortem_path`` = absolute path the JSON will land at.
        # Filename pattern ``<ts>-<model>.json`` lets ``ls -t`` show
        # newest first and groups by model when sorted alphabetically.
        postmortem_path = postmortem_dir / f"{hit_ts}-{model}.json"
        # ``payload`` is the JSON body. Carries the four diagnostic
        # dimensions the pre-PR-T ``stderr_tail`` log line discarded:
        # (1) signal — which regex / which source fired
        # (2) stdout — raw stream-json bytes claude-cli emitted
        # (3) stderr — empty in practice but kept for completeness
        # (4) events — parsed StreamJsonEvent sequence for structured
        #     post-mortem analysis (which result.error / result.message
        #     carried the upstream message). ``rc`` + ``model`` round
        #     out the run identity.
        payload = {
            "ts": hit_ts,
            "model": model,
            "rc": rc,
            "signal": {
                "matched_text": signal.matched_text,
                "source": signal.source,
                "event_type": signal.event_type,
                "event_field": signal.event_field,
            },
            "stdout": stdout,
            "stderr": stderr,
            "events": [{"type": e.type, "payload": e.payload} for e in events],
        }
        postmortem_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return postmortem_path
    except Exception:
        log.debug("claude-cli transient post-mortem dump failed", exc_info=True)
        return None


__all__ = ["ClaudeCliAdapter"]
