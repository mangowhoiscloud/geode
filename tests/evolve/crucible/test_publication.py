"""Published crucible attempt rows."""

from __future__ import annotations

import json
from pathlib import Path

from evolve.crucible import publication as pub


def _ledger(root: Path, campaign: str, rows: list[dict[str, object]]) -> Path:
    path = root / campaign / "state" / "ledger.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + "not json\n", "utf-8")
    return path


def _attempt(campaign: str, outcome: str, tokens: int) -> dict[str, object]:
    return {
        "kind": "train_attempt",
        "campaign_id": campaign,
        "outcome": outcome,
        "usage": {"tokens": tokens, "cost_usd": tokens / 1000, "calls": 3},
        "wall_seconds": 1.5,
        "reasons": ["private detail"],
        "candidate_ref": "/Users/someone/worktree",
    }


def test_attempt_rows_keep_only_bounded_train_attempt_fields(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, "c1", [_attempt("c1", "KEEP", 100), {"kind": "other"}])

    assert pub.attempt_rows(ledger, "c1") == [
        {
            "campaign_id": "c1",
            "outcome": "KEEP",
            "tokens": 100,
            "cost_usd": 0.1,
            "wall_seconds": 1.5,
        }
    ]


def test_campaign_refresh_matches_full_regeneration(tmp_path: Path) -> None:
    campaigns = tmp_path / "campaigns"
    a = _ledger(campaigns, "a", [_attempt("a", "KEEP", 1), _attempt("a", "REJECT", 2)])
    b = _ledger(campaigns, "b", [_attempt("b", "INVALID", 3)])
    incremental = tmp_path / "incremental.jsonl"
    full = tmp_path / "full.jsonl"

    pub.refresh_campaign_attempts(b, "b", incremental)
    pub.refresh_campaign_attempts(a, "a", incremental)
    with a.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_attempt("a", "KEEP", 4)) + "\n")
    pub.refresh_campaign_attempts(a, "a", incremental)
    pub.write_attempt_rows(full, pub.collect_attempt_rows(campaigns))

    assert incremental.read_bytes() == full.read_bytes()
    rows = [json.loads(line) for line in full.read_text("utf-8").splitlines()]
    assert [(r["campaign_id"], r["tokens"]) for r in rows] == [
        ("a", 1),
        ("a", 2),
        ("a", 4),
        ("b", 3),
    ]
    assert pub.write_attempt_rows(full, pub.collect_attempt_rows(campaigns)) is False
