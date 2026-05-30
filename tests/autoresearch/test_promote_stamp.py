"""PR-PROMOTE-STAMP (2026-05-26) — ``--promote`` flag baseline stamp pin.

Closes the audit finding from the 2026-05-26 autoresearch attribution
sprint Phase A audit (§5.5): the ``--promote`` operator override
bypassed ``_should_promote`` but wrote an *identical-shape*
baseline.json — downstream readers couldn't tell whether the value
came from operator force or from the auto-promote gate.

Post-PR, ``_write_baseline(manual_promote=True)`` stamps the
baseline.json with three new top-level fields:

* ``manual_promote: true``
* ``promoted_by: "operator"``
* ``promoted_at: <ts_utc>``

Auto-promote callers omit ``manual_promote`` → flag stays out of
the file → backward-compat preserved.

This file pins:

1. Default ``manual_promote=False`` → baseline.json has NO ``manual_promote``
   field (legacy shape preserved).
2. ``manual_promote=True`` → all three stamp fields present.
3. ``promoted_at`` equals ``ts_utc`` (single timestamp source).
4. The rest of the baseline payload (raw/axes/schema_version/...) is
   identical between the two modes — stamp is additive only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _common_kwargs() -> dict[str, object]:
    return {
        "session_id": "test-session",
        "commit": "abc1234",
        "sample_count": {"output_quality": 5},
        "measurement_modality": {"output_quality": "judge_llm"},
    }


def test_default_baseline_has_no_manual_promote_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-promote path (default ``manual_promote=False``) writes the
    legacy v2-schema baseline shape WITHOUT the stamp fields. This
    pins backward-compat for callers that omit the new flag."""
    from autoresearch import train as train_mod

    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(train_mod, "BASELINE_PATH", baseline_path)

    train_mod._write_baseline(
        {"output_quality": 0.8},
        {"output_quality": 0.05},
        **_common_kwargs(),
    )

    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert "manual_promote" not in payload
    assert "promoted_by" not in payload
    assert "promoted_at" not in payload
    # Sanity — the rest of the v2 shape is intact.
    assert payload["schema_version"] == 2
    assert payload["session_id"] == "test-session"
    assert payload["commit"] == "abc1234"


def test_manual_promote_stamps_baseline_with_three_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``manual_promote=True`` → baseline.json gets all three stamp
    fields. Downstream reader sees ``manual_promote: true`` and knows
    the value came from operator override, not gate approval."""
    from autoresearch import train as train_mod

    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(train_mod, "BASELINE_PATH", baseline_path)

    train_mod._write_baseline(
        {"output_quality": 0.8},
        {"output_quality": 0.05},
        manual_promote=True,
        **_common_kwargs(),
    )

    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert payload["manual_promote"] is True
    assert payload["promoted_by"] == "operator"
    assert "promoted_at" in payload


def test_manual_promote_promoted_at_equals_ts_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``promoted_at`` and ``ts_utc`` share the same timestamp source —
    no drift between when the baseline was *written* and when it was
    *promoted* (they're the same event in the manual-promote path)."""
    from autoresearch import train as train_mod

    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(train_mod, "BASELINE_PATH", baseline_path)

    train_mod._write_baseline(
        {"output_quality": 0.8},
        {"output_quality": 0.05},
        manual_promote=True,
        **_common_kwargs(),
    )

    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert payload["promoted_at"] == payload["ts_utc"]


def test_manual_promote_additive_only_rest_of_payload_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp is additive: every other field in the baseline payload
    must be identical between ``manual_promote=False`` and
    ``manual_promote=True``. Catches accidental shape drift."""
    from autoresearch import train as train_mod

    auto_path = tmp_path / "auto.json"
    manual_path = tmp_path / "manual.json"

    monkeypatch.setattr(train_mod, "BASELINE_PATH", auto_path)
    train_mod._write_baseline(
        {"output_quality": 0.8},
        {"output_quality": 0.05},
        **_common_kwargs(),
    )

    monkeypatch.setattr(train_mod, "BASELINE_PATH", manual_path)
    train_mod._write_baseline(
        {"output_quality": 0.8},
        {"output_quality": 0.05},
        manual_promote=True,
        **_common_kwargs(),
    )

    auto = json.loads(auto_path.read_text(encoding="utf-8"))
    manual = json.loads(manual_path.read_text(encoding="utf-8"))

    # Strip stamp + ts_utc/promoted_at (those can differ by milliseconds
    # between the two _write_baseline calls if the clock ticks).
    for stamp in ("manual_promote", "promoted_by", "promoted_at"):
        manual.pop(stamp, None)
    auto.pop("ts_utc", None)
    manual.pop("ts_utc", None)
    # PR-BASELINE-REGISTRY (2026-05-30) — baseline_id is a per-promote unique
    # registry id (the 2nd write increments the sequence), so it legitimately
    # differs between the two calls; it is not part of the data-shape identity
    # this test guards (same treatment as ts_utc).
    auto.pop("baseline_id", None)
    manual.pop("baseline_id", None)

    assert auto == manual
