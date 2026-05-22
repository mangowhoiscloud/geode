"""Outer-loop bundle viewer — `geode outer-bundle` Typer command.

OL-A3 (2026-05-22) prerequisite stack now in place:

- ``~/.geode/self-improving-loop/auto_trigger_history.jsonl`` (OL-A1.5)
  — per-firing JSONL, one row per terminal state of the auto-trigger
  state machine (fired / lock_busy / interval_blocked / runner_error /
  parse_error).
- ``autoresearch/state/mutations.jsonl`` — git-tracked mutation audit
  ledger (one row per ``apply_mutation`` call: applied / rejected /
  rolled_back).
- ``autoresearch/state/baseline.json`` — current fitness baseline
  (promoted only — failing audits do not update it; see PR-G2 #1346
  retrospective).

This module crosswalks the three streams into a single chronologically
sorted timeline so an operator can answer "what did the self-improving
loop do today?" without grepping three files. Output is Rich-rendered
table; output for ``--json`` is one row per event so downstream tools
can consume it.

**Why a separate viewer instead of extending `/self-improving status`?**

The slash command `_cmd_status` (`core/cli/commands/self_improving.py`)
already reads baseline + mutations and ships in the REPL. But:

1. **Outside-REPL access** — operators frequently want this view from
   their shell prompt (e.g., post-incident review, daemon health check
   from a deploy tool). A standalone Typer command satisfies that.
2. **Triple-source crosswalk** — auto_trigger_history.jsonl is OL-A1.5
   data; slash command does NOT read it. Bundling that signal with
   the mutation ledger is the new value-add.
3. **Future evolution** — OL-A3 is the foundation for richer outer-
   loop diagnostics (e.g., per-session bundle, by-state filter,
   regression timeline). A dedicated module keeps the surface focused.

The two surfaces are intentionally redundant on baseline/mutations —
in-REPL `_cmd_status` for quick check, standalone `outer-bundle` for
deeper investigation + automation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR
from core.self_improving_loop.auto_trigger import AUTO_TRIGGER_HISTORY_PATH

log = logging.getLogger(__name__)
console = Console()

__all__ = [
    "BundleEvent",
    "load_bundle_events",
    "outer_bundle_command",
]


# Default tail size — matches `/self-improving status` default. Operator
# can override with ``--limit N`` for a wider window.
_DEFAULT_TAIL = 20


@dataclass(frozen=True, slots=True)
class BundleEvent:
    """One row in the unified outer-loop timeline.

    Three sources contribute (via ``source`` discriminator):

    * ``"auto_trigger"`` — from ``auto_trigger_history.jsonl``;
      ``detail`` carries the state machine variant (fired/lock_busy/etc.)
    * ``"mutation"`` — from ``mutations.jsonl``; ``detail`` carries
      ``kind`` (applied/rejected/rolled_back) + ``target_section``.
    * ``"baseline"`` — from ``baseline.json``; single synthetic event
      representing the most recent promoted fitness, with ``ts`` from
      the file's ``timestamp`` field. Only emitted when baseline.json
      exists.

    ``ts`` is Unix epoch seconds (float). Sources that store ISO-8601
    strings are normalised to epoch in the loader; on parse failure the
    row is skipped + logged at DEBUG.
    """

    ts: float
    source: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"ts": self.ts, "source": self.source, "detail": self.detail}


def _parse_iso_or_epoch(value: Any) -> float | None:
    """Accept either a float epoch or an ISO-8601 string. Return None
    on parse failure so the row is dropped silently."""
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().rstrip("Z")
    try:
        # ISO-8601 most-common: 2026-05-22T13:42:15.123456
        from datetime import datetime

        return datetime.fromisoformat(text).timestamp()
    except (ValueError, TypeError):
        return None


def _tail_jsonl(path: Path, *, limit: int) -> list[dict[str, Any]]:
    """Read the last ``limit`` valid JSON rows from a JSONL file.

    Missing path → empty list (graceful). Malformed lines → silently
    skipped (the file is append-only; concurrent writer can leave a
    half-flushed last row).
    """
    if not path.is_file() or limit <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.debug("outer_bundle: %s unreadable: %s", path, exc)
        return []
    parsed: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            parsed.append(row)
    return parsed[-limit:]


def _load_auto_trigger_events(*, limit: int) -> list[BundleEvent]:
    """Read OL-A1.5 audit log → BundleEvent list (source='auto_trigger')."""
    rows = _tail_jsonl(AUTO_TRIGGER_HISTORY_PATH, limit=limit)
    events: list[BundleEvent] = []
    for row in rows:
        ts = _parse_iso_or_epoch(row.get("ts"))
        if ts is None:
            continue
        state = str(row.get("state") or "")
        extra = str(row.get("detail") or "")
        detail = f"{state}" + (f" — {extra}" if extra else "")
        events.append(BundleEvent(ts=ts, source="auto_trigger", detail=detail))
    return events


def _load_mutation_events(*, limit: int) -> list[BundleEvent]:
    """Read mutations.jsonl → BundleEvent list (source='mutation').

    Lazy-imports ``MUTATION_AUDIT_LOG_PATH`` from runner so the bundle
    module doesn't drag the full runner deps at module load.
    """
    try:
        from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH
    except ImportError as exc:
        log.debug("outer_bundle: mutation log path unavailable: %s", exc)
        return []
    rows = _tail_jsonl(Path(MUTATION_AUDIT_LOG_PATH), limit=limit)
    events: list[BundleEvent] = []
    for row in rows:
        ts = _parse_iso_or_epoch(row.get("ts"))
        if ts is None:
            continue
        kind = str(row.get("kind") or "")
        target_kind = str(row.get("target_kind") or "")
        target_section = str(row.get("target_section") or "")
        # Format: applied[prompt:wrapper.intro] / rejected[tool_policy:...]
        scope = f"{target_kind}:{target_section}" if target_kind or target_section else ""
        detail = f"{kind}" + (f"[{scope}]" if scope else "")
        events.append(BundleEvent(ts=ts, source="mutation", detail=detail))
    return events


def _load_baseline_event() -> BundleEvent | None:
    """Synthetic single event for the most recent promoted baseline.

    The baseline file only updates on PROMOTE — see PR-G2 #1346 — so
    this is the "last successful audit" marker in the timeline.

    Codex MCP catch (PR-OL-A3 fix-up): real `baseline.json` (written by
    ``autoresearch/train.py:_persist_baseline``) carries only aggregate
    payload (``dim_means`` / ``dim_stderr`` + optional ``ux_means`` /
    ``admire_means`` / ``bench_means``) — NO ``timestamp`` or
    ``fitness`` scalar fields. We therefore derive the event timestamp
    from the file's mtime (the moment of promotion) and synthesise the
    detail from the dim count + a "promoted" marker. Tests can still
    inject an explicit ``timestamp`` field (which takes precedence) so
    historical fixture data with the legacy schema keeps working.
    """
    try:
        from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH
    except ImportError:
        return None
    baseline_path = Path(MUTATION_AUDIT_LOG_PATH).parent / "baseline.json"
    if not baseline_path.is_file():
        return None
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("outer_bundle: baseline.json unreadable: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    # Prefer explicit timestamp / ts when present (legacy schema / test
    # fixtures). Otherwise fall back to file mtime — the actual
    # baseline writer does not emit a timestamp field.
    ts = _parse_iso_or_epoch(data.get("timestamp") or data.get("ts"))
    if ts is None:
        try:
            ts = baseline_path.stat().st_mtime
        except OSError:
            return None
    # `fitness` scalar may or may not be present; if not, summarise
    # dim_means count instead so the event still renders informatively.
    # PR-2 of petri-schema-v2 (2026-05-23) — schema_version=2 nests
    # dim_means under ``raw.``; route the count lookup accordingly so
    # promoted baselines render `dim_means[24]` instead of `dim_means[0]`.
    fitness = data.get("fitness")
    if isinstance(fitness, int | float):
        body_detail = f"fitness={fitness:.4f}"
    else:
        if data.get("schema_version") == 2:
            raw_block = data.get("raw") or {}
            dim_means = raw_block.get("dim_means") or {}
        else:
            dim_means = data.get("dim_means") or {}
        dim_count = len(dim_means) if isinstance(dim_means, dict) else 0
        body_detail = f"dim_means[{dim_count}]"
    reason = data.get("promote_reason") or data.get("reason") or "promoted"
    detail = f"baseline {body_detail} ({reason})"
    return BundleEvent(ts=ts, source="baseline", detail=detail)


def load_bundle_events(
    *,
    limit: int = _DEFAULT_TAIL,
    history_path: Path | None = None,
) -> list[BundleEvent]:
    """Public loader — three-source crosswalk + chronological sort.

    Args:
        limit: Per-source tail. The output may have up to 2×limit + 1
            events (auto_trigger + mutation + baseline).
        history_path: Override for the auto-trigger history path (test
            injection). Default uses the canonical
            :data:`AUTO_TRIGGER_HISTORY_PATH`.
    """
    # auto_trigger load uses module constant — for tests we monkey-patch
    # the module attribute instead of plumbing path here.
    if history_path is not None:
        # Temporarily redirect the constant via globals override.
        # Tests typically use monkeypatch.setattr; this branch is the
        # explicit-arg path that lets non-test callers swap the source.
        rows = _tail_jsonl(history_path, limit=limit)
        auto_events: list[BundleEvent] = []
        for row in rows:
            ts = _parse_iso_or_epoch(row.get("ts"))
            if ts is None:
                continue
            state = str(row.get("state") or "")
            extra = str(row.get("detail") or "")
            detail = f"{state}" + (f" — {extra}" if extra else "")
            auto_events.append(BundleEvent(ts=ts, source="auto_trigger", detail=detail))
    else:
        auto_events = _load_auto_trigger_events(limit=limit)
    mutation_events = _load_mutation_events(limit=limit)
    baseline_event = _load_baseline_event()
    combined = auto_events + mutation_events
    if baseline_event is not None:
        combined.append(baseline_event)
    combined.sort(key=lambda ev: ev.ts)
    return combined


def _format_ts(epoch: float) -> str:
    """Render epoch as ``YYYY-MM-DD HH:MM:SS`` local time."""
    from datetime import datetime

    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def _render_table(events: list[BundleEvent]) -> None:
    """Print events as a Rich table."""
    table = Table(title="Outer-loop bundle — auto_trigger × mutations × baseline")
    table.add_column("Timestamp", style="cyan", no_wrap=True)
    table.add_column("Source", style="magenta")
    table.add_column("Detail", style="white")
    for ev in events:
        table.add_row(_format_ts(ev.ts), ev.source, ev.detail)
    console.print(table)


def outer_bundle_command(
    limit: int = typer.Option(
        _DEFAULT_TAIL,
        "--limit",
        "-n",
        help="Per-source tail size. Output is up to 2×limit + 1 events.",
        min=1,
        max=500,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit one JSON row per event to stdout instead of a Rich table.",
    ),
) -> None:
    """View the outer self-improving loop's activity bundle.

    Crosswalks three sources into one chronological timeline:

    * ``auto_trigger_history.jsonl`` — cron firings (OL-A1.5)
    * ``mutations.jsonl`` — mutation audit ledger
    * ``baseline.json`` — current promoted fitness baseline

    Output (default) is a Rich table sorted ascending by timestamp.
    ``--json`` switches to JSONL-on-stdout for downstream tools.

    Files outside ``~/.geode/`` and ``autoresearch/state/`` are
    ignored. Missing files render as an empty bundle (no error).
    """
    events = load_bundle_events(limit=limit)
    if json_output:
        # Codex MCP catch (PR-OL-A3 fix-up): `console.print_json` pretty-
        # prints with indentation across multiple lines per object, which
        # is NOT JSONL. Downstream tools (jq, awk, line-based readers)
        # need exactly one JSON object per line. Use json.dumps + plain
        # print to satisfy the JSONL contract.
        for ev in events:
            print(json.dumps(ev.as_dict(), ensure_ascii=False))
        return
    if not events:
        console.print(
            "[muted]No bundle events — auto_trigger_history.jsonl + "
            "mutations.jsonl + baseline.json all empty/absent.[/muted]"
        )
        console.print(
            f"[muted]Looked for: {AUTO_TRIGGER_HISTORY_PATH} + "
            f"{GLOBAL_SELF_IMPROVING_LOOP_DIR.parent}/autoresearch/state/[/muted]"
        )
        return
    _render_table(events)
