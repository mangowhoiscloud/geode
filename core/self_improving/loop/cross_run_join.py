"""C.6 (2026-05-25) — cross-run SoT 3중첩 unification (PR-26).

Memory ``project_autoresearch_fragmentation_audit.md`` F1 — 3 SoT
(``latest_pointer.json`` / ``MetaReviewSnapshot`` / ``sessions.jsonl``)
의 cross-ref key (run_id + gen_tag) 가 각자 다른 reader 로 접근. PR-22
가 invariant test 만 추가 (schema parity pin). C.6 는 그 다음 단계 —
**한 dataclass + 단일 reader** 로 unification.

본 module = **selection-only helper**:

- :class:`CrossRunJoinKey` — Pydantic schema, 3 SoT 의 공통 join key
- :func:`load_cross_run_join_key()` — latest_pointer.json 으로부터
  추출. file 부재/malformed → None (graceful).
- :func:`keys_match(a, b)` — run_id + gen_tag 모두 일치 시 True.
- :func:`compose_history_view(key, sessions_iter)` — sessions.jsonl
  iterator 에서 key 일치 row 만 필터.

3 SoT 의 join 책임을 한 곳에 모음 — caller 가 lookup 위치 모르거나
schema 변경 시 한 곳만 update.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class CrossRunJoinKey(BaseModel):
    """3 SoT 의 공통 cross-ref key.

    ``run_id`` + ``gen_tag`` pair 가 unique join anchor. 같은 ``run_id``
    의 다른 ``gen_tag`` (예: rerun) 는 별 row.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    run_id: str
    gen_tag: str
    source_label: str = ""
    """어느 SoT 에서 추출됐는지 — ``latest_pointer`` / ``sessions`` /
    ``meta_review`` 중 하나. drift detection 시 출처 추적용."""


def load_cross_run_join_key(
    latest_pointer_path: Path | None = None,
) -> CrossRunJoinKey | None:
    """Load the current cross-run join key from ``latest_pointer.json``.

    Returns ``None`` when:

    - The pointer file is missing (fresh repo / no run yet).
    - The pointer JSON is malformed.
    - The pointer payload lacks ``run_id`` or ``gen_tag``.

    Caller can use this key to look up matching rows in
    ``sessions.jsonl`` or ``meta_review`` snapshots.
    """
    from core.paths import read_latest_pointer

    if latest_pointer_path is not None:
        # Test injection — read directly from the provided path
        import json as _json

        if not latest_pointer_path.is_file():
            return None
        try:
            payload = _json.loads(latest_pointer_path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            return None
    else:
        payload = read_latest_pointer()

    if not isinstance(payload, dict):
        return None
    run_id = payload.get("run_id")
    gen_tag = payload.get("gen_tag")
    if not isinstance(run_id, str) or not isinstance(gen_tag, str):
        return None
    return CrossRunJoinKey(run_id=run_id, gen_tag=gen_tag, source_label="latest_pointer")


def keys_match(a: CrossRunJoinKey | None, b: CrossRunJoinKey | None) -> bool:
    """Two keys match when both run_id and gen_tag are equal.

    ``None`` on either side → False (no signal). source_label is
    ignored — keys from different SoTs match by value.
    """
    if a is None or b is None:
        return False
    return a.run_id == b.run_id and a.gen_tag == b.gen_tag


def compose_history_view(
    key: CrossRunJoinKey,
    rows: Iterable[Any],
) -> Iterator[dict[str, Any]]:
    """Filter an iterable of session/meta-review rows to those matching
    ``key`` (same run_id + gen_tag).

    Each row must be a dict with ``run_id`` and ``gen_tag`` string
    values; rows that are non-dict or missing either field are skipped
    silently (forward-compat: older rows may lack one of the two
    fields; defensive against malformed iterables).
    """
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_run_id = row.get("run_id")
        row_gen_tag = row.get("gen_tag")
        if not isinstance(row_run_id, str) or not isinstance(row_gen_tag, str):
            continue
        if row_run_id == key.run_id and row_gen_tag == key.gen_tag:
            yield row


__all__ = [
    "CrossRunJoinKey",
    "compose_history_view",
    "keys_match",
    "load_cross_run_join_key",
]
