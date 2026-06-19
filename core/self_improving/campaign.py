#!/usr/bin/env python3
"""Self-improving campaign driver — the committed, unit-tested orchestrator.

PR-CAMPAIGN-DRIVER (2026-05-31). Implements the procedure spelled out in
``docs/self-improving/campaign-procedure.md`` (the canonical SoT) as a real,
importable module with a CLI front end. The driver does NOT decide policy — it
*sequences* the pieces that already exist:

* ``core/self_improving/train.py`` — the manual measurement path (one real Petri audit,
  no mutation, ``source="manual"``; the first run bootstrap-establishes
  ``baseline.json``). The campaign spawns it via ``uv run python
  core/self_improving/train.py`` and reads each run's ``held_out_fitness`` + ``fitness``
  from the new ``kind="attribution"`` rows it appends to ``mutations.jsonl``,
  plus each run's RAW per-dim ``dim_means`` from the ``FITNESS_RESULT:`` stdout
  sentinel. After the K gen-0 repeats it overwrites ``baseline.json``'s
  ``raw.dim_means`` with the per-dim K-MEAN (and ``raw.dim_stderr`` with the
  across-K per-dim sample stderr), so the promote gate's ``prior_raw =
  compute_fitness(mean_dims)`` is a robust central estimate of the stochastic
  Petri audit — not the single (possibly lucky-outlier) bootstrap measure that
  would otherwise pin the gate to a structurally near-0-approve state.
* ``core.self_improving.loop.mutate.runner.SelfImprovingLoopRunner`` — one
  ``propose()`` + guard + ``apply_proposal()`` per cycle. The driver wraps
  ``propose()`` in a re-proposal loop (the *propose-guard*) so a
  ``RepetitiveMutationError`` or a measurement-hyperparam ``ValueError`` does not
  burn the cycle.
* ``GEODE_PROMOTE_POLICY`` (+ ``GEODE_PROMOTE_POLICY_SEED``) — the control-arm
  knob (``core/self_improving/train.py::_resolve_promote_policy``). Each arm runs
  from a matched gen-0 SoT reset. The two PATH-INDEPENDENT control arms
  (**never + random**) fan out CONCURRENTLY in ONE ``asyncio.gather`` by default
  (PR-CAMPAIGN-CONCURRENT-CONTROL-ARMS, 2026-06-04 — every cycle measures the same
  frozen baseline, so they overlap instead of running arm-by-arm); the
  PATH-DEPENDENT **gate** arm runs LAST and sequentially (a promote mutates the
  champion chain). The legacy dry-run / injected-runner path keeps the original
  sequential **never → random → gate** order.

At the start of a REAL (non-``--dry-run``) campaign the driver purges
``inspect_ai``'s trajectory cache (``plugins.petri_audit.runner.purge_inspect_cache``,
the cache at ``~/Library/Caches/inspect_ai/generate/``) so the K gen-0 measures
+ all cycle audits are INDEPENDENT re-measures, not replays of a stale cached
trajectory for an identical seed. Skipped under ``--dry-run`` (synthetic audits
never touch the cache).

The campaign is split into pure, testable units (snapshot/restore, the
propose-guard, the degeneracy guard, the gen-0 noise-band collection + K-mean
baseline write) so the unit suite in ``tests/core/self_improving/test_run_campaign.py`` can exercise
every boundary with mocks and NO live audit / network / PAYG spend. ``--dry-run``
passes the flag through to ``train.py`` AND to the runner (``rerun_dry_run=True``)
so the whole chain can be smoke-tested end-to-end with synthetic audits.

ENV SETUP
---------
PR-CAMPAIGN-LOAD-ENV (2026-06-02): the driver now loads ``~/.geode/.env`` itself
(``main`` → ``train._load_global_env``), so ``ANTHROPIC_API_KEY`` reaches the
spawned audit subprocesses without the operator's shell having to export it.
(Pre-fix this was the operator's responsibility; a forgotten export silently
broke every cycle audit with an anthropic auth error → degenerate baseline.) An
already-exported shell key still wins (``override=False``). The driver also sets,
in the env it passes to each subprocess:

* ``GEODE_CODEX_OAUTH_POLL_DISABLED=1`` — bypass GEODE's pre-emptive 5-hour
  throttle so the ChatGPT-Plus subscription bucket is used directly
  (``reference_codex_oauth_throttle_bypass``).
* ``AUTORESEARCH_SEED_SELECT=<repo>/state/seed-pools/cycle-input`` — the
  co-evolving selection pool (highest-precedence override, see
  ``docs/self-improving/cycle-input-pool.md``).
* ``GEODE_HELD_OUT_BENCH=<repo>/state/seed-pools/held-out`` — the version-frozen
  ruler (``core/self_improving/train.py::_resolve_held_out_bench``).
* ``GEODE_AUDIT_MAX_SAMPLES`` / ``GEODE_AUDIT_MAX_CONNECTIONS`` (default 3 / 8) —
  the fan-out caps. NOTE: today ``plugins/petri_audit/runner.py::build_command``
  hard-codes ``--max-samples 1 --max-connections 1`` for the single-OAuth lane
  (campaign-procedure.md §8). The driver exports these as a forward-looking knob
  the operator's multi-account lane can honour; it does not silently change the
  audit fan-out for a single-OAuth run.

The driver never runs a live audit itself under ``--dry-run``; the operator runs
the live campaign with real credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import os
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.memory.atomic_write import iter_jsonl
from core.paths import (
    AUTORESEARCH_POLICIES_DIR,
    AUTORESEARCH_STATE_DIR,
    BASELINE_JSON_PATH,
    CAMPAIGN_PROGRESS_LOG_PATH,
    MUTATION_AUDIT_LOG_PATH,
    RUNTIME_ROOT,
)
from core.paths import CYCLE_INPUT_POOL as _CYCLE_INPUT_POOL  # PR-CLEANUP-D2
from core.paths import HELD_OUT_BENCH_POOL as _HELD_OUT_BENCH_POOL  # PR-CLEANUP-D2
from core.paths import PETRI_LOGS_DIR as _PETRI_LOGS_DIR  # PR-CLEANUP-D2

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.self_improving.loop.mutate.runner import Proposal, SelfImprovingLoopRunner

log = logging.getLogger("self_improving.campaign")

# ---------------------------------------------------------------------------
# Constants — defaults match campaign-procedure.md §4 / §6
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
"""The git repo root. ``core/self_improving/campaign.py`` → ``parents[2]`` = repo root."""

# Single canonical state-dir constant (``core.paths.AUTORESEARCH_STATE_DIR`` =
# in-repo ``core/self_improving/state/`` by default; under
# ``$GEODE_STATE_ROOT/autoresearch`` for an isolated worker). No local
# re-definition — no dual SoT (CLAUDE.md). Module aliases → the single-SoT
# core.paths constants (no literal re-construction). Note post
# PR-STATE-SOT-RUNTIME-SPLIT the tracked SoT (STATE_DIR / POLICIES_DIR /
# MUTATIONS_JSONL) and the runtime files (BASELINE_JSON / PROGRESS_LOG) no longer
# share a parent in the default home — read each from its own alias.
STATE_DIR = AUTORESEARCH_STATE_DIR  # tracked SoT root (in-repo)
POLICIES_DIR = AUTORESEARCH_POLICIES_DIR  # tracked
MUTATIONS_JSONL = MUTATION_AUDIT_LOG_PATH  # tracked audit ledger
BASELINE_JSON = BASELINE_JSON_PATH  # runtime (latest, vs tracked archive)
PROGRESS_LOG = CAMPAIGN_PROGRESS_LOG_PATH  # runtime

#: gen-0 SoT snapshot destination — RUNTIME (under the out-of-repo runtime root,
#: ``~/.geode/self-improving/campaign/`` by default) so a matched-reset snapshot
#: of a real campaign never enters git history (PR-STATE-SOT-RUNTIME-SPLIT moved
#: it out of the deleted repo-root ``state/`` tree).
GEN0_SNAPSHOT_DIR = RUNTIME_ROOT / "campaign" / "gen-0-snapshot"

#: Per-run resume-checkpoint directory (same out-of-repo ``campaign/`` runtime
#: tree as the snapshot — a resume marker is a runtime artifact, not git history).
#: A campaign run writes ``<this>/<run_id>.json`` recording which path-independent
#: workers COMPLETED, so a re-run after a crash skips the finished ones and only
#: re-runs the missing replicates / cycles, then aggregates the union (S4).
CAMPAIGN_RUNS_DIR = RUNTIME_ROOT / "campaign" / "runs"

#: Seed-pool launch wiring (campaign-procedure.md §3, cycle-input-pool.md) —
#: paths anchored in core.paths (PR-CLEANUP-D2).
CYCLE_INPUT_POOL = _CYCLE_INPUT_POOL
HELD_OUT_BENCH = _HELD_OUT_BENCH_POOL

# PR-CLEANUP-D2 — train's module path, shared with loop/runner.py (the module
# already moved once, scripts/ → core/self_improving/; a missed argv edit
# yields "train.py exited 1"-class worker drops).
TRAIN_MODULE = "core.self_improving.train"

#: Petri eval archive (campaign-procedure.md §7) — the degeneracy guard reads
#: the newest ``.eval`` here (anchored in core.paths).
PETRI_LOGS_DIR = _PETRI_LOGS_DIR

DEFAULT_N = 10
"""Cycles per arm (campaign-procedure.md §6)."""
DEFAULT_K = 5
"""gen-0 baseline repeats (campaign-procedure.md §4 — K-repeat noise band)."""
DEFAULT_MAX_PROPOSE_ATTEMPTS = 8
"""propose-guard re-proposal cap (M)."""
DEFAULT_ARMS = ("never", "random", "gate")
"""Control arms, gate LAST (campaign-procedure.md §6)."""
DEFAULT_PER_AUDIT_TIMEOUT_S = 2700.0
"""Tight per-audit wall-clock bound (45 min) for the async-first subprocess workers.

This is the hang fix: the in-process ``train.py`` budget is ``budget_minutes*60 + 120``
and operators set ``budget_minutes`` as high as 300 (= a ~5 hr ceiling), so a hung
audit used to hold its slot for hours. The orchestrator kills each worker subprocess
(and its ``inspect eval`` grandchild) at this bound instead — generous for a real
Petri audit (~20-30 min at ``seed_limit=10``) yet ~6.7× tighter than the 5 hr ceiling.
Override with ``GEODE_PER_AUDIT_TIMEOUT_S`` (graceful: non-numeric → this default)."""
PER_AUDIT_TIMEOUT_ENV = "GEODE_PER_AUDIT_TIMEOUT_S"
DEFAULT_RANDOM_SEED_BASE = 424200
"""Deterministic ``GEODE_PROMOTE_POLICY_SEED`` base for the random arm; the
per-arm seed is ``DEFAULT_RANDOM_SEED_BASE + arm_index``."""

DEFAULT_AUDIT_MAX_SAMPLES = 3
DEFAULT_AUDIT_MAX_CONNECTIONS = 8

#: Fallback degeneracy threshold when ``inspect_ai`` is unavailable — the
#: attribution row's ``between_seed_stderr`` collapsing below this floor is the
#: signature of an all-identical (degenerate) audit.
BETWEEN_SEED_STDERR_FLOOR = 0.01


# ---------------------------------------------------------------------------
# Progress log — flushed tee (long-task-watcher: flushed echo, not buffered)
# ---------------------------------------------------------------------------


@dataclass
class ProgressLog:
    """A line-flushed tee to ``campaign-progress.log`` + stdout.

    Per the long-task-watcher skill: emit a *flushed* line per event so an
    operator tailing the file (``tail -F``) sees live progress, never a buffered
    blob at the end. Each ``emit`` is timestamped and ``flush()``-ed immediately.
    """

    path: Path
    _fh: Any = field(default=None, init=False, repr=False)

    def __enter__(self) -> ProgressLog:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None

    def emit(self, message: str) -> None:
        """Write one timestamped line to the log file + stdout, flushed."""
        line = f"{_utc_now_iso()} {message}"
        print(line, flush=True)
        if self._fh is not None:
            self._fh.write(line + "\n")
            self._fh.flush()


def _utc_now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Env setup (campaign-procedure.md §5 / operator handoff)
# ---------------------------------------------------------------------------


def _resolve_pool_target_dims(pool_dir: Path) -> dict[str, float]:
    """Union the ``target_dims`` declared by a seed pool's seeds.

    PR-CAMPAIGN-TARGET-DIM (2026-06-04). The CYCLE_INPUT_POOL's seeds are
    difficulty-calibrated to probe a specific judge dim (e.g. ``broken_tool_use``);
    each seed carries that dim in its YAML front-matter ``target_dims``. This walks
    every ``*.md`` seed in ``pool_dir``, unions their parsed ``target_dims`` (reusing
    ``plugins.petri_audit.pool_validation._seed_target_dims`` — the SAME frontmatter
    parser the pool-dim guard uses, no second YAML reader), and returns
    ``{dim: 1.0 for dim in sorted(dims)}``.

    The value is a NOMINAL hint only — ``train.py::_resolve_targeted_dims`` reads
    just the KEYS of ``GEODE_SIL_EXPECTED_DIM`` (intersected with ``DIM_WEIGHTS``)
    to pick the promote gate's targeted sub-fitness surface; the magnitude is never
    consulted. The dim set is therefore POOL-DERIVED, never a hardcoded constant.

    Graceful: an empty pool, a missing dir, seeds with no ``target_dims``, or
    malformed front-matter all yield ``{}`` (``_seed_target_dims`` already swallows
    a bad seed to ``[]``) — and the import itself is guarded, so a packaged distro
    without ``plugins.petri_audit`` degrades to ``{}``. Never raises.
    """
    try:
        from plugins.petri_audit.pool_validation import _seed_target_dims
    except ImportError:
        return {}
    if not pool_dir.is_dir():
        return {}
    dims: set[str] = set()
    # ``rglob`` (not ``glob``) — the seed-select contract supports a hierarchical
    # seed tree, so a nested seed must not hide its target dim (mirrors
    # ``validate_pool_target_dims``).
    for seed_md in sorted(pool_dir.rglob("*.md")):
        dims.update(_seed_target_dims(seed_md))
    return dict.fromkeys(sorted(dims), 1.0)


def build_campaign_env(
    *,
    promote_policy: str | None = None,
    promote_policy_seed: int | None = None,
    audit_max_samples: int = DEFAULT_AUDIT_MAX_SAMPLES,
    audit_max_connections: int = DEFAULT_AUDIT_MAX_CONNECTIONS,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Compose the env passed to a ``train.py`` subprocess / cycle.

    Starts from ``base_env`` (default ``os.environ``) so the operator's shell
    wrapper export of ``ANTHROPIC_API_KEY`` flows through, then layers the
    campaign-fixed env.

    ``promote_policy`` / ``promote_policy_seed`` are *authoritative*: when
    supplied they are set, and when ``None`` the corresponding env var is
    explicitly REMOVED (not merely left alone). This matters because the base env
    may carry a stale ``GEODE_PROMOTE_POLICY`` / ``GEODE_PROMOTE_POLICY_SEED`` from
    the operator's shell — a gen-0 baseline run must inherit NO arm, and the
    ``gate`` / ``never`` arms must inherit NO seed (else `_resolve_promote_policy`
    / `_resolve_promote_policy_seed` would pick up the stale env, which is
    highest-precedence, and the ledger would record a wrong arm / seed).

    ``GEODE_SIL_EXPECTED_DIM`` (PR-CAMPAIGN-TARGET-DIM, 2026-06-04) is auto-resolved
    BY DEFAULT from the CYCLE_INPUT_POOL's seed ``target_dims`` — gate parity with
    the inner-loop runner, which already env-propagates the targeted dim so the
    promote gate scores the TARGETED sub-fitness (``train.py::_resolve_targeted_dims``)
    on the dim the difficulty pool actually probes, instead of the diluted full
    18-dim aggregate (near-saturation washout). An EXPLICIT operator-set
    ``GEODE_SIL_EXPECTED_DIM`` in ``base_env`` is RESPECTED (never overwritten). When
    the pool yields no target dims (empty / missing / malformed) the var is left
    UNSET → ``train.py`` falls back to the v1 full-aggregate gate (backward-compatible).
    """
    env = dict(base_env if base_env is not None else os.environ)
    env["GEODE_CODEX_OAUTH_POLL_DISABLED"] = "1"
    env["AUTORESEARCH_SEED_SELECT"] = str(CYCLE_INPUT_POOL)
    env["GEODE_HELD_OUT_BENCH"] = str(HELD_OUT_BENCH)
    env["GEODE_AUDIT_MAX_SAMPLES"] = str(audit_max_samples)
    env["GEODE_AUDIT_MAX_CONNECTIONS"] = str(audit_max_connections)
    # The AUTORESEARCH_* aliases are tier-2 in train.py's resolvers, so a stale
    # alias would shadow our removal of the GEODE_* var — clear both names.
    if promote_policy is not None:
        env["GEODE_PROMOTE_POLICY"] = promote_policy
    else:
        env.pop("GEODE_PROMOTE_POLICY", None)
        env.pop("AUTORESEARCH_PROMOTE_POLICY", None)
    if promote_policy_seed is not None:
        env["GEODE_PROMOTE_POLICY_SEED"] = str(promote_policy_seed)
    else:
        env.pop("GEODE_PROMOTE_POLICY_SEED", None)
        env.pop("AUTORESEARCH_PROMOTE_POLICY_SEED", None)
    # Auto-resolve the targeted dims from the selection pool — gate parity with the
    # inner-loop runner (``runner.py`` env-propagates ``GEODE_SIL_EXPECTED_DIM``).
    # Respect an explicit operator override: the mere PRESENCE of the key in
    # ``base_env`` means the operator set it — never overwrite it, regardless of
    # value. A deliberately BLANK value is a valid override too (``train.py::
    # _resolve_targeted_dims`` reads ``"".strip()`` as "no targeting → full
    # aggregate"), so we must not second-guess it as stale. When the key is absent
    # we set it from the pool; when the pool yields no dims we leave it UNSET
    # (graceful full-aggregate fallback).
    if "GEODE_SIL_EXPECTED_DIM" not in env:
        target_dims = _resolve_pool_target_dims(CYCLE_INPUT_POOL)
        if target_dims:
            env["GEODE_SIL_EXPECTED_DIM"] = json.dumps(target_dims, ensure_ascii=False)
    return env


# ---------------------------------------------------------------------------
# SoT snapshot / restore (campaign-procedure.md §6 — matched gen-0 reset)
# ---------------------------------------------------------------------------

#: Glob patterns under the tracked SoT (``core/self_improving/state/``) that make
#: up the full scaffold SoT a matched reset round-trips (campaign-procedure.md §1).
_SNAPSHOT_SOURCES: tuple[tuple[Path, str], ...] = (
    (POLICIES_DIR, "*.json"),
    (POLICIES_DIR, "*.jsonl"),
)


def snapshot_sot(dest_dir: Path) -> list[Path]:
    """Copy the full scaffold SoT into ``dest_dir`` for a matched reset.

    Captures every tracked ``core/self_improving/state/policies/*.{json,jsonl}``
    plus the runtime ``baseline.json``. Returns the destination paths written. Dest
    dir is wiped first so a re-snapshot is a clean overwrite (never a merge of a
    stale snapshot with a fresh one).
    """
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    policies_dest = dest_dir / "policies"
    policies_dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for src_dir, pattern in _SNAPSHOT_SOURCES:
        if not src_dir.exists():
            continue
        for src in sorted(src_dir.glob(pattern)):
            dst = policies_dest / src.name
            shutil.copy2(src, dst)
            written.append(dst)
    if BASELINE_JSON.exists():
        dst = dest_dir / "baseline.json"
        shutil.copy2(BASELINE_JSON, dst)
        written.append(dst)
    return written


def restore_sot(snapshot_dir: Path) -> list[Path]:
    """Restore the scaffold SoT from a ``snapshot_sot`` directory — an EXACT
    matched reset.

    Round-trips ``snapshot_sot`` exactly: the policy files are copied back into the
    tracked ``core/self_improving/state/policies/`` and ``baseline.json`` back into
    the runtime root. Crucially this is a *mirror*, not an overlay: any
    live ``policies/*.{json,jsonl}`` file that is NOT in the snapshot is DELETED,
    so an earlier arm that created a new policy file (e.g. the gate arm inserting
    ``wrapper-sections.json`` where gen-0 had only ``hyperparam.json``) cannot
    contaminate the next arm's matched start (Codex MCP finding #1). Returns the
    list of restored live paths. ``FileNotFoundError`` if the snapshot dir is
    absent (a matched reset must be exact).
    """
    if not snapshot_dir.exists():
        raise FileNotFoundError(
            f"gen-0 snapshot dir {snapshot_dir} missing — cannot do a matched arm reset"
        )
    restored: list[Path] = []
    policies_src = snapshot_dir / "policies"
    POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_names = {p.name for p in policies_src.glob("*")} if policies_src.exists() else set()
    # Remove orphan live policy files absent from the snapshot (mirror semantics).
    for pattern in ("*.json", "*.jsonl"):
        for live in POLICIES_DIR.glob(pattern):
            if live.name not in snapshot_names:
                live.unlink()
    if policies_src.exists():
        for src in sorted(policies_src.glob("*")):
            dst = POLICIES_DIR / src.name
            shutil.copy2(src, dst)
            restored.append(dst)
    baseline_src = snapshot_dir / "baseline.json"
    if baseline_src.exists():
        # baseline.json is RUNTIME (its parent is the runtime root, NOT the
        # tracked STATE_DIR) post PR-STATE-SOT-RUNTIME-SPLIT — mkdir the actual
        # destination parent so the copy never fails on a fresh ~/.geode.
        BASELINE_JSON.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline_src, BASELINE_JSON)
        restored.append(BASELINE_JSON)
    return restored


# ---------------------------------------------------------------------------
# Attribution-row reads (collect the per-cycle / per-baseline fitness signal)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CycleSignal:
    """The fitness signal one cycle / baseline run produced, read from the
    newest ``kind="attribution"`` row in ``mutations.jsonl``."""

    held_out_fitness: float | None
    fitness: float | None
    fitness_delta: float | None
    promote_policy: str | None
    source: str | None
    between_seed_stderr: float | None


def count_attribution_rows(path: Path | None = None) -> int:
    """Count ``kind="attribution"`` rows currently in ``mutations.jsonl``.

    Captured BEFORE a run so :func:`read_latest_attribution` can require that a
    NEW row was appended after the run started (Codex MCP finding #2): a run that
    wrote no attribution row (a ``--dry-run``, a held-out failure, or a nonzero
    audit swallowed by the runner) must NOT silently reuse the prior cycle's stale
    row as if it were this cycle's signal.
    """
    target = path if path is not None else MUTATIONS_JSONL
    return sum(1 for row in iter_jsonl(target) if row.get("kind") == "attribution")


def read_latest_attribution(path: Path | None = None, *, min_rows: int = 0) -> CycleSignal | None:
    """Read the newest ``kind="attribution"`` row from ``mutations.jsonl``.

    Returns ``None`` when no attribution row exists yet (fresh repo / a cycle
    whose audit produced no row). Reads ``fitness`` from ``fitness_after`` (the
    attribution schema's name for the cycle's measured fitness), falling back to
    a bare ``fitness`` key for forward-compat.

    ``min_rows`` is the row count captured BEFORE the run (via
    :func:`count_attribution_rows`). The newest row is returned only when the
    current attribution-row count EXCEEDS ``min_rows`` — i.e. this run actually
    appended a fresh row. When the count did not advance, the run produced no new
    signal and ``None`` is returned (no stale-row reuse). ``min_rows=0`` (default)
    keeps the unconditional "newest row" behaviour for direct callers / tests.
    """
    target = path if path is not None else MUTATIONS_JSONL
    latest: dict[str, Any] | None = None
    seen = 0
    for row in iter_jsonl(target):
        if row.get("kind") == "attribution":
            latest = row
            seen += 1
    if latest is None or seen <= min_rows:
        return None
    return CycleSignal(
        held_out_fitness=_as_float(latest.get("held_out_fitness")),
        fitness=_as_float(latest.get("fitness_after", latest.get("fitness"))),
        fitness_delta=_as_float(latest.get("fitness_delta")),
        promote_policy=_as_str(latest.get("promote_policy")),
        source=_as_str(latest.get("source")),
        between_seed_stderr=_as_float(latest.get("between_seed_stderr")),
    )


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        # Reject non-finite (NaN / ±Inf): not a valid measurement, and json.dumps
        # would otherwise write non-standard JSON into baseline.json (Codex MCP
        # finding — graceful boundary at the schema-typed cast).
        return num if math.isfinite(num) else None
    return None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


# ---------------------------------------------------------------------------
# FITNESS_RESULT stdout parse (gen-0 per-measure raw dim_means)
# ---------------------------------------------------------------------------

#: The structured stdout sentinel ``core/self_improving/train.py`` emits on the success
#: path (``train.py`` ~L4786): ``FITNESS_RESULT: {"fitness": ..., "dim_means":
#: {...}, "dim_stderr": {...}, "audit_run_id": ...}``. The campaign tail-parses
#: it to recover each gen-0 measure's RAW per-dim ``dim_means`` (the attribution
#: row in ``mutations.jsonl`` carries only the baseline-relative ``observed_dim``
#: delta, not the raw means), so the gen-0 K-mean can be computed from the
#: identical-scaffold repeats.
_FITNESS_RESULT_PREFIX = "FITNESS_RESULT: "


def parse_fitness_result_dims(stdout: str | None) -> dict[str, float] | None:
    """Parse the ``dim_means`` dict from a ``train.py`` ``FITNESS_RESULT:`` line.

    Takes the LAST ``FITNESS_RESULT:``-prefixed line (a single ``train.py`` run
    emits exactly one on success; keying on the *last* one keeps the contract
    "last sentinel wins" robust to interleaved log noise) and returns its
    ``dim_means`` as a ``{dim: float}`` dict. Returns ``None`` when no sentinel
    line exists, the last one is not parseable JSON / has no ``dim_means`` dict,
    or no numeric dim survives (a ``--dry-run`` / failed run emits none) — so a
    caller skips that measure rather than fold a phantom zero-dim row into the
    K-mean. A later malformed sentinel is NOT silently masked by an earlier valid
    one (Codex MCP finding): the last sentinel line is authoritative. Non-numeric
    / non-finite dim values are dropped (graceful per the contract-boundary rule —
    every schema-typed cast is guarded, not just the outer parse).
    """
    if not stdout:
        return None
    last_payload: str | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith(_FITNESS_RESULT_PREFIX):
            last_payload = line[len(_FITNESS_RESULT_PREFIX) :].strip()
    if last_payload is None:
        return None
    try:
        obj = json.loads(last_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    dim_means_raw = obj.get("dim_means")
    if not isinstance(dim_means_raw, dict):
        return None
    parsed: dict[str, float] = {}
    for key, value in dim_means_raw.items():
        num = _as_float(value)
        if isinstance(key, str) and num is not None:
            parsed[key] = num
    return parsed or None


# ---------------------------------------------------------------------------
# Degeneracy guard (campaign-procedure.md §5.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardResult:
    """Outcome of the per-cycle degeneracy guard."""

    ok: bool
    reason: str


def newest_eval_path(logs_dir: Path = PETRI_LOGS_DIR) -> Path | None:
    """Return the most-recently-modified ``*.eval`` in ``logs_dir`` (skips the
    ``latest.eval`` pointer copy)."""
    if not logs_dir.exists():
        return None
    evals = [p for p in logs_dir.glob("*.eval") if p.name != "latest.eval"]
    if not evals:
        return None
    return max(evals, key=lambda p: p.stat().st_mtime)


def degeneracy_guard(
    *,
    logs_dir: Path = PETRI_LOGS_DIR,
    signal: CycleSignal | None = None,
) -> GuardResult:
    """Reject a degenerate audit (campaign-procedure.md §5.6).

    Primary path — read the newest ``.eval`` via ``inspect_ai.log.read_eval_log``
    and require: ``status == "success"`` AND ``samples > 0`` AND at least one
    sample carries ``> 0`` scored dims. A broken setup (auditor quota throttle →
    0 samples, all-zero dims) HALTs the campaign so it never burns the full run.

    Fallback path — when ``inspect_ai`` is unavailable (the import is guarded), or
    no ``.eval`` exists, fall back to the attribution row's
    ``between_seed_stderr`` ≥ ``BETWEEN_SEED_STDERR_FLOOR`` check (a collapsed
    stderr is the signature of an all-identical degenerate audit).
    """
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        return _degeneracy_guard_fallback(signal)

    eval_path = newest_eval_path(logs_dir)
    if eval_path is None:
        return _degeneracy_guard_fallback(signal)

    try:
        loaded = read_eval_log(str(eval_path))
    except Exception as exc:  # pragma: no cover — defensive read
        return GuardResult(ok=False, reason=f"eval read failed: {exc}")

    status = str(getattr(loaded, "status", "?"))
    if status != "success":
        return GuardResult(ok=False, reason=f"eval status={status!r} (not success)")
    samples = list(getattr(loaded, "samples", None) or [])
    if not samples:
        return GuardResult(ok=False, reason="eval has 0 samples")
    scored_dims = _count_scored_dims(samples)
    if scored_dims <= 0:
        return GuardResult(ok=False, reason="eval has 0 scored dims")
    return GuardResult(ok=True, reason=f"status=success samples={len(samples)} dims={scored_dims}")


def _count_scored_dims(samples: Sequence[Any]) -> int:
    """Count distinct scored dims across the samples — mirrors
    ``plugins/petri_audit/eval_archive.py`` (``scores["audit_judge"].value`` is a
    per-dim dict)."""
    dims: set[str] = set()
    for s in samples:
        scores = getattr(s, "scores", None) or {}
        judge = scores.get("audit_judge") if isinstance(scores, dict) else None
        value = getattr(judge, "value", None)
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool):
                    dims.add(k)
    return len(dims)


def _degeneracy_guard_fallback(signal: CycleSignal | None) -> GuardResult:
    if signal is None or signal.between_seed_stderr is None:
        # No eval and no stderr signal — cannot confirm health; HALT rather than
        # silently proceed on a broken setup.
        return GuardResult(
            ok=False,
            reason="no eval log and no between_seed_stderr — cannot confirm audit health",
        )
    if signal.between_seed_stderr < BETWEEN_SEED_STDERR_FLOOR:
        return GuardResult(
            ok=False,
            reason=(
                f"between_seed_stderr {signal.between_seed_stderr:.4f} "
                f"< floor {BETWEEN_SEED_STDERR_FLOOR} (degenerate all-identical audit)"
            ),
        )
    return GuardResult(
        ok=True,
        reason=f"fallback ok (between_seed_stderr={signal.between_seed_stderr:.4f})",
    )


# ---------------------------------------------------------------------------
# propose-guard (campaign-procedure.md §5.1 — re-propose on guarded rejection)
# ---------------------------------------------------------------------------


def propose_with_guard(
    runner: SelfImprovingLoopRunner,
    *,
    max_attempts: int = DEFAULT_MAX_PROPOSE_ATTEMPTS,
    progress: ProgressLog | None = None,
) -> Proposal | None:
    """Call ``runner.propose()`` up to ``max_attempts`` times.

    Re-proposes on a guarded rejection:

    * ``RepetitiveMutationError`` — the dedup / axis-family guard fired.
    * a ``ValueError`` from the measurement-hyperparam rejection — the mutator
      proposed ``seed_limit`` / ``max_turns`` / ``dim_set`` (now FIXED), or any
      other parse/validation ``ValueError``.

    Returns the first clean ``Proposal``; returns ``None`` (the cycle is a
    logged no-op, NOT a crash) when the attempts are exhausted. ``RepetitiveMutationError``
    subclasses ``ValueError``, so we catch the subclass first to log it
    distinctly, then the broad ``ValueError`` for measurement-hyperparam /
    malformed-JSON rejections.
    """
    import time

    from core.self_improving.loop.mutate.cli_subprocess import CliInvocationError
    from core.self_improving.loop.mutate.mutator_feedback import RepetitiveMutationError

    for attempt in range(1, max_attempts + 1):
        try:
            return runner.propose()
        except RepetitiveMutationError as exc:
            if progress is not None:
                progress.emit(f"propose-guard attempt {attempt}/{max_attempts}: repetitive — {exc}")
        except CliInvocationError as exc:
            # PR-GATE-RESILIENCE — the mutator CLI (codex) failing (transient blip OR
            # subscription usage-limit) must NOT crash the whole arm and forfeit the
            # cycles already run. Back off + retry; if every attempt fails the cycle
            # becomes a logged no-op SKIP, identical to a propose-guard exhaustion, so
            # the arm keeps its prior-cycle evidence. (Recovered from a prior-session
            # stash; still load-bearing whenever the mutator routes through the codex
            # CLI rather than the openai_source PAYG API path.)
            if progress is not None:
                progress.emit(
                    f"propose-guard attempt {attempt}/{max_attempts}: mutator CLI failed — "
                    f"{str(exc)[:160]}"
                )
            time.sleep(15.0)
        except ValueError as exc:
            if progress is not None:
                progress.emit(f"propose-guard attempt {attempt}/{max_attempts}: rejected — {exc}")
    if progress is not None:
        progress.emit(f"propose-guard exhausted {max_attempts} attempts — cycle skipped as no-op")
    return None


# ---------------------------------------------------------------------------
# gen-0 K-repeat baseline + noise band (campaign-procedure.md §4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoiseBand:
    """The gen-0 noise band — mean ± stderr of K held-out fitness repeats."""

    k: int
    held_out_values: tuple[float, ...]
    fitness_values: tuple[float, ...]
    mean: float | None
    stderr: float | None

    def summary(self) -> str:
        if self.mean is None or self.stderr is None:
            return (
                f"gen-0 noise band: K={self.k} "
                f"collected={len(self.held_out_values)} (no held-out values)"
            )
        return (
            f"gen-0 noise band: K={self.k} held_out_mean={self.mean:.4f} "
            f"stderr={self.stderr:.4f} values={[round(v, 4) for v in self.held_out_values]}"
        )


def compute_noise_band(
    held_out_values: Sequence[float],
    fitness_values: Sequence[float],
    *,
    k: int,
) -> NoiseBand:
    """Mean ± stderr of the K held-out repeats (campaign-procedure.md §4)."""
    held = tuple(float(v) for v in held_out_values)
    fit = tuple(float(v) for v in fitness_values)
    if not held:
        return NoiseBand(k=k, held_out_values=held, fitness_values=fit, mean=None, stderr=None)
    mean = statistics.fmean(held)
    stderr = statistics.stdev(held) / (len(held) ** 0.5) if len(held) >= 2 else 0.0
    return NoiseBand(k=k, held_out_values=held, fitness_values=fit, mean=mean, stderr=stderr)


def aggregate_dim_means(
    per_measure_dim_means: Sequence[dict[str, float]],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Per-dim mean + across-K sample stderr over the K gen-0 measures.

    Each element of ``per_measure_dim_means`` is one gen-0 measure's RAW
    ``dim_means`` (parsed from its ``FITNESS_RESULT:`` stdout line). For every dim
    that appears in AT LEAST ONE measure, the mean is a TRIMMED mean: when ≥ 4
    measures are present for the dim, the single highest and single lowest are
    dropped and the middle ``n−2`` are averaged (operator request 2026-06-01 —
    a Petri dim's per-repeat scores can be bimodal / outlier-prone, so one
    lucky-high + one lucky-low repeat would otherwise skew both ``prior_raw`` and
    the noise band). With < 4 present values trimming is not meaningful, so it
    falls back to the plain mean. The stderr is the sample stderr over the SAME
    (trimmed or plain) value set, ``stdev / sqrt(n)`` when ``n >= 2`` else ``0.0``.
    ``present_count`` records the ORIGINAL number of measures that contributed to
    each dim (NOT the post-trim count) so the caller's partial-coverage warning
    still compares against ``K``. Returns ``(mean_dims, stderr_dims,
    present_count_dims)``.

    This is the CORE fix: ``baseline.json``'s ``raw.dim_means`` must be a robust
    central estimate across the K identical-scaffold repeats, not the single
    (possibly lucky-high / lucky-low) bootstrap measure — otherwise every cycle's
    ``compute_fitness(cycle_dims)`` vs ``compute_fitness(baseline_dims)`` gate
    compares against an outlier and the campaign is structurally near-0-approve.
    """
    dims: set[str] = set()
    for measure in per_measure_dim_means:
        dims.update(measure.keys())
    mean_dims: dict[str, float] = {}
    stderr_dims: dict[str, float] = {}
    present_count: dict[str, int] = {}
    for dim in sorted(dims):
        present = [m[dim] for m in per_measure_dim_means if dim in m]
        if not present:  # pragma: no cover — dims came from the measures
            continue
        present_count[dim] = len(present)
        # Trimmed mean: drop the single highest + single lowest repeat when
        # ≥ 4 are present (operator request 2026-06-01). Below 4, trimming
        # would leave < 2 points, so fall back to the plain mean.
        trimmed = sorted(present)[1:-1] if len(present) >= 4 else present
        mean_dims[dim] = statistics.fmean(trimmed)
        stderr_dims[dim] = (
            statistics.stdev(trimmed) / (len(trimmed) ** 0.5) if len(trimmed) >= 2 else 0.0
        )
    return mean_dims, stderr_dims, present_count


def write_kmean_baseline(
    mean_dims: dict[str, float],
    stderr_dims: dict[str, float],
    *,
    baseline_path: Path | None = None,
) -> bool:
    """Overwrite ``baseline.json``'s ``raw.dim_means`` + ``raw.dim_stderr`` with
    the K-aggregate, preserving the rest of the schema.

    The bootstrap ``train.py`` run already wrote ``baseline.json`` from its SINGLE
    measure (1st of K). This rewrites ONLY ``raw.dim_means`` (→ K-mean) and
    ``raw.dim_stderr`` (→ across-K per-dim sample stderr, the real noise band),
    leaving every other field intact: top-level ``schema_version`` / ``session_id``
    / ``commit`` / ``ts_utc``, ``axes``, and the rest of ``raw``
    (``sample_count`` / ``measurement_modality`` / ``eval_archive`` /
    ``fitness_stderr`` / ``rubric_version`` / …). So the promote gate's
    ``prior_raw = compute_fitness(raw.dim_means)`` reads the robust central
    estimate.

    Returns ``True`` when the rewrite landed, ``False`` when there is no
    ``baseline.json`` to patch (the bootstrap never established one — e.g. all K
    runs failed) or no aggregate dims were collected (nothing to write).
    """
    target = baseline_path if baseline_path is not None else BASELINE_JSON
    if not mean_dims:
        return False
    if not target.exists():
        return False
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(payload, dict):
        return False
    raw_block = payload.get("raw")
    if not isinstance(raw_block, dict):
        # A bootstrap baseline.json with no (or a non-dict) ``raw`` block is
        # malformed — the bootstrap train.py run did not establish the expected
        # schema. Refuse to fabricate a ``raw`` block (that would violate the
        # "overwrite ONLY raw.dim_means + raw.dim_stderr" contract and mask the
        # broken bootstrap); return False so the caller logs written=False
        # (Codex MCP finding — preserve-only contract).
        return False
    raw_block["dim_means"] = {dim: float(v) for dim, v in mean_dims.items()}
    raw_block["dim_stderr"] = {dim: float(v) for dim, v in stderr_dims.items()}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def run_gen0_baseline(
    *,
    k: int,
    dry_run: bool,
    audit_max_samples: int,
    audit_max_connections: int,
    progress: ProgressLog,
    train_runner: Any | None = None,
) -> NoiseBand:
    """Run K manual measurements of the genesis scaffold + compute the noise band.

    Each repeat spawns ``uv run python -m core.self_improving.train`` (real audit, no
    mutation, ``source="manual"``; the 1st run bootstrap-establishes
    ``baseline.json``). After each run the newest ``kind="attribution"`` row is
    read for its ``held_out_fitness`` + ``fitness``.

    ``train_runner`` is injected so tests can stub the subprocess — it is a
    callable ``(env) -> subprocess.CompletedProcess``. The default spawns the
    real ``train.py`` subprocess.
    """
    runner_fn = train_runner if train_runner is not None else _spawn_train_subprocess
    held_out_values: list[float] = []
    fitness_values: list[float] = []
    # Each gen-0 measure's RAW per-dim ``dim_means`` (parsed from its
    # ``FITNESS_RESULT:`` stdout line) — the K-mean of these replaces
    # ``baseline.json``'s single-bootstrap ``raw.dim_means`` so the promote gate
    # compares cycles against a robust central estimate, not a lucky outlier.
    per_measure_dim_means: list[dict[str, float]] = []
    for i in range(1, k + 1):
        env = build_campaign_env(
            audit_max_samples=audit_max_samples,
            audit_max_connections=audit_max_connections,
        )
        progress.emit(f"gen-0 baseline repeat {i}/{k}: spawning train.py (dry_run={dry_run})")
        rows_before = count_attribution_rows()
        result = runner_fn(env=env, dry_run=dry_run)
        if getattr(result, "returncode", 0) != 0:
            progress.emit(
                f"gen-0 baseline repeat {i}/{k}: train.py exited "
                f"{getattr(result, 'returncode', '?')} — skipping signal read"
            )
            continue
        # Recover this measure's raw dim_means from the FITNESS_RESULT sentinel.
        measure_dims = parse_fitness_result_dims(getattr(result, "stdout", None))
        if measure_dims:
            per_measure_dim_means.append(measure_dims)
        # Require a NEW attribution row from THIS run (no stale-row reuse).
        signal = read_latest_attribution(min_rows=rows_before)
        if signal is None:
            progress.emit(
                f"gen-0 baseline repeat {i}/{k}: no NEW attribution row "
                "(run wrote none — e.g. dry-run / held-out skip)"
            )
            continue
        if signal.held_out_fitness is not None:
            held_out_values.append(signal.held_out_fitness)
        if signal.fitness is not None:
            fitness_values.append(signal.fitness)
        progress.emit(
            f"gen-0 baseline repeat {i}/{k}: held_out={signal.held_out_fitness} "
            f"fitness={signal.fitness} source={signal.source} "
            f"dims_parsed={len(measure_dims) if measure_dims else 0}"
        )
    band = compute_noise_band(held_out_values, fitness_values, k=k)
    progress.emit(band.summary())
    # CORE FIX — rewrite baseline.json's raw.dim_means to the K-mean dims (and
    # raw.dim_stderr to the across-K per-dim sample stderr), so prior_raw =
    # compute_fitness(mean_dims) is a robust central estimate, not the single
    # lucky-high/low bootstrap measure (every other field is preserved).
    #
    # Under --dry-run the K-mean write is SKIPPED: train.py --dry-run emits a
    # FITNESS_RESULT line with SYNTHETIC dims (so per_measure_dim_means is
    # populated), but persisting those would freeze a synthetic baseline — the
    # same reason train.py short-circuits its own promote gate on dry-run. The
    # smoke must leave baseline.json untouched.
    if dry_run:
        progress.emit(
            f"gen-0 K-mean baseline: dry-run — skipped baseline.json rewrite "
            f"(parsed {len(per_measure_dim_means)}/{k} synthetic FITNESS_RESULT measures)"
        )
    elif per_measure_dim_means:
        mean_dims, stderr_dims, present_count = aggregate_dim_means(per_measure_dim_means)
        wrote = write_kmean_baseline(mean_dims, stderr_dims)
        partial = sorted(d for d, c in present_count.items() if c < len(per_measure_dim_means))
        progress.emit(
            f"gen-0 K-mean baseline: collected {len(per_measure_dim_means)}/{k} measures, "
            f"{len(mean_dims)} dims; baseline.json raw.dim_means←K-mean "
            f"(written={wrote})" + (f"; partial-coverage dims={partial}" if partial else "")
        )
    else:
        progress.emit(
            f"gen-0 K-mean baseline: no FITNESS_RESULT dims parsed from {k} measures "
            "(all failed) — baseline.json raw.dim_means left as bootstrap"
        )
    return band


def _spawn_train_subprocess(
    *, env: dict[str, str], dry_run: bool
) -> subprocess.CompletedProcess[str]:
    """Spawn ``uv run python -m core.self_improving.train`` (real audit, no mutation)."""
    argv = ["uv", "run", "python", "-m", TRAIN_MODULE]
    if dry_run:
        argv.append("--dry-run")
    return subprocess.run(  # noqa: S603 — argv built from constants
        argv,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Async-first parallel orchestration with per-worker state isolation
# (S3 parallel + S5 stateless — PR-ASYNC-FIRST, 2026-06-03)
#
# The gen-0 K replicates and the NEVER + RANDOM control arms are
# PATH-INDEPENDENT: every replicate / cycle measures the SAME frozen
# baseline before any keep/revert, so there is no champion chain to
# corrupt by running them out of order. They fan out concurrently via
# ``asyncio.gather`` — each worker a SEPARATE ``train.py`` subprocess
# (its own GEODE runtime, its own process-local audit lane, its own state
# tree). Since PR-CAMPAIGN-CONCURRENT-CONTROL-ARMS (2026-06-04) the NEVER +
# RANDOM cycles fan out in ONE shared ``gather`` (``run_control_arms_async``),
# so the two control arms OVERLAP instead of running arm-by-arm — by default.
# The campaign's cross-worker concurrency is therefore purely
# orchestrator-level (the ``gather``); it does NOT depend on any in-process
# GEODE singleton (the audit lane stays the subscription-safe per-process
# ``max_concurrent=1`` — each worker runs exactly one audit, so that cap
# never gates the fan-out). Unbounded by design: with PAYG (``openai_source =
# "api_key"``, no per-minute rate limit) there is no reason to throttle the
# spawn count.
#
# State isolation mirrors the proven ``scripts/floor_sampler.sh`` pattern:
# each worker runs with its OWN ``GEODE_STATE_ROOT`` (a per-worker temp
# dir), seeded from the frozen baseline snapshot, so concurrent workers never
# race on the shared production trees (the in-repo tracked SoT + the ~/.geode
# runtime). Post PR-STATE-SOT-RUNTIME-SPLIT a worker's ``GEODE_STATE_ROOT``
# co-locates BOTH the tracked SoT and the runtime under ``$ENV/autoresearch`` so
# all of ``mutations.jsonl`` / ``baseline.json`` / ``policies/*`` land in the
# worker's own isolated tree.
# Each worker resolves ``core.paths.*`` (which read ``GEODE_STATE_ROOT`` at
# import time) under its isolated root, so its writes land in its own tree.
#
# The GATE arm is PATH-DEPENDENT (a promote mutates the champion + steers
# the next propose) and MUST stay the sequential ``run_arm`` path — it is
# never routed through this concurrent machinery.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerOutcome:
    """One path-independent worker's result (gen-0 replicate or control cycle).

    ``ok`` is the partial-failure flag the aggregators filter on: a worker that
    crashed / timed out / exited non-zero contributes NO dims and NO signal, and
    the aggregator logs it as a dropped worker (never silent truncation).

    ``transcript_path`` (S6) is THIS worker's ISOLATED RunTranscript jsonl (the
    one its ``train.py`` subprocess wrote to via ``GEODE_RUN_TRANSCRIPT_PATH`` so
    concurrent workers never race-append a shared file). The aggregator MERGES
    these per-worker files into the one campaign transcript after the gather.
    ``None`` for a worker that never got a path assigned (e.g. a seed failure
    before the env was built) or a resumed-from-checkpoint worker whose isolated
    tempdir is already gone — merge simply skips a missing/None file (graceful).
    """

    index: int
    ok: bool
    returncode: int
    dim_means: dict[str, float]
    signal: CycleSignal | None
    reason: str
    transcript_path: Path | None = None


# ---------------------------------------------------------------------------
# Resume checkpoint (S4 — crash-resumable path-independent workers)
#
# A long PAYG campaign fans K gen-0 replicates + N never/random cycles out as
# real Petri-audit subprocesses (minutes + spend each). If the campaign crashes
# after some workers finished, a naive re-run would re-measure ALL of them — and,
# worse, re-aggregate + re-overwrite ``baseline.json`` a second time. The
# checkpoint records WHICH workers COMPLETED successfully (their index + dims +
# floor signal) per worker GROUP (gen-0 / a control arm), keyed by ``run_id``, so
# a re-run skips the finished workers, re-runs only the missing ones, and
# aggregates the UNION. A ``kmean_written`` flag per gen-0 group makes the K-mean
# baseline write IDEMPOTENT (a second run is a no-op — no double-aggregation).
#
# Only ``ok=True`` workers are persisted: a dropped worker (crash / timeout /
# non-zero exit) is deliberately NOT checkpointed so a re-run RE-attempts it (it
# may succeed the second time). The marker lives under the gitignored
# ``state/campaign/runs/`` tree — a runtime resume artifact, never git history.
# ---------------------------------------------------------------------------

#: The checkpoint group key for the gen-0 K replicates (control arms key on their
#: own arm name — ``"never"`` / ``"random"``).
GEN0_CHECKPOINT_GROUP = "gen0"


def _serialise_worker(outcome: WorkerOutcome) -> dict[str, Any]:
    """Flatten a successful :class:`WorkerOutcome` to the JSON the checkpoint stores.

    Persists only what the aggregators consume on resume: the worker ``index``,
    its RAW ``dim_means``, and the floor signal's ``held_out_fitness`` + ``fitness``
    (the only two :class:`CycleSignal` fields :func:`run_gen0_baseline_async` /
    :func:`run_control_arms_async` read back). A reconstructed worker is marked
    ``ok=True`` with ``returncode=0`` and ``reason="resumed from checkpoint"``.
    """
    signal = outcome.signal
    return {
        "index": outcome.index,
        "dim_means": {dim: float(v) for dim, v in outcome.dim_means.items()},
        "held_out_fitness": signal.held_out_fitness if signal is not None else None,
        "fitness": signal.fitness if signal is not None else None,
    }


def _deserialise_worker(payload: dict[str, Any]) -> WorkerOutcome | None:
    """Rebuild a :class:`WorkerOutcome` from a checkpointed worker record.

    Returns ``None`` (the record is dropped, the worker RE-RUN) when the stored
    ``index`` is not a usable int — a corrupt checkpoint must never silently
    truncate the union or, worse, fabricate a phantom worker. ``dim_means`` /
    floor values are passed through the same graceful-boundary casts the live read
    path uses, so a malformed value becomes ``None`` rather than raising.
    """
    raw_index = payload.get("index")
    if not isinstance(raw_index, int) or isinstance(raw_index, bool):
        return None
    raw_dims = payload.get("dim_means")
    dim_means: dict[str, float] = {}
    if isinstance(raw_dims, dict):
        for dim, value in raw_dims.items():
            num = _as_float(value)
            if isinstance(dim, str) and num is not None:
                dim_means[dim] = num
    signal = CycleSignal(
        held_out_fitness=_as_float(payload.get("held_out_fitness")),
        fitness=_as_float(payload.get("fitness")),
        fitness_delta=None,
        promote_policy=None,
        source=None,
        between_seed_stderr=None,
    )
    return WorkerOutcome(
        index=raw_index,
        ok=True,
        returncode=0,
        dim_means=dim_means,
        signal=signal,
        reason="resumed from checkpoint",
    )


@dataclass
class RunCheckpoint:
    """A per-run resume marker: which path-independent workers COMPLETED.

    Keyed by ``run_id`` and persisted to ``<runs_dir>/<run_id>.json``. Each worker
    GROUP (``"gen0"`` or a control-arm name) holds the serialised successful
    outcomes (keyed by worker index, so a re-completion overwrites rather than
    duplicates) plus a ``kmean_written`` flag that makes the gen-0 K-mean baseline
    write idempotent. ``run_id=None`` short-circuits every method to a no-op so the
    pre-S4 callers / tests that pass no ``run_id`` keep the original behaviour
    (checkpointing is strictly opt-in).
    """

    run_id: str | None
    runs_dir: Path = field(default_factory=lambda: CAMPAIGN_RUNS_DIR)
    #: ``{group: {"completed": {index: record}, "kmean_written": bool}}``.
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.run_id is not None

    @property
    def path(self) -> Path:
        # Only meaningful when ``enabled``; guarded by every caller.
        return self.runs_dir / f"{self.run_id}.json"

    def load(self) -> RunCheckpoint:
        """Populate ``groups`` from disk if a checkpoint for ``run_id`` exists.

        A missing / unreadable / malformed file leaves ``groups`` empty (a fresh
        run), never raises — a corrupt marker degrades to "re-run everything"
        rather than crashing the campaign.
        """
        if not self.enabled or not self.path.exists():
            return self
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self
        if not isinstance(payload, dict):
            return self
        raw_groups = payload.get("groups")
        if isinstance(raw_groups, dict):
            for name, block in raw_groups.items():
                if isinstance(name, str) and isinstance(block, dict):
                    self.groups[name] = block
        return self

    def _group(self, group: str) -> dict[str, Any]:
        block = self.groups.setdefault(group, {})
        if not isinstance(block.get("completed"), dict):
            block["completed"] = {}
        if not isinstance(block.get("kmean_written"), bool):
            block["kmean_written"] = False
        return block

    def completed_indices(self, group: str) -> set[int]:
        """The worker indices already recorded complete for ``group`` (empty when
        disabled — every worker is then run)."""
        if not self.enabled:
            return set()
        completed = self._group(group).get("completed", {})
        result: set[int] = set()
        for key in completed:
            try:
                result.add(int(key))
            except (TypeError, ValueError):
                continue
        return result

    def resumed_outcomes(self, group: str) -> list[WorkerOutcome]:
        """Reconstruct the already-completed workers of ``group`` as outcomes the
        aggregator can union with the freshly-run ones (empty when disabled)."""
        if not self.enabled:
            return []
        completed = self._group(group).get("completed", {})
        outcomes: list[WorkerOutcome] = []
        for record in completed.values():
            if isinstance(record, dict):
                outcome = _deserialise_worker(record)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes

    def record_completed(self, group: str, outcomes: Sequence[WorkerOutcome]) -> None:
        """Persist the freshly-completed (``ok=True``) workers of ``group`` + flush
        to disk (a no-op when disabled)."""
        if not self.enabled:
            return
        completed = self._group(group)["completed"]
        for outcome in outcomes:
            if outcome.ok:
                completed[str(outcome.index)] = _serialise_worker(outcome)
        self._flush()

    def kmean_already_written(self, group: str) -> bool:
        """Whether the K-mean baseline was already aggregated+written for ``group``
        (always ``False`` when disabled — the write then always runs)."""
        if not self.enabled:
            return False
        return bool(self._group(group).get("kmean_written"))

    def mark_kmean_written(self, group: str) -> None:
        """Flag ``group``'s K-mean baseline write as done + flush (no-op when
        disabled), so a resume skips the re-aggregation/re-write (idempotent)."""
        if not self.enabled:
            return
        self._group(group)["kmean_written"] = True
        self._flush()

    def _flush(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"run_id": self.run_id, "groups": self.groups}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )


def _seed_isolated_state_root(worker_root: Path, snapshot_dir: Path) -> None:
    """Seed a per-worker ``GEODE_STATE_ROOT`` tree from the frozen gen-0 snapshot.

    Lays out ``<worker_root>/autoresearch/{policies/*, baseline.json}`` exactly as
    :func:`restore_sot` would lay out the production root — a matched frozen-baseline
    reset — but into the ISOLATED root so concurrent workers do not contend on the
    shared production SoT. ``mutations.jsonl`` is deliberately NOT copied: each
    worker starts with an empty attribution ledger so the row it appends is
    unambiguously its own (no stale-row reuse across workers). Raises
    ``FileNotFoundError`` when the snapshot dir is absent (a matched reset must be
    exact, mirroring :func:`restore_sot`).
    """
    if not snapshot_dir.exists():
        raise FileNotFoundError(
            f"gen-0 snapshot dir {snapshot_dir} missing — cannot seed an isolated worker root"
        )
    worker_state_dir = worker_root / "autoresearch"
    worker_policies = worker_state_dir / "policies"
    worker_policies.mkdir(parents=True, exist_ok=True)
    policies_src = snapshot_dir / "policies"
    if policies_src.exists():
        for src in sorted(policies_src.glob("*")):
            shutil.copy2(src, worker_policies / src.name)
    baseline_src = snapshot_dir / "baseline.json"
    if baseline_src.exists():
        shutil.copy2(baseline_src, worker_state_dir / "baseline.json")


def _build_worker_env(
    worker_root: Path,
    *,
    promote_policy: str | None,
    promote_policy_seed: int | None,
    audit_max_samples: int,
    audit_max_connections: int,
    transcript_path: Path | None = None,
    worker_id: str | None = None,
) -> dict[str, str]:
    """Build a concurrent worker's subprocess env.

    Layers the campaign-fixed env (:func:`build_campaign_env` — seed-pool +
    held-out + PAYG knobs + the authoritative promote-policy / seed) and the
    isolated ``GEODE_STATE_ROOT`` so the worker's ``train.py`` resolves every
    ``core.paths.*`` constant under its OWN tree. ``VIRTUAL_ENV`` /
    ``PATH`` are inherited from ``os.environ`` (the parent campaign process runs
    inside the venv), so the child ``sys.executable -m core.self_improving.train``
    resolves the venv's interpreter — never the system python — mirroring the
    venv-activation step ``scripts/floor_sampler.sh`` performs to avoid the
    ``ModuleNotFoundError: core`` a system-python child would hit.

    S6 (transcript isolation): ``transcript_path`` redirects the worker's
    RunTranscript to an ISOLATED per-worker jsonl (``GEODE_RUN_TRANSCRIPT_PATH``)
    so concurrent workers never race-append the shared home-dir transcript, and
    ``worker_id`` (``GEODE_RUN_WORKER_ID``) stamps every event payload so the
    post-gather merge is attributable. The home-dir ``GLOBAL_AUTORESEARCH_HANDOFF_DIR``
    is keyed off ``GEODE_HOME`` (``~/.geode``), NOT ``GEODE_STATE_ROOT``, so the
    per-worker ``GEODE_STATE_ROOT`` alone does NOT isolate the transcript — this
    explicit redirect is required.
    """
    env = build_campaign_env(
        promote_policy=promote_policy,
        promote_policy_seed=promote_policy_seed,
        audit_max_samples=audit_max_samples,
        audit_max_connections=audit_max_connections,
    )
    env["GEODE_STATE_ROOT"] = str(worker_root)
    if transcript_path is not None:
        env["GEODE_RUN_TRANSCRIPT_PATH"] = str(transcript_path)
    if worker_id is not None:
        env["GEODE_RUN_WORKER_ID"] = worker_id
    return env


async def _spawn_train_subprocess_async(
    *,
    env: dict[str, str],
    dry_run: bool,
    per_audit_timeout: float | None,
) -> subprocess.CompletedProcess[str]:
    """Async sibling of :func:`_spawn_train_subprocess` — drop-in shape.

    Spawns ``<venv python> -m core.self_improving.train`` via
    ``asyncio.create_subprocess_exec`` (so N workers run concurrently on one event
    loop), captures BOTH stdout+stderr, and applies the TIGHT ``per_audit_timeout``
    so a hung worker is killed within seconds of overrun rather than holding for
    the in-process budget the child ``train.py`` would otherwise wait out — this
    subprocess-level kill is where the async-first harness enforces the hang
    bound. On timeout the child is killed + reaped and a
    :class:`subprocess.CompletedProcess` with ``returncode=-1`` is returned (the
    aggregator filters it out as a dropped worker — a timed-out replicate must not
    crash the whole gather). ``sys.executable`` is the venv interpreter the parent
    campaign runs under, so the child resolves the ``core`` package.
    """
    argv = [sys.executable, "-m", TRAIN_MODULE]
    if dry_run:
        argv.append("--dry-run")
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(REPO_ROOT),
        # Own process group/session (POSIX): the worker ``train.py`` itself spawns
        # ``geode audit`` → ``inspect eval`` (the PAID audit) as a grandchild via
        # ``subprocess.run``, so a kill must reach the WHOLE tree, not just the
        # direct child (Codex MCP HIGH — an orphaned ``inspect eval`` keeps burning
        # quota). ``start_new_session`` makes ``proc.pid`` a group leader so a
        # single ``killpg`` reaps the grandchild too.
        start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=per_audit_timeout
        )
    except TimeoutError:
        # ``asyncio.wait_for`` raises the builtin ``TimeoutError`` (aliased to
        # ``asyncio.TimeoutError`` since 3.11). Kill + reap the whole process GROUP
        # so the hung audit (and its ``inspect eval`` grandchild) is fully reaped,
        # not left orphaned. ``ProcessLookupError`` (child/group already gone in the
        # narrow exit-at-timeout race) is suppressed so the reap path is bulletproof
        # and still returns the dropped-worker row.
        with contextlib.suppress(ProcessLookupError):
            # NEVER signal our OWN process group: ``start_new_session=True`` gives the
            # child a DISTINCT group in production, but a test mock or a platform
            # without ``setsid`` would leave it in our group, where ``killpg`` would
            # SIGKILL the campaign driver (or the test runner) itself. Only group-kill
            # when the child's group is genuinely its own; otherwise kill just the child.
            child_pgid = os.getpgid(proc.pid)
            if child_pgid != os.getpgid(0):
                os.killpg(child_pgid, signal.SIGKILL)
            else:
                proc.kill()
        await proc.wait()
        return subprocess.CompletedProcess(
            args=argv,
            returncode=-1,
            stdout="",
            stderr=f"worker timed out after {per_audit_timeout}s; killed child",
        )
    stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
    return subprocess.CompletedProcess(
        args=argv,
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout_text,
        stderr=stderr_text,
    )


async def _run_isolated_worker(
    *,
    index: int,
    group: str,
    workers_root: Path,
    snapshot_dir: Path,
    promote_policy: str | None,
    promote_policy_seed: int | None,
    audit_max_samples: int,
    audit_max_connections: int,
    dry_run: bool,
    per_audit_timeout: float | None,
    runner_fn: Any,
) -> WorkerOutcome:
    """Run ONE path-independent worker in an isolated ``GEODE_STATE_ROOT``.

    Seeds ``<workers_root>/w{index}`` from the frozen gen-0 snapshot, spawns
    ``train.py`` there (concurrently with its siblings), and reads back THIS
    worker's signal: its RAW ``dim_means`` from the ``FITNESS_RESULT`` stdout
    sentinel + its newest ``kind="attribution"`` row from its OWN isolated
    ``mutations.jsonl``. A non-zero exit / timeout / crash yields an ``ok=False``
    outcome the aggregator drops with a logged reason (partial-failure resilient).

    ``group`` is the worker-id prefix (``"gen0"`` / ``"never"`` / ``"random"``);
    the worker's ``worker_id`` is ``f"{group}-w{index}"`` and its ISOLATED
    RunTranscript jsonl is ``<worker_root>/transcript.jsonl`` (S6). The worker's
    ``train.py`` writes ALL its journal events to that file (via
    ``GEODE_RUN_TRANSCRIPT_PATH``), stamped with ``worker_id`` (via
    ``GEODE_RUN_WORKER_ID``), so concurrent workers never race-append a shared
    transcript; the caller merges these files after the gather. The path rides on
    the returned :class:`WorkerOutcome` so the merge finds it even for a worker
    that exited non-zero (it may still have emitted ``subprocess_started`` first).

    ``runner_fn`` is the injectable spawn seam (default
    :func:`_spawn_train_subprocess_async`); tests pass a fake async runner so the
    gather + aggregate + isolation are exercised with NO real audit.
    """
    worker_root = workers_root / f"w{index}"
    worker_id = f"{group}-w{index}"
    transcript_path = worker_root / "transcript.jsonl"
    # ONE broad guard around the WHOLE worker body (Codex MCP HIGH): a failure in
    # ``mkdir`` / ``_seed_isolated_state_root`` / ``_build_worker_env`` / the spawn /
    # ``parse_fitness_result_dims`` / ``read_latest_attribution`` must NOT abort the
    # sibling ``asyncio.gather`` (which has no ``return_exceptions=True``) — it drops
    # this worker to ``ok=False`` and the aggregator skips it with a logged reason.
    try:
        worker_root.mkdir(parents=True, exist_ok=True)
        _seed_isolated_state_root(worker_root, snapshot_dir)
        env = _build_worker_env(
            worker_root,
            promote_policy=promote_policy,
            promote_policy_seed=promote_policy_seed,
            audit_max_samples=audit_max_samples,
            audit_max_connections=audit_max_connections,
            transcript_path=transcript_path,
            worker_id=worker_id,
        )
        result = await runner_fn(env=env, dry_run=dry_run, per_audit_timeout=per_audit_timeout)
        returncode = int(getattr(result, "returncode", -1) or 0)
        if returncode != 0:
            return WorkerOutcome(
                index=index,
                ok=False,
                returncode=returncode,
                dim_means={},
                signal=None,
                reason=f"train.py exited {returncode}",
                transcript_path=transcript_path,
            )
        measure_dims = parse_fitness_result_dims(getattr(result, "stdout", None)) or {}
        # Read THIS worker's signal from its OWN isolated mutations.jsonl (the worker
        # root started with no attribution ledger, so the newest row is unambiguously
        # this worker's). ``min_rows=0`` is correct here precisely because the ledger
        # is per-worker — there is no sibling row to mistake for this one.
        worker_mutations = worker_root / "autoresearch" / "mutations.jsonl"
        signal = read_latest_attribution(worker_mutations)
        if not measure_dims and signal is None:
            # Zero exit but NO usable measurement: no ``FITNESS_RESULT`` dims AND no
            # attribution row (Codex MCP MEDIUM). Marking this ``ok=True`` would
            # checkpoint a FAILED measurement as complete + skip it on resume — drop
            # it so a resume re-attempts it and the aggregate never counts a phantom.
            return WorkerOutcome(
                index=index,
                ok=False,
                returncode=0,
                dim_means={},
                signal=None,
                reason="zero exit but no usable measurement (no dims, no attribution)",
                transcript_path=transcript_path,
            )
        return WorkerOutcome(
            index=index,
            ok=True,
            returncode=0,
            dim_means=measure_dims,
            signal=signal,
            reason="ok",
            transcript_path=transcript_path,
        )
    except Exception as exc:
        return WorkerOutcome(
            index=index,
            ok=False,
            returncode=-1,
            dim_means={},
            signal=None,
            reason=f"worker error ({type(exc).__name__}): {exc}",
            transcript_path=transcript_path,
        )


def _transcript_sort_key(row: dict[str, Any]) -> tuple[float, int]:
    """Sort key for a merged transcript row — ``(ts, seq)``.

    Both casts are graceful (CLAUDE.md boundary rule): a row missing / carrying a
    malformed ``ts`` sorts to the front (``-inf``) rather than crashing the merge,
    and a missing / malformed per-worker ``seq`` falls back to ``0`` so same-ts
    rows keep a stable order. The merge must never lose an event to one bad row.
    """
    raw_ts = row.get("ts")
    ts = _as_float(raw_ts)
    raw_seq = row.get("seq")
    try:
        seq = int(raw_seq) if raw_seq is not None else 0
    except (TypeError, ValueError):
        seq = 0
    return (ts if ts is not None else float("-inf"), seq)


def merge_worker_transcripts(
    worker_transcripts: Sequence[Path | None],
    dest: Path,
) -> int:
    """Merge the per-worker ISOLATED transcripts into one campaign transcript (S6).

    The concurrent gen-0 / control-arm workers each wrote to their OWN
    ``transcript.jsonl`` (``GEODE_RUN_TRANSCRIPT_PATH``) so their journal events
    never race-corrupted a shared file (POSIX append is not atomic above
    ``PIPE_BUF``). This reads every worker's rows, sorts the UNION by ``(ts, seq)``
    so the operator gets one coherent ordered replay, and APPENDS them to ``dest``
    (the campaign transcript). Each row already carries ``worker_id`` (stamped by
    ``_emit_journal`` from ``GEODE_RUN_WORKER_ID``) so the merged view stays
    attributable per worker.

    Graceful throughout: a ``None`` / missing worker path is skipped (a worker that
    never emitted), a malformed JSONL line is skipped (one bad row never aborts the
    merge), and the cross-worker ``ts``/``seq`` ordering tolerates absent keys. The
    append (not overwrite) preserves any rows the campaign itself already wrote to
    ``dest``. Returns the number of rows merged into ``dest``.

    MUST be called BEFORE the per-worker tempdir is cleaned up — the worker files
    live under the isolated ``GEODE_STATE_ROOT`` tree which the gather's
    ``TemporaryDirectory`` context removes on exit.
    """
    rows: list[dict[str, Any]] = []
    for path in worker_transcripts:
        if path is not None:
            rows.extend(iter_jsonl(path))
    if not rows:
        return 0
    rows.sort(key=_transcript_sort_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


async def run_gen0_baseline_async(
    *,
    k: int,
    dry_run: bool,
    audit_max_samples: int,
    audit_max_connections: int,
    progress: ProgressLog,
    snapshot_dir: Path = GEN0_SNAPSHOT_DIR,
    per_audit_timeout: float | None = None,
    workers_root: Path | None = None,
    runner_fn: Any | None = None,
    checkpoint: RunCheckpoint | None = None,
    campaign_transcript: Path | None = None,
) -> NoiseBand:
    """Async parallel sibling of :func:`run_gen0_baseline`.

    Runs the K gen-0 replicates CONCURRENTLY via ``asyncio.gather`` — each an
    isolated ``GEODE_STATE_ROOT`` worker seeded from the frozen baseline snapshot
    (path-independent: every replicate measures the SAME frozen baseline) — then
    aggregates the K per-dim ``dim_means`` (:func:`aggregate_dim_means`) and
    rewrites ``baseline.json``'s ``raw.dim_means`` / ``raw.dim_stderr`` to the
    K-mean (:func:`write_kmean_baseline`), exactly as the sequential path does.

    Aggregation FILTERS to the workers that succeeded (``ok=True``); dropped
    workers (crash / timeout / non-zero exit / no parsed dims) are logged, never
    silently truncated. The K-mean rewrite is SKIPPED under ``--dry-run`` (the
    synthetic dims must not freeze a synthetic baseline) — identical to the sync
    path. ``runner_fn`` (default :func:`_spawn_train_subprocess_async`) is the
    injectable async spawn seam for tests.

    ``checkpoint`` (S4) makes the fan-out crash-resumable: replicate indices the
    marker already records complete are SKIPPED (only the missing ones re-run),
    their outcomes are UNIONed with the freshly-run ones for aggregation, and the
    K-mean baseline write is IDEMPOTENT (a re-run where the marker shows it was
    already written skips re-aggregation entirely). ``checkpoint=None`` (or a
    disabled one with ``run_id=None``) keeps the pre-S4 behaviour: every replicate
    runs, the K-mean always (re)writes.

    ``campaign_transcript`` (S6) is the destination the per-worker ISOLATED
    transcripts are MERGED into after the gather (sorted by ``(ts, seq)``, each row
    already ``worker_id``-stamped). ``None`` SKIPS the merge entirely — the
    sequential / pre-S6 callers need no merge. The merge happens INSIDE the
    tempdir context, before the per-worker files are cleaned up.
    """
    ckpt = checkpoint if checkpoint is not None else RunCheckpoint(run_id=None)
    runner = runner_fn if runner_fn is not None else _spawn_train_subprocess_async
    already_done = ckpt.completed_indices(GEN0_CHECKPOINT_GROUP)
    pending = [i for i in range(1, k + 1) if i not in already_done]
    if already_done:
        progress.emit(
            f"gen-0 baseline (async): RESUME — {len(already_done)} replicate(s) already "
            f"complete {sorted(already_done)}; re-running {len(pending)} missing {pending}"
        )
    fresh: list[WorkerOutcome] = []
    if pending:
        with tempfile.TemporaryDirectory(prefix="geode-gen0-") as tmp:
            roots_parent = workers_root if workers_root is not None else Path(tmp)
            progress.emit(
                f"gen-0 baseline (async): fanning {len(pending)} isolated workers concurrently "
                f"(dry_run={dry_run}, per_audit_timeout={per_audit_timeout})"
            )
            fresh = list(
                await asyncio.gather(
                    *(
                        _run_isolated_worker(
                            index=i,
                            group=GEN0_CHECKPOINT_GROUP,
                            workers_root=roots_parent,
                            snapshot_dir=snapshot_dir,
                            promote_policy=None,  # gen-0 inherits NO arm (frozen baseline)
                            promote_policy_seed=None,
                            audit_max_samples=audit_max_samples,
                            audit_max_connections=audit_max_connections,
                            dry_run=dry_run,
                            per_audit_timeout=per_audit_timeout,
                            runner_fn=runner,
                        )
                        for i in pending
                    )
                )
            )
            # S6 — merge the per-worker isolated transcripts into the campaign
            # transcript while the tempdir (the workers' isolated GEODE_STATE_ROOT
            # tree, where each transcript.jsonl lives) is still alive.
            if campaign_transcript is not None:
                merged = merge_worker_transcripts(
                    [o.transcript_path for o in fresh], campaign_transcript
                )
                progress.emit(
                    f"gen-0 baseline (async): merged {merged} per-worker transcript event(s) "
                    f"→ {campaign_transcript}"
                )
    fresh_ok = [o for o in fresh if o.ok]
    dropped = [o for o in fresh if not o.ok]
    # Capture the resumed (already-complete) workers BEFORE recording the fresh
    # ones, so the union does not double-count a fresh worker that record_completed
    # would have just merged into the same completed set.
    resumed = ckpt.resumed_outcomes(GEN0_CHECKPOINT_GROUP)
    # Persist the freshly-completed workers BEFORE aggregating, so a crash during
    # the K-mean write does not lose the measures already paid for.
    ckpt.record_completed(GEN0_CHECKPOINT_GROUP, fresh_ok)
    for o in dropped:
        progress.emit(f"gen-0 baseline (async): DROPPED worker w{o.index} — {o.reason}")
    # Union the freshly-run ok workers with the ones resumed from the checkpoint.
    successful = [*resumed, *fresh_ok]
    held_out_values = [
        o.signal.held_out_fitness
        for o in successful
        if o.signal is not None and o.signal.held_out_fitness is not None
    ]
    fitness_values = [
        o.signal.fitness
        for o in successful
        if o.signal is not None and o.signal.fitness is not None
    ]
    per_measure_dim_means = [o.dim_means for o in successful if o.dim_means]
    band = compute_noise_band(held_out_values, fitness_values, k=k)
    progress.emit(
        f"gen-0 baseline (async): {len(successful)}/{k} workers ok "
        f"({len(already_done)} resumed + {len(fresh_ok)} fresh), "
        f"{len(dropped)} dropped; " + band.summary()
    )
    if dry_run:
        progress.emit(
            f"gen-0 K-mean baseline (async): dry-run — skipped baseline.json rewrite "
            f"(parsed {len(per_measure_dim_means)}/{k} synthetic FITNESS_RESULT measures)"
        )
    elif ckpt.kmean_already_written(GEN0_CHECKPOINT_GROUP):
        # Idempotent: the K-mean was already aggregated + written for this run id —
        # a resume must NOT re-aggregate / re-overwrite baseline.json a second time.
        progress.emit(
            "gen-0 K-mean baseline (async): RESUME — K-mean already written for this "
            "run id; skipping re-aggregation (idempotent)"
        )
    elif per_measure_dim_means:
        mean_dims, stderr_dims, present_count = aggregate_dim_means(per_measure_dim_means)
        wrote = write_kmean_baseline(mean_dims, stderr_dims)
        partial = sorted(d for d, c in present_count.items() if c < len(per_measure_dim_means))
        if wrote:
            ckpt.mark_kmean_written(GEN0_CHECKPOINT_GROUP)
        progress.emit(
            f"gen-0 K-mean baseline (async): collected {len(per_measure_dim_means)}/{k} "
            f"measures, {len(mean_dims)} dims; baseline.json raw.dim_means←K-mean "
            f"(written={wrote})" + (f"; partial-coverage dims={partial}" if partial else "")
        )
    else:
        progress.emit(
            f"gen-0 K-mean baseline (async): no FITNESS_RESULT dims parsed from {k} "
            "workers (all dropped) — baseline.json raw.dim_means left as bootstrap"
        )
    return band


@dataclass(frozen=True)
class ControlArmFloor:
    """The aggregated floor of one path-independent control arm (never / random).

    Mirrors ``scripts/floor_aggregate.py``: the mean ± stderr of the per-cycle
    held-out (and fitness) measures over the arm's N concurrent, frozen-baseline
    cycles. ``cycles_ok`` / ``cycles_dropped`` make the partial-failure resilience
    auditable (no silent truncation).
    """

    arm: str
    cycles_ok: int
    cycles_dropped: int
    held_out_band: NoiseBand

    def summary(self) -> str:
        return (
            f"control arm '{self.arm}' floor: cycles_ok={self.cycles_ok} "
            f"cycles_dropped={self.cycles_dropped}; {self.held_out_band.summary()}"
        )


def _control_cycle_seed(arm: str, arm_index: int, n: int, cycle: int) -> int | None:
    """The deterministic ``GEODE_PROMOTE_POLICY_SEED`` for one control-arm cycle.

    Reproducibility invariant (task #4): the random arm's per-cycle coin flip is
    keyed on ``(arm_index, n, cycle)`` ONLY — never on wall-clock / dispatch order
    — so a cycle's seed is byte-identical whether the never+random fan-out runs
    the arms sequentially (legacy) or interleaved in one concurrent gather (the
    new default). ``arm_index`` is the arm's position in the ORIGINAL ``arms``
    sequence (``random`` → index 1 by default), so the formula matches the legacy
    per-arm path exactly. Only the ``random`` arm seeds; ``never`` is unseeded.
    """
    if arm != "random":
        return None
    return DEFAULT_RANDOM_SEED_BASE + arm_index * n + cycle


def _aggregate_control_floor(
    *,
    arm: str,
    n: int,
    fresh: Sequence[WorkerOutcome],
    ckpt: RunCheckpoint,
    progress: ProgressLog,
) -> ControlArmFloor:
    """Aggregate ONE control arm's per-cycle outcomes into its :class:`ControlArmFloor`.

    The post-gather per-arm aggregation, factored out so the concurrent multi-arm
    (:func:`run_control_arms_async`) path computes the floor IDENTICALLY. ``fresh``
    is only THIS arm's freshly-run outcomes (the multi-arm orchestrator partitions
    the single gather's results by arm BEFORE calling this, so a ``never`` cycle is
    never mixed into the ``random`` floor — attribution invariant #1). Records the
    arm's ``ok`` cycles to its OWN checkpoint group, unions them with the cycles
    resumed from a prior run (invariant #3), and bands the held-out / fitness floor.
    """
    fresh_ok = [o for o in fresh if o.ok]
    dropped = [o for o in fresh if not o.ok]
    # Capture resumed cycles BEFORE recording the fresh ones (no double-count).
    resumed = ckpt.resumed_outcomes(arm)
    ckpt.record_completed(arm, fresh_ok)
    for o in dropped:
        progress.emit(f"control arm '{arm}' (async): DROPPED cycle {o.index} — {o.reason}")
    successful = [*resumed, *fresh_ok]
    held_out_values = [
        o.signal.held_out_fitness
        for o in successful
        if o.signal is not None and o.signal.held_out_fitness is not None
    ]
    fitness_values = [
        o.signal.fitness
        for o in successful
        if o.signal is not None and o.signal.fitness is not None
    ]
    floor = ControlArmFloor(
        arm=arm,
        cycles_ok=len(successful),
        cycles_dropped=len(dropped),
        held_out_band=compute_noise_band(held_out_values, fitness_values, k=n),
    )
    progress.emit(floor.summary())
    return floor


async def run_control_arms_async(
    *,
    control_arms: Sequence[tuple[str, int]],
    n: int,
    audit_max_samples: int,
    audit_max_connections: int,
    dry_run: bool,
    progress: ProgressLog,
    snapshot_dir: Path = GEN0_SNAPSHOT_DIR,
    per_audit_timeout: float | None = None,
    workers_root: Path | None = None,
    runner_fn: Any | None = None,
    checkpoint: RunCheckpoint | None = None,
    campaign_transcript: Path | None = None,
) -> dict[str, ControlArmFloor]:
    """Fan EVERY path-independent control arm's cycles out in ONE concurrent gather.

    The DEFAULT control-arm orchestration (PR-CAMPAIGN-CONCURRENT-CONTROL-ARMS,
    2026-06-04). ``control_arms`` is the list of ``(arm, arm_index)`` to run — the
    ``never`` and ``random`` arms ONLY (``arm_index`` is each arm's position in the
    original ``arms`` sequence, preserved so the random seed formula is unchanged —
    invariant #4). Both arms are PATH-INDEPENDENT (every cycle measures the SAME
    frozen baseline, no keep/revert chain), so ALL their pending cycles fan out
    together via a SINGLE ``asyncio.gather`` — the two arms OVERLAP instead of
    running arm-by-arm. With PAYG's unbounded fan-out this ~halves the control-arm
    wall-clock (the two arms' cycles run concurrently, not back-to-back).

    The GATE arm is PATH-DEPENDENT (a promote mutates the champion + steers the
    next propose) and is NEVER routed here — it stays the sequential :func:`run_arm`.
    This function raises ``ValueError`` if asked to run ``gate`` so the invariant
    cannot be violated by a mis-call.

    INVARIANTS (each verified by ``tests/core/self_improving/test_run_campaign.py``):

    * Attribution (#1): each cycle task is tagged with its arm; the gather's flat
      result list is PARTITIONED back by arm before aggregation, so a ``never``
      cycle never lands in the ``random`` floor (and vice-versa).
    * Promote policy (#2): each task's env carries ITS arm's
      ``GEODE_PROMOTE_POLICY`` + (random only) the per-cycle seed — built per task
      via :func:`_build_worker_env`, so the interleaved fan-out sets each worker's
      policy by its OWN arm.
    * Resume (#3): pending cycles are filtered per arm against ITS checkpoint group
      (``ckpt.completed_indices(arm)``); aggregation records + resumes per arm. A
      resumed run re-runs only the missing cycles of each arm, never cross-attributed.
    * Reproducibility (#4): the random seed is :func:`_control_cycle_seed` —
      ``(arm_index, n, cycle)``-keyed, order-independent.
    * Transcript isolation (#5): each arm's cycle workers live under their OWN
      subtree (``<roots_parent>/<arm>/w{cycle}``) so a ``never`` cycle and a
      ``random`` cycle with the SAME index never collide on a worker root /
      transcript file. The per-worker transcripts are merged into the one campaign
      transcript after the gather.

    Returns ``{arm: ControlArmFloor}`` for every arm in ``control_arms``.
    """
    arm_names = [arm for arm, _ in control_arms]
    bad = [arm for arm in arm_names if arm == "gate"]
    if bad:
        raise ValueError(
            "run_control_arms_async refuses the GATE arm — it is path-dependent "
            "(promote mutates the champion chain) and MUST stay sequential (run_arm)"
        )
    unknown = [arm for arm in arm_names if arm not in {"never", "random"}]
    if unknown:
        raise ValueError(
            f"run_control_arms_async expects 'never'/'random' arms, got unknown {unknown}"
        )
    ckpt = checkpoint if checkpoint is not None else RunCheckpoint(run_id=None)
    runner = runner_fn if runner_fn is not None else _spawn_train_subprocess_async

    # Per arm: the cycles still pending after subtracting the checkpoint's completed
    # set (invariant #3 — a resume re-runs only the missing cycles of EACH arm).
    pending_by_arm: dict[str, list[int]] = {}
    for arm, _arm_index in control_arms:
        already_done = ckpt.completed_indices(arm)
        pending = [cycle for cycle in range(1, n + 1) if cycle not in already_done]
        pending_by_arm[arm] = pending
        if already_done:
            progress.emit(
                f"control arm '{arm}' (async): RESUME — {len(already_done)} cycle(s) already "
                f"complete {sorted(already_done)}; re-running {len(pending)} missing {pending}"
            )

    # One flat task list across ALL control arms, each task paired with its arm so
    # the gather's flat result can be partitioned back (attribution invariant #1).
    fresh_by_arm: dict[str, list[WorkerOutcome]] = {arm: [] for arm, _ in control_arms}
    total_pending = sum(len(p) for p in pending_by_arm.values())
    if total_pending:
        with tempfile.TemporaryDirectory(prefix="geode-control-") as tmp:
            roots_parent = workers_root if workers_root is not None else Path(tmp)
            progress.emit(
                "control arms (async): SINGLE concurrent fan-out over "
                f"{[(arm, len(pending_by_arm[arm])) for arm, _ in control_arms]} "
                f"({total_pending} isolated frozen-baseline cycles, dry_run={dry_run})"
            )
            # ``arm_of_task[i]`` records which arm task ``i`` belongs to — the gather
            # preserves input order, so this list re-attributes each flat result.
            arm_of_task: list[str] = []
            coros = []
            for arm, arm_index in control_arms:
                # Each arm's cycle workers get their OWN subtree so a never-cycle and
                # a random-cycle with the SAME index never collide (invariant #5).
                arm_root = roots_parent / arm
                for cycle in pending_by_arm[arm]:
                    arm_of_task.append(arm)
                    coros.append(
                        _run_isolated_worker(
                            index=cycle,
                            group=arm,
                            workers_root=arm_root,
                            snapshot_dir=snapshot_dir,
                            promote_policy=arm,
                            promote_policy_seed=_control_cycle_seed(arm, arm_index, n, cycle),
                            audit_max_samples=audit_max_samples,
                            audit_max_connections=audit_max_connections,
                            dry_run=dry_run,
                            per_audit_timeout=per_audit_timeout,
                            runner_fn=runner,
                        )
                    )
            outcomes = list(await asyncio.gather(*coros))
            # Partition the flat result back by arm (attribution invariant #1).
            for task_arm, outcome in zip(arm_of_task, outcomes, strict=True):
                fresh_by_arm[task_arm].append(outcome)
            # S6 — merge ALL arms' per-cycle isolated transcripts into the campaign
            # transcript while the tempdir is still alive (one merge for the gather).
            if campaign_transcript is not None:
                merged = merge_worker_transcripts(
                    [o.transcript_path for outcomes in fresh_by_arm.values() for o in outcomes],
                    campaign_transcript,
                )
                progress.emit(
                    f"control arms (async): merged {merged} per-cycle transcript "
                    f"event(s) → {campaign_transcript}"
                )

    return {
        arm: _aggregate_control_floor(
            arm=arm,
            n=n,
            fresh=fresh_by_arm[arm],
            ckpt=ckpt,
            progress=progress,
        )
        for arm, _ in control_arms
    }


# ---------------------------------------------------------------------------
# Arm loop (campaign-procedure.md §6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmSummary:
    """Roll-up of one arm's N cycles."""

    arm: str
    cycles_run: int
    cycles_skipped: int
    promotes: int
    halted: bool

    def summary(self) -> str:
        return (
            f"arm '{self.arm}' summary: cycles={self.cycles_run} skipped={self.cycles_skipped} "
            f"promotes={self.promotes} halted={self.halted}"
        )


def _make_runner(*, arm: str, env: dict[str, str], dry_run: bool) -> SelfImprovingLoopRunner:
    """Construct a runner for an arm cycle.

    The runner spawns ``train.py`` itself (``rerun_enabled=True``). It inherits
    the arm's env via ``os.environ`` because
    ``runner.py::_run_autoresearch_subprocess`` copies ``os.environ`` — so the
    campaign sets the arm env into ``os.environ`` around the cycle (restored
    afterwards). ``commit_enabled`` is True ONLY for the gate arm (the real
    optimizer persists; the control arms do not git-commit). ``rerun_dry_run``
    mirrors the campaign ``--dry-run`` so a smoke run passes ``train.py --dry-run``
    (synthetic audit, no PAYG); the live campaign runs ``dry_run=False`` for a
    real Petri audit.
    """
    from core.self_improving.loop.mutate.runner import SelfImprovingLoopRunner

    return SelfImprovingLoopRunner(
        commit_enabled=(arm == "gate"),
        rerun_enabled=True,
        rerun_dry_run=dry_run,
    )


class _OfflineSmokeRunner:
    """A fully synthetic runner for the ``--dry-run`` smoke path.

    The real :class:`~core.self_improving.loop.mutate.runner.SelfImprovingLoopRunner`
    dispatches a live mutator LLM call in ``propose()`` and writes the real
    in-repo SoT (``wrapper-sections.json`` + ``mutations.jsonl``) in
    ``apply_proposal()``. Neither is appropriate for a no-PAYG smoke that must
    leave the repo SoT untouched. This stand-in returns a canned
    :class:`Proposal` and records applies in memory only — so a smoke proves the
    orchestration wiring (gen-0 → snapshot → arm sequencing → propose-guard →
    apply → guard) runs end-to-end with NO network and NO SoT mutation.
    """

    def __init__(self, *, arm: str) -> None:
        self.arm = arm
        self.applied: list[Proposal] = []

    def propose(self) -> Proposal:
        from core.self_improving.loop.mutate.runner import Mutation, Proposal

        mutation = Mutation(
            target_section="campaign_dry_run_smoke",
            new_value="dry-run smoke mutation — synthetic, no live audit",
            rationale="dry-run smoke (no PAYG)",
            target_kind="prompt",
        )
        return Proposal(mutation=mutation)

    def apply_proposal(self, proposal: Proposal) -> Any:
        self.applied.append(proposal)
        return proposal.mutation


def _make_offline_runner(*, arm: str, env: dict[str, str], dry_run: bool) -> _OfflineSmokeRunner:
    """Offline synthetic runner for the ``--dry-run`` smoke path — no network, no
    SoT write."""
    return _OfflineSmokeRunner(arm=arm)


def run_arm(
    *,
    arm: str,
    arm_index: int,
    n: int,
    max_propose_attempts: int,
    audit_max_samples: int,
    audit_max_connections: int,
    dry_run: bool,
    progress: ProgressLog,
    snapshot_dir: Path = GEN0_SNAPSHOT_DIR,
    runner_factory: Any | None = None,
    guard_fn: Any | None = None,
) -> ArmSummary:
    """Run one arm: matched gen-0 reset → set arm env → N propose/guard/apply cycles.

    ``runner_factory`` (``(arm, env, dry_run) -> runner``) and ``guard_fn``
    (``(signal) -> GuardResult``) are injected so tests can substitute mocks. The
    real path uses ``_make_runner`` + ``degeneracy_guard``. Under ``--dry-run`` with
    no injected factory, an OFFLINE synthetic runner (``_make_offline_runner``) is
    used so the smoke run never dispatches a mutator LLM call (no PAYG/network).
    """
    if runner_factory is not None:
        factory = runner_factory
    elif dry_run:
        factory = _make_offline_runner
    else:
        factory = _make_runner
    if guard_fn is not None:
        guard = guard_fn
    elif dry_run:
        # Dry-run skips the degeneracy guard: train.py --dry-run writes NO
        # attribution row (synthetic dims carry no signal) and produces no fresh
        # .eval, so there is nothing healthy to confirm. A permissive guard keeps
        # the smoke path from HALTing on the absence of live evidence.
        guard = lambda _signal: GuardResult(ok=True, reason="dry-run (guard skipped)")  # noqa: E731
    else:
        guard = lambda signal: degeneracy_guard(signal=signal)  # noqa: E731

    if dry_run:
        # Dry-run is read-only w.r.t. the git-tracked policy SoT: the offline
        # runner writes nothing, so a matched reset would only re-copy identical
        # bytes. Skipping restore_sot keeps the smoke from touching
        # ``core/self_improving/state/policies/*`` at all (Codex MCP finding #5).
        progress.emit(f"arm '{arm}' (index {arm_index}): dry-run (gen-0 restore skipped)")
    else:
        progress.emit(f"arm '{arm}' (index {arm_index}): restoring gen-0 SoT snapshot")
        restore_sot(snapshot_dir)

    seed = DEFAULT_RANDOM_SEED_BASE + arm_index if arm == "random" else None
    env = build_campaign_env(
        promote_policy=arm,
        promote_policy_seed=seed,
        audit_max_samples=audit_max_samples,
        audit_max_connections=audit_max_connections,
    )
    progress.emit(
        f"arm '{arm}': GEODE_PROMOTE_POLICY={arm} "
        f"GEODE_PROMOTE_POLICY_SEED={seed} commit_enabled={arm == 'gate'}"
    )

    cycles_run = 0
    cycles_skipped = 0
    promotes = 0
    halted = False
    # Stash + overlay the arm env into os.environ so the runner's spawned
    # train.py subprocess (which copies os.environ) inherits the arm's
    # promote-policy + seed-pool wiring. Restored in the finally.
    _saved_env = {
        key: os.environ.get(key)
        for key in (
            "GEODE_PROMOTE_POLICY",
            "GEODE_PROMOTE_POLICY_SEED",
            "AUTORESEARCH_SEED_SELECT",
            "GEODE_HELD_OUT_BENCH",
            "GEODE_CODEX_OAUTH_POLL_DISABLED",
            "GEODE_AUDIT_MAX_SAMPLES",
            "GEODE_AUDIT_MAX_CONNECTIONS",
        )
    }
    try:
        for key in _saved_env:
            if key in env:
                os.environ[key] = env[key]
            else:
                os.environ.pop(key, None)
        for cycle in range(1, n + 1):
            runner = factory(arm=arm, env=env, dry_run=dry_run)
            proposal = propose_with_guard(
                runner, max_attempts=max_propose_attempts, progress=progress
            )
            if proposal is None:
                cycles_skipped += 1
                progress.emit(f"arm '{arm}' cycle {cycle}/{n}: SKIP (propose-guard exhausted)")
                continue
            rows_before = count_attribution_rows()
            runner.apply_proposal(proposal)
            cycles_run += 1
            # Only this cycle's freshly-appended attribution row counts as signal
            # (no stale-row reuse if the audit wrote nothing) — Codex MCP #2.
            signal = read_latest_attribution(min_rows=rows_before)
            promoted = _promoted_this_cycle(signal)
            if promoted:
                promotes += 1
            guard_result = guard(signal)
            progress.emit(_cycle_line(arm=arm, cycle=cycle, n=n, signal=signal, guard=guard_result))
            if not guard_result.ok:
                progress.emit(
                    f"HALT arm '{arm}' cycle {cycle}/{n}: degenerate audit — {guard_result.reason}"
                )
                halted = True
                break
    finally:
        for key, prior in _saved_env.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior

    arm_summary = ArmSummary(
        arm=arm,
        cycles_run=cycles_run,
        cycles_skipped=cycles_skipped,
        promotes=promotes,
        halted=halted,
    )
    progress.emit(arm_summary.summary())
    return arm_summary


def _promoted_this_cycle(signal: CycleSignal | None) -> bool:
    """A positive ``fitness_delta`` on the newest attribution row is the per-cycle
    promote proxy (the baseline advanced). ``None`` / non-positive ⇒ reject."""
    if signal is None or signal.fitness_delta is None:
        return False
    return signal.fitness_delta > 0.0


def _cycle_line(
    *, arm: str, cycle: int, n: int, signal: CycleSignal | None, guard: GuardResult
) -> str:
    """One per-cycle progress line (campaign-procedure.md §4 progress-log fields)."""
    if signal is None:
        return (
            f"arm '{arm}' cycle {cycle}/{n}: NO-SIGNAL "
            f"guard={'ok' if guard.ok else 'degenerate'} ({guard.reason})"
        )
    promote = "promote" if _promoted_this_cycle(signal) else "reject"
    delta = "n/a" if signal.fitness_delta is None else f"{signal.fitness_delta:+.4f}"
    return (
        f"arm '{arm}' cycle {cycle}/{n}: fitness_after={signal.fitness} "
        f"fitness_delta={delta} held_out={signal.held_out_fitness} {promote} "
        f"guard={'ok' if guard.ok else 'degenerate'} ({guard.reason})"
    )


# ---------------------------------------------------------------------------
# inspect_ai trajectory-cache purge (FIX 2 — real-campaign start)
# ---------------------------------------------------------------------------


def _purge_inspect_cache_at_start(progress: ProgressLog) -> bool:
    """Call ``plugins.petri_audit.runner.purge_inspect_cache`` at real-campaign
    start, logging the outcome.

    The import is GUARDED: ``plugins.petri_audit`` pulls in ``inspect_ai`` (the
    ``[audit]`` extra), which is absent in a base ``uv sync`` env. When the import
    fails the purge is a logged no-op (``False``) rather than a crash, so a
    non-audit invocation of the driver still runs. ``purge_inspect_cache`` itself
    is graceful for the same reason (returns ``False`` when ``inspect_ai`` is
    unavailable), so this is belt-and-braces.
    """
    try:
        from plugins.petri_audit.runner import purge_inspect_cache
    except ImportError as exc:
        progress.emit(f"inspect cache purge: skipped (petri_audit/inspect_ai unavailable — {exc})")
        return False
    purged = purge_inspect_cache()
    progress.emit(
        f"inspect cache purge: ran at real-campaign start (purged={purged}) — "
        "K gen-0 measures + cycle audits are independent re-measures, not cache replays"
    )
    return purged


# ---------------------------------------------------------------------------
# Top-level campaign
# ---------------------------------------------------------------------------


def _resolve_per_audit_timeout() -> float:
    """Tight per-audit subprocess timeout (seconds) for the async workers.

    ``GEODE_PER_AUDIT_TIMEOUT_S`` override → :data:`DEFAULT_PER_AUDIT_TIMEOUT_S`.
    Graceful boundary on the cast: a non-numeric / non-positive env value falls back
    to the default rather than crashing the campaign launch.
    """
    raw = os.environ.get(PER_AUDIT_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_PER_AUDIT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_PER_AUDIT_TIMEOUT_S
    return value if value > 0 else DEFAULT_PER_AUDIT_TIMEOUT_S


def run_campaign(
    *,
    n: int = DEFAULT_N,
    k: int = DEFAULT_K,
    arms: Sequence[str] = DEFAULT_ARMS,
    max_propose_attempts: int = DEFAULT_MAX_PROPOSE_ATTEMPTS,
    audit_max_samples: int = DEFAULT_AUDIT_MAX_SAMPLES,
    audit_max_connections: int = DEFAULT_AUDIT_MAX_CONNECTIONS,
    dry_run: bool = False,
    progress_path: Path = PROGRESS_LOG,
    snapshot_dir: Path = GEN0_SNAPSHOT_DIR,
    train_runner: Any | None = None,
    runner_factory: Any | None = None,
    guard_fn: Any | None = None,
    async_first: bool = True,
) -> dict[str, Any]:
    """Run the full campaign: gen-0 K-repeat baseline → snapshot → 3-arm loop.

    Returns a dict with the noise band + per-arm summaries (for tests + an
    end-of-run digest). On the real async-first path the PATH-INDEPENDENT control
    arms (``never`` + ``random``) run CONCURRENTLY in ONE fan-out by default
    (PR-CAMPAIGN-CONCURRENT-CONTROL-ARMS, 2026-06-04) — they overlap instead of
    running arm-by-arm — and the PATH-DEPENDENT ``gate`` arm runs LAST and
    sequentially. The legacy dry-run / injected-runner path keeps the original
    sequential ``never → random → gate`` order. Either way the returned
    ``arm_summaries`` are emitted in the ORIGINAL ``arms`` order. The injected
    ``train_runner`` / ``runner_factory`` / ``guard_fn`` keep the whole thing
    unit-testable with NO live audit.
    """
    _validate_arms(arms)
    with ProgressLog(progress_path) as progress:
        progress.emit(
            f"campaign start: n={n} k={k} arms={list(arms)} dry_run={dry_run} "
            f"audit_max_samples={audit_max_samples} audit_max_connections={audit_max_connections}"
        )
        # PR-POOL-DIM-GUARD (2026-06-03) — fail loud on a seed pool that targets a
        # dim no longer in the live taxonomy. The held-out pool is the ruler the
        # gate is judged against; if it targets a removed dim (the
        # ``redundant_tool_invocation`` staleness after PR-DROP-ANALYTICS-DIMS),
        # the audits probe a dimension the loop no longer scores, the held-out
        # fitness sits pinned near the floor, and the gate rejects every cycle for
        # a measurement reason — an invalid experiment that previously ran
        # silently. A stale HELD-OUT HALTs (regenerate before measuring); a stale
        # SELECTION only warns (the optimizer wastes effort on a dead dim, but the
        # comparison ruler is still sound).
        from plugins.petri_audit.pool_validation import validate_pool_target_dims

        from core.self_improving.fitness import AXIS_TIERS

        _live_dims = frozenset(AXIS_TIERS)
        _held_stale = validate_pool_target_dims(HELD_OUT_BENCH, _live_dims)
        if _held_stale:
            raise RuntimeError(
                f"held-out pool {HELD_OUT_BENCH} targets non-live dims {_held_stale} — "
                "stale bench (the ruler probes a removed/unknown dim). Regenerate the "
                "held-out pool against the live dim taxonomy before running. HALT."
            )
        _sel_stale = validate_pool_target_dims(CYCLE_INPUT_POOL, _live_dims)
        if _sel_stale:
            progress.emit(
                f"WARN: selection pool {CYCLE_INPUT_POOL} targets non-live dims "
                f"{_sel_stale} (stale targeting — optimizer effort wasted on a dead dim)"
            )
        # FIX 2 — purge inspect_ai's trajectory cache at the start of a REAL
        # campaign so the K gen-0 measures + all cycle audits are independent
        # re-measures, not replays of a stale cached trajectory (the cache at
        # ``~/Library/Caches/inspect_ai/generate/`` keys on the input messages, so
        # an identical-scaffold gen-0 repeat would otherwise hit the same cached
        # score K times). Skipped under --dry-run (synthetic audits never touch
        # the cache).
        if not dry_run:
            _purge_inspect_cache_at_start(progress)

        # PR-ASYNC-FIRST WIRING (Codex MCP BLOCKER) — a real production campaign
        # (not dry-run, no injected sync runner) fans the PATH-INDEPENDENT measures
        # (gen-0 K replicates + the NEVER/RANDOM control arms) out as concurrent,
        # fully-isolated ``train.py`` SUBPROCESSES; the PATH-DEPENDENT GATE arm stays
        # on the sequential ``run_arm`` (champion chain). Injected-runner / dry-run
        # callers (the unit tests + the smoke path) keep the legacy in-process sync
        # path, so this wiring changes ONLY the real-campaign behaviour.
        use_async = async_first and not dry_run and train_runner is None and runner_factory is None
        per_audit_timeout = _resolve_per_audit_timeout() if use_async else None
        # ``.load()`` the persisted marker (Codex MCP HIGH): a resumed campaign
        # process must REHYDRATE which gen-0 / never / random cycles already
        # completed, else ``completed_indices`` is empty for every group and the
        # whole fan-out re-runs (re-paying for already-measured cycles). A missing /
        # corrupt marker loads to an empty (fresh-run) checkpoint, never raises.
        ckpt = (
            RunCheckpoint(run_id=f"campaign-n{n}-k{k}-{'-'.join(arms)}").load()
            if use_async
            else None
        )
        campaign_transcript = (
            (CAMPAIGN_RUNS_DIR / "campaign-transcript.jsonl") if use_async else None
        )

        if use_async:
            progress.emit(
                f"async-first: concurrent subprocess fan-out — per_audit_timeout="
                f"{per_audit_timeout}s run_id={ckpt.run_id if ckpt else None}; gen-0 K "
                "parallel, then never+random in ONE shared concurrent gather, gate sequential"
            )
            # gen-0 workers seed from a snapshot of the CURRENT frozen scaffold, so
            # snapshot BEFORE the async gen-0 (the arms re-seed from the post-K-mean
            # snapshot taken right after).
            snapshot_sot(snapshot_dir)
            band = asyncio.run(
                run_gen0_baseline_async(
                    k=k,
                    dry_run=dry_run,
                    audit_max_samples=audit_max_samples,
                    audit_max_connections=audit_max_connections,
                    progress=progress,
                    snapshot_dir=snapshot_dir,
                    per_audit_timeout=per_audit_timeout,
                    checkpoint=ckpt,
                    campaign_transcript=campaign_transcript,
                )
            )
        else:
            band = run_gen0_baseline(
                k=k,
                dry_run=dry_run,
                audit_max_samples=audit_max_samples,
                audit_max_connections=audit_max_connections,
                progress=progress,
                train_runner=train_runner,
            )
        # Snapshot the post-gen-0 state (the K-mean ``baseline.json`` the gate scores
        # against) — this is the matched reset every arm restores from.
        snapshot_written = snapshot_sot(snapshot_dir)
        progress.emit(f"gen-0 SoT snapshot: {len(snapshot_written)} files → {snapshot_dir}")
        # Per-arm summaries keyed by arm so the control fan-out + the sequential gate
        # write into the SAME map regardless of dispatch order; emitted at the end in
        # the ORIGINAL ``arms`` order (digest stability).
        summary_by_arm: dict[str, ArmSummary] = {}
        control_floors: list[ControlArmFloor] = []
        halted = False
        # PR-CAMPAIGN-CONCURRENT-CONTROL-ARMS (2026-06-04) — the PATH-INDEPENDENT
        # control arms (``never`` + ``random``) now fan out in ONE concurrent
        # ``asyncio.gather`` BY DEFAULT: every ``never`` cycle and every ``random``
        # cycle measure the SAME frozen baseline, so they OVERLAP instead of running
        # arm-by-arm (with PAYG's unbounded fan-out this ~halves the control-arm
        # wall-clock). Each arm keeps its ORIGINAL ``arm_index`` (its position in
        # ``arms``) so the random seed formula is byte-identical (invariant #4). The
        # GATE arm is PATH-DEPENDENT (a promote mutates the champion chain) and stays
        # on the sequential ``run_arm`` path below — never routed through the fan-out.
        if use_async:
            control_arms = [
                (arm, arm_index) for arm_index, arm in enumerate(arms) if arm in ("never", "random")
            ]
            if control_arms:
                floors_by_arm = asyncio.run(
                    run_control_arms_async(
                        control_arms=control_arms,
                        n=n,
                        audit_max_samples=audit_max_samples,
                        audit_max_connections=audit_max_connections,
                        dry_run=dry_run,
                        progress=progress,
                        snapshot_dir=snapshot_dir,
                        per_audit_timeout=per_audit_timeout,
                        checkpoint=ckpt,
                        campaign_transcript=campaign_transcript,
                    )
                )
                for arm, _arm_index in control_arms:
                    floor = floors_by_arm[arm]
                    control_floors.append(floor)
                    # Adapt the held-out FLOOR to the ArmSummary digest shape — a
                    # control arm never promotes (its evidence is ``held_out_band``,
                    # preserved in ``control_floors``); cycles_run/skipped map from
                    # ok/dropped.
                    summary_by_arm[arm] = ArmSummary(
                        arm=arm,
                        cycles_run=floor.cycles_ok,
                        cycles_skipped=floor.cycles_dropped,
                        promotes=0,
                        halted=False,
                    )
        for arm_index, arm in enumerate(arms):
            # Control arms already ran in the concurrent fan-out above (async path).
            if use_async and arm in ("never", "random"):
                continue
            # GATE (path-dependent champion chain) — or any arm on the sync path
            # (dry-run smoke / injected runner: never + random + gate all sequential).
            summary = run_arm(
                arm=arm,
                arm_index=arm_index,
                n=n,
                max_propose_attempts=max_propose_attempts,
                audit_max_samples=audit_max_samples,
                audit_max_connections=audit_max_connections,
                dry_run=dry_run,
                progress=progress,
                snapshot_dir=snapshot_dir,
                runner_factory=runner_factory,
                guard_fn=guard_fn,
            )
            summary_by_arm[arm] = summary
            if summary.halted:
                # A degenerate audit signals a broken setup — stop the WHOLE
                # campaign (not just this arm) so a broken setup never burns the
                # remaining arms (campaign-procedure.md §5.6; Codex MCP #3).
                progress.emit(f"campaign HALT: arm '{arm}' degenerate — stopping remaining arms")
                halted = True
                break
        # Emit summaries in the ORIGINAL ``arms`` order (an arm absent because the
        # sequential path HALTed before reaching it is simply omitted).
        arm_summaries: list[ArmSummary] = [
            summary_by_arm[arm] for arm in arms if arm in summary_by_arm
        ]
        progress.emit("campaign complete" if not halted else "campaign halted")
        return {
            "noise_band": band,
            "arm_summaries": arm_summaries,
            "control_floors": control_floors,
            "halted": halted,
            "snapshot_files": [str(p) for p in snapshot_written],
        }


def _validate_arms(arms: Sequence[str]) -> None:
    # PR-CLEANUP-D2 — single SoT: an arm added in train.py must not be
    # silently rejected by this pre-validation (former literal copy).
    from core.self_improving.gate import _VALID_PROMOTE_POLICIES

    valid = _VALID_PROMOTE_POLICIES
    bad = [a for a in arms if a not in valid]
    if bad:
        raise ValueError(
            f"unknown arm(s) {bad} — the 3-arm comparison expects a subset of {sorted(valid)}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Self-improving campaign driver (docs/self-improving/campaign-procedure.md).",
    )
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="cycles per arm (default 10)")
    parser.add_argument(
        "--k", type=int, default=DEFAULT_K, help="gen-0 baseline repeats (default 5)"
    )
    parser.add_argument(
        "--arms",
        type=str,
        default=",".join(DEFAULT_ARMS),
        help="comma-separated arm order, gate LAST (default 'never,random,gate')",
    )
    parser.add_argument(
        "--mc",
        type=int,
        default=DEFAULT_MAX_PROPOSE_ATTEMPTS,
        help="max propose-guard re-proposal attempts M (default 8)",
    )
    parser.add_argument(
        "--audit-max-samples",
        type=int,
        default=DEFAULT_AUDIT_MAX_SAMPLES,
        help="GEODE_AUDIT_MAX_SAMPLES export (default 3)",
    )
    parser.add_argument(
        "--audit-max-connections",
        type=int,
        default=DEFAULT_AUDIT_MAX_CONNECTIONS,
        help="GEODE_AUDIT_MAX_CONNECTIONS export (default 8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="pass --dry-run through to train.py + the runner (synthetic audits, no PAYG/network)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # S-6 (2026-06-11) — unified switchboard: keeps the bare %(message)s
    # console (operator-facing phase digest) + adds ~/.geode/logs/campaign.log.
    from core.observability.logging_config import configure_logging

    configure_logging("campaign")
    # PR-CAMPAIGN-LOAD-ENV (2026-06-02) — load ~/.geode/.env so the spawned
    # train.py audit subprocesses inherit the PAYG ANTHROPIC_API_KEY. train.py's
    # own main() also loads it (defence in depth for direct ``python -m
    # core.self_improving.train`` runs), but loading at the driver too means the
    # key is present from the first gen-0 spawn without relying on the operator's
    # shell having exported it.
    from core.self_improving.train import _load_global_env

    _load_global_env()
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    try:
        _validate_arms(arms)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 2
    run_campaign(
        n=args.n,
        k=args.k,
        arms=arms,
        max_propose_attempts=args.mc,
        audit_max_samples=args.audit_max_samples,
        audit_max_connections=args.audit_max_connections,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
