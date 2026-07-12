"""Launch-gate a Crucible campaign against the current quota window.

The r23 incident: a full paired run was launched into a window that could not
hold it, died at task 7 of 12 on a 429, and burned ~$5.77 for an INVALID with
zero verdict bits. This preflight makes the launcher ask the question the
sleep-until wrapper never asked — *does this run fit the window that just
opened?* — using measured campaign costs, not guesses.

Decision tiers (exit codes; the launcher picks its policy):

- 0 ``cap_fit``: the estimated remaining token budget covers the campaign's
  own hard cap (``limits.max_tokens``).
- 1 ``history_fit``: the estimate covers the historical worst completed
  campaign but not the hard cap.
- 3 ``defer``: remaining does not cover even the historical worst — launching
  reproduces r23.

These are launch-capacity estimates, not provider guarantees. Subscription
quota can use non-token accounting or change independently of the local hard
cap. The preflight therefore reports its source and arithmetic while the
evaluator still treats any provider limit as infrastructure contamination.

Every number is sourced: the cap from the campaign config, history from
completed campaign summaries, remaining from the operator or a live Codex
usage probe (utilization percent × operator-supplied window capacity; the
capacity is an account fact this script refuses to invent).

Usage:
    uv run python scripts/eval/crucible_window_preflight.py CONFIG \\
        --history artifacts/eval/runs/crucible/campaigns \\
        --remaining-tokens 6000000
    uv run python scripts/eval/crucible_window_preflight.py CONFIG \\
        --history artifacts/eval/runs/crucible/campaigns \\
        --auto-codex --window-capacity-tokens 12000000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _campaign_token_cap(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    cap = config.get("limits", {}).get("max_tokens")
    if not isinstance(cap, int) or cap <= 0:
        raise SystemExit(f"config {config_path} has no positive limits.max_tokens")
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


def _remaining_from_codex(window_capacity_tokens: int) -> tuple[int, str]:
    from core.llm.codex_oauth_usage import fetch_codex_usage, read_codex_oauth_credentials

    credentials = read_codex_oauth_credentials()
    if credentials is None:
        raise SystemExit("no Codex OAuth credentials available for --auto-codex")
    usage = fetch_codex_usage(credentials)
    if usage is None or usage.five_hour is None or usage.five_hour.utilization is None:
        raise SystemExit("Codex usage probe returned no five-hour window")
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
        "schema": "crucible.window-preflight.v2",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--history", type=Path, help="campaigns root holding */state/summary.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--remaining-tokens", type=int)
    source.add_argument("--auto-codex", action="store_true")
    parser.add_argument(
        "--window-capacity-tokens",
        type=int,
        help="account window capacity in tokens (required with --auto-codex)",
    )
    args = parser.parse_args(argv)

    if args.auto_codex:
        if not args.window_capacity_tokens or args.window_capacity_tokens <= 0:
            parser.error("--auto-codex requires a positive --window-capacity-tokens")
        remaining, source_detail = _remaining_from_codex(args.window_capacity_tokens)
    else:
        if args.remaining_tokens is None or args.remaining_tokens < 0:
            parser.error("--remaining-tokens must be non-negative")
        remaining, source_detail = args.remaining_tokens, "operator-supplied"

    history = completed_campaign_tokens(args.history) if args.history else []
    verdict = decide(
        hard_cap_tokens=_campaign_token_cap(args.config),
        remaining_tokens=remaining,
        history_tokens=history,
    )
    verdict["remaining_source"] = source_detail
    print(json.dumps(verdict, sort_keys=True))
    exit_code = verdict["exit_code"]
    assert isinstance(exit_code, int)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
