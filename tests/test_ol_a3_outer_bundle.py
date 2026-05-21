"""OL-A3 — `geode outer-bundle` viewer invariants.

Pins:
- `BundleEvent` shape (ts / source / detail) round-trips via as_dict.
- `_parse_iso_or_epoch` accepts float, ISO-8601, returns None on garbage.
- `_tail_jsonl` reads last N rows + skips malformed lines silently.
- `load_bundle_events` merges 3 sources chronologically.
- Auto-trigger row → source='auto_trigger'.
- Mutation row → source='mutation'.
- Baseline → source='baseline', synthetic 1-row.
- Missing files → empty event list (no raise).
- Output sorted ascending by ts.
- Typer CLI command registered.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_bundle_event_round_trip() -> None:
    from core.cli.outer_bundle import BundleEvent

    ev = BundleEvent(ts=1000.5, source="auto_trigger", detail="fired — target=x")
    d = ev.as_dict()
    assert d == {"ts": 1000.5, "source": "auto_trigger", "detail": "fired — target=x"}


def test_parse_iso_or_epoch_accepts_float() -> None:
    from core.cli.outer_bundle import _parse_iso_or_epoch

    assert _parse_iso_or_epoch(1234567890.5) == 1234567890.5
    assert _parse_iso_or_epoch(1234567890) == 1234567890.0


def test_parse_iso_or_epoch_accepts_iso8601() -> None:
    # Round-trip via datetime to get expected epoch
    from datetime import datetime

    from core.cli.outer_bundle import _parse_iso_or_epoch

    expected = datetime.fromisoformat("2026-05-22T12:34:56").timestamp()
    assert _parse_iso_or_epoch("2026-05-22T12:34:56") == expected
    # Trailing Z stripped
    assert _parse_iso_or_epoch("2026-05-22T12:34:56Z") == expected


def test_parse_iso_or_epoch_garbage_returns_none() -> None:
    from core.cli.outer_bundle import _parse_iso_or_epoch

    assert _parse_iso_or_epoch(None) is None
    assert _parse_iso_or_epoch("") is None
    assert _parse_iso_or_epoch("not-a-date") is None
    assert _parse_iso_or_epoch({}) is None


def test_tail_jsonl_reads_last_n_rows(tmp_path: Path) -> None:
    from core.cli.outer_bundle import _tail_jsonl

    p = tmp_path / "log.jsonl"
    lines = [json.dumps({"i": i}) for i in range(10)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = _tail_jsonl(p, limit=3)
    assert [r["i"] for r in out] == [7, 8, 9]


def test_tail_jsonl_skips_malformed_lines(tmp_path: Path) -> None:
    from core.cli.outer_bundle import _tail_jsonl

    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"ok": 1}\nnot-json\n{"ok": 2}\n   \n{"ok": 3}\n',
        encoding="utf-8",
    )
    out = _tail_jsonl(p, limit=10)
    assert [r["ok"] for r in out] == [1, 2, 3]


def test_tail_jsonl_missing_file_returns_empty(tmp_path: Path) -> None:
    from core.cli.outer_bundle import _tail_jsonl

    assert _tail_jsonl(tmp_path / "no_such.jsonl", limit=5) == []


def test_load_bundle_events_auto_trigger_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bundle reader picks up auto_trigger rows when only that source exists."""
    from core.cli import outer_bundle as ob

    hist = tmp_path / "auto_trigger_history.jsonl"
    rows = [
        {"ts": 1000.0, "state": "fired", "detail": "target_section=wrapper.intro"},
        {"ts": 2000.0, "state": "lock_busy", "detail": ""},
    ]
    hist.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    # Redirect mutation/baseline lookups to nonexistent paths so only
    # auto_trigger contributes.
    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", hist)
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        tmp_path / "no_mutations.jsonl",
    )
    events = ob.load_bundle_events(limit=10)
    assert len(events) == 2
    assert {ev.source for ev in events} == {"auto_trigger"}
    assert events[0].ts == 1000.0
    assert "fired" in events[0].detail
    assert "wrapper.intro" in events[0].detail
    assert events[1].detail.startswith("lock_busy")


def test_load_bundle_events_mutation_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.cli import outer_bundle as ob

    mut = tmp_path / "mutations.jsonl"
    rows = [
        {
            "ts": 1500.0,
            "kind": "applied",
            "target_kind": "prompt",
            "target_section": "wrapper.intro",
            "mutation_id": "m1",
        },
        {
            "ts": 1600.0,
            "kind": "rejected",
            "target_kind": "tool_policy",
            "target_section": "search",
            "mutation_id": "m2",
        },
    ]
    mut.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr("core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH", mut)
    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", tmp_path / "no_history.jsonl")
    events = ob.load_bundle_events(limit=10)
    assert len(events) == 2
    assert all(ev.source == "mutation" for ev in events)
    assert "applied" in events[0].detail
    assert "prompt:wrapper.intro" in events[0].detail
    assert "rejected" in events[1].detail


def test_load_bundle_events_baseline_synthetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.cli import outer_bundle as ob

    mut = tmp_path / "state" / "mutations.jsonl"
    mut.parent.mkdir(parents=True)
    baseline = mut.parent / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "ts": 3000.0,
                "fitness": 0.875,
                "promote_reason": "audit_passed",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH", mut)
    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", tmp_path / "no_history.jsonl")
    events = ob.load_bundle_events(limit=10)
    assert len(events) == 1
    assert events[0].source == "baseline"
    assert "0.8750" in events[0].detail
    assert "audit_passed" in events[0].detail


def test_load_bundle_events_sorts_ascending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crosswalk must interleave the three sources by timestamp."""
    from core.cli import outer_bundle as ob

    hist = tmp_path / "auto_trigger_history.jsonl"
    mut = tmp_path / "state" / "mutations.jsonl"
    mut.parent.mkdir(parents=True)
    baseline = mut.parent / "baseline.json"

    hist.write_text(
        json.dumps({"ts": 1500.0, "state": "fired", "detail": "x"}) + "\n",
        encoding="utf-8",
    )
    mut.write_text(
        json.dumps(
            {
                "ts": 1700.0,
                "kind": "applied",
                "target_kind": "prompt",
                "target_section": "intro",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps({"ts": 1200.0, "fitness": 0.5, "promote_reason": "init"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", hist)
    monkeypatch.setattr("core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH", mut)
    events = ob.load_bundle_events(limit=10)
    assert [ev.source for ev in events] == ["baseline", "auto_trigger", "mutation"]
    assert events[0].ts == 1200.0 < events[1].ts == 1500.0 < events[2].ts == 1700.0


def test_load_bundle_events_all_missing_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No files anywhere → empty list, no exception."""
    from core.cli import outer_bundle as ob

    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", tmp_path / "no_hist.jsonl")
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        tmp_path / "no_state" / "no_mut.jsonl",
    )
    assert ob.load_bundle_events(limit=10) == []


def test_outer_bundle_command_registered_on_app() -> None:
    """Typer should resolve `outer-bundle` as a registered command."""
    from core.cli import app

    cmd_names = {c.name for c in app.registered_commands}
    assert "outer-bundle" in cmd_names


def test_outer_bundle_command_callable_with_no_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling the command directly with no input files should
    print the empty-state message without raising."""
    from core.cli import outer_bundle as ob

    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", tmp_path / "no_hist.jsonl")
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        tmp_path / "no_state" / "no_mut.jsonl",
    )
    # Call the function directly (bypass Typer arg parsing).
    ob.outer_bundle_command(limit=10, json_output=False)


def test_outer_bundle_command_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--json mode emits ONE JSON object PER LINE (true JSONL).

    Codex MCP catch (PR-OL-A3 fix-up): `console.print_json` pretty-prints
    across multiple lines per object, which breaks downstream jq /
    line-based readers. Pin the JSONL contract here.
    """
    from core.cli import outer_bundle as ob

    hist = tmp_path / "auto_trigger_history.jsonl"
    rows = [
        {"ts": 1000.0, "state": "fired", "detail": "alpha"},
        {"ts": 2000.0, "state": "lock_busy", "detail": ""},
    ]
    hist.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", hist)
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        tmp_path / "no_mut.jsonl",
    )
    ob.outer_bundle_command(limit=10, json_output=True)
    out = capsys.readouterr().out
    # Exactly 2 non-empty lines → 2 events
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 2, f"Expected JSONL output, got {out!r}"
    # Each line must parse as valid JSON dict
    parsed = [json.loads(ln) for ln in lines]
    assert all(isinstance(p, dict) for p in parsed)
    assert {p["detail"][:5] for p in parsed} == {"fired", "lock_"}


def test_baseline_uses_file_mtime_when_no_timestamp_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex MCP catch (PR-OL-A3 fix-up): the real `baseline.json` writer
    (`autoresearch/train.py:_persist_baseline`) does NOT emit ``timestamp``
    or ``fitness`` fields — only ``dim_means`` / ``dim_stderr`` /
    optional axis-specific means. The viewer must fall back to file
    mtime + synthesise the detail from dim count.
    """
    import os
    import time

    from core.cli import outer_bundle as ob

    mut = tmp_path / "state" / "mutations.jsonl"
    mut.parent.mkdir(parents=True)
    baseline = mut.parent / "baseline.json"
    # Production schema — only aggregate payload, NO timestamp/fitness.
    baseline.write_text(
        json.dumps(
            {
                "dim_means": {"correctness": 0.85, "safety": 0.92, "depth": 0.78},
                "dim_stderr": {"correctness": 0.02, "safety": 0.01, "depth": 0.03},
            }
        ),
        encoding="utf-8",
    )
    # Stamp a known mtime so the test is deterministic.
    fixed_mtime = time.time() - 3600  # 1 hour ago
    os.utime(baseline, (fixed_mtime, fixed_mtime))
    monkeypatch.setattr("core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH", mut)
    monkeypatch.setattr(ob, "AUTO_TRIGGER_HISTORY_PATH", tmp_path / "no_history.jsonl")
    events = ob.load_bundle_events(limit=10)
    assert len(events) == 1
    ev = events[0]
    assert ev.source == "baseline"
    # mtime fallback worked
    assert abs(ev.ts - fixed_mtime) < 1.0
    # detail uses dim_means count (3 axes) since no fitness scalar
    assert "dim_means[3]" in ev.detail
    assert "promoted" in ev.detail
