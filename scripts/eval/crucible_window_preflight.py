"""Launch-gate a Crucible campaign against the current quota window.

Thin CLI over :mod:`plugins.crucible.preflight`, which owns the decision
model (tiers, history scan, Codex usage probe) so ``prepare_campaign`` and
this launcher share one implementation. Exit codes: 0 ``cap_fit`` ·
1 ``history_fit`` · 3 ``defer``.

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.crucible.contract import ContractError
from plugins.crucible.preflight import (
    campaign_token_cap,
    completed_campaign_tokens,
    decide,
    remaining_from_codex,
)


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
        remaining, source_detail = remaining_from_codex(args.window_capacity_tokens)
    else:
        if args.remaining_tokens is None or args.remaining_tokens < 0:
            parser.error("--remaining-tokens must be non-negative")
        remaining, source_detail = args.remaining_tokens, "operator-supplied"

    history = completed_campaign_tokens(args.history) if args.history else []
    try:
        hard_cap = campaign_token_cap(args.config)
    except ContractError as error:
        raise SystemExit(str(error)) from error
    verdict = decide(
        hard_cap_tokens=hard_cap,
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
