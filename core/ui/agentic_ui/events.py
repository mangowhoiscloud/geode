"""Structured IPC event emitters — AgenticLoop state changes and pipeline milestones."""

from __future__ import annotations

from typing import Any

from core.ui.agentic_ui._state import _ipc_writer_local


def emit_budget_warning(budget: float, actual: float, pct: float) -> None:
    """Emit proactive budget warning at 80% threshold."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("budget_warning", budget=budget, actual=actual, pct=pct)
        return
    _pkg.console.print(
        f"  [warning]$ Budget warning: ${actual:.2f} / ${budget:.2f} ({pct:.0f}% used)[/warning]"
    )


def emit_reasoning_summary(provider: str, model: str, text: str) -> None:
    """v0.57.0 R6 — surface a model's reasoning-summary chunk to the UI.

    Called from ``AgenticLoop`` after each LLM call returns with one
    or more summaries on ``response.reasoning_summaries`` (sidecar).
    Per-item granularity, not per-delta — emitting from inside the
    streaming worker thread would require thread-local IPC writer
    plumbing for marginal UX gain.

    Long summaries are truncated for the inline render (full text is
    in the IPC event); 3-codebase consensus is "show enough to confirm
    progress, not enough to overwhelm." Hermes uses a TUI activity
    feed; Claude Code uses rainbow-coloured React state with 30 s auto-
    hide; OpenClaw pushes per-event. We keep it simple: one muted
    line per summary chunk, prefixed with a bullet.
    """
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "reasoning_summary",
            provider=provider,
            model=model,
            text=text,
        )
        return
    snippet = text.strip().replace("\n", " ")
    if len(snippet) > 240:
        snippet = snippet[:237] + "…"
    _pkg.console.print(f"  [muted]∙ thinking · {snippet}[/muted]")


def emit_retry_wait(
    model: str,
    attempt: int,
    max_retries: int,
    delay_s: float,
    elapsed_s: float,
    error_type: str,
) -> None:
    """Emit retry_wait event during LLM retry backoff."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "retry_wait",
            model=model,
            attempt=attempt,
            max_retries=max_retries,
            delay_s=delay_s,
            elapsed_s=elapsed_s,
            error_type=error_type,
        )
        return
    _pkg.console.print(
        f"  [warning]~ Retrying in {delay_s:.1f}s... "
        f"[{model} · {attempt}/{max_retries} · {elapsed_s:.0f}s elapsed] "
        f"(Ctrl+C to skip)[/warning]"
    )


def emit_llm_error(
    error_type: str,
    severity: str,
    hint: str,
    model: str,
    provider: str,
    attempt: int = 0,
    elapsed_s: float = 0.0,
) -> None:
    """Emit llm_error event with severity classification and actionable hint."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "llm_error",
            error_type=error_type,
            severity=severity,
            hint=hint,
            model=model,
            provider=provider,
            attempt=attempt,
            elapsed_s=elapsed_s,
        )
        return
    # Severity -> Rich style mapping
    style = {"critical": "error", "error": "error", "warning": "warning"}.get(severity, "dim")
    symbol = {"critical": "!!", "error": "!", "warning": "~"}.get(severity, "·")
    _pkg.console.print(f"  [{style}]{symbol} {hint} [{model} · {elapsed_s:.1f}s][/{style}]")


def emit_model_switch_required(
    model: str,
    error_type: str,
    attempts: int,
    suggested_models: list[str] | None = None,
) -> None:
    """Emit ``model_switch_required`` — the loop needs the user to pick a model.

    v0.90.0 — replaces the prior ``emit_model_escalation`` event. The agent
    no longer auto-swaps models on LLM error; instead it surfaces this
    event so terminal UI / IPC consumers can render a "switch model"
    prompt with the same suggestions the diagnostic carries.
    """
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    suggestions = list(suggested_models or [])
    if writer is not None:
        writer.send_event(
            "model_switch_required",
            model=model,
            error_type=error_type,
            attempts=attempts,
            suggested_models=suggestions,
        )
        return
    suggested_str = f" — try /model {' | '.join(suggestions)}" if suggestions else " — run /model"
    _pkg.console.print(
        f"  [warning]✕ Model switch required: {model} hit {error_type} "
        f"after {attempts} attempts{suggested_str}[/warning]"
    )


def emit_llm_retry(delay_s: int, attempt: int, max_attempts: int) -> None:
    """Emit llm_retry event when retrying after LLM failure with backoff."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "llm_retry",
            delay_s=delay_s,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        return
    _pkg.console.print(
        f"  [warning]~ LLM retry in {delay_s}s (attempt {attempt}/{max_attempts})[/warning]"
    )


def emit_cost_budget_exceeded(budget: float, actual: float) -> None:
    """Emit cost_budget_exceeded event when session cost hits limit."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("cost_budget_exceeded", budget=budget, actual=actual)
        return
    _pkg.console.print(f"  [error]$ Cost budget exceeded: ${actual:.2f} / ${budget:.2f}[/error]")


def emit_time_budget_expired(budget_s: float, elapsed_s: float, rounds: int) -> None:
    """Emit time_budget_expired event when time limit reached."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "time_budget_expired",
            budget_s=budget_s,
            elapsed_s=elapsed_s,
            rounds=rounds,
        )
        return
    _pkg.console.print(
        f"  [warning]⏱ Time budget expired: {elapsed_s:.0f}s / {budget_s:.0f}s"
        f" ({rounds} rounds)[/warning]"
    )


def emit_convergence_detected(error_pattern: str, rounds: int) -> None:
    """Emit convergence_detected event when stuck loop is broken."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("convergence_detected", error=error_pattern, rounds=rounds)
        return
    _pkg.console.print(
        f"  [error]⟳ Convergence detected: repeating failure after {rounds} rounds[/error]"
    )


def emit_goal_decomposition(steps: list[str]) -> None:
    """Emit goal_decomposition event when multi-step plan is created."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("goal_decomposition", steps=steps, count=len(steps))
        return
    _pkg.console.print(f"  [dim]● Goal decomposed into {len(steps)} steps[/dim]")


def emit_tool_backpressure(consecutive_errors: int) -> None:
    """Emit tool_backpressure event when error recovery kicks in."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("tool_backpressure", consecutive_errors=consecutive_errors)
        return
    _pkg.console.print(
        f"  [warning]⏸ Tool backpressure: {consecutive_errors} consecutive errors[/warning]"
    )


def emit_tool_diversity_forced(tool_name: str, count: int) -> None:
    """Emit tool_diversity_forced event when same tool repeated too many times."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("tool_diversity_forced", tool=tool_name, count=count)
        return
    _pkg.console.print(
        f"  [warning]⟳ Diversity forced: {tool_name} called {count}x consecutively[/warning]"
    )


def emit_model_switched(from_model: str, to_model: str, reason: str) -> None:
    """Emit model_switched event for user-initiated model change."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "model_switched",
            from_model=from_model,
            to_model=to_model,
            reason=reason,
        )


def emit_checkpoint_saved(session_id: str, round_idx: int) -> None:
    """Emit checkpoint_saved event after session state is persisted."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("checkpoint_saved", session_id=session_id, round_idx=round_idx)


# ───────────────────────────────────────────────────────────────────────────
# OAuth device-code flow events (v0.51.1 IPC parity)
# ───────────────────────────────────────────────────────────────────────────
#
# Pre-v0.51.1 the OAuth login flow printed directly to daemon stdout, so
# thin-client REPLs never saw the verification URL or user code. The flow
# now emits structured events that ``event_renderer`` translates into
# rich, in-place terminal output for both modes (IPC + direct).


def emit_oauth_login_started(provider: str, verification_uri: str, user_code: str) -> None:
    """Surface the device-code prompt to the user.

    Two render paths share the same Press [Enter] prompt + browser watcher:

      * IPC path — when an IPC writer is bound (event_renderer renders).
      * Direct path — when the OAuth flow runs in the thin CLI itself
        (e.g. ``/login openai`` is a ``RunLocation.THIN`` command),
        no writer is set so we render via console.print here.

    Both paths call :func:`core.ui.oauth_browser.start_oauth_browser_watcher`
    so the user gets identical Enter-to-open-browser UX in either mode.
    """
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "oauth_login_started",
            provider=provider,
            verification_uri=verification_uri,
            user_code=user_code,
        )
        return
    # rich.Padding preserves the left indent when the terminal wraps a long
    # line. Hard-coded ``"  "`` / ``"     "`` prefixes only paint the first
    # wrapped line; wrap continuations jag back to column 0.
    from rich.padding import Padding as _Padding

    _l1 = (0, 0, 0, 2)  # primary indent (numbered step, status line)
    _l2 = (0, 0, 0, 5)  # nested indent (URL/code under a step)

    _pkg.console.print()
    _pkg.console.print(_Padding(f"[header]{provider} OAuth Login[/header]", _l1))
    _pkg.console.print()
    _pkg.console.print(_Padding("1. Open this URL in your browser:", _l1))
    _pkg.console.print(_Padding(f"[link]{verification_uri}[/link]", _l2))
    _pkg.console.print()
    _pkg.console.print(_Padding("2. Enter this code:", _l1))
    _pkg.console.print(_Padding(f"[bold yellow]{user_code}[/bold yellow]", _l2))
    _pkg.console.print()
    if verification_uri:
        _pkg.console.print(
            _Padding("[muted]Press \\[Enter] to open the URL in your browser.[/muted]", _l1)
        )
        from core.ui.oauth_browser import start_oauth_browser_watcher

        start_oauth_browser_watcher(verification_uri)
    _pkg.console.print(_Padding("[muted]Waiting for sign-in... (Ctrl+C to cancel)[/muted]", _l1))
    _pkg.console.print()


def emit_oauth_login_pending(provider: str, elapsed_s: int) -> None:
    """Periodic heartbeat while polling the token endpoint."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "oauth_login_pending",
            provider=provider,
            elapsed_s=elapsed_s,
        )


def emit_oauth_login_success(
    provider: str,
    *,
    account_id: str = "",
    email: str = "",
    plan_type: str = "",
    stored_at: str = "",
) -> None:
    """Surface successful token receipt + storage location."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "oauth_login_success",
            provider=provider,
            account_id=account_id,
            email=email,
            plan_type=plan_type,
            stored_at=stored_at,
        )
        return
    from rich.padding import Padding as _Padding

    _l1 = (0, 0, 0, 2)
    _l2 = (0, 0, 0, 4)
    _pkg.console.print()
    _pkg.console.print(_Padding(f"[success]✓ {provider} login successful[/success]", _l1))
    if email or account_id:
        _pkg.console.print(_Padding(f"[muted]Account:[/muted] {email or account_id}", _l2))
    if plan_type:
        _pkg.console.print(_Padding(f"[muted]Plan:[/muted] {plan_type}", _l2))
    if stored_at:
        _pkg.console.print(_Padding(f"[muted]Stored:[/muted] {stored_at}", _l2))
    _pkg.console.print()


def emit_oauth_login_failed(provider: str, reason: str) -> None:
    """Surface a failed/cancelled login flow."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "oauth_login_failed",
            provider=provider,
            reason=reason,
        )
        return
    from rich.padding import Padding as _Padding

    _pkg.console.print()
    _pkg.console.print(
        _Padding(f"[error]✗ {provider} login failed:[/error] {reason}", (0, 0, 0, 2))
    )
    _pkg.console.print()


# ───────────────────────────────────────────────────────────────────────────
# Billing error event (v0.51.1 IPC parity)
# ───────────────────────────────────────────────────────────────────────────


def emit_billing_error(message: str) -> None:
    """Surface a billing/credit error from the agentic loop.

    Pre-v0.51.1 used a raw ``rich.console.Console`` print that bypassed
    the thin-client renderer.
    """
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("billing_error", message=message)
        return
    _pkg.console.print()
    _pkg.console.print(f"  [error]✗ Billing error[/error] — {message}")
    _pkg.console.print()


def emit_quota_exhausted(
    *,
    provider: str,
    plan_id: str = "",
    plan_display_name: str = "",
    upgrade_url: str = "",
    resets_in_seconds: int = 0,
    message: str = "",
) -> None:
    """v0.53.0 — emit a plan-aware quota-exhausted panel event.

    Distinct from ``emit_billing_error`` (which is a single-line UI):
    this carries the structured Plan context so the thin client renders
    a multi-line actionable panel (header + reset-time + Options 1/2/3).
    Pre-v0.53.0 the user saw ``"All glm models exhausted"`` with no
    next step; this surfaces the user-paid plan + a switch path.
    """
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "quota_exhausted",
            provider=provider,
            plan_id=plan_id,
            plan_display_name=plan_display_name,
            upgrade_url=upgrade_url,
            resets_in_seconds=resets_in_seconds,
            message=message,
        )
        return
    _pkg.console.print()
    label = plan_display_name or provider or "Provider"
    _pkg.console.print(f"  [error]⚠ {label} quota exhausted[/error]")
    if message:
        _pkg.console.print(f"  {message}")
    _pkg.console.print()


# ───────────────────────────────────────────────────────────────────────────
# Structured IPC event emitters — Pipeline milestones
# ───────────────────────────────────────────────────────────────────────────


def emit_pipeline_gather(
    ip_info: dict[str, Any],
    monolake: dict[str, Any],
    signals: dict[str, Any] | None = None,
) -> None:
    """Emit pipeline_gather event with structured IP metadata + signals."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    sig = signals or {}
    writer.send_event(
        "pipeline_gather",
        ip_name=ip_info.get("ip_name", ""),
        media_type=ip_info.get("media_type", ""),
        release_year=ip_info.get("release_year", 0),
        studio=ip_info.get("studio", ""),
        dau=monolake.get("dau_current", 0),
        revenue=monolake.get("revenue_ltm", 0),
        youtube_views=sig.get("youtube_views", 0),
        reddit_subscribers=sig.get("reddit_subscribers", 0),
        fan_art_yoy_pct=sig.get("fan_art_yoy_pct", 0),
    )


def emit_pipeline_analysis(analyses: list[dict[str, Any]]) -> None:
    """Emit pipeline_analysis event with per-analyst scores."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    items = []
    for a in analyses:
        items.append(
            {
                "analyst": getattr(a, "analyst_type", str(a)),
                "score": getattr(a, "score", 0),
                "finding": getattr(a, "key_finding", ""),
            }
        )
    writer.send_event("pipeline_analysis", analysts=items, count=len(items))


def emit_pipeline_evaluation(evaluations: dict[str, Any]) -> None:
    """Emit pipeline_evaluation event with per-evaluator scores."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    items = {}
    for key, ev in evaluations.items():
        items[key] = {
            "score": getattr(ev, "composite_score", 0),
            "rationale": getattr(ev, "rationale", "")[:100],
        }
    writer.send_event("pipeline_evaluation", evaluators=items, count=len(items))


def emit_pipeline_score(
    final_score: float,
    subscores: dict[str, float],
    confidence: float,
    tier: str,
    *,
    psm: Any | None = None,
) -> None:
    """Emit pipeline_score event with PSM results."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    writer.send_event(
        "pipeline_score",
        final_score=final_score,
        subscores=subscores,
        confidence=confidence,
        tier=tier,
        att_pct=getattr(psm, "att_pct", 0) if psm else 0,
        z_value=getattr(psm, "z_value", 0) if psm else 0,
        rosenbaum_gamma=getattr(psm, "rosenbaum_gamma", 0) if psm else 0,
    )


def emit_pipeline_verification(
    guardrails_pass: bool,
    biasbuster_pass: bool,
    *,
    details: list[str] | None = None,
) -> None:
    """Emit pipeline_verification event with optional failure details."""
    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is None:
        return
    writer.send_event(
        "pipeline_verification",
        guardrails_pass=guardrails_pass,
        biasbuster_pass=biasbuster_pass,
        details=details or [],
    )


def emit_feedback_loop(iteration: int, confidence: float, threshold: float) -> None:
    """Emit feedback_loop event when confidence loop re-runs."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event(
            "feedback_loop",
            iteration=iteration,
            confidence=confidence,
            threshold=threshold,
        )
        return
    _pkg.console.print(
        f"  [dim]⟳ Feedback loop iteration {iteration}:"
        f" confidence {confidence:.1f}% < {threshold:.1f}%[/dim]"
    )


def emit_node_skipped(node: str, reason: str) -> None:
    """Emit node_skipped event when pipeline node is dynamically skipped."""
    from core.ui import agentic_ui as _pkg

    writer = getattr(_ipc_writer_local, "writer", None)
    if writer is not None:
        writer.send_event("node_skipped", node=node, reason=reason)
        return
    _pkg.console.print(f"  [dim]⤳ Node skipped: {node} ({reason})[/dim]")
