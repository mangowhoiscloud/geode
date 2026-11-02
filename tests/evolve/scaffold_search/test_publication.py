"""Published snapshots of runtime self-improving evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evolve.scaffold_search import publication as pub

_LEGACY_LOG = """\
2026-05-31T06:00:00Z campaign start: n=2 k=2 arms=['never', 'gate'] dry_run=False audit_max_samples=3
2026-05-31T06:01:00Z gen-0 baseline repeat 1/2: held_out=0.81 fitness=0.66 source=manual dims_parsed=22
2026-05-31T06:02:00Z gen-0 baseline repeat 2/2: held_out=None fitness=0.67 source=manual dims_parsed=0
2026-05-31T06:03:00Z gen-0 noise band: K=2 held_out_mean=0.8100 stderr=0.0000 values=[0.81]
2026-05-31T06:04:00Z arm 'never' cycle 1/2: fitness_after=0.665 fitness_delta=-0.1473 held_out=0.83 reject guard=ok (ok)
2026-05-31T06:05:00Z arm 'never' cycle 2/2: SKIP (propose-guard exhausted)
2026-05-31T06:06:00Z control arm 'never' floor: cycles_ok=1 cycles_dropped=0; gen-0 noise band: K=2 held_out_mean=0.9000 stderr=0.0100 values=[0.9]
2026-05-31T06:07:00Z arm 'gate' cycle 1/2: fitness_after=0.70 fitness_delta=+0.0025 held_out=0.86 promote guard=ok (ok)
2026-05-31T06:08:00Z arm 'gate' cycle 2/2: NO-SIGNAL guard=ok (no row)
2026-05-31T06:09:00Z arm 'gate' cycle 3/3: fitness_after=None fitness_delta=n/a held_out=None reject guard=ok (x)
2026-06-01T00:00:00Z campaign start: n=1 k=1 arms=['never'] dry_run=True audit_max_samples=3
2026-06-01T00:01:00Z gen-0 noise band: K=1 held_out_mean=0.5000 stderr=0.0000 values=[0.5]
2026-06-01T00:02:00Z arm 'never' cycle 1/1: SKIP (propose-guard exhausted)
2026-06-02T00:00:00Z campaign start: n=1 k=1 arms=['gate'] dry_run=False audit_max_samples=3
2026-06-02T00:01:00Z gen-0 baseline (async): 1/1 workers ok (0 resumed + 1 fresh), 0 dropped; gen-0 noise band: K=1 collected=0 (no held-out values)
"""


def test_scrub_drops_absolute_paths_but_keeps_urls_and_relative_paths() -> None:
    scrubbed = pub.scrub(
        {
            "eval_archive": "/Users/user/.geode/petri/logs/a_audit_x.eval",
            "home": "~/.geode/self-improving/baseline.json",
            "url": "https://github.com/mangowhoiscloud/geode/blob/main/x.md",
            "relative": "docs/self-improving/run-1.md",
            "ratio": "1/10",
            "nested": [{"path": "/srv/work/report.json"}],
        }
    )

    assert scrubbed == {
        "eval_archive": "a_audit_x.eval",
        "home": "baseline.json",
        "url": "https://github.com/mangowhoiscloud/geode/blob/main/x.md",
        "relative": "docs/self-improving/run-1.md",
        "ratio": "1/10",
        "nested": [{"path": "report.json"}],
    }


def test_publish_baseline_wraps_scrubs_and_skips_unchanged_rewrites(tmp_path: Path) -> None:
    source = tmp_path / "baseline.json"
    source.write_text(
        json.dumps(
            {"ts_utc": "2026-06-01T20:24:47Z", "raw": {"eval_archive": "/Users/user/b/c.eval"}}
        ),
        encoding="utf-8",
    )
    out = tmp_path / "published"

    assert pub.publish_baseline(source, out_dir=out) is True
    assert pub.publish_baseline(source, out_dir=out) is False
    published = json.loads((out / pub.PUBLISHED_BASELINE_NAME).read_text(encoding="utf-8"))
    assert published == {
        "schema_version": 1,
        "stale": False,
        "source": "baseline.json",
        "captured_at": "2026-06-01T20:24:47Z",
        "baseline": {"ts_utc": "2026-06-01T20:24:47Z", "raw": {"eval_archive": "c.eval"}},
    }


def test_latest_runtime_baseline_prefers_live_then_newest_outdated(tmp_path: Path) -> None:
    assert pub.latest_runtime_baseline(tmp_path) is None
    for suffix in ("20260522", "20260529"):
        (tmp_path / f"baseline.json.outdated-{suffix}").write_text("{}", encoding="utf-8")
    assert pub.latest_runtime_baseline(tmp_path) == (
        tmp_path / "baseline.json.outdated-20260529",
        True,
    )
    (tmp_path / "baseline.json").write_text("{}", encoding="utf-8")
    assert pub.latest_runtime_baseline(tmp_path) == (tmp_path / "baseline.json", False)


def test_publish_baseline_without_timestamp_records_null_capture(tmp_path: Path) -> None:
    source = tmp_path / "baseline.json.outdated-20260529"
    source.write_text('{"raw": {}}', encoding="utf-8")

    pub.publish_baseline(source, stale=True, out_dir=tmp_path)

    published = json.loads((tmp_path / pub.PUBLISHED_BASELINE_NAME).read_text(encoding="utf-8"))
    assert (published["stale"], published["captured_at"]) == (True, None)


def test_gen0_fitness_stderr_requires_a_recorded_value(tmp_path: Path) -> None:
    snapshot = tmp_path / "baseline.json"
    snapshot.write_text('{"ts_utc": "t", "raw": {"fitness_stderr": 0.013}}', encoding="utf-8")

    pub.publish_gen0_fitness_stderr(snapshot, out_dir=tmp_path)

    published = json.loads((tmp_path / pub.GEN0_FITNESS_STDERR_NAME).read_text(encoding="utf-8"))
    assert published == {"schema_version": 1, "fitness_stderr": 0.013, "captured_at": "t"}
    snapshot.write_text('{"raw": {}}', encoding="utf-8")
    with pytest.raises(pub.PublishedStateError, match="fitness_stderr"):
        pub.publish_gen0_fitness_stderr(snapshot, out_dir=tmp_path / "other")
    assert not (tmp_path / "other").exists()


def test_legacy_log_parser_records_real_campaign_events_only() -> None:
    data = pub.parse_campaign_progress_log(_LEGACY_LOG)

    assert [(c["arm"], c["n"], c["skip"], c["verdict"]) for c in data["cycles"]] == [
        ("never", 1, False, "reject"),
        ("never", 2, True, None),
        ("gate", 1, False, "promote"),
        ("gate", 2, False, "no-signal"),
        ("gate", 3, False, "reject"),
    ]
    assert data["cycles"][2] == {
        "ts": "2026-05-31T06:07:00Z",
        "arm": "gate",
        "n": 1,
        "total": 2,
        "skip": False,
        "verdict": "promote",
        "sel": 0.70,
        "held": 0.86,
        "delta": 0.0025,
    }
    assert data["cycles"][4]["sel"] is None and data["cycles"][4]["delta"] is None
    assert [(g["n"], g["sel"], g["held"]) for g in data["gen0"]] == [
        (1, 0.66, 0.81),
        (2, 0.67, None),
    ]
    # The control-arm floor and the dry-run band are not gen-0 noise bands.
    assert [(b["ts"], b["mean"], b["stderr"]) for b in data["noise"]] == [
        ("2026-05-31T06:03:00Z", 0.81, 0.0),
        ("2026-06-02T00:01:00Z", None, None),
    ]


def test_append_campaign_record_rejects_unknown_group_and_malformed_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / pub.CAMPAIGN_PROGRESS_NAME
    with pytest.raises(ValueError, match="unknown"):
        pub.append_campaign_record(path, "other", {})
    path.write_text('{"cycles": {}}', encoding="utf-8")
    with pytest.raises(pub.PublishedStateError, match="malformed"):
        pub.append_campaign_record(path, "cycles", {"ts": "t"})
    assert path.read_text(encoding="utf-8") == '{"cycles": {}}'


def test_cycle_record_requires_exactly_one_of_skip_or_verdict() -> None:
    with pytest.raises(ValueError, match="invalid cycle outcome"):
        pub.cycle_record(arm="gate", n=1, total=1)
    with pytest.raises(ValueError, match="invalid cycle outcome"):
        pub.cycle_record(arm="gate", n=1, total=1, skip=True, verdict="reject")
