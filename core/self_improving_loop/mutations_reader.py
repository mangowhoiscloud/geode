"""C.2 (2026-05-25) — mutations.jsonl reader (history access for mutator + meta-judge).

``mutations.jsonl`` 은 self-improving loop 의 single-ledger SoT — apply row
(``kind="applied"`` / ``"applied_sibling"``) + attribution row
(``kind="attribution"``) 가 한 file 에 row-append. 본 module 이전엔 writer
(``runner.append_mutation`` / ``attribution.write_attribution``) 만 있고
reader 부재 — F3 신호 (mutator 가 자기 history 를 못 봄 → repetitive mutation
위험) + meta-judge (A.5, PR-13) 의 prereq.

본 module 은 **read-only iterator + type-safe filter**:

- :func:`iter_mutations` — kind filter + limit 지원, malformed row graceful skip
- :func:`read_recent_attributions` — N 최근 attribution row 만
- :func:`read_recent_applies` — N 최근 apply row 만 (sibling 포함/제외)

Pydantic 검증으로 schema drift fail-fast. ``extra="allow"`` 라 legacy /
future-added field 도 호환.

Path: ``core/paths.MUTATION_AUDIT_LOG_PATH`` 기본. caller 가 다른 path 지정
가능 (test fixture / 다른 worktree audit log).
"""

from __future__ import annotations

import json as _json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from core.paths import MUTATION_AUDIT_LOG_PATH
from core.self_improving_loop.attribution import AttributionRecord
from core.self_improving_loop.runner import ApplyRecord

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)


_KINDS_APPLY: frozenset[str] = frozenset({"applied", "applied_sibling"})
_KINDS_ATTRIBUTION: frozenset[str] = frozenset({"attribution"})


def _parse_row(raw: str) -> ApplyRecord | AttributionRecord | None:
    """Parse one JSONL line. Returns ``None`` on malformed / unknown kind.

    Discriminator: top-level ``kind`` field. ``applied`` / ``applied_sibling``
    → ApplyRecord, ``attribution`` → AttributionRecord. 다른 kind 는 future-
    proof skip (log.debug 만).
    """
    raw_strip = raw.strip()
    if not raw_strip:
        return None
    try:
        payload = _json.loads(raw_strip)
    except _json.JSONDecodeError as exc:
        log.warning("mutations_reader: malformed JSON line skipped (%s)", exc)
        return None
    if not isinstance(payload, dict):
        log.warning("mutations_reader: non-dict row skipped (type=%s)", type(payload).__name__)
        return None
    kind = payload.get("kind", "applied")
    try:
        if kind in _KINDS_APPLY:
            return ApplyRecord.model_validate(payload)
        if kind in _KINDS_ATTRIBUTION:
            return AttributionRecord.model_validate(payload)
    except ValidationError as exc:
        log.warning(
            "mutations_reader: schema-invalid row skipped (kind=%s mutation_id=%s err=%s)",
            kind,
            payload.get("mutation_id", "?"),
            exc.errors()[0]["msg"] if exc.errors() else "<unknown>",
        )
        return None
    log.debug("mutations_reader: unknown kind=%r skipped", kind)
    return None


def iter_mutations(
    path: Path | None = None,
    *,
    kinds: Iterable[str] | None = None,
    limit: int | None = None,
) -> Iterator[ApplyRecord | AttributionRecord]:
    """Yield validated rows from ``mutations.jsonl`` (file or empty if absent).

    Parameters
    ----------
    path
        JSONL file. Default = ``MUTATION_AUDIT_LOG_PATH``.
    kinds
        Iterable of kind strings to keep (``"applied"`` / ``"applied_sibling"``
        / ``"attribution"``). ``None`` = all kinds.
    limit
        Max rows to yield (post-filter). ``None`` = unlimited.

    File 부재 → 빈 iterator (caller 가 attribution.jsonl 없는 fresh repo
    에서 graceful 동작). Malformed / schema-invalid row 는 warning + skip
    (이미 운영 중인 long-running loop 에서 1 row 손상이 reader 전체를
    abort 시키면 안 됨).
    """
    target = path if path is not None else MUTATION_AUDIT_LOG_PATH
    if not target.exists():
        return
    kind_filter: frozenset[str] | None = frozenset(kinds) if kinds is not None else None
    emitted = 0
    with target.open("r", encoding="utf-8") as fh:
        for line in fh:
            record = _parse_row(line)
            if record is None:
                continue
            if kind_filter is not None and record.kind not in kind_filter:
                continue
            yield record
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def read_recent_attributions(
    n: int = 10,
    path: Path | None = None,
) -> list[AttributionRecord]:
    """Return the most-recent N attribution rows (newest last in file order).

    JSONL 은 append-only 이므로 file 의 마지막 N 행이 최근 N 회 attribution.
    Pre-PR-5 file 에는 attribution row 자체가 없을 수 있음 → 빈 list 반환
    (graceful, meta-judge caller 가 빈 list 시 skip).
    """
    if n <= 0:
        raise ValueError(f"n must be >= 1, got {n}")
    rows = [
        r for r in iter_mutations(path, kinds={"attribution"}) if isinstance(r, AttributionRecord)
    ]
    return rows[-n:]


def read_recent_applies(
    n: int = 10,
    path: Path | None = None,
    *,
    include_siblings: bool = False,
) -> list[ApplyRecord]:
    """Return the most-recent N apply rows.

    Parameters
    ----------
    n
        Number of recent rows to return.
    include_siblings
        ``False`` (default) → ``kind="applied"`` only (top-1 채택). ``True``
        → ``applied_sibling`` (group 의 non-best, in-memory only) 포함 — group
        statistic 재구성 / repetitive-mutation 검사용.
    """
    if n <= 0:
        raise ValueError(f"n must be >= 1, got {n}")
    kinds = {"applied", "applied_sibling"} if include_siblings else {"applied"}
    rows = [r for r in iter_mutations(path, kinds=kinds) if isinstance(r, ApplyRecord)]
    return rows[-n:]


__all__ = [
    "ApplyRecord",
    "AttributionRecord",
    "iter_mutations",
    "read_recent_applies",
    "read_recent_attributions",
]
