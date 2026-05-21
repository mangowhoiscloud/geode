"""Few-shot exemplar pool reader + applier — ADR-012 M3.

S5 의 ``exemplars`` slot 의 실제 *적재 메커니즘*. fitness gate 통과한
task-completion candidate 의 ``(user_msg, assistant_msg, fitness_delta)``
triple 을 JSONL append-only 로 축적; runtime 에 top-K 선별해 messages
앞에 in-context exemplar pair 로 삽입.

**SoT schema** (JSONL — 한 줄 = 한 exemplar):

.. code-block:: json

    {"user_msg": "...",
     "assistant_msg": "...",
     "fitness_delta": 0.12,
     "source": "audit_cycle_2026-05-21T0143"}

Field 정의:
- ``user_msg`` (str, required) — user role message 의 content.
- ``assistant_msg`` (str, required) — assistant role의 successful response.
- ``fitness_delta`` (float, optional, default 0.0) — baseline 대비 향상폭
  (postive=개선). top-K rank 의 ordering key.
- ``source`` (str, optional) — 추적용 메타.

**Resolution order** (PR-BACKFILL-SOT 2026-05-21 shared chain):

1. ``GEODE_FEW_SHOT_POOL_OVERRIDE`` env var — explicit override.
   - With ``GEODE_FEW_SHOT_POOL_STRICT=1`` (audit subprocess): strict.
   - Without strict flag: graceful (no fall-through).
2. ``~/.geode/self-improving-loop/few-shot-pool.jsonl`` — operator-local.
3. ``autoresearch/state/policies/few-shot-pool.jsonl`` — in-repo.
4. ``None`` — no-op.

**Frontier**: Anthropic prompt caching docs — 동일 prefix 의 multi-turn
exemplar 가 cache 적중률 높음. T5 의 cache_policy 와 자연스럽게 호환
(exemplar block 이 cache_control breakpoint 의 stable prefix 가 됨).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import (
    GLOBAL_FEW_SHOT_POOL_PATH,
    OPERATOR_LOCAL_FEW_SHOT_POOL_PATH,
)
from core.self_improving_loop.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

_FEW_SHOT_POOL_OVERRIDE_ENV = "GEODE_FEW_SHOT_POOL_OVERRIDE"

_FEW_SHOT_POOL_SOT_PATH = GLOBAL_FEW_SHOT_POOL_PATH
"""Cross-process in-repo SoT path (M3, 2026-05-21). Module-local alias."""

_OPERATOR_LOCAL_FEW_SHOT_POOL_PATH = OPERATOR_LOCAL_FEW_SHOT_POOL_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""


@dataclass(frozen=True)
class FewShotExemplar:
    """Single exemplar entry — frozen so callers can pass through safely."""

    user_msg: str
    assistant_msg: str
    fitness_delta: float = 0.0
    source: str = ""


def _load_few_shot_pool_override() -> list[FewShotExemplar] | None:
    """Return the active exemplar list (rank-by fitness_delta desc), or
    ``None`` if no SoT applies."""
    selection = resolve_sot(
        env_var=_FEW_SHOT_POOL_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_FEW_SHOT_POOL_PATH,
        in_repo=_FEW_SHOT_POOL_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> list[FewShotExemplar]:
    if not path.is_file():
        raise RuntimeError(f"{_FEW_SHOT_POOL_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"{_FEW_SHOT_POOL_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    return _parse_jsonl(raw, path, strict=True)


def _graceful_load(path: Path) -> list[FewShotExemplar] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        log.warning("few-shot-pool at %s is unreadable; ignoring", path)
        return None
    return _parse_jsonl(raw, path, strict=False)


def _parse_jsonl(raw: str, path: Path, *, strict: bool) -> list[FewShotExemplar]:
    """Parse JSONL line-by-line — per-line graceful (one bad line doesn't
    invalidate the rest)."""
    exemplars: list[FewShotExemplar] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            if strict:
                raise RuntimeError(
                    f"few-shot-pool at {path}:{lineno} JSON decode failed: {exc}"
                ) from exc
            log.warning(
                "few-shot-pool at %s:%d JSON decode failed; skipping line: %s",
                path,
                lineno,
                exc,
            )
            continue
        coerced = _coerce_entry(entry, path, lineno, strict=strict)
        if coerced is not None:
            exemplars.append(coerced)
    return exemplars


def _coerce_entry(entry: Any, path: Path, lineno: int, *, strict: bool) -> FewShotExemplar | None:
    if not isinstance(entry, dict):
        msg = f"few-shot-pool at {path}:{lineno} must be a dict, got {type(entry).__name__}"
        if strict:
            raise RuntimeError(msg)
        log.warning("%s; skipping", msg)
        return None
    user_msg = entry.get("user_msg")
    assistant_msg = entry.get("assistant_msg")
    if not isinstance(user_msg, str) or not user_msg:
        if strict:
            raise RuntimeError(f"few-shot-pool at {path}:{lineno} missing/invalid user_msg")
        return None
    if not isinstance(assistant_msg, str) or not assistant_msg:
        if strict:
            raise RuntimeError(f"few-shot-pool at {path}:{lineno} missing/invalid assistant_msg")
        return None
    raw_delta = entry.get("fitness_delta", 0.0)
    try:
        fitness_delta = float(raw_delta) if not isinstance(raw_delta, bool) else 0.0
    except (TypeError, ValueError):
        fitness_delta = 0.0
    source_raw = entry.get("source", "")
    source = source_raw if isinstance(source_raw, str) else ""
    return FewShotExemplar(
        user_msg=user_msg,
        assistant_msg=assistant_msg,
        fitness_delta=fitness_delta,
        source=source,
    )


def apply_few_shot_pool(
    messages: list[dict[str, Any]],
    pool: list[FewShotExemplar] | None,
    *,
    max_entries: int = 3,
) -> list[dict[str, Any]]:
    """Insert top-K exemplar (user/assistant) pairs at the head of ``messages``.

    Returns a new list (no in-place mutation). When ``pool is None`` or
    empty / ``max_entries <= 0``, returns the original list unchanged.

    Top-K selection ranks by ``fitness_delta`` descending. Ties tolerate
    insertion order (stable sort).
    """
    if not pool or max_entries <= 0:
        return messages
    ranked = sorted(pool, key=lambda e: -e.fitness_delta)[:max_entries]
    if not ranked:
        return messages
    prefix: list[dict[str, Any]] = []
    for ex in ranked:
        prefix.append({"role": "user", "content": ex.user_msg})
        prefix.append({"role": "assistant", "content": ex.assistant_msg})
    return prefix + list(messages)


__all__ = ["FewShotExemplar", "apply_few_shot_pool"]
