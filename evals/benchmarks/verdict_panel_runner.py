"""Judgment-level verdict panel runner: frozen states × {Choice, Noul} × {Astra, Jev}.

The runner calls the matched verifier directly — no Harbor task, no root loop. It
fixes the preregistered dispatch order (a 4×4 Latin square over the four engine ×
primitive cells), bounded concurrency, pacing, an event-loop heartbeat and the
panel-only transport-substitution rule. Model clients and credentials stay
caller-owned; nothing here reads a key. Correctness is scored only after gold is
unsealed, so attempts record admission, not task success.

After a U2s stability unit, :func:`stability_report` reads the two retained
attempt files and their native-result receipts, groups the selected judgments by
(engine, primitive, state_id) and feeds ``decision_metrics.stability_summary``;
:func:`record_stability_aggregate` and :func:`stability_metric_rows` bind the
result to an analysis under the unchanged schema (preregistration v2.2 §3.7-3).
Usage: ``python -m evals.benchmarks.verdict_panel_runner stability --run-spec
<choice run-spec> --choice <dir> --noul <dir> [--gold <jsonl> --aliases <json>]
[--record]``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import SecretStr

from evals.benchmarks.decision_handoff import ROOT_MODEL
from evals.benchmarks.decision_metrics import NOT_MEASURABLE, stability_summary
from evals.benchmarks.decision_verification import VERDICTS, MatchedVerifierAdapter
from evals.benchmarks.typesafe_decision import JEV_MODEL

_Engine = Literal["llm", "jev"]
_Primitive = Literal["choice", "noul"]
# [A-Choice, B-Choice, A-Noul, B-Noul]; state i uses row i mod 4 (05 §2.2).
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
    """Bind frozen workload IDs (``<state_id>`` or ``<state_id>#<variant>``) to states."""
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


def latin_cells(index: int) -> tuple[tuple[_Engine, _Primitive], ...]:
    shift = index % len(CELLS)
    return CELLS[shift:] + CELLS[:shift]


@dataclass
class PanelUnit:
    run_ids: Mapping[str, str]
    outputs: Mapping[str, Path]
    session_dir: Path
    pacing_s: float = 1.0
    max_concurrency: int = MAX_CONCURRENCY
    heartbeat_s: float = 5.0
    paraphrases: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    timeouts: Mapping[str, float] = field(default_factory=lambda: dict(CALL_TIMEOUTS))

    def validate(self) -> None:
        if set(self.run_ids) != {"choice", "noul"} or set(self.outputs) != {"choice", "noul"}:
            raise ValueError("a panel unit writes one Choice and one Noul attempts file")
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
        self.planned = len(self.workloads) * len(CELLS)
        self.sequence = {"choice": 0, "noul": 0}
        self.substitutions = 0
        self.stop_reason: str | None = None
        self.counts: dict[str, dict[str, int]] = {
            primitive: {
                "admitted": 0,
                "rejected": 0,
                "invalid_selected": 0,
                "invalid_unselected": 0,
            }
            for primitive in ("choice", "noul")
        }
        self._lock = asyncio.Lock()
        if any(workload.variant == "para" for workload in self.workloads):
            from evals.benchmarks.decision_verification import question_variant

            for primitive in ("choice", "noul"):
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

    async def _call_once(
        self, workload: Workload, engine: _Engine, primitive: _Primitive
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
        started = self.clock()
        try:
            result = await asyncio.wait_for(
                adapter.acomplete(request), timeout=self.unit.timeouts[engine]
            )
        except BillingError as exc:
            return "quota_exhausted", {"latency_s": self.clock() - started}, exc
        except (TimeoutError, httpx.TransportError, httpx.HTTPStatusError) as exc:
            return "transport_error", {"latency_s": self.clock() - started}, exc
        except Exception as exc:  # harness defect: never substituted
            return "harness_error", {"latency_s": self.clock() - started}, exc
        latency = self.clock() - started
        receipt = adapter.receipts[-1] if adapter.receipts else None
        evidence = {
            "latency_s": latency,
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

    async def _dispatch(self, workload: Workload, engine: _Engine, primitive: _Primitive) -> None:
        parent: str | None = None
        for attempt in (0, 1):
            if engine == "jev" and self.jev_guard is not None:
                try:
                    self.jev_guard.admit_call(f"{workload.workload_id}:{primitive}:{attempt}")
                except Exception as exc:
                    self._stop(f"jev_budget:{type(exc).__name__}")
                    return
            started_at = _now()
            status, evidence, error = await self._call_once(workload, engine, primitive)
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
                await self._record(
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
                return
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
            if not substitutable:
                self._stop(status if attempt == 0 else "replacement_failed")
                return
            self.substitutions += 1
            parent = attempt_id

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
        done = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(done))
        semaphore = asyncio.Semaphore(self.unit.max_concurrency)
        tasks: list[asyncio.Task[None]] = []
        last_start: float | None = None

        async def guarded(workload: Workload, engine: _Engine, primitive: _Primitive) -> None:
            try:
                await self._dispatch(workload, engine, primitive)
            finally:
                semaphore.release()

        try:
            for index, workload in enumerate(self.workloads):
                for engine, primitive in latin_cells(index):
                    await semaphore.acquire()
                    if self.stop_reason is not None:
                        semaphore.release()
                        break
                    if last_start is not None:
                        wait = self.unit.pacing_s - (self.clock() - last_start)
                        if wait > 0:
                            await self.sleep(wait)
                    last_start = self.clock()
                    _append(
                        self.unit.session_dir / "dispatch-log.jsonl",
                        {
                            "at": _now(),
                            "workload_id": workload.workload_id,
                            "engine": engine,
                            "primitive": primitive,
                        },
                    )
                    tasks.append(asyncio.create_task(guarded(workload, engine, primitive)))
                if self.stop_reason is not None:
                    break
            await asyncio.gather(*tasks)
        finally:
            done.set()
            await heartbeat
        return {
            "planned_calls": self.planned,
            "dispatched_calls": len(tasks),
            "substitutions": self.substitutions,
            "substitution_rate": self.substitutions / self.planned if self.planned else 0.0,
            "stopped": self.stop_reason is not None,
            "stop_reason": self.stop_reason,
            "counts": self.counts,
            "attempts": {
                primitive: str(self.unit.outputs[primitive] / "attempts.jsonl")
                for primitive in ("choice", "noul")
            },
        }


# ---------------------------------------------------------------------------
# U2s stability analysis (preregistration v2.2 §3.2 and §3.7-3)
# ---------------------------------------------------------------------------

STABILITY_VARIANTS = ("rep1", "rep2", "order-rev", "para")
STABILITY_SCHEMA_ID = "geode.jev-panel-stability@1"
STABILITY_RESULTS = "stability-results.json"
STABILITY_PRIMARY = "jev_choice_pair_consistency"
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

    Read only after every U2s attempt has finished (preregistration §3.4).
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
    run_dir: Path, primitive: str
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Selected panel attempts of one run with their digest-checked native-result receipt."""
    selected = []
    for row in _panel_attempts(run_dir):
        if row["change"]["surface"] != _PANEL_SURFACE or row["selected_for_analysis"] is not True:
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
        runs[primitive] = {
            "selected_invalid_attempts": selected_invalid,
            "complete": selected_invalid == 0
            and all(entry["summary"] is not None for entry in engines.values()),
            "engines": engines,
        }
    choice = runs.get("choice")
    reasons: list[str] = []
    pair: Mapping[str, Any] | None = None
    if choice is None:
        reasons.append("choice_run_missing")
    else:
        reasons.extend(choice["engines"]["jev"]["reasons"])
        if choice["selected_invalid_attempts"]:
            reasons.append("selected_invalid_attempt")
        if not reasons:
            pair = choice["engines"]["jev"]["summary"]["pair_consistency"]
    primary = {"name": STABILITY_PRIMARY, "reasons": reasons, **_ratio_or_unknown(pair)}
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


def record_stability_aggregate(
    run_dir: Path, report: Mapping[str, Any], *, primitive: str
) -> dict[str, Any]:
    """Write ``stability-results.json`` and append its selected analysis-only attempt.

    The native-result aggregate lets an analysis bind the primary metric to selected
    evidence. An incomplete run records an invalid aggregate, so the primary stays
    not-measurable under the evaluation contract.
    """
    rows = _panel_attempts(run_dir)
    if not rows:
        raise ValueError("a stability aggregate needs the run's attempts")
    digest = _write_new(
        run_dir / STABILITY_RESULTS,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    reference = {"kind": "native-result", "path": STABILITY_RESULTS, "sha256": digest}
    complete = bool(report["runs"][primitive]["complete"])
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
        "change": {
            "surface": "analysis-only",
            "description": "Frozen U2s stability aggregation; zero model dispatches.",
        },
        "expected_effect": "Pair consistency and flip rates over the frozen stability states.",
        "observed_result": "Every planned variant was judged."
        if complete
        else "A planned variant is missing or an invalid attempt stays selected.",
        "failure_class": None if complete else "incomplete_planned_cells",
        "error_ref": None,
        "evidence_refs": [reference],
        "selected_for_analysis": True,
    }
    _append(run_dir / "attempts.jsonl", aggregate)
    return {"evidence_ref": reference, "aggregate_attempt_id": aggregate["attempt_id"]}


def stability_metric_rows(
    report: Mapping[str, Any], *, primitive: str, source_ref: str = STABILITY_RESULTS
) -> list[dict[str, Any]]:
    """``analysis.json`` metric rows under the unchanged schema, bound by JSON pointers.

    Names are ``<engine>_<primitive>_pair_consistency``, ``..._flip_rate_order_rev``,
    ``..._flip_rate_para`` and, once gold is attached, ``..._pair_correct_consistency``.
    ``jev_choice_pair_consistency`` comes from the report's primary block. Unmeasured
    rows carry ``"not-measurable"`` with null numerator, denominator and locator.
    """
    run = report["runs"].get(primitive)
    if run is None:
        raise ValueError(f"the stability report has no {primitive} run")

    def row(name: str, value: Mapping[str, Any], pointer: str) -> dict[str, Any]:
        measured = value["value"] != NOT_MEASURABLE
        return {
            "name": name,
            "value": value["value"],
            "numerator": value["numerator"] if measured else None,
            "denominator": value["denominator"] if measured else None,
            "unit": "ratio",
            "source_ref": source_ref,
            "source_locator": {
                key: f"{pointer}/{key}" for key in ("value", "numerator", "denominator")
            }
            if measured
            else None,
        }

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
            if name == report["primary"]["name"]:
                rows.append(row(name, report["primary"], "/primary"))
                continue
            value = summary
            for part in path.split("/"):
                value = value[part] if value is not None else None
            rows.append(row(name, _ratio_or_unknown(value), f"{base}/{path}"))
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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] != ["stability"]:
        print("usage: python -m evals.benchmarks.verdict_panel_runner stability ...")
        return 2
    return _stability_main(arguments[1:])


if __name__ == "__main__":
    raise SystemExit(main())
