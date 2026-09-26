"""Host-scoped, append-only cost ledger and hard cap for billed Jev calls.

Scope
-----
This module runs on the evaluation host. The Harbor container path never
imports it. One ledger guards the whole Jev program (preregistration §9):

* Before a unit starts, :meth:`JevCostLedger.admit_unit` requires
  ``committed + planned_jev_calls x p95_input_tokens x rate <= start limit``
  and refuses outright once committed spend has reached the start limit.
* Before each Harbor trial or panel call, :meth:`JevCostLedger.reserve` holds
  that dispatch's worst case, ``max_calls x input_tokens_per_call x rate``.
* After the trial's cleanup, :meth:`JevCostLedger.settle` replaces the
  reservation with the observed Jev calls, normally
  ``jev_calls_from_call_accounting(handoff_result["call_accounting"])``. When
  the result is missing or its accounting is incomplete, settle the missing
  calls as unknown (``input_tokens=None``); never release them as zero.
  In-process panel code can use :meth:`JevCostLedger.call` instead.
* Once committed spend reaches the stop limit, or a settlement reports more
  calls than were reserved, the ledger records ``stop`` and raises
  :class:`JevBudgetExhaustedError`. The caller halts Jev dispatch immediately; a
  stopped ledger refuses every later admission and reservation.

Refusals raise :class:`JevBudgetRefusedError` and authorize no spend. Both
budget errors carry ``reason``, the post-decision ``status`` and any recorded
``record``; the design's names ``JevBudgetRefused`` and ``JevBudgetExhausted``
alias them.

The container keeps ``settings.cost_limit_usd = 0`` (disabled). Its loop
tracker prices every recorded call by model tariff, including Astra
subscription calls at API-equivalent rates, so a positive in-container limit
would stop on charges that were never billed while still not reserving Jev
spend. Model settings do not enforce this budget; this host ledger does. For
the same reason the ledger never reads 0 as "unlimited": creating or opening
one requires a positive, finite cost limit no larger than
:data:`PROGRAM_CAP_USD`.

Amounts
-------
Ledger amounts are published-tariff estimates, not invoices: ``input_tokens x
JEV_INPUT_USD_PER_MILLION / 1e6`` with output at $0, using the TypeSafe price
reference recorded in ``decision_handoff_runtime.PRICE_REFERENCE``. A call
without an observed input-token count goes to a separate reserve column at
:data:`RESERVE_INPUT_TOKENS` tokens. Committed spend is the estimate column
plus the reserve column (settled missing-token reserves and open
reservations). Actual charges remain unknown until reconciled with TypeSafe
billing. Money is :class:`~decimal.Decimal`, serialized as fixed-point strings
quantized to 1e-9 USD and rounded up; at $0.042 per million input tokens every
per-call amount is exact at that quantum. A reservation bounds each call at
``input_tokens_per_call``; the margin between the stop limit and the cost
limit absorbs in-flight calls that exceed it, and callers that need a strict
bound reserve with the model's maximum input size.

Storage
-------
The ledger is a JSONL file created exclusively with mode 0600. Each line is a
canonical JSON object (sorted keys, no whitespace, ASCII). The first record is
the ``header``: schema, limits, rate, reserve tokens and price reference.
Every record carries a contiguous ``seq``, a UTC ISO ``ts``, its ``kind`` and
``prev_sha256``, the SHA-256 of the previous line's bytes without the newline.
Opening re-verifies every line, checks the header against this module's
constants, and replays every amount and budget decision. The ``<ledger>.head``
sidecar anchors the newest record (record count and hash), so removing or
editing trailing records is detected; after a crash between an append and the
anchor update it may lag behind by one record. ``fcntl.flock`` serializes
read-verify-append across processes and threads, and lines are never
rewritten. Records hold only ids, counts, tokens and USD, never prompts,
outputs or credentials.

CLI
---
``python -m evals.benchmarks.jev_cost_ledger {init,status,admit,reserve,settle}``
prints one JSON object on stdout. Exit codes:

* 0: success.
* 2: invalid arguments or input.
* 3: refused while the ledger stays open (unit not admitted, projection or
  reservation over its limit).
* 4: exhausted or stopped; halt all Jev dispatch.
* 5: integrity or file-system failure (tampered, truncated or unsafe ledger,
  header mismatch, missing file, or an existing path on ``init``).
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Context, Decimal, DivisionByZero, InvalidOperation, Overflow
from pathlib import Path
from typing import Any, NoReturn

from evals.benchmarks.decision_handoff_runtime import (
    JEV_INPUT_USD_PER_MILLION,
    JEV_MODEL,
    PRICE_REFERENCE,
)

SCHEMA_ID = "geode.jev-cost-ledger@1"
ANCHOR_SCHEMA_ID = "geode.jev-cost-ledger-head@1"
PROGRAM_CAP_USD = Decimal("1.00")
START_LIMIT_USD = Decimal("0.90")
STOP_LIMIT_USD = Decimal("0.95")
RESERVE_INPUT_TOKENS = 25_000
USD_QUANTUM = Decimal("0.000000001")
MAX_INPUT_TOKENS_PER_CALL = 10_000_000
MAX_CALLS = 1_000_000
COST_AUTHORITY = "published-input-token-tariff-estimate-not-invoice"

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_REFUSED = 3
EXIT_STOPPED = 4
EXIT_INTEGRITY = 5

_CTX = Context(prec=40, rounding=ROUND_CEILING, traps=[InvalidOperation, DivisionByZero, Overflow])
USD_PER_INPUT_TOKEN = _CTX.divide(JEV_INPUT_USD_PER_MILLION, Decimal(1_000_000))
_ZERO = Decimal(0)
_MONEY = re.compile(r"\d{1,15}\.\d{9}")
_ID = re.compile(r"[\x21-\x7e]{1,256}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
_COMMON_FIELDS = frozenset({"seq", "ts", "kind", "prev_sha256"})
_LIMIT_FIELDS = ("cost_limit_usd", "start_limit_usd", "stop_limit_usd")
_ADMISSION_FIELDS = frozenset(
    {
        "unit_id",
        "planned_jev_calls",
        "p95_input_tokens",
        "p95_source",
        "p95_sample_calls",
        "projection_usd",
        "committed_before_usd",
        "reason",
    }
)
_RECORD_FIELDS = {
    "unit_admitted": _ADMISSION_FIELDS,
    "unit_refused": _ADMISSION_FIELDS,
    "reservation": frozenset(
        {
            "reservation_id",
            "unit_id",
            "max_calls",
            "input_tokens_per_call",
            "reserved_usd",
            "committed_before_usd",
        }
    ),
    "settlement": frozenset(
        {
            "reservation_id",
            "unit_id",
            "max_calls",
            "released_usd",
            "calls",
            "estimate_usd",
            "reserve_usd",
            "overrun_calls",
            "committed_after_usd",
        }
    ),
    "stop": frozenset({"reason", "reservation_id", "committed_usd"}),
}
_CALL_FIELDS = frozenset({"call_id", "input_tokens", "estimate_usd", "reserve_usd"})
_P95_SOURCES = frozenset({"explicit", "earlier_units", "reserve_default"})
_STOP_REASONS = frozenset({"stop_limit_reached", "reservation_overrun"})


class JevLedgerError(RuntimeError):
    """Base class for Jev cost-ledger failures."""


class JevLedgerIntegrityError(JevLedgerError):
    """Ledger bytes, header, head anchor or file safety failed verification."""


class JevBudgetError(JevLedgerError):
    """A budget decision; ``status`` is the verified ledger state after it."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        status: dict[str, Any],
        record: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.status = status
        self.record = record

    @property
    def stopped(self) -> bool:
        """Whether the ledger is stopped, so every Jev dispatch must halt."""
        return self.status.get("stopped") is True


class JevBudgetRefusedError(JevBudgetError):
    """An admission or reservation was refused; no spend was authorized."""


class JevBudgetExhaustedError(JevBudgetError):
    """The ledger is stopped. Any triggering settlement was already recorded."""


# Names used by the experiment design; the classes carry GEODE's ``Error`` suffix.
JevBudgetRefused = JevBudgetRefusedError
JevBudgetExhausted = JevBudgetExhaustedError


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _require_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _require_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be 1-256 printable ASCII characters without spaces")
    return value


def _add(values: Iterable[Decimal]) -> Decimal:
    total = _ZERO
    for value in values:
        total = _CTX.add(total, value)
    return total


def _usd(tokens: int) -> Decimal:
    """Published-tariff estimate for ``tokens`` input tokens (output is free)."""
    return _CTX.multiply(Decimal(tokens), USD_PER_INPUT_TOKEN).quantize(USD_QUANTUM, context=_CTX)


def _money(value: Decimal) -> str:
    return format(value.quantize(USD_QUANTUM, context=_CTX), "f")


def _parse_money(value: object, *, name: str) -> Decimal:
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        raise ValueError(f"{name} is not a fixed-point USD amount")
    return Decimal(value)


def _require_usd(value: object, *, name: str) -> Decimal:
    """Parse a positive, finite USD limit; 0 is refused, never read as unlimited."""
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise ValueError(f"{name} must be a Decimal, int or decimal string")
    try:
        amount = Decimal(value.strip()) if isinstance(value, str) else Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{name} is not a decimal amount") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError(
            f"{name} must be positive and finite; GEODE reads cost_limit_usd = 0 as disabled"
        )
    if amount > PROGRAM_CAP_USD:
        raise ValueError(f"{name} exceeds the program cap of {PROGRAM_CAP_USD} USD")
    if amount != amount.quantize(USD_QUANTUM, context=_CTX):
        raise ValueError(f"{name} must be a multiple of {format(USD_QUANTUM, 'f')} USD")
    return amount.quantize(USD_QUANTUM, context=_CTX)


def _validated_limits(
    cost: object, start: object, stop: object
) -> tuple[Decimal, Decimal, Decimal]:
    cost_limit = _require_usd(cost, name="cost_limit_usd")
    start_limit = _require_usd(start, name="start_limit_usd")
    stop_limit = _require_usd(stop, name="stop_limit_usd")
    if not start_limit <= stop_limit <= cost_limit:
        raise ValueError(
            "limits must satisfy 0 < start_limit_usd <= stop_limit_usd <= cost_limit_usd"
        )
    return cost_limit, start_limit, stop_limit


def nearest_rank_p95(values: Sequence[int]) -> int:
    """Nearest-rank 95th percentile: the ceil(0.95 n)-th smallest value."""
    if not values:
        raise ValueError("the p95 of an empty sample is undefined")
    ordered = sorted(values)
    return ordered[(95 * len(ordered) + 99) // 100 - 1]


def _normalize_call(call: object) -> dict[str, Any]:
    if not isinstance(call, Mapping) or set(call) != {"call_id", "input_tokens"}:
        raise ValueError("each call must be an object with exactly call_id and input_tokens")
    call_id = call["call_id"]
    tokens = call["input_tokens"]
    return {
        "call_id": None if call_id is None else _require_id(call_id, name="call_id"),
        "input_tokens": None
        if tokens is None
        else _require_int(
            tokens, name="input_tokens", minimum=0, maximum=MAX_INPUT_TOKENS_PER_CALL
        ),
    }


def _priced_call(call: dict[str, Any]) -> dict[str, Any]:
    """Known tokens go to the estimate column; missing tokens to the reserve column."""
    tokens = call["input_tokens"]
    return {
        **call,
        "estimate_usd": None if tokens is None else _money(_usd(tokens)),
        "reserve_usd": _money(_usd(RESERVE_INPUT_TOKENS)) if tokens is None else None,
    }


def jev_calls_from_call_accounting(rows: Iterable[object]) -> list[dict[str, Any]]:
    """Select Jev calls from ``run_arm``/handoff-result ``call_accounting`` rows.

    A row counts when its ``model`` or ``response_model`` is ``JEV_MODEL``.
    ``llm_attempt_id`` becomes ``call_id``; an input-token count that is not a
    non-negative int becomes ``None`` so the call settles in the reserve column.
    """
    calls = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("call_accounting rows must be objects")
        if JEV_MODEL not in (row.get("model"), row.get("response_model")):
            continue
        usage = row.get("usage")
        tokens = usage.get("input_tokens") if isinstance(usage, Mapping) else None
        attempt = row.get("llm_attempt_id")
        calls.append(
            {
                "call_id": attempt if isinstance(attempt, str) and _ID.fullmatch(attempt) else None,
                "input_tokens": tokens
                if isinstance(tokens, int)
                and not isinstance(tokens, bool)
                and 0 <= tokens <= MAX_INPUT_TOKENS_PER_CALL
                else None,
            }
        )
    return calls


def _header_constants() -> dict[str, Any]:
    typesafe = PRICE_REFERENCE["typesafe"]
    return {
        "schema_id": SCHEMA_ID,
        "model": JEV_MODEL,
        "program_cap_usd": _money(PROGRAM_CAP_USD),
        "input_usd_per_million": str(JEV_INPUT_USD_PER_MILLION),
        "output_usd_per_million": "0",
        "reserve_input_tokens": RESERVE_INPUT_TOKENS,
        "reserve_usd_per_call": _money(_usd(RESERVE_INPUT_TOKENS)),
        "usd_quantum": format(USD_QUANTUM, "f"),
        "price_reference_checked_at": typesafe["checked_at"],
        "price_source": typesafe["source"],
        "cost_authority": COST_AUTHORITY,
    }


@dataclass
class _Unit:
    admitted: bool = False
    planned_jev_calls: int | None = None
    p95_input_tokens: int | None = None
    projection_usd: Decimal | None = None
    refusals: int = 0
    reservations: int = 0
    reserved_calls: int = 0
    settled_calls: int = 0
    missing_token_calls: int = 0
    input_tokens_observed: int = 0
    estimate_usd: Decimal = _ZERO
    settled_reserve_usd: Decimal = _ZERO


@dataclass(frozen=True)
class _Reservation:
    unit_id: str
    max_calls: int
    reserved_usd: Decimal


@dataclass
class _State:
    """Derived ledger state; every record passes through :meth:`apply`."""

    cost_limit: Decimal
    start_limit: Decimal
    stop_limit: Decimal
    line_hashes: list[str] = field(default_factory=list)
    estimate_usd: Decimal = _ZERO
    settled_reserve_usd: Decimal = _ZERO
    open_reservations: dict[str, _Reservation] = field(default_factory=dict)
    closed_reservations: set[str] = field(default_factory=set)
    # (reservation_id, reason) of the stop record that must immediately follow.
    pending_stop: tuple[str, str] | None = None
    call_ids: set[str] = field(default_factory=set)
    known_input_tokens: list[int] = field(default_factory=list)
    units: dict[str, _Unit] = field(default_factory=dict)
    stop_reasons: list[str] = field(default_factory=list)

    @property
    def records(self) -> int:
        return len(self.line_hashes)

    @property
    def head_sha256(self) -> str:
        return self.line_hashes[-1]

    @property
    def open_reserved_usd(self) -> Decimal:
        return _add(item.reserved_usd for item in self.open_reservations.values())

    @property
    def reserve_usd(self) -> Decimal:
        return _CTX.add(self.settled_reserve_usd, self.open_reserved_usd)

    @property
    def committed_usd(self) -> Decimal:
        return _CTX.add(self.estimate_usd, self.reserve_usd)

    @property
    def stopped(self) -> bool:
        return bool(self.stop_reasons)

    def default_p95(self) -> tuple[int, str]:
        if self.known_input_tokens:
            return nearest_rank_p95(self.known_input_tokens), "earlier_units"
        return RESERVE_INPUT_TOKENS, "reserve_default"

    def admission_refusal(self, projection: Decimal) -> str | None:
        committed = self.committed_usd
        if self.stopped:
            return "ledger_stopped"
        if committed >= self.start_limit:
            return "committed_at_or_above_start_limit"
        if _CTX.add(committed, projection) > self.start_limit:
            return "projection_exceeds_start_limit"
        return None

    def reservation_refusal(self, unit_id: str, reserved: Decimal) -> str | None:
        committed = self.committed_usd
        unit = self.units.get(unit_id)
        if self.stopped:
            return "ledger_stopped"
        if unit is None or not unit.admitted:
            return "unit_not_admitted"
        if committed >= self.stop_limit:
            return "committed_at_or_above_stop_limit"
        if _CTX.add(committed, reserved) > self.cost_limit:
            return "reservation_exceeds_cost_limit"
        return None

    def apply(self, record: dict[str, Any]) -> None:
        """Replay one non-header record, recomputing every amount and decision."""
        try:
            kind = record["kind"]
            expected = _RECORD_FIELDS.get(kind) if isinstance(kind, str) else None
            if expected is None:
                raise ValueError("unknown record kind")
            _check(set(record) == _COMMON_FIELDS | expected, f"bad {kind} fields")
            _check(self.pending_stop is None or kind == "stop", "settlement lacks its stop record")
            if kind in ("unit_admitted", "unit_refused"):
                self._apply_admission(record, admitted=kind == "unit_admitted")
            elif kind == "reservation":
                self._apply_reservation(record)
            elif kind == "settlement":
                self._apply_settlement(record)
            else:
                self._apply_stop(record)
        # A consistently re-hashed forgery can carry any JSON type; never let it escape
        # as anything other than an integrity failure.
        except (ValueError, TypeError) as error:
            raise JevLedgerIntegrityError(f"record {record.get('seq')}: {error}") from error

    def _apply_admission(self, record: dict[str, Any], *, admitted: bool) -> None:
        unit_id = _require_id(record["unit_id"], name="unit_id")
        planned = _require_int(
            record["planned_jev_calls"], name="planned_jev_calls", minimum=0, maximum=MAX_CALLS
        )
        p95 = _require_int(
            record["p95_input_tokens"],
            name="p95_input_tokens",
            minimum=0,
            maximum=MAX_INPUT_TOKENS_PER_CALL,
        )
        source = record["p95_source"]
        _check(isinstance(source, str) and source in _P95_SOURCES, "unknown p95_source")
        _check(
            _require_int(
                record["p95_sample_calls"], name="p95_sample_calls", minimum=0, maximum=2**63
            )
            == len(self.known_input_tokens),
            "p95 sample size does not replay",
        )
        _check(source == "explicit" or (p95, source) == self.default_p95(), "p95 does not replay")
        projection = _usd(planned * p95)
        _check(
            _parse_money(record["projection_usd"], name="projection_usd") == projection,
            "bad projection",
        )
        _check(
            _parse_money(record["committed_before_usd"], name="committed_before_usd")
            == self.committed_usd,
            "committed_before_usd does not replay",
        )
        unit = self.units.setdefault(unit_id, _Unit())
        _check(not unit.admitted, "unit is already admitted")
        refusal = self.admission_refusal(projection)
        if admitted:
            _check(
                refusal is None and record["reason"] == "within_start_limit", "admission over limit"
            )
            unit.admitted = True
            unit.planned_jev_calls = planned
            unit.p95_input_tokens = p95
            unit.projection_usd = projection
        else:
            _check(refusal is not None and record["reason"] == refusal, "refusal does not replay")
            unit.refusals += 1

    def _apply_reservation(self, record: dict[str, Any]) -> None:
        reservation_id = _require_id(record["reservation_id"], name="reservation_id")
        _check(
            reservation_id not in self.open_reservations
            and reservation_id not in self.closed_reservations,
            "reservation id reused",
        )
        unit_id = _require_id(record["unit_id"], name="unit_id")
        max_calls = _require_int(
            record["max_calls"], name="max_calls", minimum=1, maximum=MAX_CALLS
        )
        per_call = _require_int(
            record["input_tokens_per_call"],
            name="input_tokens_per_call",
            minimum=1,
            maximum=MAX_INPUT_TOKENS_PER_CALL,
        )
        reserved = _usd(max_calls * per_call)
        _check(_parse_money(record["reserved_usd"], name="reserved_usd") == reserved, "bad reserve")
        _check(
            _parse_money(record["committed_before_usd"], name="committed_before_usd")
            == self.committed_usd,
            "committed_before_usd does not replay",
        )
        _check(self.reservation_refusal(unit_id, reserved) is None, "reservation over limit")
        self.open_reservations[reservation_id] = _Reservation(unit_id, max_calls, reserved)
        unit = self.units[unit_id]
        unit.reservations += 1
        unit.reserved_calls += max_calls

    def _apply_settlement(self, record: dict[str, Any]) -> None:
        reservation_id = _require_id(record["reservation_id"], name="reservation_id")
        reservation = self.open_reservations.get(reservation_id)
        if reservation is None:
            raise ValueError("settlement without an open reservation")
        _check(record["unit_id"] == reservation.unit_id, "settlement unit does not replay")
        _check(
            type(record["max_calls"]) is int and record["max_calls"] == reservation.max_calls,
            "settlement max_calls does not replay",
        )
        _check(
            _parse_money(record["released_usd"], name="released_usd") == reservation.reserved_usd,
            "released_usd does not replay",
        )
        calls = record["calls"]
        _check(isinstance(calls, list) and len(calls) <= MAX_CALLS, "calls must be a list")
        priced = []
        for call in calls:
            _check(isinstance(call, dict) and set(call) == _CALL_FIELDS, "bad call fields")
            expected = _priced_call(
                _normalize_call({"call_id": call["call_id"], "input_tokens": call["input_tokens"]})
            )
            _check(call == expected, "call amounts do not replay")
            priced.append(expected)
        call_ids = [call["call_id"] for call in priced if call["call_id"] is not None]
        _check(
            len(set(call_ids)) == len(call_ids) and not self.call_ids.intersection(call_ids),
            "call id settled twice",
        )
        estimate = _add(Decimal(call["estimate_usd"]) for call in priced if call["estimate_usd"])
        reserve = _add(Decimal(call["reserve_usd"]) for call in priced if call["reserve_usd"])
        _check(
            _parse_money(record["estimate_usd"], name="estimate_usd") == estimate, "bad estimate"
        )
        _check(_parse_money(record["reserve_usd"], name="reserve_usd") == reserve, "bad reserve")
        overrun = max(0, len(priced) - reservation.max_calls)
        _check(
            type(record["overrun_calls"]) is int and record["overrun_calls"] == overrun,
            "overrun_calls does not replay",
        )
        was_stopped = self.stopped
        del self.open_reservations[reservation_id]
        self.closed_reservations.add(reservation_id)
        self.call_ids.update(call_ids)
        known = [call["input_tokens"] for call in priced if call["input_tokens"] is not None]
        self.known_input_tokens.extend(known)
        self.estimate_usd = _CTX.add(self.estimate_usd, estimate)
        self.settled_reserve_usd = _CTX.add(self.settled_reserve_usd, reserve)
        unit = self.units[reservation.unit_id]
        unit.settled_calls += len(priced)
        unit.missing_token_calls += len(priced) - len(known)
        unit.input_tokens_observed += sum(known)
        unit.estimate_usd = _CTX.add(unit.estimate_usd, estimate)
        unit.settled_reserve_usd = _CTX.add(unit.settled_reserve_usd, reserve)
        committed = self.committed_usd
        _check(
            _parse_money(record["committed_after_usd"], name="committed_after_usd") == committed,
            "committed_after_usd does not replay",
        )
        # The writer appends the stop in the same write; its absence is tampering.
        if overrun:
            self.pending_stop = (reservation_id, "reservation_overrun")
        elif not was_stopped and committed >= self.stop_limit:
            self.pending_stop = (reservation_id, "stop_limit_reached")

    def _apply_stop(self, record: dict[str, Any]) -> None:
        reason = record["reason"]
        _check(isinstance(reason, str) and reason in _STOP_REASONS, "unknown stop reason")
        reservation_id = _require_id(record["reservation_id"], name="reservation_id")
        _check(self.pending_stop == (reservation_id, reason), "stop does not replay")
        _check(
            _parse_money(record["committed_usd"], name="committed_usd") == self.committed_usd,
            "committed_usd does not replay",
        )
        self.pending_stop = None
        self.stop_reasons.append(reason)


def _state_from_header(record: dict[str, Any]) -> _State:
    constants = _header_constants()
    if record.get("kind") != "header" or set(record) != (
        _COMMON_FIELDS | set(constants) | set(_LIMIT_FIELDS)
    ):
        raise JevLedgerIntegrityError("header fields do not match this ledger schema")
    mismatched = sorted(
        key
        for key, value in constants.items()
        if type(record[key]) is not type(value) or record[key] != value
    )
    if mismatched:
        raise JevLedgerIntegrityError(f"header mismatch: {', '.join(mismatched)}")
    try:
        limits = _validated_limits(*(record[key] for key in _LIMIT_FIELDS))
    except ValueError as error:
        raise JevLedgerIntegrityError(f"header limits refused: {error}") from error
    if [record[key] for key in _LIMIT_FIELDS] != [_money(limit) for limit in limits]:
        raise JevLedgerIntegrityError("header limits are not canonical")
    return _State(*limits)


def _encode(record: Mapping[str, Any]) -> bytes:
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(text: str) -> Any:
    def reject_constant(name: str) -> NoReturn:
        raise ValueError(f"non-finite JSON constant {name}")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate JSON key")
        return dict(pairs)

    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique)


def _decode(raw: bytes, seq: int, prev: str | None) -> dict[str, Any]:
    try:
        record = _strict_json(raw.decode("ascii"))
    except ValueError as error:
        raise JevLedgerIntegrityError(f"line {seq + 1} is not a JSON record") from error
    if not isinstance(record, dict) or _encode(record) != raw:
        raise JevLedgerIntegrityError(f"line {seq + 1} is not a canonical ledger record")
    if type(record.get("seq")) is not int or record["seq"] != seq:
        raise JevLedgerIntegrityError(f"line {seq + 1} breaks the record sequence")
    if record.get("prev_sha256") != prev:
        raise JevLedgerIntegrityError(f"line {seq + 1} breaks the hash chain")
    ts = record.get("ts")
    if not isinstance(ts, str) or not _TS.fullmatch(ts):
        raise JevLedgerIntegrityError(f"line {seq + 1} has no UTC timestamp")
    return record


def _verify(data: bytes) -> _State:
    if not data:
        raise JevLedgerIntegrityError("ledger is empty")
    if not data.endswith(b"\n"):
        raise JevLedgerIntegrityError("ledger ends with a truncated line")
    header, *rest = data[:-1].split(b"\n")
    state = _state_from_header(_decode(header, 0, None))
    state.line_hashes.append(_sha256(header))
    for seq, raw in enumerate(rest, start=1):
        state.apply(_decode(raw, seq, state.head_sha256))
        state.line_hashes.append(_sha256(raw))
    if state.pending_stop is not None:
        raise JevLedgerIntegrityError("ledger ends before a required stop record")
    return state


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _push(state: _State, body: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Frame a record and pass it through the reader's replay before any write."""
    record = {**body, "seq": state.records, "ts": _utc_now(), "prev_sha256": state.head_sha256}
    raw = _encode(record)
    state.apply(record)
    state.line_hashes.append(_sha256(raw))
    return record, raw


def _check_file(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise JevLedgerIntegrityError(
            "ledger files must be regular, owned by this user and not group/world-writable"
        )


def _read_all(fd: int) -> bytes:
    chunks = []
    offset = 0
    while chunk := os.pread(fd, 1 << 20, offset):
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]
    os.fsync(fd)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _locked(path: Path, *, exclusive: bool) -> Iterator[int]:
    flags = (os.O_RDWR | os.O_APPEND) if exclusive else os.O_RDONLY
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _check_file(fd)
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield fd
    finally:
        os.close(fd)


def _anchor_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.head")


def _write_anchor(path: Path, records: int, head_sha256: str) -> None:
    anchor = _anchor_path(path)
    temporary = anchor.with_name(f".{anchor.name}.{uuid.uuid4().hex}.tmp")
    body = {"schema_id": ANCHOR_SCHEMA_ID, "records": records, "head_sha256": head_sha256}
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        try:
            _write_all(fd, _encode(body) + b"\n")
        finally:
            os.close(fd)
        os.replace(temporary, anchor)
    except BaseException:
        with suppress(FileNotFoundError):
            temporary.unlink()
        raise
    _fsync_dir(path.parent)


def _check_anchor(path: Path, state: _State) -> None:
    try:
        fd = os.open(_anchor_path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise JevLedgerIntegrityError("ledger head anchor is missing") from None
    try:
        _check_file(fd)
        data = _read_all(fd)
    finally:
        os.close(fd)
    try:
        anchor = _strict_json(data.decode("ascii"))
    except ValueError as error:
        raise JevLedgerIntegrityError("ledger head anchor is not JSON") from error
    if (
        not isinstance(anchor, dict)
        or set(anchor) != {"schema_id", "records", "head_sha256"}
        or anchor["schema_id"] != ANCHOR_SCHEMA_ID
        or type(anchor["records"]) is not int
        or not isinstance(anchor["head_sha256"], str)
        or not _SHA256.fullmatch(anchor["head_sha256"])
    ):
        raise JevLedgerIntegrityError("ledger head anchor is malformed")
    records = anchor["records"]
    if not 1 <= records <= state.records or state.line_hashes[records - 1] != anchor["head_sha256"]:
        raise JevLedgerIntegrityError("ledger is shorter than, or differs from, its head anchor")


def _status(state: _State) -> dict[str, Any]:
    committed = state.committed_usd
    pending: dict[str, list[_Reservation]] = {}
    for reservation in state.open_reservations.values():
        pending.setdefault(reservation.unit_id, []).append(reservation)
    units = {}
    for unit_id, unit in sorted(state.units.items()):
        held = pending.get(unit_id, [])
        reserve = _CTX.add(unit.settled_reserve_usd, _add(item.reserved_usd for item in held))
        units[unit_id] = {
            "admitted": unit.admitted,
            "planned_jev_calls": unit.planned_jev_calls,
            "p95_input_tokens": unit.p95_input_tokens,
            "projection_usd": None if unit.projection_usd is None else _money(unit.projection_usd),
            "refusals": unit.refusals,
            "reservations": unit.reservations,
            "open_reservations": len(held),
            "reserved_calls": unit.reserved_calls,
            "settled_calls": unit.settled_calls,
            "missing_token_calls": unit.missing_token_calls,
            "input_tokens_observed_sum": unit.input_tokens_observed,
            "estimate_usd": _money(unit.estimate_usd),
            "reserve_usd": _money(reserve),
            "committed_usd": _money(_CTX.add(unit.estimate_usd, reserve)),
        }

    def remaining(limit: Decimal) -> str:
        return _money(max(_ZERO, _CTX.subtract(limit, committed)))

    settled = sum(unit.settled_calls for unit in state.units.values())
    return {
        "schema_id": SCHEMA_ID,
        "model": JEV_MODEL,
        "cost_authority": COST_AUTHORITY,
        "price_reference_checked_at": PRICE_REFERENCE["typesafe"]["checked_at"],
        "cost_limit_usd": _money(state.cost_limit),
        "start_limit_usd": _money(state.start_limit),
        "stop_limit_usd": _money(state.stop_limit),
        "committed_usd": _money(committed),
        "estimate_usd_total": _money(state.estimate_usd),
        "reserve_usd_total": _money(state.reserve_usd),
        "settled_reserve_usd": _money(state.settled_reserve_usd),
        "open_reserved_usd": _money(state.open_reserved_usd),
        "remaining_to_start_usd": remaining(state.start_limit),
        "remaining_to_stop_usd": remaining(state.stop_limit),
        "remaining_to_cap_usd": remaining(state.cost_limit),
        "stopped": state.stopped,
        "stop_reasons": list(state.stop_reasons),
        "open_reservations": len(state.open_reservations),
        "settled_calls": settled,
        "known_token_calls": len(state.known_input_tokens),
        "missing_token_calls": settled - len(state.known_input_tokens),
        "input_tokens_observed_sum": sum(state.known_input_tokens),
        "records": state.records,
        "head_sha256": state.head_sha256,
        "units": units,
    }


@dataclass
class _Outcome:
    records: list[dict[str, Any]]
    error: tuple[type[JevBudgetError], str, str] | None = None
    written: list[dict[str, Any]] = field(default_factory=list)


class JevCallHandle:
    """One reserved Jev call; set ``input_tokens`` (and ``call_id``) once observed."""

    def __init__(self, reservation_id: str) -> None:
        self.reservation_id = reservation_id
        self._input_tokens: int | None = None
        self._call_id: str | None = None

    @property
    def input_tokens(self) -> int | None:
        return self._input_tokens

    @input_tokens.setter
    def input_tokens(self, value: int | None) -> None:
        self._input_tokens = (
            None
            if value is None
            else _require_int(
                value, name="input_tokens", minimum=0, maximum=MAX_INPUT_TOKENS_PER_CALL
            )
        )

    @property
    def call_id(self) -> str | None:
        return self._call_id

    @call_id.setter
    def call_id(self, value: str | None) -> None:
        self._call_id = None if value is None else _require_id(value, name="call_id")

    def as_call(self) -> dict[str, Any]:
        return {"call_id": self._call_id, "input_tokens": self._input_tokens}


class JevCostLedger:
    """Program-wide Jev spending guard; construct with :meth:`create` or :meth:`open`."""

    def __init__(self, path: Path, seen: tuple[int, str]) -> None:
        self._path = path
        # Records this process already verified; the file must keep them as a prefix.
        self._seen = seen

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        cost_limit_usd: Decimal | int | str = PROGRAM_CAP_USD,
        start_limit_usd: Decimal | int | str = START_LIMIT_USD,
        stop_limit_usd: Decimal | int | str = STOP_LIMIT_USD,
    ) -> JevCostLedger:
        """Create a new ledger exclusively (mode 0600) with its header record."""
        limits = _validated_limits(cost_limit_usd, start_limit_usd, stop_limit_usd)
        header = {
            "kind": "header",
            **_header_constants(),
            **{key: _money(limit) for key, limit in zip(_LIMIT_FIELDS, limits, strict=True)},
            "seq": 0,
            "ts": _utc_now(),
            "prev_sha256": None,
        }
        _state_from_header(header)
        raw = _encode(header)
        ledger_path = Path(path)
        fd = os.open(
            ledger_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.fchmod(fd, 0o600)
                _write_all(fd, raw + b"\n")
                _fsync_dir(ledger_path.parent)
                _write_anchor(ledger_path, 1, _sha256(raw))
            finally:
                os.close(fd)
        except BaseException:
            with suppress(FileNotFoundError):
                ledger_path.unlink()
            raise
        return cls(ledger_path, (1, _sha256(raw)))

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> JevCostLedger:
        """Open an existing ledger after verifying every record and its head anchor."""
        ledger_path = Path(path)
        with _locked(ledger_path, exclusive=False) as fd:
            state = _verify(_read_all(fd))
            _check_anchor(ledger_path, state)
        return cls(ledger_path, (state.records, state.head_sha256))

    def _verified(self, fd: int) -> _State:
        state = _verify(_read_all(fd))
        _check_anchor(self._path, state)
        records, head = self._seen
        if state.records < records or state.line_hashes[records - 1] != head:
            raise JevLedgerIntegrityError("ledger lost records this process already verified")
        self._seen = (state.records, state.head_sha256)
        return state

    def _transact(self, decide: Callable[[_State], _Outcome]) -> _Outcome:
        with _locked(self._path, exclusive=True) as fd:
            state = self._verified(fd)
            outcome = decide(state)
            if outcome.records:
                frames = [_push(state, body) for body in outcome.records]
                if state.pending_stop is not None:
                    raise JevLedgerIntegrityError("refusing to write a settlement without its stop")
                _write_all(fd, b"".join(raw + b"\n" for _, raw in frames))
                self._seen = (state.records, state.head_sha256)
                _write_anchor(self._path, state.records, state.head_sha256)
                outcome.written = [record for record, _ in frames]
        if outcome.error is not None:
            error_type, reason, message = outcome.error
            raise error_type(
                message,
                reason=reason,
                status=_status(state),
                record=outcome.written[0] if outcome.written else None,
            )
        return outcome

    def status(self) -> dict[str, Any]:
        """JSON-ready totals for run-log lines; money is fixed-point USD strings."""
        with _locked(self._path, exclusive=False) as fd:
            return _status(self._verified(fd))

    def admit_unit(
        self,
        unit_id: str,
        planned_jev_calls: int,
        *,
        p95_input_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Record a unit admission, or record a refusal and raise ``JevBudgetRefusedError``.

        Without ``p95_input_tokens`` the projection uses the nearest-rank p95
        of settled known input tokens from earlier units, else
        :data:`RESERVE_INPUT_TOKENS`.
        """
        _require_id(unit_id, name="unit_id")
        _require_int(planned_jev_calls, name="planned_jev_calls", minimum=0, maximum=MAX_CALLS)
        if p95_input_tokens is not None:
            _require_int(
                p95_input_tokens,
                name="p95_input_tokens",
                minimum=0,
                maximum=MAX_INPUT_TOKENS_PER_CALL,
            )

        def decide(state: _State) -> _Outcome:
            unit = state.units.get(unit_id)
            if unit is not None and unit.admitted:
                raise ValueError(f"unit {unit_id} is already admitted")
            p95, source = (
                (p95_input_tokens, "explicit")
                if p95_input_tokens is not None
                else state.default_p95()
            )
            projection = _usd(planned_jev_calls * p95)
            refusal = state.admission_refusal(projection)
            body = {
                "kind": "unit_admitted" if refusal is None else "unit_refused",
                "unit_id": unit_id,
                "planned_jev_calls": planned_jev_calls,
                "p95_input_tokens": p95,
                "p95_source": source,
                "p95_sample_calls": len(state.known_input_tokens),
                "projection_usd": _money(projection),
                "committed_before_usd": _money(state.committed_usd),
                "reason": refusal or "within_start_limit",
            }
            if refusal is None:
                return _Outcome([body])
            return _Outcome(
                [body], (JevBudgetRefusedError, refusal, f"unit {unit_id} refused: {refusal}")
            )

        return dict(self._transact(decide).written[0])

    def reserve(
        self,
        unit_id: str,
        max_calls: int = 1,
        *,
        input_tokens_per_call: int = RESERVE_INPUT_TOKENS,
    ) -> str:
        """Hold ``max_calls x input_tokens_per_call`` for an admitted unit; return its id."""
        _require_id(unit_id, name="unit_id")
        _require_int(max_calls, name="max_calls", minimum=1, maximum=MAX_CALLS)
        _require_int(
            input_tokens_per_call,
            name="input_tokens_per_call",
            minimum=1,
            maximum=MAX_INPUT_TOKENS_PER_CALL,
        )
        reservation_id = uuid.uuid4().hex

        def decide(state: _State) -> _Outcome:
            reserved = _usd(max_calls * input_tokens_per_call)
            refusal = state.reservation_refusal(unit_id, reserved)
            if refusal is not None:
                message = f"reservation for unit {unit_id} refused: {refusal}"
                return _Outcome([], (JevBudgetRefusedError, refusal, message))
            body = {
                "kind": "reservation",
                "reservation_id": reservation_id,
                "unit_id": unit_id,
                "max_calls": max_calls,
                "input_tokens_per_call": input_tokens_per_call,
                "reserved_usd": _money(reserved),
                "committed_before_usd": _money(state.committed_usd),
            }
            return _Outcome([body])

        self._transact(decide)
        return reservation_id

    def settle(self, reservation_id: str, calls: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Replace an open reservation with observed calls; return the settlement.

        Each call is ``{"call_id": str | None, "input_tokens": int | None}``.
        Raises :class:`JevBudgetExhaustedError` after recording the settlement when
        the ledger is, or becomes, stopped.
        """
        _require_id(reservation_id, name="reservation_id")
        rows = [_priced_call(_normalize_call(call)) for call in calls]
        call_ids = [row["call_id"] for row in rows if row["call_id"] is not None]
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("call ids must be unique within a settlement")

        def decide(state: _State) -> _Outcome:
            reservation = state.open_reservations.get(reservation_id)
            if reservation is None:
                raise ValueError(f"reservation {reservation_id} is not open")
            if state.call_ids.intersection(call_ids):
                raise ValueError("a call id was already settled")
            estimate = _add(Decimal(row["estimate_usd"]) for row in rows if row["estimate_usd"])
            reserve = _add(Decimal(row["reserve_usd"]) for row in rows if row["reserve_usd"])
            committed = _CTX.add(
                _CTX.subtract(state.committed_usd, reservation.reserved_usd),
                _CTX.add(estimate, reserve),
            )
            overrun = max(0, len(rows) - reservation.max_calls)
            records: list[dict[str, Any]] = [
                {
                    "kind": "settlement",
                    "reservation_id": reservation_id,
                    "unit_id": reservation.unit_id,
                    "max_calls": reservation.max_calls,
                    "released_usd": _money(reservation.reserved_usd),
                    "calls": rows,
                    "estimate_usd": _money(estimate),
                    "reserve_usd": _money(reserve),
                    "overrun_calls": overrun,
                    "committed_after_usd": _money(committed),
                }
            ]
            if overrun:
                reason = "reservation_overrun"
            elif not state.stopped and committed >= state.stop_limit:
                reason = "stop_limit_reached"
            elif state.stopped:
                message = "settlement recorded; the ledger is already stopped"
                return _Outcome(records, (JevBudgetExhaustedError, "ledger_stopped", message))
            else:
                return _Outcome(records)
            stop = {
                "kind": "stop",
                "reason": reason,
                "reservation_id": reservation_id,
                "committed_usd": _money(committed),
            }
            message = f"settlement recorded; ledger stopped: {reason}"
            return _Outcome([*records, stop], (JevBudgetExhaustedError, reason, message))

        return dict(self._transact(decide).written[0])

    @contextmanager
    def call(
        self, unit_id: str, *, input_tokens_per_call: int = RESERVE_INPUT_TOKENS
    ) -> Iterator[JevCallHandle]:
        """Reserve one call, yield its handle and settle on exit, even on error.

        A handle left without ``input_tokens`` (for example a failed call with
        no usage) settles in the reserve column.
        """
        handle = JevCallHandle(
            self.reserve(unit_id, 1, input_tokens_per_call=input_tokens_per_call)
        )
        try:
            yield handle
        finally:
            self.settle(handle.reservation_id, [handle.as_call()])


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m evals.benchmarks.jev_cost_ledger",
        description="Host-scoped Jev cost ledger (published-tariff estimates, not invoices).",
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    init = commands.add_parser("init", help="create a ledger exclusively")
    init.add_argument("ledger", type=Path)
    init.add_argument("--cost-limit-usd", default=str(PROGRAM_CAP_USD))
    init.add_argument("--start-limit-usd", default=str(START_LIMIT_USD))
    init.add_argument("--stop-limit-usd", default=str(STOP_LIMIT_USD))
    status = commands.add_parser("status", help="verify the ledger and print its totals")
    status.add_argument("ledger", type=Path)
    admit = commands.add_parser("admit", help="admit a unit or record its refusal")
    admit.add_argument("ledger", type=Path)
    admit.add_argument("--unit-id", required=True)
    admit.add_argument("--planned-jev-calls", type=int, required=True)
    admit.add_argument("--p95-input-tokens", type=int)
    reserve = commands.add_parser("reserve", help="reserve Jev calls for an admitted unit")
    reserve.add_argument("ledger", type=Path)
    reserve.add_argument("--unit-id", required=True)
    reserve.add_argument("--max-calls", type=int, default=1)
    reserve.add_argument("--input-tokens-per-call", type=int, default=RESERVE_INPUT_TOKENS)
    settle = commands.add_parser("settle", help="settle a reservation with observed calls")
    settle.add_argument("ledger", type=Path)
    settle.add_argument("--reservation-id", required=True)
    source = settle.add_mutually_exclusive_group()
    source.add_argument("--calls-json", type=Path, help="JSON array of {call_id, input_tokens}")
    source.add_argument(
        "--call-accounting",
        type=Path,
        help=(
            "handoff result object (call_accounting plus usage completeness) or a bare "
            "call_accounting array, which is taken as complete"
        ),
    )
    settle.add_argument(
        "--unknown-calls",
        type=int,
        default=0,
        help="add this many Jev calls without observed input tokens (reserve column)",
    )
    return parser


def _load_json(path: Path) -> Any:
    return _strict_json(path.read_text(encoding="utf-8"))


def _accounting_calls(document: object, *, unknown_calls: int) -> list[dict[str, Any]]:
    if isinstance(document, list):
        return jev_calls_from_call_accounting(document)
    if not isinstance(document, dict) or not isinstance(document.get("call_accounting"), list):
        raise ValueError("--call-accounting needs a call_accounting array or an object holding one")
    usage = document.get("usage")
    complete = (
        isinstance(usage, dict)
        and usage.get("attempt_pairing_complete") is True
        and usage.get("observation_status") == "no_known_faults"
    )
    if not complete and unknown_calls == 0:
        raise ValueError(
            "call accounting is incomplete; settle unobserved Jev calls with --unknown-calls"
        )
    return jev_calls_from_call_accounting(document["call_accounting"])


def _cli_calls(args: argparse.Namespace) -> list[dict[str, Any]]:
    unknown = _require_int(args.unknown_calls, name="--unknown-calls", minimum=0, maximum=MAX_CALLS)
    calls: list[dict[str, Any]] = []
    if args.calls_json is not None:
        document = _load_json(args.calls_json)
        if not isinstance(document, list):
            raise ValueError("--calls-json must hold a JSON array of {call_id, input_tokens}")
        calls.extend(document)
    elif args.call_accounting is not None:
        calls.extend(_accounting_calls(_load_json(args.call_accounting), unknown_calls=unknown))
    elif unknown == 0:
        raise ValueError("settle needs --calls-json, --call-accounting or --unknown-calls")
    calls.extend({"call_id": None, "input_tokens": None} for _ in range(unknown))
    return calls


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "init":
        ledger = JevCostLedger.create(
            args.ledger,
            cost_limit_usd=args.cost_limit_usd,
            start_limit_usd=args.start_limit_usd,
            stop_limit_usd=args.stop_limit_usd,
        )
        return {"status": ledger.status()}
    ledger = JevCostLedger.open(args.ledger)
    result: dict[str, Any] = {}
    if args.command == "admit":
        result["record"] = ledger.admit_unit(
            args.unit_id, args.planned_jev_calls, p95_input_tokens=args.p95_input_tokens
        )
    elif args.command == "reserve":
        result["reservation_id"] = ledger.reserve(
            args.unit_id, args.max_calls, input_tokens_per_call=args.input_tokens_per_call
        )
    elif args.command == "settle":
        result["record"] = ledger.settle(args.reservation_id, _cli_calls(args))
    return {**result, "status": ledger.status()}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ledger CLI; see the module docstring for commands and exit codes."""
    command: str | None = None
    payload: dict[str, Any]
    try:
        args = _parser().parse_args(argv)
        command = args.command
        payload = _run(args)
        code = EXIT_OK
    except _UsageError as error:
        payload, code = {"error": "invalid", "message": str(error)}, EXIT_INVALID
    except JevBudgetError as error:
        stopped = isinstance(error, JevBudgetExhaustedError) or error.stopped
        payload = {
            "error": "stopped" if stopped else "refused",
            "reason": error.reason,
            "message": str(error),
            "record": error.record,
            "status": error.status,
        }
        code = EXIT_STOPPED if stopped else EXIT_REFUSED
    except JevLedgerIntegrityError as error:
        payload, code = {"error": "integrity", "message": str(error)}, EXIT_INTEGRITY
    except OSError as error:
        # strerror omits the host path that str(error) would include.
        message = f"{type(error).__name__}: {error.strerror or 'file-system error'}"
        payload, code = {"error": "integrity", "message": message}, EXIT_INTEGRITY
    except ValueError as error:
        payload, code = {"error": "invalid", "message": str(error)}, EXIT_INVALID
    sys.stdout.write(
        json.dumps({"ok": code == EXIT_OK, "command": command, **payload}, sort_keys=True) + "\n"
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
