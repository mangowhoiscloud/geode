"""In-context slot schema + reader — ADR-012 S5.

GEODE 의 agent 가 매 turn 마다 system prompt + tool messages 에 추가로
주입하는 dynamic context 의 **4 canonical slot category** 를 명시적
schema 로 선언. M4.4 후속 PR 이 이 schema 를 inference path 에서 소비.

**4 canonical slots**:

- ``exemplars`` — Petri / 사용자 task 성공 케이스. seed-generation 의
  Elo ranker 가 산출한 top-K. 동일 task family 에 대해 *"이렇게 하면
  성공"* 의 in-context demonstration.
- ``memory_recall`` — ``~/.geode/memory/`` 의 user/feedback/project/
  reference 4 type 중 현재 task 와 매칭되는 항목. recency × cosine
  similarity 로 rank.
- ``rubric_excerpts`` — Petri 17-dim 의 worst-regressed dim 의 rubric
  요약. baseline.json 의 worst dim → rubric → 해당 dim 의 *"이렇게
  하면 안됨"* directive.
- ``tool_hints`` — T1 tool_descriptions 의 ``hints`` field 와 다른,
  *최근 성공/실패* 에서 추출된 tool-specific 힌트. RunLog + episodic
  memory 의 success_rate 로 rank.

**SoT schema** (모든 slot optional, default = no-op):

.. code-block:: json

    {
      "exemplars": {
        "max_entries": 3,
        "rank_by": "elo_rating",
        "injection_point": "system_prompt"
      },
      "memory_recall": {
        "max_entries": 5,
        "rank_by": "recency",
        "injection_point": "system_prompt"
      },
      "rubric_excerpts": {
        "max_entries": 3,
        "rank_by": "regression_severity",
        "injection_point": "system_prompt"
      },
      "tool_hints": {
        "max_entries": 5,
        "rank_by": "success_rate",
        "injection_point": "tool_descriptions"
      }
    }

빈 정책 / 누락 slot → 해당 slot 비활성 (no-op). 부적합 schema 또는
unknown slot 은 graceful drop (forward-compat).

**Resolution order** (PR-BACKFILL-SOT 2026-05-21 shared chain):

1. ``GEODE_IN_CONTEXT_SLOTS_OVERRIDE`` env var — explicit override.
   - With ``GEODE_IN_CONTEXT_SLOTS_STRICT=1``: strict-fail.
   - Without strict flag: graceful (no fall-through).
2. ``~/.geode/self-improving-loop/in-context-slots.json`` — operator-local.
3. ``autoresearch/state/policies/in-context-slots.json`` — in-repo.
4. ``None`` — no-op.

**Frontier**: Frontier agent harnesses (Claude Code 의 system prompt,
Codex CLI 의 ``<system-reminder>``) 가 4 종 in-context wiring 을 모두
hardcoded layout 으로 보유. GEODE 는 그 layout 자체를 mutator 가
optimize 할 수 있도록 명시적 JSON schema 로 표면화.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import (
    GLOBAL_IN_CONTEXT_SLOTS_PATH,
    OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH,
)
from core.self_improving_loop.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

_IN_CONTEXT_SLOTS_OVERRIDE_ENV = "GEODE_IN_CONTEXT_SLOTS_OVERRIDE"

_IN_CONTEXT_SLOTS_SOT_PATH = GLOBAL_IN_CONTEXT_SLOTS_PATH
"""Cross-process in-repo SoT path (S5, 2026-05-21). Module-local alias."""

_OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH = OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""

# 5 canonical slot identifiers — 4 from the original ADR-012 S5 set
# plus ``tool_ranking`` (CL-A2, 2026-05-26) which complements
# ``tool_hints`` with the positive (success-side) signal.
SLOT_EXEMPLARS = "exemplars"
SLOT_MEMORY_RECALL = "memory_recall"
SLOT_RUBRIC_EXCERPTS = "rubric_excerpts"
SLOT_TOOL_HINTS = "tool_hints"
SLOT_TOOL_RANKING = "tool_ranking"

CANONICAL_SLOTS: tuple[str, ...] = (
    SLOT_EXEMPLARS,
    SLOT_MEMORY_RECALL,
    SLOT_RUBRIC_EXCERPTS,
    SLOT_TOOL_HINTS,
    SLOT_TOOL_RANKING,
)

# Valid ``injection_point`` choices — namespaces the system prompt
# assembly + tool-descriptions wiring expose. Constrained enum so a
# mutator's typo lands in graceful drop, not silent injection into
# the wrong section.
INJECTION_SYSTEM_PROMPT = "system_prompt"
INJECTION_TOOL_DESCRIPTIONS = "tool_descriptions"
VALID_INJECTION_POINTS: frozenset[str] = frozenset(
    {INJECTION_SYSTEM_PROMPT, INJECTION_TOOL_DESCRIPTIONS}
)


@dataclass(frozen=True)
class InContextSlot:
    """Per-slot configuration loaded from ``in-context-slots.json``.

    Frozen so a loaded snapshot is safe to pass through M4.4 's wiring
    layer without aliasing risk.
    """

    name: str
    max_entries: int
    rank_by: str
    injection_point: str


def _load_in_context_slots_override() -> dict[str, InContextSlot] | None:
    """Return the active slot configuration, or ``None`` if no SoT applies."""
    selection = resolve_sot(
        env_var=_IN_CONTEXT_SLOTS_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH,
        in_repo=_IN_CONTEXT_SLOTS_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> dict[str, InContextSlot]:
    if not path.is_file():
        raise RuntimeError(f"{_IN_CONTEXT_SLOTS_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_IN_CONTEXT_SLOTS_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    _validate_schema(data, path)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, InContextSlot] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("in-context-slots SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path)
    except RuntimeError as exc:
        log.warning("in-context-slots SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


def _validate_schema(data: Any, path: Path) -> None:
    """Top-level ``dict[str, dict]``; each entry must contain int + 2 str."""
    if not isinstance(data, dict):
        raise RuntimeError(f"in-context-slots at {path} must be a dict")
    for slot, entry in data.items():
        if not isinstance(slot, str):
            type_name = type(slot).__name__
            raise RuntimeError(f"in-context-slots at {path} key must be str, got {type_name}")
        if not isinstance(entry, dict):
            type_name = type(entry).__name__
            raise RuntimeError(
                f"in-context-slots at {path}[{slot!r}] must be dict, got {type_name}"
            )
        if "max_entries" in entry:
            v = entry["max_entries"]
            if not isinstance(v, int) or isinstance(v, bool):
                raise RuntimeError(f"in-context-slots at {path}[{slot!r}].max_entries must be int")
            # Negative range check is intentionally deferred to ``_coerce``
            # (per-axis graceful drop). Raising here would let one slot's
            # negative value discard the entire SoT via ``_graceful_load``
            # — contradicts the per-axis graceful claim. (Codex MCP catch,
            # PR #1425 FAIL #2.)
        if "rank_by" in entry and not isinstance(entry["rank_by"], str):
            raise RuntimeError(f"in-context-slots at {path}[{slot!r}].rank_by must be str")
        if "injection_point" in entry and not isinstance(entry["injection_point"], str):
            raise RuntimeError(f"in-context-slots at {path}[{slot!r}].injection_point must be str")


def _coerce(data: dict[str, Any]) -> dict[str, InContextSlot]:
    """Extract canonical slots with field defaults. Unknown slot dropped
    (forward-compat); unknown ``injection_point`` value dropped (per-axis
    graceful)."""
    result: dict[str, InContextSlot] = {}
    for slot in CANONICAL_SLOTS:
        if slot not in data:
            continue
        entry = data[slot]
        if not isinstance(entry, dict):
            continue
        max_entries = entry.get("max_entries", 0)
        if not isinstance(max_entries, int) or isinstance(max_entries, bool):
            continue
        if max_entries < 0:
            continue
        rank_by = entry.get("rank_by", "")
        if not isinstance(rank_by, str):
            continue
        injection_point = entry.get("injection_point", INJECTION_SYSTEM_PROMPT)
        if injection_point not in VALID_INJECTION_POINTS:
            log.warning(
                "in-context-slots[%r].injection_point=%r not in %s; dropping slot",
                slot,
                injection_point,
                sorted(VALID_INJECTION_POINTS),
            )
            continue
        result[slot] = InContextSlot(
            name=slot,
            max_entries=max_entries,
            rank_by=rank_by,
            injection_point=injection_point,
        )
    return result


__all__ = [
    "CANONICAL_SLOTS",
    "INJECTION_SYSTEM_PROMPT",
    "INJECTION_TOOL_DESCRIPTIONS",
    "SLOT_EXEMPLARS",
    "SLOT_MEMORY_RECALL",
    "SLOT_RUBRIC_EXCERPTS",
    "SLOT_TOOL_HINTS",
    "SLOT_TOOL_RANKING",
    "VALID_INJECTION_POINTS",
    "InContextSlot",
]
