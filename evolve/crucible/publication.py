"""Published crucible attempt rows for the publication bundle.

Crucible campaign ledgers live in gitignored campaign state directories, so a
bundle built in CI cannot read them. After each ``train_attempt`` the
supervisor refreshes ``crucible-attempts.jsonl`` in
``core.paths.PUBLISHED_STATE_DIR`` with one bounded row per attempt:
``{campaign_id, outcome, tokens, cost_usd, wall_seconds}``. Contract:
``docs/architecture/publication-bundle.md``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import core.paths
from core.memory.atomic_write import atomic_write_text

log = logging.getLogger(__name__)

CRUCIBLE_ATTEMPTS_NAME = "crucible-attempts.jsonl"
LEDGER_GLOB = "*/state/ledger.jsonl"


def published_attempts_path() -> Path:
    """Resolve at call time so test isolation of ``core.paths`` applies."""
    return Path(core.paths.PUBLISHED_STATE_DIR) / CRUCIBLE_ATTEMPTS_NAME


def _number(value: Any, cast: type[int] | type[float]) -> int | float:
    try:
        return cast(value or 0)
    except (TypeError, ValueError):
        return cast(0)


def attempt_rows(ledger: Path, campaign_id: str) -> list[dict[str, Any]]:
    """Project one campaign ledger's ``train_attempt`` records, in ledger order."""
    rows: list[dict[str, Any]] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("kind") != "train_attempt":
            continue
        raw_usage = record.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        recorded_id = record.get("campaign_id")
        rows.append(
            {
                "campaign_id": recorded_id if isinstance(recorded_id, str) else campaign_id,
                "outcome": str(record.get("outcome", "?")),
                "tokens": _number(usage.get("tokens"), int),
                "cost_usd": _number(usage.get("cost_usd"), float),
                "wall_seconds": _number(record.get("wall_seconds"), float),
            }
        )
    return rows


def collect_attempt_rows(campaigns_dir: Path) -> list[dict[str, Any]]:
    """Rows from every ``<campaign>/state/ledger.jsonl`` under ``campaigns_dir``."""
    rows: list[dict[str, Any]] = []
    for ledger in sorted(campaigns_dir.glob(LEDGER_GLOB)):
        rows.extend(attempt_rows(ledger, ledger.parent.parent.name))
    return rows


def write_attempt_rows(path: Path, rows: Iterable[dict[str, Any]]) -> bool:
    """Write rows grouped by campaign (stable within one); False when unchanged."""
    ordered = sorted(rows, key=lambda row: str(row["campaign_id"]))
    text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ordered)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    return True


def _read_published_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def refresh_campaign_attempts(ledger: Path, campaign_id: str, out_path: Path | None = None) -> bool:
    """Replace one campaign's rows in the published file from its ledger."""
    target = out_path or published_attempts_path()
    fresh = attempt_rows(ledger, campaign_id)
    replaced = {row["campaign_id"] for row in fresh} | {campaign_id}
    kept = [row for row in _read_published_rows(target) if row.get("campaign_id") not in replaced]
    return write_attempt_rows(target, [*kept, *fresh])


def refresh_published_attempts(ledger: Path, campaign_id: str) -> None:
    """Supervisor hook after a ledger append; failures only log."""
    try:
        refresh_campaign_attempts(ledger, campaign_id)
    except (OSError, ValueError) as exc:
        log.warning("published crucible attempts refresh failed: %s", exc)
