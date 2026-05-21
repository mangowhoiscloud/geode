"""OL-C2 — few-shot pool writer invariants.

Pins:
- ``append_exemplar`` writes one JSONL row per call; reader round-trips.
- Idempotency: same ``(user_msg, assistant_msg)`` → no second write.
- FIFO eviction: pool > ``max_size`` drops oldest entries.
- Graceful: read/write OSError → False return, no raise.
- autoresearch/train.py promote step calls ``append_exemplar`` with
  ``source="autoresearch_audit_promote"`` only on PROMOTED audits.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def pool_path(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "pool.jsonl"


def _read_pool(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# Signature ---------------------------------------------------------------


def test_signature_deterministic() -> None:
    from core.llm.few_shot_pool import _exemplar_signature

    a = _exemplar_signature("q", "a")
    b = _exemplar_signature("q", "a")
    assert a == b
    assert len(a) == 16


def test_signature_differs_on_each_field() -> None:
    from core.llm.few_shot_pool import _exemplar_signature

    base = _exemplar_signature("q", "a")
    assert _exemplar_signature("q2", "a") != base
    assert _exemplar_signature("q", "a2") != base


# Writer core -------------------------------------------------------------


def test_append_writes_row(pool_path: Path) -> None:
    from core.llm.few_shot_pool import append_exemplar

    ok = append_exemplar(
        user_msg="explain DPO",
        assistant_msg="DPO trains preference-aligned models",
        fitness_delta=0.7,
        source="autoresearch_audit_promote",
        pool_path=pool_path,
    )
    assert ok is True
    rows = _read_pool(pool_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_msg"] == "explain DPO"
    assert row["assistant_msg"] == "DPO trains preference-aligned models"
    assert row["fitness_delta"] == 0.7
    assert row["source"] == "autoresearch_audit_promote"


def test_append_idempotent_on_duplicate(pool_path: Path) -> None:
    """Same (user, assistant) → second call returns False, no second row."""
    from core.llm.few_shot_pool import append_exemplar

    assert (
        append_exemplar(user_msg="q", assistant_msg="a", fitness_delta=0.5, pool_path=pool_path)
        is True
    )
    assert (
        append_exemplar(user_msg="q", assistant_msg="a", fitness_delta=0.9, pool_path=pool_path)
        is False
    )
    rows = _read_pool(pool_path)
    assert len(rows) == 1
    # First-write wins — fitness_delta stays 0.5
    assert rows[0]["fitness_delta"] == 0.5


def test_append_different_pairs_both_persist(pool_path: Path) -> None:
    from core.llm.few_shot_pool import append_exemplar

    append_exemplar(user_msg="q1", assistant_msg="a1", pool_path=pool_path)
    append_exemplar(user_msg="q2", assistant_msg="a2", pool_path=pool_path)
    rows = _read_pool(pool_path)
    assert len(rows) == 2
    assert {r["user_msg"] for r in rows} == {"q1", "q2"}


# Reader round-trip -------------------------------------------------------


def test_writer_reader_round_trip(pool_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """append_exemplar → _parse_jsonl reads it as a FewShotExemplar."""
    from core.llm.few_shot_pool import _parse_jsonl, append_exemplar

    append_exemplar(
        user_msg="q1",
        assistant_msg="a1",
        fitness_delta=0.42,
        source="autoresearch_audit_promote",
        pool_path=pool_path,
    )
    raw = pool_path.read_text(encoding="utf-8")
    exemplars = _parse_jsonl(raw, pool_path, strict=False)
    assert len(exemplars) == 1
    e = exemplars[0]
    assert e.user_msg == "q1"
    assert e.assistant_msg == "a1"
    assert e.fitness_delta == 0.42
    assert e.source == "autoresearch_audit_promote"


# FIFO eviction -----------------------------------------------------------


def test_fifo_eviction_when_over_cap(pool_path: Path) -> None:
    """max_size=3 + 5 inserts → only last 3 survive."""
    from core.llm.few_shot_pool import append_exemplar

    for i in range(5):
        append_exemplar(user_msg=f"q{i}", assistant_msg=f"a{i}", pool_path=pool_path, max_size=3)
    rows = _read_pool(pool_path)
    assert len(rows) == 3
    # Oldest dropped — q0, q1 evicted; q2, q3, q4 survive
    assert [r["user_msg"] for r in rows] == ["q2", "q3", "q4"]


def test_default_cap_constant() -> None:
    """Module constant exposed for callers + ratchet."""
    from core.llm.few_shot_pool import MAX_EXEMPLAR_POOL_SIZE

    assert MAX_EXEMPLAR_POOL_SIZE == 1000


# Graceful ----------------------------------------------------------------


def test_append_creates_parent_dir(tmp_path: Path) -> None:
    """Missing parent dir → created lazily."""
    from core.llm.few_shot_pool import append_exemplar

    nested = tmp_path / "subdir" / "deeper" / "pool.jsonl"
    assert not nested.parent.exists()
    ok = append_exemplar(user_msg="q", assistant_msg="a", pool_path=nested)
    assert ok is True
    assert nested.is_file()


def test_append_preserves_unicode(pool_path: Path) -> None:
    """Non-ASCII content survives (CJK / emoji edge case)."""
    from core.llm.few_shot_pool import append_exemplar

    append_exemplar(
        user_msg="안녕하세요 explain DPO",
        assistant_msg="DPO 는 preference 모델 학습 기법입니다",
        pool_path=pool_path,
    )
    raw = pool_path.read_text(encoding="utf-8")
    assert "안녕하세요" in raw
    assert "preference 모델" in raw


# autoresearch caller wiring (source check) -------------------------------


def test_train_py_imports_append_exemplar() -> None:
    """``autoresearch/train.py`` must contain the import + call after OL-C1."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    assert "from core.llm.few_shot_pool import append_exemplar" in train_py
    assert "append_exemplar(" in train_py
    assert 'source="autoresearch_audit_promote"' in train_py


def test_train_py_writer_gated_on_promote() -> None:
    """The writer call must be guarded by ``promoted_line`` check
    (rejected audits stay out of the pool)."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    # Pin the gate shape — args.dry_run skip + promoted_line truthy
    assert "not args.dry_run" in train_py
    assert '"true" in promoted_line.lower()' in train_py


def test_train_py_writer_wrapped_in_try_except() -> None:
    """Writer must be wrapped in try/except so audit cycle never breaks."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    pos = train_py.find("append_exemplar(")
    assert pos > 0
    preceding = train_py[max(0, pos - 1500) : pos]
    assert "try:" in preceding, "append_exemplar must be wrapped in try/except"


def test_train_py_writer_after_ol_c1_emit() -> None:
    """OL-C2 writer must come AFTER OL-C1 emit (same scope, post-promote)."""
    train_py = Path("autoresearch/train.py").read_text(encoding="utf-8")
    emit_pos = train_py.find("emit_eval_response_recorded(")
    append_pos = train_py.find("append_exemplar(")
    assert emit_pos > 0 and append_pos > 0
    assert append_pos > emit_pos
