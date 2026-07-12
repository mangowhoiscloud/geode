"""Window preflight — does this campaign fit the quota window that just opened?

The r23 incident: a full paired run was launched into a window that could not
hold it, died at task 7 of 12 on a 429, and burned ~$5.77 for an INVALID with
zero verdict bits. The decision below compares the campaign's own hard cap
(``limits.max_tokens``) and the measured history of completed campaigns
against the operator-supplied (or probed) remaining budget.

This module is the library home; ``scripts/eval/crucible_window_preflight.py``
is the thin CLI over it, and ``prepare_campaign`` consumes ``decide`` directly
so a prepared config can carry its launch-capacity verdict.

Decision tiers (also the CLI exit codes):

- 0 ``cap_fit``: remaining covers the campaign's hard cap.
- 1 ``history_fit``: remaining covers the historical worst completed campaign
  but not the hard cap.
- 3 ``defer``: remaining does not cover even the historical worst — launching
  reproduces r23.

These are launch-capacity estimates, not provider guarantees; the evaluator
still treats any provider limit as infrastructure contamination.
"""

from __future__ import annotations

import json
from pathlib import Path

from .contract import ContractError

PREFLIGHT_SCHEMA = "crucible.window-preflight.v2"


def campaign_token_cap(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    cap = config.get("limits", {}).get("max_tokens")
    if not isinstance(cap, int) or cap <= 0:
        raise ContractError(f"config {config_path} has no positive limits.max_tokens")
    return cap


def completed_campaign_tokens(history_root: Path) -> list[int]:
    """Token totals of every campaign that reached a summary (finished loop)."""
    totals: list[int] = []
    for summary_path in sorted(history_root.glob("*/state/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tokens = summary.get("usage", {}).get("tokens")
        if isinstance(tokens, (int, float)) and tokens > 0:
            totals.append(int(tokens))
    return totals


def remaining_from_codex(window_capacity_tokens: int) -> tuple[int, str]:
    """Estimate remaining window tokens from a live Codex usage probe.

    The window capacity is an account fact the caller must supply; this
    function refuses to invent it.
    """
    from core.llm.codex_oauth_usage import fetch_codex_usage, read_codex_oauth_credentials

    credentials = read_codex_oauth_credentials()
    if credentials is None:
        raise ContractError("no Codex OAuth credentials available for the usage probe")
    usage = fetch_codex_usage(credentials)
    if usage is None or usage.five_hour is None or usage.five_hour.utilization is None:
        raise ContractError("Codex usage probe returned no five-hour window")
    utilization = usage.five_hour.utilization
    fraction = utilization / 100.0 if utilization > 1.0 else utilization
    remaining = int(window_capacity_tokens * max(0.0, 1.0 - fraction))
    detail = (
        f"five_hour utilization {utilization} (resets_at {usage.five_hour.resets_at}), "
        f"capacity {window_capacity_tokens}"
    )
    return remaining, detail


def decide(
    *,
    hard_cap_tokens: int,
    remaining_tokens: int,
    history_tokens: list[int],
) -> dict[str, object]:
    worst_completed = max(history_tokens) if history_tokens else None
    if remaining_tokens >= hard_cap_tokens:
        fit, exit_code = "cap_fit", 0
    elif worst_completed is not None and remaining_tokens >= worst_completed:
        fit, exit_code = "history_fit", 1
    else:
        fit, exit_code = "defer", 3
    return {
        "schema": PREFLIGHT_SCHEMA,
        "fit": fit,
        "exit_code": exit_code,
        "hard_cap_tokens": hard_cap_tokens,
        "remaining_tokens": remaining_tokens,
        "history_completed_runs": len(history_tokens),
        "history_worst_tokens": worst_completed,
        "history_mean_tokens": (
            int(sum(history_tokens) / len(history_tokens)) if history_tokens else None
        ),
    }
