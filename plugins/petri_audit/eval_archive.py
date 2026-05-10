"""Persist petri eval logs outside the worktree + extract a committable summary.

The ``inspect_ai`` ``logs/*.eval`` files are large (~50-300KB each) and
can carry transcript data we do not want in git. The default
``.gitignore`` excludes ``logs/`` for that reason. But because every
``geode audit --live`` lands its raw ``.eval`` *inside the active
worktree*, a routine ``git worktree remove`` after a merged PR silently
deletes the only copy of the audit's ground truth.

This module gives that ground truth two homes:

1. **Raw ``.eval`` archive**: copied to
   ``~/.geode/petri/logs/<basename>`` so the file survives worktree
   cleanup. OS-level only — no git touch.
2. **Summary YAML**: the audit's deterministic, PII-light metadata
   (sample ids, judge scores, ``stats.model_usage`` per role, status,
   total wall-time) extracted into ``docs/audits/eval-logs/<date>-
   <eval-hash>.summary.yaml``. Small, diffable, committable — feeds
   the cross-session comparison the audit reports lean on.

Both halves are idempotent: re-archiving an already-archived eval
overwrites the YAML (re-extract may pick up a fixed scorer) and
overwrites the raw copy (the copy is byte-identical).

Cross-version note: this module imports ``inspect_ai.log`` lazily so
the runner-side surface (``run_audit`` etc.) keeps loading on a default
``uv sync`` without the ``[audit]`` extra. ``archive_eval`` raises
``ImportError`` with the install hint if the extra is absent.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_RAW_ARCHIVE_DIR",
    "DEFAULT_SUMMARY_DIR",
    "ArchiveResult",
    "archive_eval",
    "extract_summary",
]

#: Worktree-independent raw archive. Out of git on purpose (PII / size).
DEFAULT_RAW_ARCHIVE_DIR: Path = Path("~/.geode/petri/logs").expanduser()

#: Committed summary directory under repo root.
DEFAULT_SUMMARY_DIR: Path = Path("docs/audits/eval-logs")


@dataclass(frozen=True)
class ArchiveResult:
    """Pair of paths produced by :func:`archive_eval`."""

    raw_path: Path
    """Where the raw ``.eval`` was copied. Out of git."""

    summary_path: Path
    """Where the YAML summary was written. Inside repo, committable."""

    summary: dict[str, Any]
    """The summary dict written to ``summary_path``. Returned for callers
    that want to log the headline finding without re-reading the file."""


def extract_summary(eval_path: Path) -> dict[str, Any]:
    """Read a petri ``.eval`` and produce a small dict suitable for YAML.

    Output shape:
        {
          "eval_file": "<basename>",
          "status": "success" | "error" | "started",
          "samples": int,
          "task": str,
          "models": {"auditor": str, "target": str, "judge": str},
          "stats": {
             "<model_id>": {
                "input_tokens": int, "output_tokens": int,
                "input_tokens_cache_write": int,
                "input_tokens_cache_read": int,
             },
             ...
          },
          "samples_summary": [
             {
               "id": str | int,
               "non_baseline_dims": {dim: score, ...},  # only score != 1.0
               "scored": bool,
             },
             ...
          ],
        }

    Requires ``[audit]`` extra (inspect_ai). Raises ``ImportError`` with
    install hint when the extra is missing.
    """
    try:
        from inspect_ai.log import read_eval_log
    except ImportError as exc:
        raise ImportError(
            "extract_summary requires the [audit] extra: `uv sync --extra audit`."
        ) from exc

    log = read_eval_log(str(eval_path))
    samples = list(log.samples or [])

    summary: dict[str, Any] = {
        "eval_file": eval_path.name,
        "status": str(getattr(log, "status", "?")),
        "samples": len(samples),
        "task": getattr(log.eval, "task", None) or "inspect_petri/audit",
    }

    model_roles = getattr(log.eval, "model_roles", None) or {}
    if model_roles:
        summary["models"] = {role: str(m) for role, m in model_roles.items()}

    stats = getattr(log.stats, "model_usage", {}) or {}
    summary["stats"] = {
        m: {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
            "input_tokens_cache_write": getattr(u, "input_tokens_cache_write", 0) or 0,
            "input_tokens_cache_read": getattr(u, "input_tokens_cache_read", 0) or 0,
        }
        for m, u in stats.items()
    }

    samples_summary: list[dict[str, Any]] = []
    for s in samples:
        scores = s.scores or {}
        scored = "audit_judge" in scores
        non_baseline: dict[str, float | int] = {}
        if scored:
            value = scores["audit_judge"].value
            if isinstance(value, dict):
                for k, vv in value.items():
                    if isinstance(vv, (int, float)) and vv != 1.0:
                        non_baseline[k] = int(vv) if float(vv).is_integer() else round(float(vv), 2)
        samples_summary.append(
            {
                "id": s.id,
                "scored": scored,
                "non_baseline_dims": non_baseline,
            }
        )
    summary["samples_summary"] = samples_summary
    return summary


def _summary_filename(eval_path: Path) -> str:
    """Stable, short summary filename: ``<YYYY-MM-DD>-<hash8>.summary.yaml``.

    The eval file itself starts with an ISO timestamp; we keep the date
    portion (sortable) and append an 8-char hash of the full basename
    for collision safety when two audits land on the same date.
    """
    name = eval_path.name
    date_prefix = name[:10] if len(name) >= 10 and name[4] == "-" and name[7] == "-" else "unknown"
    # Filename hash, not crypto — sha1 short hex matches inspect-petri's
    # own log id length and is plenty for collision avoidance on a
    # 10-char date prefix.
    h = hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{date_prefix}-{h}.summary.yaml"


def archive_eval(
    eval_path: Path,
    *,
    raw_archive_dir: Path = DEFAULT_RAW_ARCHIVE_DIR,
    summary_dir: Path = DEFAULT_SUMMARY_DIR,
) -> ArchiveResult:
    """Copy raw eval to the archive + write a committable YAML summary.

    Returns the resolved paths + summary dict. Idempotent: re-running
    over the same eval overwrites both outputs.

    The function does not move or delete the source eval — callers can
    keep the worktree copy (it's gitignored anyway) until they're sure
    the archive is on a backed-up disk.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover — yaml ships with inspect_ai/audit extra
        raise ImportError(
            "archive_eval requires PyYAML (already a dep of [audit]); "
            "install with `uv sync --extra audit`."
        ) from exc

    eval_path = Path(eval_path).expanduser().resolve()
    if not eval_path.is_file():
        raise FileNotFoundError(f"eval file not found: {eval_path}")

    summary = extract_summary(eval_path)

    raw_archive_dir = Path(raw_archive_dir).expanduser()
    summary_dir = Path(summary_dir)
    raw_archive_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    raw_target = raw_archive_dir / eval_path.name
    summary_target = summary_dir / _summary_filename(eval_path)

    shutil.copy2(eval_path, raw_target)
    summary_target.write_text(
        yaml.safe_dump(summary, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return ArchiveResult(raw_path=raw_target, summary_path=summary_target, summary=summary)
