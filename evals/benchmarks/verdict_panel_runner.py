"""Judgment-level verdict panel runner: frozen states × {Choice, Noul} × {Astra, Jev}.

The runner calls the matched verifier directly — no Harbor task, no root loop. It
fixes the preregistered dispatch order (a 4×4 Latin square over the four engine ×
primitive cells), bounded concurrency, pacing, an event-loop heartbeat and the
panel-only transport-substitution rule. Model clients and credentials stay
caller-owned; nothing here reads a key. Correctness is scored only after gold is
unsealed, so attempts record admission, not task success.

A Choice-only unit (U3, X1a, X1) keys its run IDs and outputs by ``choice`` alone
and rotates the two Choice cells the same way. Its states may come from an
authored split or an external one; both bind through ``state_sha256`` and the
split manifest digest only orders workloads and seeds intervals. The
``paired-latency`` mode (U3) launches the Astra and Jev calls of each state
together and starts the next state only after both finish.

After a U2s stability unit, :func:`stability_report` reads the two retained
attempt files and their native-result receipts, groups the selected judgments by
(engine, primitive, state_id) and feeds ``decision_metrics.stability_summary``;
:func:`record_stability_aggregate` and :func:`stability_metric_rows` bind the
result to an analysis under the unchanged schema (preregistration v2.2 §3.7-3).
Usage: ``python -m evals.benchmarks.verdict_panel_runner stability --run-spec
<choice run-spec> --choice <dir> --noul <dir> [--gold <jsonl> --aliases <json>]
[--record]``. After U3, :func:`latency_report` computes the within-pair latency
primary and :func:`latency_metric_rows` binds it the same way: ``python -m
evals.benchmarks.verdict_panel_runner latency --run-spec <spec> --run-dir <dir>
--split-manifest <manifest> [--gold <jsonl> --aliases <json>] [--record]``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import SecretStr

from evals.benchmarks.decision_handoff import ROOT_MODEL
from evals.benchmarks.decision_metrics import (
    NOT_MEASURABLE,
    Interval,
    accuracy,
    bootstrap_seed,
    choice_record,
    cluster_bootstrap,
    paired_median_delta,
    stability_summary,
)
from evals.benchmarks.decision_verification import VERDICTS, MatchedVerifierAdapter
from evals.benchmarks.typesafe_decision import JEV_MODEL

_Engine = Literal["llm", "jev"]
_Primitive = Literal["choice", "noul"]
PRIMITIVES: tuple[_Primitive, ...] = ("choice", "noul")
# [A-Choice, B-Choice, A-Noul, B-Noul]; state i uses row i mod 4 (05 §2.2). A
# Choice-only unit keeps the two Choice cells: even states A first, odd B first.
CELLS: tuple[tuple[_Engine, _Primitive], ...] = (
    ("llm", "choice"),
    ("jev", "choice"),
    ("llm", "noul"),
    ("jev", "noul"),
)
MAX_CONCURRENCY = 4
SUBSTITUTION_LIMIT = 0.02
CALL_TIMEOUTS = {"llm": 180.0, "jev": 60.0}
VARIANTS = ("base", "rep1", "rep2", "order-rev", "para")
# Dispatch modes: the Latin-square panel (≤4 calls in flight) and U3's paired
# latency mode (A and B launched together per state, one pair in flight; 05 §2.4).
LATIN_MODE = "latin"
PAIRED_LATENCY_MODE = "paired-latency"
DISPATCH_MODES = (LATIN_MODE, PAIRED_LATENCY_MODE)
PAIRED_CONCURRENCY = 2
# A launch skew above one second is a dispatcher defect that stops the unit (05 §4.3).
PAIR_SKEW_LIMIT_S = 1.0
PAIR_LOG = "pair-log.jsonl"

INVALIDATION_RULES: dict[str, str] = {
    "panel": (
        "Judgment-output invalid (schema, label, non-finite probability, Choice sum beyond "
        "0.025, verdict not an argmax label, refusal, unexpected stop reason) is a valid "
        "attempt with a wrong answer: it stays in accuracy denominators and is excluded from "
        "probability metrics. Infrastructure invalid (no response, timeout, missing capture "
        "or receipt, harness error, quota exhaustion) is validity=invalid, outcome=unknown. "
        "Preregistered panel exception: a transport failure without any response is kept as "
        "an unselected invalid attempt and replaced exactly once by a child attempt on the "
        "same input; a failed replacement stays selected, makes the primary not measurable "
        "and stops the unit; replacements above 2% of planned calls stop the unit. Quota "
        "exhaustion, harness errors and route violations (non-subscription Astra, model, "
        "effort or provider drift, global Jev) are selected invalid attempts and stop the unit."
    ),
    "e2e": (
        "Judgment-output invalid is a semantic failure of a valid trial and keeps the trial "
        "in its denominator. Infrastructure invalid (transport failure, route drift, missing "
        "or contradictory usage, observation-check failure, incomplete export) is "
        "validity=invalid, outcome=unknown with a failure class; the first such cell stops "
        "dispatch, it stays selected and the primary is reported as not measurable. There "
        "is no replacement. A Jev failure followed by an LLM decision never counts as Jev "
        "acceptance."
    ),
}


class UnitStoppedError(RuntimeError):
    """The unit must not dispatch further calls; the reason is recorded."""


class JevSpendGuard(Protocol):
    """Host-level Jev budget hook (implemented by the program ledger)."""

    def admit_call(self, attempt_id: str) -> None: ...

    def record_call(self, attempt_id: str, input_tokens: int | None) -> None: ...


@dataclass(frozen=True)
class Workload:
    workload_id: str
    state_id: str
    cluster_id: str
    variant: str
    state: dict[str, Any]


def workloads_from_states(
    rows: Sequence[Mapping[str, Any]],
    ordered_ids: Sequence[str],
) -> list[Workload]:
    """Bind frozen workload IDs (``<state_id>`` or ``<state_id>#<variant>``) to states.

    Rows of an authored split (``verdict_panel`` states) and of an external split
    (e.g. ``states.x1.jsonl``) share this contract: ``state_id``, ``cluster_id``,
    ``state`` and its canonical ``state_sha256``. Other row fields are ignored.
    """
    by_state = {row["state_id"]: row for row in rows}
    workloads = []
    for workload_id in ordered_ids:
        state_id, _, variant = workload_id.partition("#")
        variant = variant or "base"
        if variant not in VARIANTS or state_id not in by_state:
            raise ValueError(f"unknown workload {workload_id!r}")
        row = by_state[state_id]
        digest = hashlib.sha256(
            json.dumps(
                row["state"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if digest != row["state_sha256"]:
            raise ValueError(f"state digest mismatch for {state_id}")
        workloads.append(
            Workload(workload_id, state_id, row["cluster_id"], variant, dict(row["state"]))
        )
    if len({workload.workload_id for workload in workloads}) != len(workloads):
        raise ValueError("workload IDs must be unique")
    return workloads


def latin_cells(
    index: int, cells: tuple[tuple[_Engine, _Primitive], ...] = CELLS
) -> tuple[tuple[_Engine, _Primitive], ...]:
    """Row ``index`` of the Latin square over a unit's cells (4×4, or 2×2 Choice-only)."""
    shift = index % len(cells)
    return cells[shift:] + cells[:shift]


@dataclass
class PanelUnit:
    """One frozen panel unit, keyed by primitive.

    ``run_ids`` and ``outputs`` hold ``choice`` and ``noul`` (U0a, U1, U2c/n, U2s:
    one attempts file per primitive) or ``choice`` alone (U3, X1a, X1). ``mode``
    ``paired-latency`` is U3: Choice alone with exactly one pair (two calls) in
    flight.
    """

    run_ids: Mapping[str, str]
    outputs: Mapping[str, Path]
    session_dir: Path
    pacing_s: float = 1.0
    max_concurrency: int = MAX_CONCURRENCY
    heartbeat_s: float = 5.0
    paraphrases: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    timeouts: Mapping[str, float] = field(default_factory=lambda: dict(CALL_TIMEOUTS))
    mode: str = LATIN_MODE

    @property
    def primitives(self) -> tuple[_Primitive, ...]:
        return tuple(primitive for primitive in PRIMITIVES if primitive in self.run_ids)

    def validate(self) -> None:
        keys = set(self.run_ids)
        if keys not in ({"choice", "noul"}, {"choice"}) or set(self.outputs) != keys:
            raise ValueError(
                "a panel unit writes one Choice and one Noul attempts file, or one Choice file"
            )
        if self.mode not in DISPATCH_MODES:
            raise ValueError(f"unknown panel dispatch mode {self.mode!r}")
        if self.mode == PAIRED_LATENCY_MODE and (
            keys != {"choice"} or self.max_concurrency != PAIRED_CONCURRENCY
        ):
            raise ValueError(
                "paired latency runs Choice alone with one simultaneous pair (two calls)"
            )
        if not 1 <= self.max_concurrency <= MAX_CONCURRENCY:
            raise ValueError("panel concurrency is at most four")
        if self.pacing_s < 0 or self.heartbeat_s <= 0:
            raise ValueError("pacing must be non-negative and heartbeat positive")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_new(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(text.encode()).hexdigest()


def _append(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _usage(result: Any) -> dict[str, int | None]:
    usage = getattr(result, "usage", None)
    fields = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
    return {
        name: int(getattr(usage, name)) if getattr(usage, f"{name}_present", False) else None
        for name in fields
    }


def _call_summary(attempt_id: str, status: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """One attempt's latency and paired-mode timing for the session pair log."""
    return {
        "attempt_id": attempt_id,
        "status": status,
        "latency_s": evidence["latency_s"],
        **evidence.get("call_timing", {}),
    }


class PanelRunner:
    """Dispatch one frozen unit; attempts are appended in completion order."""

    def __init__(
        self,
        unit: PanelUnit,
        workloads: Sequence[Workload],
        *,
        llm_adapter: Any,
        jev_client: httpx.AsyncClient | None,
        jev_key: SecretStr | None,
        jev_guard: JevSpendGuard | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        unit.validate()
        self.unit = unit
        self.workloads = list(workloads)
        self.llm_adapter = llm_adapter
        self.jev_client = jev_client
        self.jev_key = jev_key
        self.jev_guard = jev_guard
        self.clock = clock
        self.sleep = sleep
        self.cells = tuple(cell for cell in CELLS if cell[1] in unit.run_ids)
        self.planned = len(self.workloads) * len(self.cells)
        self.sequence = dict.fromkeys(unit.primitives, 0)
        self.substitutions = 0
        self.stop_reason: str | None = None
        self.counts: dict[str, dict[str, int]] = {
            primitive: {
                "admitted": 0,
                "rejected": 0,
                "invalid_selected": 0,
                "invalid_unselected": 0,
            }
            for primitive in unit.primitives
        }
        self.max_dispatch_skew_s: float | None = None
        self._in_flight = 0
        self._origin = 0.0
        self._lock = asyncio.Lock()
        if any(workload.variant == "para" for workload in self.workloads):
            from evals.benchmarks.decision_verification import question_variant

            for primitive in unit.primitives:
                question_variant(primitive, "para", self.unit.paraphrases.get(primitive))

    def _adapter(
        self, engine: _Engine, primitive: _Primitive, variant: str
    ) -> MatchedVerifierAdapter:
        question_variant = variant if variant in {"order-rev", "para"} else "base"
        paraphrase = self.unit.paraphrases.get(primitive) if question_variant == "para" else None
        if engine == "llm":
            return MatchedVerifierAdapter(
                "llm",
                primitive=primitive,
                llm_adapter=self.llm_adapter,
                receipts=[],
                variant=question_variant,
                paraphrase=paraphrase,
            )
        return MatchedVerifierAdapter(
            "jev",
            primitive=primitive,
            client=self.jev_client,
            api_key=self.jev_key,
            receipts=[],
            variant=question_variant,
            paraphrase=paraphrase,
        )

    async def _record(
        self,
        primitive: _Primitive,
        workload: Workload,
        engine: _Engine,
        evidence: dict[str, Any],
        *,
        validity: str,
        outcome: str,
        failure_class: str | None,
        selected: bool,
        parent: str | None,
        started_at: str,
        finished_at: str,
    ) -> str:
        async with self._lock:
            sequence = self.sequence[primitive]
            self.sequence[primitive] += 1
            run_id = self.unit.run_ids[primitive]
            attempt_id = f"{run_id}-a{sequence:05d}"
            directory = self.unit.outputs[primitive]
            receipt_path = f"receipts/{attempt_id}.json"
            digest = _write_new(
                directory / receipt_path,
                json.dumps(
                    {"attempt_id": attempt_id, **evidence},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
            )
            row = {
                "schema_id": "geode.eval-attempt@1",
                "schema_version": 1,
                "run_id": run_id,
                "attempt_id": attempt_id,
                "parent_attempt_id": parent,
                "sequence": sequence,
                "timing": {
                    "status": "exact",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "source_ref": None,
                },
                "validity": validity,
                "outcome": outcome,
                "change": {
                    "surface": "judgment-panel",
                    "description": f"{workload.workload_id} {engine} {primitive}",
                },
                "expected_effect": (
                    "One matched judgment on a frozen state; correctness is scored after the "
                    "gold is unsealed."
                ),
                "observed_result": evidence["observed_result"],
                "failure_class": failure_class,
                "error_ref": None,
                "evidence_refs": [
                    {"kind": "native-result", "path": receipt_path, "sha256": digest}
                ],
                "selected_for_analysis": selected,
            }
            _append(directory / "attempts.jsonl", row)
            bucket = self.counts[primitive]
            if validity == "valid":
                bucket["admitted" if outcome == "passed" else "rejected"] += 1
            else:
                bucket["invalid_selected" if selected else "invalid_unselected"] += 1
            return attempt_id

    def _elapsed(self, started: float, call: dict[str, Any] | None) -> dict[str, Any]:
        """Dispatch-to-completion latency on the runner clock; pacing waits lie outside.

        ``call`` (paired mode only) gains the monotonic offsets from the unit start and
        the UTC completion time, so a pair's launch skew is recomputable from receipts.
        """
        finished = self.clock()
        evidence: dict[str, Any] = {"latency_s": finished - started}
        if call is not None:
            evidence["call_timing"] = {
                **call,
                "dispatched_monotonic_s": started - self._origin,
                "completed_monotonic_s": finished - self._origin,
                "completed_at": _now(),
            }
        return evidence

    async def _call_once(
        self,
        workload: Workload,
        engine: _Engine,
        primitive: _Primitive,
        position: int | None = None,
    ) -> tuple[str, dict[str, Any], BaseException | None]:
        from core.llm.adapters.base import AdapterCallRequest, Message
        from core.llm.errors import BillingError

        adapter = self._adapter(engine, primitive, workload.variant)
        request = AdapterCallRequest(
            model=ROOT_MODEL if engine == "llm" else JEV_MODEL,
            effort="xhigh" if engine == "llm" else "none",
            messages=(Message("user", json.dumps(workload.state, ensure_ascii=False)),),
            metadata={
                "verification_correlation": {
                    "llm_call_id": f"{engine}.{primitive}.{workload.workload_id}"[:128].replace(
                        "#", "."
                    ),
                    "step_id": workload.variant,
                }
            },
        )
        call = None
        if position is not None:
            call = {
                "position": position,
                "in_flight_panel_calls": self._in_flight,
                "dispatched_at": _now(),
            }
        self._in_flight += 1
        started = self.clock()
        try:
            # The per-engine limit (Astra 180 s, Jev 60 s) is a transport error (§4.2).
            result = await asyncio.wait_for(
                adapter.acomplete(request), timeout=self.unit.timeouts[engine]
            )
        except BillingError as exc:
            return "quota_exhausted", self._elapsed(started, call), exc
        except (TimeoutError, httpx.TransportError, httpx.HTTPStatusError) as exc:
            return "transport_error", self._elapsed(started, call), exc
        except Exception as exc:  # harness defect: never substituted
            return "harness_error", self._elapsed(started, call), exc
        finally:
            self._in_flight -= 1
        timing = self._elapsed(started, call)
        receipt = adapter.receipts[-1] if adapter.receipts else None
        evidence = {
            **timing,
            "usage": _usage(result),
            "receipt": receipt,
            "stop_reason": result.stop_reason,
        }
        if receipt is None:
            return "harness_error", evidence, None
        expected_model = ROOT_MODEL if engine == "llm" else JEV_MODEL
        if not receipt["accepted"] and (
            receipt.get("response_model") not in (None, expected_model)
            or receipt.get("response_provider") not in (None, adapter.provider)
        ):
            return "route_violation", evidence, None
        return ("admitted" if receipt["accepted"] else "rejected"), evidence, None

    async def _dispatch(
        self,
        workload: Workload,
        engine: _Engine,
        primitive: _Primitive,
        position: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run one planned call and at most one §4.2 replacement; return their timings.

        ``position`` (paired mode) is the launch order within the state's pair.
        """
        parent: str | None = None
        calls: list[dict[str, Any]] = []
        for attempt in (0, 1):
            if engine == "jev" and self.jev_guard is not None:
                try:
                    self.jev_guard.admit_call(f"{workload.workload_id}:{primitive}:{attempt}")
                except Exception as exc:
                    self._stop(f"jev_budget:{type(exc).__name__}")
                    return calls
            started_at = _now()
            status, evidence, error = await self._call_once(workload, engine, primitive, position)
            finished_at = _now()
            if engine == "jev" and self.jev_guard is not None:
                usage = evidence.get("usage") or {}
                self.jev_guard.record_call(
                    f"{workload.workload_id}:{primitive}:{attempt}", usage.get("input_tokens")
                )
            base = {
                "workload_id": workload.workload_id,
                "state_id": workload.state_id,
                "cluster_id": workload.cluster_id,
                "variant": workload.variant,
                "engine": engine,
                "primitive": primitive,
                "status": status,
                "error_type": type(error).__name__ if error else None,
                **evidence,
            }
            if status in {"admitted", "rejected"}:
                base["observed_result"] = (
                    "Admitted matched judgment; correctness is scored after unseal."
                    if status == "admitted"
                    else "Completed judgment rejected by the V1 validator; counts as wrong."
                )
                attempt_id = await self._record(
                    primitive,
                    workload,
                    engine,
                    base,
                    validity="valid",
                    outcome="passed" if status == "admitted" else "failed",
                    failure_class=None if status == "admitted" else "invalid_judge_output",
                    selected=True,
                    parent=parent,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                calls.append(_call_summary(attempt_id, status, evidence))
                return calls
            substitutable = status == "transport_error" and attempt == 0
            if substitutable and (self.substitutions + 1) / self.planned > SUBSTITUTION_LIMIT:
                substitutable = False
                self._stop("substitution_rate_exceeded")
            base["observed_result"] = (
                "Transport failure without a response; replaced once on the same input."
                if substitutable
                else f"Infrastructure invalid ({status}); the unit stops."
            )
            attempt_id = await self._record(
                primitive,
                workload,
                engine,
                base,
                validity="invalid",
                outcome="unknown",
                failure_class=status,
                selected=not substitutable,
                parent=parent,
                started_at=started_at,
                finished_at=finished_at,
            )
            calls.append(_call_summary(attempt_id, status, evidence))
            if not substitutable:
                self._stop(status if attempt == 0 else "replacement_failed")
                return calls
            self.substitutions += 1
            parent = attempt_id
        return calls

    def _stop(self, reason: str) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason

    async def _heartbeat(self, done: asyncio.Event) -> None:
        path = self.unit.session_dir / "heartbeat.jsonl"
        interval = self.unit.heartbeat_s
        while not done.is_set():
            before = self.clock()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=interval)
            observed = self.clock() - before
            _append(
                path,
                {
                    "at": _now(),
                    "expected_s": interval,
                    "observed_s": observed,
                    "lag_s": max(0.0, observed - interval) if not done.is_set() else None,
                },
            )

    async def run(self) -> dict[str, Any]:
        """Dispatch every planned call in frozen order until a stop condition."""
        for directory in self.unit.outputs.values():
            if (directory / "attempts.jsonl").exists():
                raise FileExistsError("attempts already exist; start a new lineage")
        self.unit.session_dir.mkdir(parents=True, exist_ok=True)
        self._origin = self.clock()
        done = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(done))
        try:
            if self.unit.mode == PAIRED_LATENCY_MODE:
                dispatched = await self._run_pairs()
            else:
                dispatched = await self._run_latin()
        finally:
            done.set()
            await heartbeat
        summary: dict[str, Any] = {
            "planned_calls": self.planned,
            "dispatched_calls": dispatched,
            "substitutions": self.substitutions,
            "substitution_rate": self.substitutions / self.planned if self.planned else 0.0,
            "stopped": self.stop_reason is not None,
            "stop_reason": self.stop_reason,
            "counts": self.counts,
            "attempts": {
                primitive: str(self.unit.outputs[primitive] / "attempts.jsonl")
                for primitive in self.unit.primitives
            },
        }
        if self.unit.mode == PAIRED_LATENCY_MODE:
            summary.update(
                mode=PAIRED_LATENCY_MODE,
                max_dispatch_skew_s=self.max_dispatch_skew_s,
                pair_log=str(self.unit.session_dir / PAIR_LOG),
            )
        return summary

    def _log_dispatch(self, workload: Workload, engine: _Engine, primitive: _Primitive) -> None:
        _append(
            self.unit.session_dir / "dispatch-log.jsonl",
            {
                "at": _now(),
                "workload_id": workload.workload_id,
                "engine": engine,
                "primitive": primitive,
            },
        )

    async def _run_latin(self) -> int:
        """Latin-square cells with at most ``max_concurrency`` calls and paced starts."""
        semaphore = asyncio.Semaphore(self.unit.max_concurrency)
        tasks: list[asyncio.Task[None]] = []
        last_start: float | None = None

        async def guarded(workload: Workload, engine: _Engine, primitive: _Primitive) -> None:
            try:
                await self._dispatch(workload, engine, primitive)
            finally:
                semaphore.release()

        for index, workload in enumerate(self.workloads):
            for engine, primitive in latin_cells(index, self.cells):
                await semaphore.acquire()
                if self.stop_reason is not None:
                    semaphore.release()
                    break
                if last_start is not None:
                    wait = self.unit.pacing_s - (self.clock() - last_start)
                    if wait > 0:
                        await self.sleep(wait)
                last_start = self.clock()
                self._log_dispatch(workload, engine, primitive)
                tasks.append(asyncio.create_task(guarded(workload, engine, primitive)))
            if self.stop_reason is not None:
                break
        await asyncio.gather(*tasks)
        return len(tasks)

    async def _run_pairs(self) -> int:
        """U3: launch a state's Astra and Jev Choice calls together, one pair in flight.

        Launch order alternates by state index (the Choice-only Latin rotation). The
        next pair starts only after both calls, and any §4.2 replacement, finish;
        pacing applies between pair starts, outside every measured latency.
        """
        dispatched = 0
        last_start: float | None = None
        for index, workload in enumerate(self.workloads):
            if self.stop_reason is not None:
                break
            if last_start is not None:
                wait = self.unit.pacing_s - (self.clock() - last_start)
                if wait > 0:
                    await self.sleep(wait)
            last_start = self.clock()
            cells = latin_cells(index, self.cells)
            for engine, primitive in cells:
                self._log_dispatch(workload, engine, primitive)
            results = await asyncio.gather(
                *(
                    self._dispatch(workload, engine, primitive, position)
                    for position, (engine, primitive) in enumerate(cells)
                ),
                return_exceptions=True,
            )
            dispatched += len(cells)
            calls = [result for result in results if not isinstance(result, BaseException)]
            if len(calls) != len(results):
                raise next(result for result in results if isinstance(result, BaseException))
            self._log_pair(index, workload, cells, calls)
        return dispatched

    def _log_pair(
        self,
        index: int,
        workload: Workload,
        cells: tuple[tuple[_Engine, _Primitive], ...],
        calls: list[list[dict[str, Any]]],
    ) -> None:
        """Record the pair's launch skew; above one second the dispatcher stops the unit."""
        launched = {
            engine: attempts[0]["dispatched_monotonic_s"]
            for (engine, _), attempts in zip(cells, calls, strict=True)
            if attempts
        }
        skew = None
        if len(launched) == len(cells):
            skew = abs(launched["llm"] - launched["jev"])
            self.max_dispatch_skew_s = max(skew, self.max_dispatch_skew_s or 0.0)
        _append(
            self.unit.session_dir / PAIR_LOG,
            {
                "at": _now(),
                "pair_index": index,
                "workload_id": workload.workload_id,
                "launch_order": [engine for engine, _ in cells],
                "dispatch_skew_s": skew,
                "calls": {
                    engine: attempts for (engine, _), attempts in zip(cells, calls, strict=True)
                },
            },
        )
        if skew is not None and skew > PAIR_SKEW_LIMIT_S:
            self._stop("dispatch_skew_exceeded")


# ---------------------------------------------------------------------------
# U2s stability analysis (preregistration v2.2 §3.2 and §3.7-3)
# ---------------------------------------------------------------------------

STABILITY_VARIANTS = ("rep1", "rep2", "order-rev", "para")
STABILITY_SCHEMA_ID = "geode.jev-panel-stability@1"
STABILITY_RESULTS = "stability-results.json"
STABILITY_PRIMARY = "jev_choice_pair_consistency"
# Each U2s run's frozen primary (05 v2.2: Choice; coordinator 2026-09-27: Noul).
STABILITY_PRIMARIES = {"choice": STABILITY_PRIMARY, "noul": "jev_noul_pair_consistency"}
_PANEL_SURFACE = "judgment-panel"
_NOUL_KEYS = ("has_contradiction", "missing_evidence")


def stability_plan(workload_ids: Sequence[str]) -> list[str]:
    """Frozen U2s states in dispatch order; each carries rep1, rep2, order-rev and para once."""
    variants: dict[str, list[str]] = {}
    for workload_id in workload_ids:
        state_id, separator, variant = workload_id.partition("#")
        if not separator or variant not in STABILITY_VARIANTS:
            raise ValueError(f"{workload_id!r} is not a stability workload")
        variants.setdefault(state_id, []).append(variant)
    for state_id, found in variants.items():
        if sorted(found) != sorted(STABILITY_VARIANTS):
            raise ValueError(f"{state_id}: plan rep1, rep2, order-rev and para exactly once each")
    if not variants:
        raise ValueError("a stability plan needs at least one state")
    return list(variants)


def _canonical_projection(projection: Any) -> str:
    if (
        not isinstance(projection, Mapping)
        or set(projection) != set(_NOUL_KEYS)
        or any(type(projection[key]) is not bool for key in _NOUL_KEYS)
    ):
        raise ValueError("a Noul decision needs both boolean conditions")
    return json.dumps(
        {key: projection[key] for key in _NOUL_KEYS}, sort_keys=True, separators=(",", ":")
    )


def stability_decision(primitive: str, evidence: Mapping[str, Any]) -> str | None:
    """One selected judgment's code-owned decision; ``None`` when it was not admitted.

    Choice gives the admitted verdict and Noul the canonical JSON (sorted keys) of the
    admitted boolean projection. A validator rejection or an infrastructure-invalid
    attempt is ``None``: never filled from another call or variant.
    """
    receipt = evidence.get("receipt")
    if (
        evidence.get("status") != "admitted"
        or not isinstance(receipt, Mapping)
        or receipt.get("accepted") is not True
    ):
        return None
    if primitive == "choice":
        verdict = receipt.get("verdict")
        if verdict not in VERDICTS:
            raise ValueError("an admitted Choice receipt lacks its verdict")
        return str(verdict)
    return _canonical_projection(receipt.get("boolean_projection"))


def gold_decision(primitive: str, gold: Mapping[str, Any]) -> str:
    """The unsealed gold in the same representation as :func:`stability_decision`."""
    if primitive == "choice":
        if gold.get("verdict") not in VERDICTS:
            raise ValueError("a gold row lacks its verdict")
        return str(gold["verdict"])
    return _canonical_projection({key: gold.get(key) for key in _NOUL_KEYS})


def load_stability_gold(
    gold_path: Path, aliases_path: Path | None = None
) -> dict[str, dict[str, Any]]:
    """Unsealed gold keyed by the dispatched state ID (the public alias of a sealed split).

    Read only after every U2c, U2n, U2s and U3 attempt has finished (preregistration
    §3.4); U3's latency report reuses it for its secondary accuracy.
    """
    rows: dict[str, dict[str, Any]] = {}
    for line in gold_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["state_id"] in rows:
                raise ValueError("gold repeats a state")
            rows[str(row["state_id"])] = row
    if aliases_path is None:
        return rows
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    return {str(alias): rows[original] for alias, original in aliases.items() if original in rows}


def _panel_attempts(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "attempts.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _selected_judgments(
    run_dir: Path, primitive: str, *, selected_only: bool = True
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Selected panel attempts of one run with their digest-checked native-result receipt.

    ``selected_only=False`` also returns unselected replaced attempts (U3 launch skew).
    """
    selected = []
    for row in _panel_attempts(run_dir):
        if row["change"]["surface"] != _PANEL_SURFACE or (
            selected_only and row["selected_for_analysis"] is not True
        ):
            continue
        refs = [ref for ref in row["evidence_refs"] if ref["kind"] == "native-result"]
        if len(refs) != 1:
            raise ValueError(f"{row['attempt_id']}: one native-result receipt is required")
        raw = (run_dir / refs[0]["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != refs[0]["sha256"]:
            raise ValueError(f"{row['attempt_id']}: receipt digest mismatch")
        evidence = json.loads(raw)
        if (
            evidence.get("attempt_id") != row["attempt_id"]
            or evidence.get("primitive") != primitive
        ):
            raise ValueError(
                f"{row['attempt_id']}: receipt belongs to another attempt or primitive"
            )
        selected.append((row, evidence))
    return selected


def _ratio_or_unknown(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {"value": NOT_MEASURABLE, "numerator": None, "denominator": None}
    return {key: value[key] for key in ("value", "numerator", "denominator")}


def _bound_row(
    name: str, value: Mapping[str, Any], pointer: str, *, unit: str, source_ref: str
) -> dict[str, Any]:
    """One analysis metric row bound by JSON pointers; unmeasured rows carry no locator."""
    measured = value["value"] != NOT_MEASURABLE
    return {
        "name": name,
        "value": value["value"],
        "numerator": value["numerator"] if measured else None,
        "denominator": value["denominator"] if measured else None,
        "unit": unit,
        "source_ref": source_ref,
        "source_locator": {key: f"{pointer}/{key}" for key in ("value", "numerator", "denominator")}
        if measured
        else None,
    }


def stability_report(
    outputs: Mapping[str, Path],
    workload_ids: Sequence[str],
    *,
    gold: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Group selected U2s judgments by (engine, primitive, state_id) into stability items.

    ``outputs`` maps each primitive to its run directory (``attempts.jsonl`` and
    ``receipts/``); ``workload_ids`` is the frozen ``<state>#<variant>`` order. A state
    with any variant lacking a selected judgment makes that engine and primitive
    not-measurable; nothing is filled in. The primary ``jev_choice_pair_consistency``
    is also not-measurable when the Choice run keeps a selected invalid attempt.
    """
    states = stability_plan(workload_ids)
    if not outputs or set(outputs) - {"choice", "noul"}:
        raise ValueError("stability outputs are keyed by choice and noul")
    if gold is not None and any(state_id not in gold for state_id in states):
        raise ValueError("unsealed gold must cover every planned stability state")
    runs: dict[str, Any] = {}
    for primitive in sorted(outputs):
        cells: dict[tuple[str, str, str], str | None] = {}
        selected_invalid = 0
        for row, evidence in _selected_judgments(outputs[primitive], primitive):
            engine, state_id, variant = (
                evidence.get("engine"),
                evidence.get("state_id"),
                evidence.get("variant"),
            )
            key = (str(engine), str(state_id), str(variant))
            if engine not in ("llm", "jev"):
                raise ValueError(f"{row['attempt_id']}: unknown engine {engine!r}")
            if state_id not in states or variant not in STABILITY_VARIANTS:
                raise ValueError(f"{row['attempt_id']}: {state_id}#{variant} is not planned")
            if key in cells:
                raise ValueError(f"{row['attempt_id']}: a planned judgment is selected twice")
            cells[key] = stability_decision(primitive, evidence)
            selected_invalid += row["validity"] != "valid"
        engines: dict[str, Any] = {}
        for engine in ("llm", "jev"):
            missing = [
                f"{state_id}#{variant}"
                for state_id in states
                for variant in STABILITY_VARIANTS
                if (engine, state_id, variant) not in cells
            ]
            items = [
                {
                    "state_id": state_id,
                    **{
                        variant: cells.get((engine, state_id, variant))
                        for variant in STABILITY_VARIANTS
                    },
                    "gold": gold_decision(primitive, gold[state_id]) if gold else None,
                }
                for state_id in states
            ]
            engines[engine] = {
                "status": "measured" if not missing else NOT_MEASURABLE,
                "reasons": [] if not missing else ["missing_variant"],
                "planned_states": len(states),
                "missing_variants": missing,
                "summary": stability_summary(items) if not missing else None,
                "items": items,
            }
        reasons = list(engines["jev"]["reasons"])
        if selected_invalid:
            reasons.append("selected_invalid_attempt")
        pair = None if reasons else engines["jev"]["summary"]["pair_consistency"]
        runs[primitive] = {
            "selected_invalid_attempts": selected_invalid,
            "complete": selected_invalid == 0
            and all(entry["summary"] is not None for entry in engines.values()),
            # The run's primary follows the evaluation contract: not measurable while a
            # variant is missing or an invalid attempt stays selected.
            "primary": {
                "name": STABILITY_PRIMARIES[primitive],
                "reasons": reasons,
                **_ratio_or_unknown(pair),
            },
            "engines": engines,
        }
    choice = runs.get("choice")
    primary = (
        dict(choice["primary"])
        if choice is not None
        else {"name": STABILITY_PRIMARY, "reasons": ["choice_run_missing"]}
        | _ratio_or_unknown(None)
    )
    return {
        "schema_id": STABILITY_SCHEMA_ID,
        "variants": list(STABILITY_VARIANTS),
        "planned_states": len(states),
        "gold_attached": gold is not None,
        "decision_rule": (
            "Choice: admitted receipt.verdict; Noul: canonical JSON of the admitted "
            "receipt.boolean_projection; a rejection or invalid attempt is null"
        ),
        "primary": primary,
        "runs": runs,
    }


def _record_aggregate(
    run_dir: Path,
    filename: str,
    document: Mapping[str, Any],
    *,
    failure_class: str | None,
    description: str,
    expected_effect: str,
    observed: tuple[str, str],
) -> dict[str, Any]:
    """Write a native-result aggregate and append its selected analysis-only attempt.

    The aggregate lets an analysis bind the primary metric to selected evidence. An
    incomplete run (a ``failure_class``) records an invalid aggregate, so the primary
    stays not-measurable under the evaluation contract.
    """
    complete = failure_class is None
    rows = _panel_attempts(run_dir)
    if not rows:
        raise ValueError("an aggregate needs the run's attempts")
    digest = _write_new(
        run_dir / filename,
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    reference = {"kind": "native-result", "path": filename, "sha256": digest}
    at = _now()
    run_id = rows[-1]["run_id"]
    aggregate = {
        "schema_id": "geode.eval-attempt@1",
        "schema_version": 1,
        "run_id": run_id,
        "attempt_id": f"{run_id}-aggregate",
        "parent_attempt_id": rows[-1]["attempt_id"],
        "sequence": len(rows),
        "timing": {"status": "exact", "started_at": at, "finished_at": at, "source_ref": None},
        "validity": "valid" if complete else "invalid",
        "outcome": "mixed" if complete else "unknown",
        "change": {"surface": "analysis-only", "description": description},
        "expected_effect": expected_effect,
        "observed_result": observed[0] if complete else observed[1],
        "failure_class": failure_class,
        "error_ref": None,
        "evidence_refs": [reference],
        "selected_for_analysis": True,
    }
    _append(run_dir / "attempts.jsonl", aggregate)
    return {"evidence_ref": reference, "aggregate_attempt_id": aggregate["attempt_id"]}


def record_stability_aggregate(
    run_dir: Path, report: Mapping[str, Any], *, primitive: str
) -> dict[str, Any]:
    """Write ``stability-results.json`` and append its selected analysis-only attempt.

    The native-result aggregate lets an analysis bind the primary metric to selected
    evidence. An incomplete run records an invalid aggregate, so the primary stays
    not-measurable under the evaluation contract.
    """
    return _record_aggregate(
        run_dir,
        STABILITY_RESULTS,
        report,
        failure_class=None if report["runs"][primitive]["complete"] else "incomplete_planned_cells",
        description="Frozen U2s stability aggregation; zero model dispatches.",
        expected_effect="Pair consistency and flip rates over the frozen stability states.",
        observed=(
            "Every planned variant was judged.",
            "A planned variant is missing or an invalid attempt stays selected.",
        ),
    )


def stability_metric_rows(
    report: Mapping[str, Any], *, primitive: str, source_ref: str = STABILITY_RESULTS
) -> list[dict[str, Any]]:
    """``analysis.json`` metric rows under the unchanged schema, bound by JSON pointers.

    Names are ``<engine>_<primitive>_pair_consistency``, ``..._flip_rate_order_rev``,
    ``..._flip_rate_para`` and, once gold is attached, ``..._pair_correct_consistency``.
    Each run's primary (``jev_choice_pair_consistency``, ``jev_noul_pair_consistency``)
    comes from that run's primary block. Unmeasured
    rows carry ``"not-measurable"`` with null numerator, denominator and locator.
    """
    run = report["runs"].get(primitive)
    if run is None:
        raise ValueError(f"the stability report has no {primitive} run")

    def row(name: str, value: Mapping[str, Any], pointer: str) -> dict[str, Any]:
        return _bound_row(name, value, pointer, unit="ratio", source_ref=source_ref)

    rows = []
    for engine in ("jev", "llm"):
        summary = run["engines"][engine]["summary"]
        base = f"/runs/{primitive}/engines/{engine}/summary"
        prefix = f"{engine}_{primitive}"
        metrics = [("pair_consistency", "pair_consistency")] + [
            (f"flip_rate_{variant.replace('-', '_')}", f"flip_rate/{variant}")
            for variant in STABILITY_VARIANTS[2:]
        ]
        if report["gold_attached"]:
            metrics.append(("pair_correct_consistency", "pair_correct_consistency"))
        for suffix, path in metrics:
            name = f"{prefix}_{suffix}"
            if name == run["primary"]["name"]:
                rows.append(row(name, run["primary"], f"/runs/{primitive}/primary"))
                continue
            value = summary
            for part in path.split("/"):
                value = value[part] if value is not None else None
            rows.append(row(name, _ratio_or_unknown(value), f"{base}/{path}"))
    return rows


# ---------------------------------------------------------------------------
# U3 paired latency analysis (preregistration v2.2 §2.2, §3.2-§3.4, §3.6)
# ---------------------------------------------------------------------------

LATENCY_SCHEMA_ID = "geode.jev-panel-latency@1"
LATENCY_RESULTS = "latency-results.json"
LATENCY_PRIMARY = "paired_median_latency_delta_s"
# Why a pair leaves the within-pair latency summary, in the order they are checked.
LATENCY_EXCLUSIONS = (
    "missing_attempt",
    "infrastructure_invalid",
    "replaced_call",
    "judgment_output_invalid",
    "dispatch_skew_exceeded",
)
_ENGINES: tuple[_Engine, ...] = ("llm", "jev")


def _latency_seconds(value: Any, attempt_id: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{attempt_id}: a recorded latency must be positive seconds")
    return float(value)


def _latency_exclusion(
    sides: Mapping[str, Mapping[str, Any] | None], skew: float | None
) -> str | None:
    present = [side for side in sides.values() if side is not None]
    if len(present) != len(sides):
        return "missing_attempt"
    if any(side["validity"] != "valid" for side in present):
        return "infrastructure_invalid"
    if any(side["replacement"] for side in present):
        return "replaced_call"
    if any(side["status"] != "admitted" for side in present):
        return "judgment_output_invalid"
    if skew is None or skew > PAIR_SKEW_LIMIT_S:
        return "dispatch_skew_exceeded"
    return None


def _latency_decision(interval: Interval) -> str:
    """05 §3.4 U3: Jev is faster when the whole interval lies below zero seconds."""
    if interval.upper is not None and interval.upper < 0:
        return "supported"
    if interval.lower is not None and interval.lower > 0:
        return "not-supported"
    return "mixed"


def _seconds(value: float | None) -> dict[str, Any]:
    return _ratio_or_unknown(
        None if value is None else {"value": value, "numerator": value, "denominator": 1}
    )


def latency_report(
    run_dir: Path,
    workload_ids: Sequence[str],
    *,
    split_manifest_sha256: str,
    gold: Mapping[str, Mapping[str, Any]] | None = None,
    min_clusters: int = 10,
) -> dict[str, Any]:
    """U3 within-pair latency from a paired-latency run's attempts and receipts.

    Each planned workload is one pair: the selected Astra (A) and Jev (B) Choice
    judgments launched together. Latency is the runner's monotonic dispatch-to-
    completion time with pacing waits outside it (05 §3.2). The primary
    ``paired_median_latency_delta_s`` is the median over comparable pairs of B − A,
    with the source-cluster bootstrap seeded by the split manifest digest, authored
    or external (§3.3), and the §3.4 decision: supported when the upper bound is
    below 0 s, not-supported when the lower bound is above 0 s, mixed otherwise.

    A pair leaves the latency summary when a side is missing, infrastructure
    invalid, a §4.2 replacement (launched after its sibling) or a V1 rejection, or
    when its launch skew exceeds one second; counts are kept per reason. The primary
    is not-measurable while a planned pair is missing, an invalid attempt stays
    selected, a launch skew exceeds one second or no pair is comparable. With
    unsealed ``gold`` each engine's accuracy keeps every planned state and counts a
    rejection as wrong (§3.1); a missing or infrastructure-invalid side makes that
    engine's accuracy not-measurable instead of being filled.
    """
    planned = list(workload_ids)
    if not planned or len(set(planned)) != len(planned):
        raise ValueError("a latency plan needs unique workload IDs")
    if not re.fullmatch(r"[0-9a-f]{64}", split_manifest_sha256):
        raise ValueError("split manifest digest must be a SHA-256 hex string")
    states = {workload_id: workload_id.partition("#")[0] for workload_id in planned}
    if gold is not None and any(state_id not in gold for state_id in states.values()):
        raise ValueError("unsealed gold must cover every planned latency state")
    launched: dict[tuple[str, str], Mapping[str, Any]] = {}
    selected: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for row, evidence in _selected_judgments(run_dir, "choice", selected_only=False):
        engine, workload_id = evidence.get("engine"), evidence.get("workload_id")
        timing = evidence.get("call_timing")
        if engine not in _ENGINES or workload_id not in states:
            raise ValueError(f"{row['attempt_id']}: {engine} {workload_id} is not planned")
        if not isinstance(timing, Mapping):
            raise ValueError(f"{row['attempt_id']}: not a paired-latency attempt")
        key = (str(engine), str(workload_id))
        if row["parent_attempt_id"] is None:
            if key in launched:
                raise ValueError(f"{row['attempt_id']}: a planned call was launched twice")
            launched[key] = timing
        if row["selected_for_analysis"] is True:
            if key in selected:
                raise ValueError(f"{row['attempt_id']}: a planned call is selected twice")
            selected[key] = (row, evidence)
    pairs: list[dict[str, Any]] = []
    for workload_id in planned:
        sides: dict[str, dict[str, Any] | None] = {}
        clusters = set()
        for engine in _ENGINES:
            found = selected.get((engine, workload_id))
            if found is None:
                sides[engine] = None
                continue
            row, evidence = found
            clusters.add(evidence.get("cluster_id"))
            sides[engine] = {
                "attempt_id": row["attempt_id"],
                "status": evidence.get("status"),
                "validity": row["validity"],
                "replacement": row["parent_attempt_id"] is not None,
                "latency_s": _latency_seconds(evidence.get("latency_s"), row["attempt_id"]),
            }
        if len(clusters) > 1:
            raise ValueError(f"{workload_id}: the two sides disagree on the source cluster")
        first = {engine: launched.get((engine, workload_id)) for engine in _ENGINES}
        skew = None
        if first["llm"] is not None and first["jev"] is not None:
            skew = abs(
                float(first["jev"]["dispatched_monotonic_s"])
                - float(first["llm"]["dispatched_monotonic_s"])
            )
        reason = _latency_exclusion(sides, skew)
        llm, jev = sides["llm"], sides["jev"]
        pairs.append(
            {
                "workload_id": workload_id,
                "state_id": states[workload_id],
                "cluster_id": next(iter(clusters), None),
                "launch_order": [
                    engine
                    for _, engine in sorted(
                        (int(timing["position"]), engine)
                        for engine, timing in first.items()
                        if timing is not None
                    )
                ],
                "dispatch_skew_s": skew,
                "llm": llm,
                "jev": jev,
                "delta_s": jev["latency_s"] - llm["latency_s"]
                if reason is None and llm is not None and jev is not None
                else None,
                "excluded_reason": reason,
            }
        )
    comparable = [pair for pair in pairs if pair["excluded_reason"] is None]

    def statistic(rows: list[dict[str, Any]]) -> float | None:
        latencies = [(row["llm"]["latency_s"], row["jev"]["latency_s"]) for row in rows]
        value = paired_median_delta(latencies)["value"]
        return None if value is None else float(value)

    selected_invalid = sum(row["validity"] != "valid" for row, _ in selected.values())
    skews = [pair["dispatch_skew_s"] for pair in pairs if pair["dispatch_skew_s"] is not None]
    reasons = []
    if any(pair["llm"] is None or pair["jev"] is None for pair in pairs):
        reasons.append("incomplete_planned_pairs")
    if selected_invalid:
        reasons.append("selected_invalid_attempt")
    if any(skew > PAIR_SKEW_LIMIT_S for skew in skews):
        reasons.append("dispatch_skew_exceeded")
    if not comparable:
        reasons.append("no_comparable_pairs")
    primary: dict[str, Any] = {"name": LATENCY_PRIMARY, "unit": "s", "reasons": reasons}
    if reasons:
        primary.update(_ratio_or_unknown(None), interval=None, decision="invalidated")
    else:
        by_cluster: dict[str, list[dict[str, Any]]] = {}
        for pair in comparable:
            by_cluster.setdefault(str(pair["cluster_id"]), []).append(pair)
        interval = cluster_bootstrap(
            by_cluster,
            statistic,
            seed=bootstrap_seed(split_manifest_sha256, LATENCY_PRIMARY),
            min_clusters=min_clusters,
        )
        primary.update(
            _seconds(statistic(comparable)),
            interval=interval.as_dict(),
            decision=_latency_decision(interval),
        )
    exclusions = Counter(pair["excluded_reason"] for pair in pairs)
    summary = {
        "planned_pairs": len(pairs),
        "comparable_pairs": {
            "value": len(comparable) / len(pairs),
            "numerator": len(comparable),
            "denominator": len(pairs),
        },
        "excluded_pairs": len(pairs) - len(comparable),
        "excluded_by_reason": {reason: exclusions[reason] for reason in LATENCY_EXCLUSIONS},
        "selected_invalid_attempts": selected_invalid,
        "median_latency_s": {
            engine: _seconds(
                statistics.median(pair[engine]["latency_s"] for pair in comparable)
                if comparable
                else None
            )
            for engine in _ENGINES
        },
        "max_dispatch_skew_s": _seconds(max(skews) if skews else None),
        "dispatch_skew_limit_s": PAIR_SKEW_LIMIT_S,
        "launched_first": {
            engine: sum(pair["launch_order"][:1] == [engine] for pair in pairs)
            for engine in _ENGINES
        },
    }
    accuracies: dict[str, Any] | None = None
    if gold is not None:
        accuracies = {}
        for engine in _ENGINES:
            if any(pair[engine] is None or pair[engine]["validity"] != "valid" for pair in pairs):
                accuracies[engine] = {**_ratio_or_unknown(None), "reasons": ["missing_or_invalid"]}
                continue
            records = [
                choice_record(
                    pair["state_id"],
                    str(pair["cluster_id"]),
                    gold_decision("choice", gold[pair["state_id"]]),
                    selected[(engine, pair["workload_id"])][1].get("receipt") or {},
                )
                for pair in pairs
            ]
            accuracies[engine] = {**accuracy(records).as_dict(), "reasons": []}
    return {
        "schema_id": LATENCY_SCHEMA_ID,
        "mode": PAIRED_LATENCY_MODE,
        "split_manifest_sha256": split_manifest_sha256,
        "latency_rule": (
            "runner monotonic clock from dispatch to completion; pacing waits excluded; "
            "median over comparable pairs of Jev minus Astra"
        ),
        "decision_rule": (
            "supported: CI upper < 0 s (Jev faster); not-supported: CI lower > 0 s; mixed otherwise"
        ),
        "primary": primary,
        "summary": summary,
        "gold_attached": gold is not None,
        "accuracy": accuracies,
        "pairs": pairs,
    }


def record_latency_aggregate(run_dir: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    """Write ``latency-results.json`` and append its selected analysis-only attempt.

    A not-measurable primary makes the aggregate invalid, with the first reason as
    its failure class, so the evaluation contract keeps the primary unpublished.
    """
    reasons = report["primary"]["reasons"]
    return _record_aggregate(
        run_dir,
        LATENCY_RESULTS,
        report,
        failure_class=reasons[0] if reasons else None,
        description="Frozen U3 paired latency aggregation; zero model dispatches.",
        expected_effect="Median within-pair Jev minus Astra latency over the frozen states.",
        observed=(
            "Every planned pair was launched together and compared.",
            "A planned pair is missing, an invalid attempt stays selected, a launch skew "
            "exceeded one second or no pair is comparable.",
        ),
    )


def latency_metric_rows(
    report: Mapping[str, Any], *, source_ref: str = LATENCY_RESULTS
) -> list[dict[str, Any]]:
    """U3 ``analysis.json`` rows under the unchanged schema, bound by JSON pointers.

    The primary ``paired_median_latency_delta_s`` (unit s, denominator 1), then the
    comparable-pair ratio, each engine's median latency over comparable pairs and the
    largest launch skew; with gold, ``<engine>_choice_accuracy``. Unmeasured rows
    carry ``"not-measurable"`` with null numerator, denominator and locator.
    """
    summary = report["summary"]
    rows = [
        _bound_row(LATENCY_PRIMARY, report["primary"], "/primary", unit="s", source_ref=source_ref),
        _bound_row(
            "latency_comparable_pair_ratio",
            summary["comparable_pairs"],
            "/summary/comparable_pairs",
            unit="ratio",
            source_ref=source_ref,
        ),
    ]
    rows.extend(
        _bound_row(
            f"{engine}_choice_median_latency_s",
            summary["median_latency_s"][engine],
            f"/summary/median_latency_s/{engine}",
            unit="s",
            source_ref=source_ref,
        )
        for engine in _ENGINES
    )
    rows.append(
        _bound_row(
            "max_dispatch_skew_s",
            summary["max_dispatch_skew_s"],
            "/summary/max_dispatch_skew_s",
            unit="s",
            source_ref=source_ref,
        )
    )
    if report["accuracy"] is not None:
        rows.extend(
            _bound_row(
                f"{engine}_choice_accuracy",
                report["accuracy"][engine],
                f"/accuracy/{engine}",
                unit="ratio",
                source_ref=source_ref,
            )
            for engine in _ENGINES
        )
    return rows


def _stability_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.benchmarks.verdict_panel_runner stability",
        description="U2s stability aggregation from retained panel attempts (no model call).",
    )
    parser.add_argument("--run-spec", type=Path, required=True, help="frozen U2s run spec")
    parser.add_argument("--choice", type=Path, required=True)
    parser.add_argument("--noul", type=Path, required=True)
    parser.add_argument("--gold", type=Path, help="unsealed gold; only after every U2s attempt")
    parser.add_argument("--aliases", type=Path, help="sealed alias map for the gold state IDs")
    parser.add_argument(
        "--record", action="store_true", help="write results and aggregate attempts per run"
    )
    # Exit 1 reports a not-measurable primary; the report and rows are still printed.
    args = parser.parse_args(argv)
    spec = json.loads(args.run_spec.read_text(encoding="utf-8"))
    outputs = {"choice": args.choice, "noul": args.noul}
    gold = load_stability_gold(args.gold, args.aliases) if args.gold else None
    report = stability_report(
        outputs, spec["reproduction"]["execution"]["ordered_workload_ids"], gold=gold
    )
    if args.record:
        for primitive, directory in outputs.items():
            record_stability_aggregate(directory, report, primitive=primitive)
    rows = {primitive: stability_metric_rows(report, primitive=primitive) for primitive in outputs}
    print(json.dumps({"primary": report["primary"], "metrics": rows}, indent=2, sort_keys=True))
    return 0 if report["primary"]["value"] != NOT_MEASURABLE else 1


def _latency_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.benchmarks.verdict_panel_runner latency",
        description="U3 paired latency aggregation from retained panel attempts (no model call).",
    )
    parser.add_argument("--run-spec", type=Path, required=True, help="frozen U3 run spec")
    parser.add_argument("--run-dir", type=Path, required=True, help="the U3 Choice run directory")
    parser.add_argument(
        "--split-manifest",
        type=Path,
        required=True,
        help="split manifest (authored or external) whose sha256 seeds the interval",
    )
    parser.add_argument("--gold", type=Path, help="unsealed gold; only after every test attempt")
    parser.add_argument("--aliases", type=Path, help="sealed alias map for the gold state IDs")
    parser.add_argument(
        "--record", action="store_true", help="write latency-results.json and its aggregate"
    )
    # Exit 1 reports a not-measurable primary; the report and rows are still printed.
    args = parser.parse_args(argv)
    spec = json.loads(args.run_spec.read_text(encoding="utf-8"))
    report = latency_report(
        args.run_dir,
        spec["reproduction"]["execution"]["ordered_workload_ids"],
        split_manifest_sha256=hashlib.sha256(args.split_manifest.read_bytes()).hexdigest(),
        gold=load_stability_gold(args.gold, args.aliases) if args.gold else None,
    )
    if args.record:
        record_latency_aggregate(args.run_dir, report)
    output = {
        "primary": report["primary"],
        "summary": report["summary"],
        "metrics": latency_metric_rows(report),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if report["primary"]["value"] != NOT_MEASURABLE else 1


_COMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "stability": _stability_main,
    "latency": _latency_main,
}


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in _COMMANDS:
        print("usage: python -m evals.benchmarks.verdict_panel_runner {stability,latency} ...")
        return 2
    return _COMMANDS[arguments[0]](arguments[1:])


if __name__ == "__main__":
    raise SystemExit(main())
