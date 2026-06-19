"""Append-only MANIFEST of petri ``.eval`` archives.

`~/.geode/petri/logs/*.eval` is out-of-git (large + PII). The matching
``docs/audits/eval-logs/*.summary.yaml`` is committed but only carries
per-eval metadata — there is no cross-session index telling you which
seed_id ran in which archive at which time. `geode history` cannot
answer "show me every petri audit that ran the
``helpful_only_model_harmful_task`` seed last month" without this index.

This module writes a single ``MANIFEST.jsonl`` (append-only, one line
per ``.eval``) under ``docs/audits/eval-logs/`` that captures the
small, stable facts about each archive: sha, timing, model roles,
seed ids, and per-role token totals. The runner appends after every
``geode audit --live`` and a one-shot retro-fit script populates the
file from existing ``~/.geode/petri/logs/`` entries.

Idempotent — :func:`append_manifest` skips an eval whose archive_sha
is already present, so re-running the retrofit is safe.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.memory.atomic_write import iter_jsonl, read_jsonl

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "append_manifest",
    "extract_manifest_entry",
    "has_archive",
    "read_manifest",
]

#: Committable manifest path (relative to repo root).
DEFAULT_MANIFEST_PATH: Path = Path("docs/audits/eval-logs/MANIFEST.jsonl")


def _sha1_file(path: Path) -> str:
    """Compute sha1 of a file's bytes — collision-safe id for the archive
    even when filename collides (same date, different audit).
    """
    h = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _basename_model(model_id: str) -> str:
    """Strip ``provider/`` prefix so the manifest stays compact."""
    return model_id.rsplit("/", 1)[-1] if model_id else ""


def _compact_usage(usage: Any) -> dict[str, int]:
    """Reduce ``inspect_ai.model.ModelUsage`` to the four token classes
    we care about for cross-session comparison.
    """
    return {
        "in": int(getattr(usage, "input_tokens", 0) or 0),
        "out": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_w": int(getattr(usage, "input_tokens_cache_write", 0) or 0),
        "cache_r": int(getattr(usage, "input_tokens_cache_read", 0) or 0),
    }


def extract_manifest_entry(
    eval_path: Path | str,
    *,
    summary_yaml: Path | str | None = None,
) -> dict[str, Any]:
    """Read an ``.eval`` header and build the JSONL line dict.

    Raises ``ImportError`` when ``inspect_ai`` is not installed (the
    caller is expected to guard for the optional ``[audit]`` extra).
    Raises ``FileNotFoundError`` when the eval is missing.
    """
    from inspect_ai.log import read_eval_log

    path = Path(eval_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"eval file not found: {path}")

    elog = read_eval_log(str(path), header_only=True)

    entry: dict[str, Any] = {
        "archive": path.name,
        "archive_sha": _sha1_file(path),
    }
    if summary_yaml is not None:
        entry["summary_yaml"] = Path(summary_yaml).name

    entry["status"] = str(getattr(elog, "status", "") or "")
    entry["task"] = str(getattr(elog.eval, "task", "") or "inspect_petri/audit")

    # Sample count + seed_ids — ``header_only=True`` empties ``log.samples``
    # but ``log.eval.dataset.samples`` / ``.sample_ids`` are populated
    # because they describe the input plan, not the per-sample output.
    dataset = getattr(elog.eval, "dataset", None)
    sample_count: int | None = None
    if dataset is not None:
        n = getattr(dataset, "samples", None)
        if isinstance(n, int):
            sample_count = n
        sample_ids = getattr(dataset, "sample_ids", None) or []
        seed_ids = [str(s) for s in sample_ids if s]
        if seed_ids:
            entry["seed_ids"] = seed_ids
    if sample_count is None:
        results = getattr(elog, "results", None)
        n = getattr(results, "total_samples", None) if results is not None else None
        if isinstance(n, int):
            sample_count = n
    entry["samples"] = sample_count if sample_count is not None else 0

    started = str(getattr(elog.eval, "created", "") or "")
    if started:
        entry["started_at"] = started
    completed = str(getattr(elog.stats, "completed_at", "") or "")
    if completed:
        entry["completed_at"] = completed

    model_roles = getattr(elog.eval, "model_roles", None) or {}
    models: dict[str, str] = {}
    role_to_model_id: dict[str, str] = {}
    for role, cfg in model_roles.items():
        model_id = getattr(cfg, "model", None) or str(cfg)
        if model_id:
            models[str(role)] = _basename_model(str(model_id))
            role_to_model_id[str(role)] = str(model_id)
    if models:
        entry["models"] = models

    role_usage = dict(getattr(elog.stats, "role_usage", None) or {})

    # Defect B-4 fallback — `inspect_ai` occasionally fails to fold a
    # judge `ModelEvent.output.usage` into `stats.role_usage` (race
    # in the scoring path). When a role declared in `eval.model_roles`
    # is missing from `role_usage`, re-aggregate from `sample.events`
    # so the manifest's `role_usage_summary` stays complete.
    expected_roles = set(role_to_model_id.keys())
    present_roles = {str(r) for r in role_usage}
    missing_roles = expected_roles - present_roles
    if missing_roles:
        missing_models = {role_to_model_id[r] for r in missing_roles}
        recovered = _walk_events_for_missing_roles(path, missing_roles, role_to_model_id)
        for role_name, synth in recovered.items():
            role_usage[role_name] = synth
        log.info(
            "manifest: B-4 fallback for %s — recovered roles %s from events",
            path.name,
            sorted(recovered.keys()),
        )
        # Even if recovery yields nothing, log the missing_models so a
        # debugger can spot the scoring-race archives.
        if not recovered:
            log.warning(
                "manifest: B-4 fallback for %s — no ModelEvent for missing models %s",
                path.name,
                sorted(missing_models),
            )

    if role_usage:
        entry["role_usage_summary"] = {
            str(role): _compact_usage(usage) for role, usage in role_usage.items()
        }

    return entry


@dataclass
class _SyntheticUsage:
    """Stand-in for ``inspect_ai.model.ModelUsage`` built from event
    aggregation when ``stats.role_usage`` misses a role (Defect B-4).
    Mirrors :class:`core.audit.eval_to_jsonl._SyntheticUsage` — kept
    independent so neither module imports from the other.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    input_tokens_cache_write: int = 0
    input_tokens_cache_read: int = 0
    reasoning_tokens: int = 0


def _walk_events_for_missing_roles(
    eval_path: Path,
    missing_roles: set[str],
    role_to_model_id: dict[str, str],
) -> dict[str, _SyntheticUsage]:
    """Re-read the eval with ``header_only=False`` and aggregate
    ``ModelEvent.output.usage`` for each missing role.

    Returns ``{role_name: _SyntheticUsage}`` for every role whose
    declared model produced at least one ``ModelEvent``. Empty when
    inspect_ai can't read the file or no events match.
    """
    from inspect_ai.log import read_eval_log

    try:
        elog_full = read_eval_log(str(eval_path))
    except Exception:
        log.warning("manifest: B-4 fallback re-read failed for %s", eval_path, exc_info=True)
        return {}

    # role-name → model-id (from manifest) reversed so we can match on
    # the ModelEvent.model field which carries the full provider id.
    model_to_role = {role_to_model_id[r]: r for r in missing_roles if r in role_to_model_id}
    totals: dict[str, _SyntheticUsage] = {}
    for sample in getattr(elog_full, "samples", None) or []:
        for event in getattr(sample, "events", None) or []:
            if type(event).__name__ != "ModelEvent":
                continue
            model_id = getattr(event, "model", "") or ""
            role_name = model_to_role.get(model_id)
            if role_name is None:
                continue
            output = getattr(event, "output", None)
            usage = getattr(output, "usage", None) if output is not None else None
            if usage is None:
                continue
            row = totals.setdefault(role_name, _SyntheticUsage())
            row.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            row.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
            row.input_tokens_cache_write += int(getattr(usage, "input_tokens_cache_write", 0) or 0)
            row.input_tokens_cache_read += int(getattr(usage, "input_tokens_cache_read", 0) or 0)
            row.reasoning_tokens += int(getattr(usage, "reasoning_tokens", 0) or 0)
    return totals


def append_manifest(
    eval_path: Path | str,
    *,
    summary_yaml: Path | str | None = None,
    manifest_path: Path | str | None = None,
    skip_if_present: bool = True,
) -> dict[str, Any] | None:
    """Read an ``.eval`` header and append one JSONL line.

    Returns the entry dict on success, ``None`` when:

    - ``inspect_ai`` is not installed (default ``uv sync`` env)
    - the eval is missing
    - ``skip_if_present`` and the archive_sha is already in the manifest

    All failures are logged at WARNING and re-raised only for
    programmer errors (TypeError). Audit failures never propagate from
    a bookkeeping path.
    """
    try:
        entry = extract_manifest_entry(eval_path, summary_yaml=summary_yaml)
    except ImportError:
        log.debug("inspect_ai not installed — append_manifest is a no-op")
        return None
    except FileNotFoundError:
        log.warning("append_manifest: %s does not exist", eval_path)
        return None
    except Exception:
        log.warning("append_manifest: failed to extract entry from %s", eval_path, exc_info=True)
        return None

    target = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    if skip_if_present and has_archive(entry["archive_sha"], manifest_path=target):
        log.debug("append_manifest: archive_sha already present — skipping %s", entry["archive"])
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return entry


def has_archive(archive_sha: str, *, manifest_path: Path | str | None = None) -> bool:
    """Return True when the manifest already records this archive_sha."""
    if not archive_sha:
        return False
    target = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    return any(row.get("archive_sha") == archive_sha for row in iter_jsonl(target))


def read_manifest(manifest_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return all manifest entries as a list of dicts. Empty when missing."""
    target = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    return read_jsonl(target)


def parse_started_ts(entry: dict[str, Any]) -> float | None:
    """Convenience — ``started_at`` ISO8601 string → unix epoch float.

    Returns ``None`` when the field is missing or unparseable.
    """
    s = entry.get("started_at", "")
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None
