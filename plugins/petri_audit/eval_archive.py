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
          "contract_results": [
             {"contract_id": str, "status": str, "hard": bool,
              "failed_samples": [str, ...], "detail": str},
             ...
          ],
        }

    The ``contract_results`` key holds the deterministic tool-call contract
    ledger (``core.audit.contracts.extract_contract_results``) — a discrete
    PASS / FAIL ledger (NOT averaged into a dim) that the promote gate vetoes
    on. ``[]`` when the archive carries no contract signal.

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

    # Eval-level wall-time. ``EvalStats.started_at`` / ``completed_at``
    # are ISO8601 strings (or empty when the run cancelled before
    # bootstrap). Extract both as-is; the duration is the readable
    # signal a future Phase-2x report wants without re-deriving from
    # per-sample timestamps.
    eval_started = str(getattr(log.stats, "started_at", "") or "")
    eval_completed = str(getattr(log.stats, "completed_at", "") or "")
    if eval_started or eval_completed:
        summary["timing"] = {
            "started_at": eval_started,
            "completed_at": eval_completed,
            "duration_seconds": _duration_seconds(eval_started, eval_completed),
        }

    model_roles = getattr(log.eval, "model_roles", None) or {}
    if model_roles:
        # ``model_roles`` values are ``ModelConfig`` pydantic objects.
        # ``str(m)`` falls back to the dataclass-style repr which dumps
        # every nested ``GenerateConfig`` field as a giant inline blob —
        # not what a summary YAML wants. Reach into ``.model`` so the
        # output is the bare ``provider/name`` string the report-writer
        # actually reads.
        summary["models"] = {
            role: getattr(m, "model", None) or str(m) for role, m in model_roles.items()
        }

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
        sample_entry: dict[str, Any] = {
            "id": s.id,
            "scored": scored,
            "non_baseline_dims": non_baseline,
        }
        # Time efficiency axis (결함 F) — sample-level wall-time +
        # working-time + turn count. ``total_time`` and ``working_time``
        # are floats in seconds; ``messages`` length is the number of
        # ChatMessage entries (system + alternating user/assistant +
        # tool), not turns directly, but it is the strongest proxy
        # available without walking events.
        total_time = getattr(s, "total_time", None)
        working_time = getattr(s, "working_time", None)
        if total_time is not None or working_time is not None:
            sample_entry["timing"] = {
                "total_time": float(total_time) if total_time is not None else None,
                "working_time": float(working_time) if working_time is not None else None,
            }
        msgs = getattr(s, "messages", None) or []
        if msgs:
            sample_entry["messages"] = len(msgs)
        # Seed mapping (결함 L) — ``sample.input`` carries the seed
        # name (or, in inspect-petri's id:-form bug we filed as 결함 R,
        # the literal ``id:<name>`` string for the first item). Strip
        # the ``id:`` prefix and keep the first 80 chars so a future
        # report-generator can join on this value without re-walking
        # the seed catalogue.
        seed_id = _extract_seed_id(s)
        if seed_id is not None:
            sample_entry["seed_id"] = seed_id
        samples_summary.append(sample_entry)
    summary["samples_summary"] = samples_summary

    # Deterministic tool-call contract ledger (plugins → core is the allowed
    # dependency direction; sibling ``runner.py`` already imports
    # ``core.audit.manifest``). Graceful ``[]`` on any read failure — the
    # contract extractor never raises (mirrors ``dim_extractor``).
    from core.audit.contracts import extract_contract_results

    summary["contract_results"] = extract_contract_results(eval_path)
    return summary


def _duration_seconds(started: str, completed: str) -> float | None:
    """Parse two ISO8601 strings and return ``completed - started``
    as a float-seconds value. Returns ``None`` when either side is
    blank or unparseable so the YAML omits the field instead of
    emitting a misleading 0.

    Inspect uses Pydantic's ``BeforeValidator`` to normalise to UTC,
    so the strings always end with ``+00:00`` or ``Z`` — we accept
    either via ``fromisoformat``.
    """
    from datetime import datetime

    if not started or not completed:
        return None
    try:
        dt0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
        dt1 = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((dt1 - dt0).total_seconds(), 3)


def _extract_seed_id(sample: Any) -> str | None:
    """Best-effort seed-name recovery from an ``EvalSample``.

    Petri's seed loading produces samples whose ``id`` is the seed
    filename stem (e.g. ``system_prompt_quirk_reveal``). When the
    caller passes ``seed_instructions=id:a,b,...`` via inspect_ai's
    ``-T`` flag (결함 R), the first item leaks an ``id:`` prefix into
    ``sample.input`` while ``sample.id`` becomes a 1-based integer.
    We try ``sample.id`` first (string form), then fall back to the
    first short token of ``sample.input`` with the prefix stripped.
    """
    sample_id = getattr(sample, "id", None)
    if isinstance(sample_id, str) and sample_id and not sample_id.isdigit():
        return sample_id
    raw_input = getattr(sample, "input", None)
    if not isinstance(raw_input, str):
        return None
    first_line = raw_input.strip().splitlines()[0] if raw_input.strip() else ""
    if first_line.startswith("id:"):
        first_line = first_line[3:]
    # Heuristic — petri seed names are short (< 60 chars), all-lower
    # snake_case. Anything outside that shape is a seed body, not a
    # name; return None so the YAML omits ``seed_id``.
    if 0 < len(first_line) < 60 and " " not in first_line and "_" in first_line:
        return first_line
    return None


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

    # Idempotent re-archive: when the caller hands us an eval that
    # already lives inside the archive dir (e.g. ``geode petri-archive
    # ~/.geode/petri/logs/foo.eval`` for a re-extract after the
    # extractor evolved), shutil.copy2 raises ``SameFileError``. Skip
    # the copy in that case but still rewrite the summary YAML so the
    # latest extractor runs.
    if raw_target.resolve() != eval_path.resolve():
        shutil.copy2(eval_path, raw_target)
    summary_target.write_text(
        yaml.safe_dump(summary, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return ArchiveResult(raw_path=raw_target, summary_path=summary_target, summary=summary)
