"""Scheduled read-only engineering report collectors.

Four background jobs that snapshot engineering health into
``.geode/reports/<job>/<date>.md`` and return a one-line summary. All four
are **pure-python collectors** (v1): NO LLM calls, ``budget_usd=0.0``, and
no tool loop at all — they run on the scheduler's ``callback`` path, which
never constructs an AgenticLoop or a ``ToolExecutor``, so the exec-hardening
denied-tools rail is structural (there is no tool surface to deny; the
``denied_tools`` metadata on each job documents the contract for readers).
LLM synthesis of the collected reports is an explicit follow-up, gated on a
non-zero per-job ``budget_usd``.

Jobs (registered by :func:`register_engineering_report_jobs`, disabled by
default — enable via ``/schedule enable <job_id>``, run once via
``/schedule run <job_id>`` or the ``schedule_job`` tool):

* ``engineering:todo_aging_report`` — ``git grep`` TODO/FIXME + ``git blame``
  age buckets.
* ``engineering:dependency_drift_report`` — resolved-dependency snapshot
  (parsed from ``uv.lock``, the lockfile SoT of the ``uv tree`` output)
  diffed against the previous run's snapshot.
* ``engineering:docs_link_report`` — invokes the existing
  ``scripts/check_docs_links.py`` checker when present.
* ``engineering:runtime_warning_triage`` — tails ``~/.geode/logs/serve.log``
  WARNING lines, grouped by logger with counts.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import time
import tomllib
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.memory.atomic_write import atomic_write_text
from core.paths import PROJECT_REPORTS_DIR, SERVE_LOG_PATH
from core.scheduler.models import Schedule, ScheduledJob, ScheduleKind

if TYPE_CHECKING:
    from core.scheduler.service import SchedulerService

log = logging.getLogger(__name__)

__all__ = [
    "ENGINEERING_REPORT_JOBS",
    "EngineeringReportSpec",
    "dependency_drift_report",
    "docs_link_report",
    "register_engineering_report_jobs",
    "runtime_warning_triage",
    "todo_aging_report",
]

# Cap git-blame subprocess fan-out per run (weekly job; 200 line-blames is
# a few seconds on this repo). Hits beyond the cap still count in totals,
# bucketed as "unblamed".
MAX_BLAME_LINES = 200

_GIT_TIMEOUT_S = 120
_SCRIPT_TIMEOUT_S = 300

_AGE_BUCKETS: tuple[tuple[str, float], ...] = (
    ("<30d", 30.0),
    ("30-90d", 90.0),
    ("90-365d", 365.0),
    (">365d", float("inf")),
)

_WARNING_LOGGER_RE = re.compile(r"^(?:\S+\s+\S+\s+)?([\w\.]+)\s+WARNING\b\s*(.*)$")


def _report_path(project_root: Path, job_key: str, *, now: datetime) -> Path:
    return project_root / PROJECT_REPORTS_DIR / job_key / f"{now.strftime('%Y-%m-%d')}.md"


def _write_report(project_root: Path, job_key: str, body: str, *, now: datetime) -> Path:
    path = _report_path(project_root, job_key, now=now)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, body)
    return path


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — argv from module constants + repo-relative paths
        ["git", *args],  # noqa: S607  # nosec B607 — git in PATH
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )


# ---------------------------------------------------------------------------
# 1. to-do marker aging (spelled lowercase here so the slop ratchet
#    does not self-count its own collector)
# ---------------------------------------------------------------------------


def todo_aging_report(project_root: Path | None = None, *, now: datetime | None = None) -> str:
    """git-grep TODO/FIXME markers, blame each line, bucket by age."""
    root = (project_root or Path.cwd()).resolve()
    at = now or datetime.now(UTC)
    grep = _git(["grep", "-nI", "-e", "TODO", "-e", "FIXME"], cwd=root)
    if grep.returncode not in (0, 1):  # 1 = no matches; >1 = real git failure
        raise RuntimeError(f"git grep failed (rc={grep.returncode}): {grep.stderr.strip()}")
    hits = [line for line in grep.stdout.splitlines() if line.strip()]

    buckets: Counter[str] = Counter()
    aged: list[tuple[float, str]] = []  # (age_days, "file:line text")
    unblamed = 0
    for raw in hits[:MAX_BLAME_LINES]:
        file_part, _, rest = raw.partition(":")
        line_no, _, text = rest.partition(":")
        if not line_no.isdigit():
            unblamed += 1
            continue
        blame = _git(
            ["blame", "-L", f"{line_no},{line_no}", "--line-porcelain", "--", file_part],
            cwd=root,
        )
        match = re.search(r"^committer-time (\d+)$", blame.stdout, re.MULTILINE)
        if blame.returncode != 0 or match is None:
            unblamed += 1
            continue
        age_days = max(0.0, (at.timestamp() - float(match.group(1))) / 86400.0)
        for label, ceiling in _AGE_BUCKETS:
            if age_days <= ceiling:
                buckets[label] += 1
                break
        aged.append((age_days, f"`{file_part}:{line_no}` {text.strip()[:120]}"))
    unblamed += max(0, len(hits) - MAX_BLAME_LINES)

    aged.sort(key=lambda item: -item[0])
    bucket_rows = "\n".join(f"| {label} | {buckets.get(label, 0)} |" for label, _ in _AGE_BUCKETS)
    oldest = "\n".join(f"- {age:.0f}d — {desc}" for age, desc in aged[:20]) or "- none"
    body = (
        f"# To-do marker aging report — {at.strftime('%Y-%m-%d')}\n\n"
        f"Total markers: {len(hits)} (blamed {len(aged)}, unblamed {unblamed}, "
        f"blame cap {MAX_BLAME_LINES})\n\n"
        "| age bucket | count |\n|---|---|\n"
        f"{bucket_rows}\n\n"
        "## Oldest 20\n\n"
        f"{oldest}\n"
    )
    path = _write_report(root, "todo_aging_report", body, now=at)
    summary = f"todo_aging_report: {len(hits)} markers ({dict(buckets)}) -> {path}"
    log.info(summary)
    return summary


# ---------------------------------------------------------------------------
# 2. Dependency drift
# ---------------------------------------------------------------------------


def dependency_drift_report(
    project_root: Path | None = None, *, now: datetime | None = None
) -> str:
    """Diff the resolved dependency set (uv.lock) against the last run."""
    root = (project_root or Path.cwd()).resolve()
    at = now or datetime.now(UTC)
    lock_file = root / "uv.lock"
    if not lock_file.is_file():
        raise FileNotFoundError(f"uv.lock not found at {lock_file} — nothing to snapshot")
    lock = tomllib.loads(lock_file.read_text(encoding="utf-8"))
    current: dict[str, str] = {
        pkg.get("name", ""): pkg.get("version", "")
        for pkg in lock.get("package", [])
        if pkg.get("name")
    }

    snapshot_file = root / PROJECT_REPORTS_DIR / "dependency_drift_report" / "snapshot.json"
    previous: dict[str, str] = {}
    if snapshot_file.is_file():
        previous = json.loads(snapshot_file.read_text(encoding="utf-8"))

    if previous:
        added = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        changed = sorted(
            name for name in set(current) & set(previous) if current[name] != previous[name]
        )
    else:
        added, removed, changed = [], [], []  # first run = baseline, not drift

    if not previous:
        drift_block = "First run — baseline snapshot established, no diff.\n"
    elif not (added or removed or changed):
        drift_block = "No drift since last run.\n"
    else:
        lines: list[str] = []
        lines.extend(f"- added: `{name}` {current[name]}" for name in added)
        lines.extend(f"- removed: `{name}` {previous[name]}" for name in removed)
        lines.extend(f"- changed: `{name}` {previous[name]} -> {current[name]}" for name in changed)
        drift_block = "\n".join(lines) + "\n"

    body = (
        f"# Dependency drift report — {at.strftime('%Y-%m-%d')}\n\n"
        f"Resolved packages in uv.lock: {len(current)}\n\n"
        "## Drift vs last run\n\n"
        f"{drift_block}"
    )
    path = _write_report(root, "dependency_drift_report", body, now=at)
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(snapshot_file, json.dumps(current, indent=2, sort_keys=True))
    summary = (
        f"dependency_drift_report: {len(current)} packages, "
        f"+{len(added)}/-{len(removed)}/~{len(changed)} -> {path}"
    )
    log.info(summary)
    return summary


# ---------------------------------------------------------------------------
# 3. Docs link check
# ---------------------------------------------------------------------------


def docs_link_report(project_root: Path | None = None, *, now: datetime | None = None) -> str:
    """Run the existing ``scripts/check_docs_links.py`` checker and capture it."""
    root = (project_root or Path.cwd()).resolve()
    at = now or datetime.now(UTC)
    script = root / "scripts" / "check_docs_links.py"
    if not script.is_file():
        body = (
            f"# Docs link report — {at.strftime('%Y-%m-%d')}\n\n"
            f"SKIPPED: `{script}` does not exist in this project.\n"
        )
        path = _write_report(root, "docs_link_report", body, now=at)
        summary = f"docs_link_report: SKIPPED (no checker script) -> {path}"
        log.warning(summary)
        return summary

    proc = subprocess.run(  # noqa: S603 — argv is sys.executable + repo-tracked script path
        [sys.executable, str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=_SCRIPT_TIMEOUT_S,
        check=False,
    )
    status = "PASS" if proc.returncode == 0 else f"FAIL (exit {proc.returncode})"
    output = (proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")).strip()
    body = (
        f"# Docs link report — {at.strftime('%Y-%m-%d')}\n\n"
        f"Checker: `scripts/check_docs_links.py` — {status}\n\n"
        "```\n"
        f"{output or '(no output)'}\n"
        "```\n"
    )
    path = _write_report(root, "docs_link_report", body, now=at)
    summary = f"docs_link_report: {status} -> {path}"
    log.info(summary)
    return summary


# ---------------------------------------------------------------------------
# 4. Runtime WARNING triage
# ---------------------------------------------------------------------------


def runtime_warning_triage(
    project_root: Path | None = None,
    *,
    log_path: Path | None = None,
    max_lines: int = 2000,
    now: datetime | None = None,
) -> str:
    """Tail the serve log, group WARNING lines by logger, count them."""
    root = (project_root or Path.cwd()).resolve()
    at = now or datetime.now(UTC)
    source = log_path or SERVE_LOG_PATH
    counts: Counter[str] = Counter()
    samples: dict[str, str] = {}
    tail_count = 0
    if source.is_file():
        with source.open(encoding="utf-8", errors="replace") as handle:
            tail = deque(handle, maxlen=max_lines)
        tail_count = len(tail)
        for line in tail:
            match = _WARNING_LOGGER_RE.match(line.strip())
            if match is None:
                continue
            logger_name, message = match.group(1), match.group(2)
            counts[logger_name] += 1
            samples.setdefault(logger_name, message[:140])

    if not source.is_file():
        triage_block = f"Log file `{source}` does not exist — nothing to triage.\n"
    elif not counts:
        triage_block = f"No WARNING lines in the last {tail_count} log lines.\n"
    else:
        rows = "\n".join(
            f"| `{logger_name}` | {count} | {samples[logger_name]} |"
            for logger_name, count in counts.most_common()
        )
        triage_block = f"| logger | count | sample |\n|---|---|---|\n{rows}\n"

    body = (
        f"# Runtime WARNING triage — {at.strftime('%Y-%m-%d')}\n\n"
        f"Source: `{source}` (tail {tail_count} of max {max_lines} lines)\n\n"
        f"{triage_block}"
    )
    path = _write_report(root, "runtime_warning_triage", body, now=at)
    summary = (
        f"runtime_warning_triage: {sum(counts.values())} warnings "
        f"across {len(counts)} loggers -> {path}"
    )
    log.info(summary)
    return summary


# ---------------------------------------------------------------------------
# Job registration — extends the existing SchedulerService job machinery
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineeringReportSpec:
    """One schedulable read-only report job."""

    job_id: str
    name: str
    description: str
    cron_expr: str  # weekly default
    collector: Callable[..., str]


ENGINEERING_REPORT_JOBS: tuple[EngineeringReportSpec, ...] = (
    EngineeringReportSpec(
        job_id="engineering:todo_aging_report",
        name="TODO/FIXME aging report",
        description="git grep TODO/FIXME with git blame age buckets",
        cron_expr="0 9 * * 1",
        collector=todo_aging_report,
    ),
    EngineeringReportSpec(
        job_id="engineering:dependency_drift_report",
        name="Dependency drift report",
        description="uv.lock resolved-package snapshot diff vs last run",
        cron_expr="15 9 * * 1",
        collector=dependency_drift_report,
    ),
    EngineeringReportSpec(
        job_id="engineering:docs_link_report",
        name="Docs link report",
        description="scripts/check_docs_links.py pass/fail capture",
        cron_expr="30 9 * * 1",
        collector=docs_link_report,
    ),
    EngineeringReportSpec(
        job_id="engineering:runtime_warning_triage",
        name="Runtime WARNING triage",
        description="serve.log WARNING lines grouped by logger",
        cron_expr="45 9 * * 1",
        collector=runtime_warning_triage,
    ),
)


def _make_collector_callback(
    spec: EngineeringReportSpec, project_root: Path | None
) -> Callable[[dict[str, object]], None]:
    """Build the pure-python collector callback for ``spec``."""

    def _run(_fired: dict[str, object]) -> None:
        summary = spec.collector(project_root)
        log.info("engineering report %s: %s", spec.job_id, summary)

    return _run


def build_engineering_report_job(
    spec: EngineeringReportSpec,
    *,
    project_root: Path | None = None,
    enabled: bool = False,
) -> ScheduledJob:
    """Build the callback-path ScheduledJob for one report spec.

    ``durable=False`` because callbacks cannot be serialised (a persisted
    callback job reloads as a zombie); the wiring re-registers on every
    boot instead. ``permanent=True`` exempts the boot-registered job from
    the 30-day recurring age-out.
    """

    return ScheduledJob(
        job_id=spec.job_id,
        name=spec.name,
        schedule=Schedule(kind=ScheduleKind.CRON, cron_expr=spec.cron_expr),
        enabled=enabled,
        durable=True,  # persists the operator's enabled flag across restarts
        permanent=True,
        callback=_make_collector_callback(spec, project_root),
        budget_usd=0.0,  # pure collector — NO LLM calls in v1
        metadata={
            "kind": "engineering_report",
            "read_only": True,
            # Structural rail: callback jobs never build an AgenticLoop or
            # ToolExecutor, so every tool is effectively denied. Kept as
            # metadata so operators see the contract in /schedule status.
            "denied_tools": "*",
            "description": spec.description,
        },
        created_at_ms=time.time() * 1000,
    )


def register_engineering_report_jobs(
    scheduler_service: SchedulerService,
    *,
    project_root: Path | None = None,
    enabled: bool = False,
) -> list[str]:
    """Register the four report jobs on a SchedulerService. Idempotent per boot.

    Disabled by default — operators opt in via ``/schedule enable <job_id>``
    (or run once with ``/schedule run <job_id>`` / the ``schedule_job`` tool,
    which executes regardless of the enabled flag).
    """
    registered: list[str] = []
    for spec in ENGINEERING_REPORT_JOBS:
        existing = scheduler_service.get_job(spec.job_id)
        if existing is not None:
            # Durable copy loaded from disk carries no callable (callbacks are
            # not serialised) — re-attach the collector while PRESERVING the
            # operator's persisted enabled flag (Codex MED: enable must
            # survive restart).
            existing.callback = _make_collector_callback(spec, project_root)
            continue
        job = build_engineering_report_job(spec, project_root=project_root, enabled=enabled)
        scheduler_service.add_job(job)
        registered.append(spec.job_id)
    if registered:
        log.info("registered %d engineering report jobs: %s", len(registered), registered)
    return registered
