"""Published snapshots of runtime self-improving evidence.

The self-improving hub renders a few views from runtime-only files under
``~/.geode/self-improving`` (the latest ``baseline.json``, the campaign progress
log and the gen-0 snapshot). The publication bundle carries committed data only,
so the producers that write those runtime files also refresh small,
deterministic, path-scrubbed mirrors in ``core.paths.PUBLISHED_STATE_DIR``.
Contract: ``docs/architecture/publication-bundle.md``.

Campaign progress is recorded as structured events at the point
``campaign.ProgressLog`` writes the matching text line, so readers no longer
parse the log. :func:`parse_campaign_progress_log` exists only to rebuild the
snapshot from a log written before the structured sink existed.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import core.paths
from core.memory.atomic_write import atomic_write_text
from core.observability.redaction import redact_secrets

log = logging.getLogger(__name__)

SNAPSHOT_SCHEMA_VERSION = 1
PUBLISHED_BASELINE_NAME = "baseline.json"
CAMPAIGN_PROGRESS_NAME = "campaign-progress.json"
GEN0_FITNESS_STDERR_NAME = "gen0-fitness-stderr.json"
PUBLISHED_STATE_FILES: tuple[str, ...] = (
    PUBLISHED_BASELINE_NAME,
    CAMPAIGN_PROGRESS_NAME,
    GEN0_FITNESS_STDERR_NAME,
)
CAMPAIGN_GROUPS: tuple[str, ...] = ("cycles", "gen0", "noise")
CYCLE_VERDICTS = frozenset({"promote", "reject", "no-signal"})

# A POSIX absolute (or ``~``-relative) path with at least two components that is
# not part of a URL or a relative path. Only its final component is published.
_ABSOLUTE_PATH = re.compile(r"(?<![\w.:/~-])~?(?:/[^\s/\"'<>]+){2,}")


class PublishedStateError(RuntimeError):
    """A runtime source or an existing snapshot is unreadable or malformed."""


def published_state_dir() -> Path:
    """Resolve at call time so test isolation of ``core.paths`` applies."""
    return Path(core.paths.PUBLISHED_STATE_DIR)


def scrub(value: Any) -> Any:
    """Drop absolute paths to their final component and redact secrets."""
    if isinstance(value, str):
        return redact_secrets(_ABSOLUTE_PATH.sub(lambda m: m.group(0).rsplit("/", 1)[-1], value))
    if isinstance(value, Mapping):
        return {str(key): scrub(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(item) for item in value]
    return value


def write_snapshot_json(path: Path, payload: Mapping[str, Any]) -> bool:
    """Write scrubbed, key-sorted JSON; return False when the bytes are unchanged."""
    text = json.dumps(scrub(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    return True


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishedStateError(f"unreadable JSON: {path.name}") from exc
    if not isinstance(data, dict):
        raise PublishedStateError(f"expected a JSON object: {path.name}")
    return data


# --------------------------------------------------------------------------- #
# Baseline and gen-0 snapshot                                                  #
# --------------------------------------------------------------------------- #


def latest_runtime_baseline(runtime_dir: Path) -> tuple[Path, bool] | None:
    """Return ``(path, stale)``: the live baseline, else the newest outdated copy.

    Outdated copies are named ``baseline.json.outdated-YYYYMMDD``; the newest is
    chosen by name, which is stable across machines (mtimes are not).
    """
    live = runtime_dir / "baseline.json"
    if live.is_file():
        return live, False
    outdated = sorted(p for p in runtime_dir.glob("baseline.json.outdated-*") if p.is_file())
    return (outdated[-1], True) if outdated else None


def publish_baseline(source: Path, *, stale: bool = False, out_dir: Path | None = None) -> bool:
    """Mirror a runtime baseline as ``{stale, captured_at, source, baseline}``.

    ``captured_at`` is the baseline's own ``ts_utc``; it is ``null`` when the
    document does not record one.
    """
    data = _read_json_object(source)
    captured_at = data.get("ts_utc")
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "stale": stale,
        "source": source.name,
        "captured_at": captured_at if isinstance(captured_at, str) else None,
        "baseline": data,
    }
    return write_snapshot_json(
        (out_dir or published_state_dir()) / PUBLISHED_BASELINE_NAME, payload
    )


def publish_gen0_fitness_stderr(snapshot_baseline: Path, *, out_dir: Path | None = None) -> bool:
    """Mirror ``raw.fitness_stderr`` of the gen-0 snapshot baseline."""
    data = _read_json_object(snapshot_baseline)
    raw = data.get("raw")
    stderr = raw.get("fitness_stderr") if isinstance(raw, dict) else None
    if isinstance(stderr, bool) or not isinstance(stderr, int | float):
        raise PublishedStateError(f"no numeric raw.fitness_stderr in {snapshot_baseline.name}")
    captured_at = data.get("ts_utc")
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "fitness_stderr": float(stderr),
        "captured_at": captured_at if isinstance(captured_at, str) else None,
    }
    return write_snapshot_json(
        (out_dir or published_state_dir()) / GEN0_FITNESS_STDERR_NAME, payload
    )


def refresh_published_baseline(source: Path) -> None:
    """Producer hook after a runtime baseline write; failures only log."""
    try:
        publish_baseline(source)
    except (OSError, PublishedStateError) as exc:
        log.warning("published baseline refresh failed: %s", exc)


# --------------------------------------------------------------------------- #
# Campaign progress                                                            #
# --------------------------------------------------------------------------- #


def empty_campaign_progress() -> dict[str, Any]:
    return {"schema_version": SNAPSHOT_SCHEMA_VERSION, "cycles": [], "gen0": [], "noise": []}


def cycle_record(
    *,
    arm: str,
    n: int,
    total: int,
    skip: bool = False,
    verdict: str | None = None,
    sel: float | None = None,
    held: float | None = None,
    delta: float | None = None,
) -> dict[str, Any]:
    """One per-cycle outcome. ``verdict`` is ``None`` exactly when ``skip``."""
    if skip == (verdict is not None) or (verdict is not None and verdict not in CYCLE_VERDICTS):
        raise ValueError(f"invalid cycle outcome: skip={skip} verdict={verdict!r}")
    return {
        "arm": arm,
        "n": n,
        "total": total,
        "skip": skip,
        "verdict": verdict,
        "sel": sel,
        "held": held,
        "delta": delta,
    }


def gen0_record(*, n: int, total: int, sel: float | None, held: float | None) -> dict[str, Any]:
    return {"n": n, "total": total, "sel": sel, "held": held}


def noise_record(*, k: int, mean: float | None, stderr: float | None) -> dict[str, Any]:
    """Values are rounded to the four decimals the progress log prints."""
    return {
        "k": k,
        "mean": None if mean is None else round(mean, 4),
        "stderr": None if stderr is None else round(stderr, 4),
    }


def load_campaign_progress(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return empty_campaign_progress()
    data = _read_json_object(path)
    if not all(isinstance(data.get(group), list) for group in CAMPAIGN_GROUPS):
        raise PublishedStateError(f"malformed campaign progress snapshot: {path.name}")
    return data


def append_campaign_record(path: Path, group: str, record: Mapping[str, Any]) -> None:
    """Append one timestamped event to a campaign progress snapshot."""
    if group not in CAMPAIGN_GROUPS:
        raise ValueError(f"unknown campaign progress group: {group!r}")
    data = load_campaign_progress(path)
    data[group].append(dict(record))
    write_snapshot_json(path, data)


_LOG_LINE = re.compile(r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (?P<msg>.*)$")
_LOG_CYCLE = re.compile(r"^arm '(?P<arm>[\w-]+)' cycle (?P<n>\d+)/(?P<total>\d+): (?P<rest>.*)$")
_LOG_CYCLE_RESULT = re.compile(
    r"^fitness_after=(?P<sel>\S+) fitness_delta=(?P<delta>\S+) "
    r"held_out=(?P<held>\S+) (?P<verdict>promote|reject)\b"
)
_LOG_GEN0 = re.compile(
    r"^gen-0 baseline repeat (?P<n>\d+)/(?P<total>\d+): "
    r"held_out=(?P<held>\S+) fitness=(?P<sel>\S+)"
)
_LOG_NOISE = re.compile(r"gen-0 noise band: K=(?P<k>\d+) (?P<rest>.*)$")
_LOG_NOISE_VALUES = re.compile(r"^held_out_mean=(?P<mean>\S+) stderr=(?P<stderr>\S+)")


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _parse_cycle(match: re.Match[str]) -> dict[str, Any] | None:
    arm, n, total, rest = match["arm"], int(match["n"]), int(match["total"]), match["rest"]
    if rest.startswith("SKIP"):
        return cycle_record(arm=arm, n=n, total=total, skip=True)
    if rest.startswith("NO-SIGNAL"):
        return cycle_record(arm=arm, n=n, total=total, verdict="no-signal")
    result = _LOG_CYCLE_RESULT.match(rest)
    if result is None:
        return None
    return cycle_record(
        arm=arm,
        n=n,
        total=total,
        verdict=result["verdict"],
        sel=_number(result["sel"]),
        held=_number(result["held"]),
        delta=_number(result["delta"]),
    )


def _parse_noise(message: str) -> dict[str, Any] | None:
    # Control-arm floor lines embed the same band summary; only gen-0 bands count.
    if not message.startswith(("gen-0 noise band:", "gen-0 baseline (async):")):
        return None
    match = _LOG_NOISE.search(message)
    if match is None:
        return None
    values = _LOG_NOISE_VALUES.match(match["rest"])
    return noise_record(
        k=int(match["k"]),
        mean=_number(values["mean"]) if values else None,
        stderr=_number(values["stderr"]) if values else None,
    )


def parse_campaign_progress_log(text: str) -> dict[str, Any]:
    """Rebuild the structured snapshot from a legacy ``campaign-progress.log``.

    Events inside a ``campaign start: ... dry_run=True`` campaign are skipped,
    matching the live sink, which records real campaigns only.
    """
    data = empty_campaign_progress()
    in_dry_run = False
    for line in text.splitlines():
        parsed = _LOG_LINE.match(line)
        if parsed is None:
            continue
        ts, message = parsed["ts"], parsed["msg"]
        if message.startswith("campaign start:"):
            in_dry_run = "dry_run=True" in message
            continue
        if in_dry_run:
            continue
        cycle = _LOG_CYCLE.match(message)
        gen0 = _LOG_GEN0.match(message)
        record: dict[str, Any] | None
        if cycle is not None:
            group, record = "cycles", _parse_cycle(cycle)
        elif gen0 is not None:
            group = "gen0"
            record = gen0_record(
                n=int(gen0["n"]),
                total=int(gen0["total"]),
                sel=_number(gen0["sel"]),
                held=_number(gen0["held"]),
            )
        else:
            group, record = "noise", _parse_noise(message)
        if record is not None:
            data[group].append({"ts": ts, **record})
    return data
