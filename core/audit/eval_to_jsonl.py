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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.usage_store import UsageStore

log = logging.getLogger(__name__)

__all__ = ["extract_to_usage_store"]


@dataclass
class _SyntheticUsage:
    """Stand-in for ``inspect_ai.model.ModelUsage`` built from the
    sample event stream when ``stats.model_usage`` misses a role
    (Defect B-4 race). Matches the attribute names the main extraction
    path reads via ``getattr`` so the downstream code is shape-agnostic.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    input_tokens_cache_write: int = 0
    input_tokens_cache_read: int = 0
    reasoning_tokens: int = 0
    total_cost: float | None = None


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


def _walk_events_for_missing_models(
    eval_path: Path,
    missing_models: set[str],
) -> dict[str, dict[str, int]]:
    """Defect B-4 fallback — re-read the eval with ``header_only=False``
    and aggregate ``ModelEvent.output.usage`` for each missing model.

    Returns ``{model_id: {input_tokens, output_tokens,
    input_tokens_cache_write, input_tokens_cache_read,
    reasoning_tokens}}`` keyed by the model id (with provider prefix
    preserved). Empty when ``inspect_ai`` cannot read the file or no
    ``ModelEvent`` for the missing models exists.

    inspect_ai's scoring path occasionally fails to fold a judge
    ``ModelEvent.output.usage`` into ``stats.model_usage`` /
    ``stats.role_usage`` — 8 archives across the 5/11 session showed
    ~43% miss rate for the judge role (B-4 of the Defect B inventory).
    The event itself is always present though, so re-aggregating from
    the event stream produces the correct totals.
    """
    from inspect_ai.log import read_eval_log

    try:
        elog_full = read_eval_log(str(eval_path))
    except Exception:
        log.warning("eval_to_jsonl: B-4 fallback failed for %s", eval_path, exc_info=True)
        return {}

    totals: dict[str, dict[str, int]] = {}
    for sample in getattr(elog_full, "samples", None) or []:
        for event in getattr(sample, "events", None) or []:
            if type(event).__name__ != "ModelEvent":
                continue
            model_id = getattr(event, "model", "") or ""
            if model_id not in missing_models:
                continue
            output = getattr(event, "output", None)
            usage = getattr(output, "usage", None) if output is not None else None
            if usage is None:
                continue
            row = totals.setdefault(
                model_id,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "input_tokens_cache_write": 0,
                    "input_tokens_cache_read": 0,
                    "reasoning_tokens": 0,
                },
            )
            row["input_tokens"] += int(getattr(usage, "input_tokens", 0) or 0)
            row["output_tokens"] += int(getattr(usage, "output_tokens", 0) or 0)
            row["input_tokens_cache_write"] += int(
                getattr(usage, "input_tokens_cache_write", 0) or 0
            )
            row["input_tokens_cache_read"] += int(getattr(usage, "input_tokens_cache_read", 0) or 0)
            row["reasoning_tokens"] += int(getattr(usage, "reasoning_tokens", 0) or 0)
    return totals


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
    - ``EvalStats.model_usage`` is empty AND no fallback path finds
      events to aggregate
    - ``skip_if_present`` and the ``eval_id`` is already in the JSONL

    Defect B-4 fallback: when a role declared in ``eval.model_roles``
    is missing from ``stats.model_usage`` (judge race), re-read with
    ``header_only=False`` and aggregate from the per-sample
    ``ModelEvent.output.usage`` stream. The event itself is always
    present even when the stats roll-up drops it.

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

    stats: dict[str, Any] = dict(getattr(elog.stats, "model_usage", None) or {})

    model_roles = getattr(elog.eval, "model_roles", None) or {}
    inverted: dict[str, str] = {}
    for role, cfg in model_roles.items():
        model_id = getattr(cfg, "model", None) or str(cfg)
        if model_id:
            inverted[str(model_id)] = str(role)

    # Defect B-4 fallback — re-aggregate missing models from sample
    # events. Only triggers when ``eval.model_roles`` declares a model
    # that ``stats.model_usage`` did not record; the common-case (all
    # roles present) stays on the cheap header_only path.
    expected_models = set(inverted.keys())
    present_models = {str(k) for k in stats}
    missing_models = expected_models - present_models
    if missing_models:
        log.info(
            "eval_to_jsonl: B-4 fallback for %s — stats missing %s, walking events",
            eval_id,
            sorted(missing_models),
        )
        events_totals = _walk_events_for_missing_models(path, missing_models)
        for model_id, totals in events_totals.items():
            stats[model_id] = _SyntheticUsage(**totals)

    if not stats:
        log.debug("eval_to_jsonl: %s has empty model_usage", eval_id)
        return 0

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
