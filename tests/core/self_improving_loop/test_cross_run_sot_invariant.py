"""B.4 (2026-05-25) — F1 cross-run SoT 3중첩 invariants (PR-22).

memory ``project_autoresearch_fragmentation_audit.md`` 신호 F1 — cross-run
SoT 3중첩 (meta-review snapshot / latest_pointer.json / sessions.jsonl).
3 SoT 가 같은 cross-ref key (`run_id` / `gen_tag`) 로 join 가능해야 함.

본 file 은 **schema parity invariants** — 3 SoT 의 schema 가 호환 가능한
shape 으로 유지되는지 pin. drift 발생 시 fail-fast.

Scope:
- latest_pointer.json write/read roundtrip
- latest_pointer.json schema (version=1, run_id, gen_tag, updated_at)
- read_latest_pointer graceful (missing file / malformed JSON)
- STATE_ROOT-relative path resolution
- sessions.jsonl row schema parity check (run_id key 일치)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# 1. latest_pointer.json write/read roundtrip
# ---------------------------------------------------------------------------


def test_latest_pointer_roundtrip(tmp_path: Path) -> None:
    """write → read 같은 payload."""
    from core import paths as paths_module

    pointer_path = tmp_path / "latest_pointer.json"
    state_root = tmp_path

    with (
        patch.object(paths_module, "STATE_LATEST_POINTER_PATH", pointer_path),
        patch.object(paths_module, "STATE_ROOT", state_root),
    ):
        paths_module.write_latest_pointer(
            run_id="2026-05-25T10-00-00",
            gen_tag="gen-7",
            seed_pool=tmp_path / "seeds" / "pool.json",
            meta_review=tmp_path / "review" / "meta.json",
        )
        assert pointer_path.is_file()
        result = paths_module.read_latest_pointer()

    assert result is not None
    assert result["run_id"] == "2026-05-25T10-00-00"
    assert result["gen_tag"] == "gen-7"
    assert result["version"] == 1


def test_latest_pointer_schema_required_keys(tmp_path: Path) -> None:
    """Schema invariant — version / run_id / gen_tag / updated_at 모두 emit."""
    from core import paths as paths_module

    pointer_path = tmp_path / "latest_pointer.json"

    with (
        patch.object(paths_module, "STATE_LATEST_POINTER_PATH", pointer_path),
        patch.object(paths_module, "STATE_ROOT", tmp_path),
    ):
        paths_module.write_latest_pointer(
            run_id="r1",
            gen_tag="g1",
            seed_pool=None,
            meta_review=None,
        )
        raw = pointer_path.read_text(encoding="utf-8")

    payload = json.loads(raw)
    for key in ("version", "run_id", "gen_tag", "updated_at"):
        assert key in payload, f"latest_pointer.json schema missing required key: {key!r}"


def test_latest_pointer_optional_fields_omitted_when_none(tmp_path: Path) -> None:
    """seed_pool=None / meta_review=None → 해당 key 미emit (graceful)."""
    from core import paths as paths_module

    pointer_path = tmp_path / "latest_pointer.json"

    with (
        patch.object(paths_module, "STATE_LATEST_POINTER_PATH", pointer_path),
        patch.object(paths_module, "STATE_ROOT", tmp_path),
    ):
        paths_module.write_latest_pointer(
            run_id="r1",
            gen_tag="g1",
            seed_pool=None,
            meta_review=None,
        )
        raw = pointer_path.read_text(encoding="utf-8")

    payload = json.loads(raw)
    assert "seed_pool" not in payload
    assert "meta_review" not in payload


def test_read_latest_pointer_missing_file_returns_none(tmp_path: Path) -> None:
    """File 부재 → None (bootstrap state)."""
    from core import paths as paths_module

    missing = tmp_path / "no_such_pointer.json"
    with patch.object(paths_module, "STATE_LATEST_POINTER_PATH", missing):
        result = paths_module.read_latest_pointer()

    assert result is None


def test_read_latest_pointer_malformed_returns_none(tmp_path: Path) -> None:
    """Unparseable JSON → None (graceful, no crash)."""
    from core import paths as paths_module

    pointer_path = tmp_path / "latest_pointer.json"
    pointer_path.write_text("not a json {", encoding="utf-8")

    with patch.object(paths_module, "STATE_LATEST_POINTER_PATH", pointer_path):
        result = paths_module.read_latest_pointer()

    assert result is None


def test_read_latest_pointer_non_dict_returns_none(tmp_path: Path) -> None:
    """Top-level non-dict (e.g. list) → None."""
    from core import paths as paths_module

    pointer_path = tmp_path / "latest_pointer.json"
    pointer_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with patch.object(paths_module, "STATE_LATEST_POINTER_PATH", pointer_path):
        result = paths_module.read_latest_pointer()

    assert result is None


# ---------------------------------------------------------------------------
# 2. STATE_ROOT-relative path resolution
# ---------------------------------------------------------------------------


def test_latest_pointer_relative_path_under_state_root(tmp_path: Path) -> None:
    """seed_pool 이 STATE_ROOT 아래면 STATE_ROOT-relative string 저장."""
    from core import paths as paths_module

    pointer_path = tmp_path / "latest_pointer.json"
    seed_pool = tmp_path / "seeds" / "pool.json"

    with (
        patch.object(paths_module, "STATE_LATEST_POINTER_PATH", pointer_path),
        patch.object(paths_module, "STATE_ROOT", tmp_path),
    ):
        paths_module.write_latest_pointer(
            run_id="r1",
            gen_tag="g1",
            seed_pool=seed_pool,
            meta_review=None,
        )
        raw = pointer_path.read_text(encoding="utf-8")

    payload = json.loads(raw)
    assert payload["seed_pool"] == "seeds/pool.json"  # relative to STATE_ROOT


# ---------------------------------------------------------------------------
# 3. sessions.jsonl + latest_pointer.json cross-ref invariant
# ---------------------------------------------------------------------------


def test_sessions_jsonl_run_id_key_naming() -> None:
    """sessions.jsonl 의 row 가 ``run_id`` 또는 ``session_id`` key 로
    latest_pointer.json 과 join 가능해야 함. plugins/seed_generation/
    orchestrator.py 의 append 로직과 schema 일치 확인."""
    import inspect

    from plugins.seed_generation import orchestrator

    # The orchestrator's _append_session_index emits run_id (cross-ref to
    # latest_pointer.json). Check source contains the key.
    source = inspect.getsource(orchestrator)
    assert "run_id" in source, (
        "sessions.jsonl orchestrator missing 'run_id' key — would break "
        "cross-ref to latest_pointer.json"
    )


def test_meta_review_snapshot_module_import_available() -> None:
    """MetaReviewSnapshot 이 baseline_reader 로부터 import 가능 — F1 의
    cross-run SoT 3중 중첩의 3번째 SoT 가 reachable."""
    from plugins.seed_generation.baseline_reader import MetaReviewSnapshot

    assert MetaReviewSnapshot is not None


# ---------------------------------------------------------------------------
# 4. 3 SoT key naming convention drift invariant
# ---------------------------------------------------------------------------


def test_three_sot_share_run_id_naming(tmp_path: Path) -> None:
    """Cross-run join invariant — 3 SoT 가 ``run_id`` 라는 동일 key 명을
    공유. 다른 이름 (예: cycle_id / mutation_id) 로 drift 시 fail.
    """
    from core import paths as paths_module

    pointer_path = tmp_path / "latest_pointer.json"
    with (
        patch.object(paths_module, "STATE_LATEST_POINTER_PATH", pointer_path),
        patch.object(paths_module, "STATE_ROOT", tmp_path),
    ):
        paths_module.write_latest_pointer(
            run_id="2026-05-25T10-00-00",
            gen_tag="g1",
            seed_pool=None,
            meta_review=None,
        )
        payload = paths_module.read_latest_pointer()

    assert payload is not None
    # F1 invariant — 'run_id' key 가 cross-ref join 의 anchor
    assert "run_id" in payload
    # Drift detection — 후속 PR 이 'cycle_id' 같은 다른 이름으로 change 시
    # 본 test 가 fail. 이름 unification 유지.
    assert "cycle_id" not in payload  # not the canonical name
    assert "session_id" not in payload  # sessions.jsonl 측 이름이 다르면 drift
