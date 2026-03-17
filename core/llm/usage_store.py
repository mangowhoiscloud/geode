"""Usage Store -- persistent LLM cost tracking to ~/.geode/usage/YYYY-MM.jsonl.

Appends one JSONL record per LLM call with model, tokens, cost, and context.
Provides monthly/daily aggregation for the ``geode history`` command.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_USAGE_DIR = Path.home() / ".geode" / "usage"


@dataclass(slots=True)
class UsageRecord:
    """Single LLM call usage record for JSONL persistence."""

    ts: float
    model: str
    input_tokens: int = field(metadata={"alias": "in"})
    output_tokens: int = field(metadata={"alias": "out"})
    cost_usd: float = field(metadata={"alias": "cost"})
    session: str = ""
    ip_name: str = ""

    def to_json(self) -> str:
        """Serialize to compact JSON line."""
        d = {
            "ts": self.ts,
            "model": self.model,
            "in": self.input_tokens,
            "out": self.output_tokens,
            "cost": self.cost_usd,
        }
        if self.session:
            d["session"] = self.session
        if self.ip_name:
            d["ip"] = self.ip_name
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> UsageRecord:
        """Deserialize from a JSON line."""
        data = json.loads(line)
        return cls(
            ts=data.get("ts", 0.0),
            model=data.get("model", ""),
            input_tokens=data.get("in", 0),
            output_tokens=data.get("out", 0),
            cost_usd=data.get("cost", 0.0),
            session=data.get("session", ""),
            ip_name=data.get("ip", ""),
        )


class UsageStore:
    """Persistent JSONL usage store with monthly file rotation.

    Each month's data is stored in ``~/.geode/usage/YYYY-MM.jsonl``.

    Usage::

        store = UsageStore()
        store.record("claude-opus-4-6", 1200, 350, 0.0148)
        summary = store.get_monthly_summary()
    """

    def __init__(self, usage_dir: Path | None = None) -> None:
        self._usage_dir = usage_dir or DEFAULT_USAGE_DIR
        self._lock = threading.Lock()

    @property
    def usage_dir(self) -> Path:
        return self._usage_dir

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        *,
        session: str = "",
        ip_name: str = "",
    ) -> UsageRecord:
        """Append a usage record to the current month's JSONL file."""
        now = time.time()
        entry = UsageRecord(
            ts=now,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            session=session,
            ip_name=ip_name,
        )
        self._append(entry)
        return entry

    def get_monthly_summary(
        self,
        year: int | None = None,
        month: int | None = None,
    ) -> dict[str, Any]:
        """Aggregate usage for a given month (default: current month).

        Returns::

            {
                "year": 2026,
                "month": 3,
                "total_cost": 3.66,
                "total_calls": 180,
                "total_input_tokens": 190800,
                "total_output_tokens": 50800,
                "by_model": {
                    "claude-opus-4-6": {"calls": 142, "in": 168500, "out": 42100, "cost": 3.47},
                    ...
                },
            }
        """
        today = date.today()
        y = year or today.year
        m = month or today.month
        records = self._read_month(y, m)

        by_model: dict[str, dict[str, float]] = defaultdict(
            lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
        )
        total_cost = 0.0
        total_in = 0
        total_out = 0

        for rec in records:
            entry = by_model[rec.model]
            entry["calls"] += 1
            entry["in"] += rec.input_tokens
            entry["out"] += rec.output_tokens
            entry["cost"] += rec.cost_usd
            total_cost += rec.cost_usd
            total_in += rec.input_tokens
            total_out += rec.output_tokens

        return {
            "year": y,
            "month": m,
            "total_cost": round(total_cost, 4),
            "total_calls": len(records),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "by_model": dict(by_model),
        }

    def get_daily_summary(self, target_date: date | None = None) -> dict[str, Any]:
        """Aggregate usage for a specific day (default: today).

        Returns::

            {
                "date": "2026-03-17",
                "total_cost": 0.52,
                "total_calls": 12,
                "by_model": {...},
            }
        """
        d = target_date or date.today()
        records = self._read_month(d.year, d.month)

        # Filter to target date
        day_start = datetime(d.year, d.month, d.day).timestamp()
        day_end = day_start + 86400
        day_records = [r for r in records if day_start <= r.ts < day_end]

        by_model: dict[str, dict[str, float]] = defaultdict(
            lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
        )
        total_cost = 0.0

        for rec in day_records:
            entry = by_model[rec.model]
            entry["calls"] += 1
            entry["in"] += rec.input_tokens
            entry["out"] += rec.output_tokens
            entry["cost"] += rec.cost_usd
            total_cost += rec.cost_usd

        return {
            "date": d.isoformat(),
            "total_cost": round(total_cost, 4),
            "total_calls": len(day_records),
            "by_model": dict(by_model),
        }

    def get_recent_records(self, limit: int = 20) -> list[UsageRecord]:
        """Read the most recent N usage records from the current month."""
        today = date.today()
        records = self._read_month(today.year, today.month)
        # Records are in chronological order; return newest first
        return list(reversed(records[-limit:]))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _month_file(self, year: int, month: int) -> Path:
        return self._usage_dir / f"{year:04d}-{month:02d}.jsonl"

    def _append(self, entry: UsageRecord) -> None:
        """Thread-safe append to JSONL file."""
        dt = datetime.fromtimestamp(entry.ts)
        fpath = self._month_file(dt.year, dt.month)
        with self._lock:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(entry.to_json() + "\n")
            except OSError as e:
                log.warning("Failed to write usage record: %s", e)

    def _read_month(self, year: int, month: int) -> list[UsageRecord]:
        """Read all records from a month file."""
        fpath = self._month_file(year, month)
        if not fpath.exists():
            return []

        records: list[UsageRecord] = []
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(UsageRecord.from_json(line))
                    except (json.JSONDecodeError, KeyError, TypeError):
                        log.debug("Skipping malformed usage line: %s", line[:80])
        except OSError as e:
            log.warning("Failed to read usage file %s: %s", fpath, e)

        return records


# ---------------------------------------------------------------------------
# Module-level singleton (lazy init via contextvars not needed here;
# UsageStore is stateless except for file I/O and thread-safe)
# ---------------------------------------------------------------------------

_store: UsageStore | None = None
_store_lock = threading.Lock()


def get_usage_store() -> UsageStore:
    """Get or create the module-level UsageStore singleton."""
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            _store = UsageStore()
        return _store


def reset_usage_store(store: UsageStore | None = None) -> None:
    """Reset the singleton (for testing)."""
    global _store
    _store = store
