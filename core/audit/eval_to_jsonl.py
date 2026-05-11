"""Extract token usage from a petri ``.eval`` archive into the GEODE
``~/.geode/usage/`` JSONL ledger.

inspect_ai's native ``AnthropicAPI`` / ``OpenAIAPI`` reach the provider
SDK directly — GEODE's TokenTracker sees zero calls when the audit's
judge / auditor models fire. Verified 2026-05-11 against the 5/11 live
archive: ``.eval`` ``role_usage`` shows judge + auditor token counts,
the same wall-clock minute in ``~/.geode/usage/2026-05.jsonl`` has zero
matching rows.

This module closes the gap by walking ``EvalStats.model_usage`` after
the eval completes and appending one ``source='petri_eval'`` JSONL row
per model with the role tag recovered from ``eval.model_roles``. Run
once per archive and idempotent (duplicate ``eval_id`` inserts are
skipped via :meth:`core.llm.usage_store.UsageStore.has_eval_id`).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.usage_store import UsageStore

log = logging.getLogger(__name__)

__all__ = ["extract_to_usage_store"]


def _basename(model_id: str) -> str:
    """Strip the inspect_ai provider prefix (``anthropic/`` etc.) so
    GEODE ``MODEL_PRICING`` lookup hits.
    """
    return model_id.rsplit("/", 1)[-1]


def _parse_eval_ts(created: Any) -> float | None:
    """Parse ``eval.created`` ISO8601 string → unix epoch float.

    Returns ``None`` when the string is missing or unparseable so the
    caller falls back to ``time.time()`` rather than stamping the row
    with epoch 0.
    """
    if not created:
        return None
    try:
        return datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def extract_to_usage_store(
    eval_path: Path | str,
    *,
    store: UsageStore | None = None,
    skip_if_present: bool = True,
) -> int:
    """Read a petri ``.eval`` header and append one row per model.

    Returns the number of rows actually written. Returns ``0`` (silent
    no-op) when:

    - ``inspect_ai`` is not installed (default ``uv sync`` env)
    - the eval file does not exist
    - ``EvalStats.model_usage`` is empty (eval cancelled before any LLM
      call landed)
    - ``skip_if_present`` and the ``eval_id`` is already in the JSONL

    Failures inside the read path are caught + logged at WARNING — a
    bookkeeping error must never fail the audit.
    """
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        log.debug("inspect_ai not installed — eval_to_jsonl is a no-op")
        return 0

    from core.llm.token_tracker import get_tracker
    from core.llm.usage_store import get_usage_store

    path = Path(eval_path).expanduser()
    if not path.is_file():
        log.warning("eval_to_jsonl: %s does not exist", path)
        return 0

    eval_id = path.name
    target_store: UsageStore = store if store is not None else get_usage_store()

    if skip_if_present and target_store.has_eval_id(eval_id):
        log.debug("eval_to_jsonl: skipping already-imported %s", eval_id)
        return 0

    try:
        elog = read_eval_log(str(path), header_only=True)
    except Exception:
        log.warning("eval_to_jsonl: failed to read %s", path, exc_info=True)
        return 0

    stats = getattr(elog.stats, "model_usage", None) or {}
    if not stats:
        log.debug("eval_to_jsonl: %s has empty model_usage", eval_id)
        return 0

    model_roles = getattr(elog.eval, "model_roles", None) or {}
    inverted: dict[str, str] = {}
    for role, cfg in model_roles.items():
        model_id = getattr(cfg, "model", None) or str(cfg)
        if model_id:
            inverted[str(model_id)] = str(role)

    eval_ts = _parse_eval_ts(getattr(elog.eval, "created", None))
    tracker = get_tracker()

    appended = 0
    for model_id, usage in stats.items():
        role = inverted.get(str(model_id), "")
        basename = _basename(str(model_id))
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        cache_w = int(getattr(usage, "input_tokens_cache_write", 0) or 0)
        cache_r = int(getattr(usage, "input_tokens_cache_read", 0) or 0)
        think = int(getattr(usage, "reasoning_tokens", 0) or 0)
        # Prefer inspect_ai's own total_cost when present; fall back to
        # GEODE MODEL_PRICING when the field is None or 0 (current
        # behaviour for both anthropic and openai providers as of
        # inspect_ai 0.3.220 — total_cost is unset in EvalStats).
        cost = float(getattr(usage, "total_cost", 0.0) or 0.0)
        if cost <= 0.0:
            cost = tracker.calculate_cost(
                basename,
                in_tok,
                out_tok,
                cache_creation_tokens=cache_w,
                cache_read_tokens=cache_r,
                thinking_tokens=think,
            )
        target_store.record(
            basename,
            in_tok,
            out_tok,
            cost,
            cache_creation_tokens=cache_w,
            cache_read_tokens=cache_r,
            thinking_tokens=think,
            role=role,
            source="petri_eval",
            eval_id=eval_id,
            ts=eval_ts,
        )
        appended += 1

    log.info(
        "eval_to_jsonl: imported %d rows from %s (roles=%s)",
        appended,
        eval_id,
        sorted(set(inverted.values())),
    )
    return appended
