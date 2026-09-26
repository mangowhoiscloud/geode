"""Host-scoped Jev cost ledger: cap guard, admission, reservations, integrity and CLI."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from evals.benchmarks.decision_handoff_runtime import JEV_MODEL, MODEL, PRICE_REFERENCE, _accounting
from evals.benchmarks.jev_cost_ledger import (
    EXIT_INTEGRITY,
    EXIT_INVALID,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_STOPPED,
    RESERVE_INPUT_TOKENS,
    JevBudgetExhausted,
    JevBudgetExhaustedError,
    JevBudgetRefused,
    JevBudgetRefusedError,
    JevCostLedger,
    JevLedgerIntegrityError,
    jev_calls_from_call_accounting,
    main,
    nearest_rank_p95,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RATE = Decimal("0.042") / Decimal(1_000_000)
RESERVE_USD = Decimal("0.00105")
MONEY = re.compile(r"\d+\.\d{9}")


def usd(tokens: int) -> Decimal:
    return tokens * RATE


# Limits that are exact multiples of the per-token rate make the boundaries reachable:
# cap = 1000 tokens, start = 900 tokens, stop = 950 tokens.
SMALL = {"cost_limit_usd": usd(1000), "start_limit_usd": usd(900), "stop_limit_usd": usd(950)}
SMALL_CLI = [
    *("--cost-limit-usd", "0.000042"),
    *("--start-limit-usd", "0.0000378"),
    *("--stop-limit-usd", "0.0000399"),
]


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "jev-cost-ledger.jsonl"


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _committed(ledger: JevCostLedger) -> Decimal:
    return Decimal(ledger.status()["committed_usd"])


def _spend(ledger: JevCostLedger, unit_id: str, tokens: int) -> dict[str, Any]:
    reservation = ledger.reserve(unit_id, 1, input_tokens_per_call=max(tokens, 1))
    return ledger.settle(reservation, [{"call_id": None, "input_tokens": tokens}])


def _rewrite(path: Path, records: list[dict[str, Any]]) -> None:
    """Re-chain records in the documented format: a consistent forgery, not a torn write."""
    lines: list[bytes] = []
    prev = None
    for seq, record in enumerate(records):
        raw = json.dumps(
            {**record, "seq": seq, "prev_sha256": prev},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        lines.append(raw)
        prev = hashlib.sha256(raw).hexdigest()
    path.write_bytes(b"".join(line + b"\n" for line in lines))
    anchor = {
        "head_sha256": prev,
        "records": len(lines),
        "schema_id": "geode.jev-cost-ledger-head@1",
    }
    Path(f"{path}.head").write_text(json.dumps(anchor, separators=(",", ":")) + "\n")


def _sample(path: Path) -> JevCostLedger:
    ledger = JevCostLedger.create(path)
    ledger.admit_unit("U0a", 16)
    reservation = ledger.reserve("U0a", 2)
    ledger.settle(
        reservation,
        [
            {"call_id": "c1:attempt-1", "input_tokens": 1000},
            {"call_id": None, "input_tokens": None},
        ],
    )
    ledger.reserve("U0a", 1)
    return ledger


def _cli(capsys: pytest.CaptureFixture[str], *argv: object) -> tuple[int, dict[str, Any]]:
    code = main([str(arg) for arg in argv])
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    "limit",
    [
        0,
        Decimal(0),
        "0",
        "0.00",
        -1,
        Decimal("-0.01"),
        "-0.5",
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        "inf",
        "nan",
        float("nan"),
        float("inf"),
        0.5,
        None,
        True,
        False,
        "",
        "abc",
        "1.01",
        2,
        Decimal("1.000000001"),
        "0.0000000001",
    ],
)
def test_cost_limit_guard_never_reads_zero_or_garbage_as_unlimited(path: Path, limit: Any) -> None:
    with pytest.raises(ValueError):
        JevCostLedger.create(
            path, cost_limit_usd=limit, start_limit_usd="0.1", stop_limit_usd="0.1"
        )
    assert not path.exists()
    assert not Path(f"{path}.head").exists()


@pytest.mark.parametrize(
    ("cost", "start", "stop", "accepted"),
    [
        ("1.00", "0.90", "0.95", True),
        (1, "0.90", "0.95", True),
        ("0.50", "0.50", "0.50", True),
        ("1.00", "0.95", "0.90", False),
        ("0.94", "0.90", "0.95", False),
        ("1.00", "0", "0.95", False),
        ("1.00", "0.90", "0", False),
        ("0.50", "0.90", "0.95", False),
    ],
)
def test_thresholds_must_be_ordered_within_the_cost_limit(
    path: Path, cost: Any, start: str, stop: str, accepted: bool
) -> None:
    if accepted:
        status = JevCostLedger.create(
            path, cost_limit_usd=cost, start_limit_usd=start, stop_limit_usd=stop
        ).status()
        assert Decimal(status["start_limit_usd"]) <= Decimal(status["stop_limit_usd"])
        assert Decimal(status["stop_limit_usd"]) <= Decimal(status["cost_limit_usd"])
    else:
        with pytest.raises(ValueError, match="limit"):
            JevCostLedger.create(
                path, cost_limit_usd=cost, start_limit_usd=start, stop_limit_usd=stop
            )
        assert not path.exists()


def test_create_is_exclusive_owner_only_and_writes_the_header(path: Path) -> None:
    JevCostLedger.create(path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        JevCostLedger.create(path)
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600
    assert Path(f"{path}.head").stat().st_mode & 0o777 == 0o600
    (header,) = _records(path)
    assert header == {
        "kind": "header",
        "seq": 0,
        "prev_sha256": None,
        "ts": header["ts"],
        "schema_id": "geode.jev-cost-ledger@1",
        "model": JEV_MODEL,
        "cost_limit_usd": "1.000000000",
        "start_limit_usd": "0.900000000",
        "stop_limit_usd": "0.950000000",
        "program_cap_usd": "1.000000000",
        "input_usd_per_million": "0.042",
        "output_usd_per_million": "0",
        "reserve_input_tokens": RESERVE_INPUT_TOKENS,
        "reserve_usd_per_call": "0.001050000",
        "usd_quantum": "0.000000001",
        "price_reference_checked_at": PRICE_REFERENCE["typesafe"]["checked_at"],
        "price_source": PRICE_REFERENCE["typesafe"]["source"],
        "cost_authority": "published-input-token-tariff-estimate-not-invoice",
    }
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", header["ts"])
    status = JevCostLedger.open(path).status()
    assert status["committed_usd"] == "0.000000000"
    assert status["stopped"] is False
    assert status["records"] == 1


def test_spec_names_alias_the_error_classes() -> None:
    assert JevBudgetRefused is JevBudgetRefusedError
    assert JevBudgetExhausted is JevBudgetExhaustedError


def test_admission_boundary_is_inclusive_and_stops_new_units_at_the_start_limit(
    path: Path,
) -> None:
    ledger = JevCostLedger.create(path, **SMALL)
    ledger.admit_unit("warmup", 1, p95_input_tokens=899)
    _spend(ledger, "warmup", 899)

    with pytest.raises(JevBudgetRefused) as refused:
        ledger.admit_unit("over", 1, p95_input_tokens=2)
    assert refused.value.reason == "projection_exceeds_start_limit"
    assert refused.value.stopped is False
    assert refused.value.record is not None
    assert refused.value.record["kind"] == "unit_refused"
    assert refused.value.record["committed_before_usd"] == "0.000037758"  # 899 tokens

    admitted = ledger.admit_unit("fits", 1, p95_input_tokens=1)
    assert admitted["kind"] == "unit_admitted"
    assert admitted["projection_usd"] == "0.000000042"
    _spend(ledger, "fits", 1)
    assert _committed(ledger) == usd(900) == SMALL["start_limit_usd"]

    with pytest.raises(JevBudgetRefused) as late:
        ledger.admit_unit("late", 0)
    assert late.value.reason == "committed_at_or_above_start_limit"
    units = ledger.status()["units"]
    assert units["over"]["admitted"] is False
    assert units["over"]["refusals"] == 1
    assert units["late"]["refusals"] == 1
    assert [row["kind"] for row in _records(path)].count("unit_refused") == 2


def test_default_limits_project_reserve_tokens_until_usage_is_observed(path: Path) -> None:
    ledger = JevCostLedger.create(path)
    admitted = ledger.admit_unit("U-a", 857)
    assert admitted["p95_source"] == "reserve_default"
    assert admitted["p95_input_tokens"] == RESERVE_INPUT_TOKENS
    assert Decimal(admitted["projection_usd"]) == 857 * RESERVE_USD == Decimal("0.89985")
    with pytest.raises(JevBudgetRefused, match="projection_exceeds_start_limit"):
        ledger.admit_unit("U-b", 858)
    assert _committed(ledger) == 0


def test_nearest_rank_p95() -> None:
    assert nearest_rank_p95([5]) == 5
    assert nearest_rank_p95([3, 1, 2]) == 3
    assert nearest_rank_p95(list(range(1, 21))) == 19
    assert nearest_rank_p95(list(range(100, 0, -1))) == 95
    with pytest.raises(ValueError):
        nearest_rank_p95([])


def test_admission_projects_with_p95_of_earlier_units(path: Path) -> None:
    ledger = JevCostLedger.create(path)
    ledger.admit_unit("U-a", 21, p95_input_tokens=2000)
    reservation = ledger.reserve("U-a", 21, input_tokens_per_call=2000)
    calls: list[dict[str, Any]] = [
        {"call_id": f"a{index}", "input_tokens": 100 * index} for index in range(1, 21)
    ]
    ledger.settle(reservation, [*calls, {"call_id": None, "input_tokens": None}])

    derived = ledger.admit_unit("U-b", 10)
    assert derived["p95_source"] == "earlier_units"
    assert derived["p95_sample_calls"] == 20
    assert derived["p95_input_tokens"] == 1900
    assert Decimal(derived["projection_usd"]) == usd(10 * 1900)
    explicit = ledger.admit_unit("U-c", 10, p95_input_tokens=5)
    assert (explicit["p95_source"], explicit["p95_input_tokens"]) == ("explicit", 5)


def test_reservations_never_let_committed_exceed_the_cost_limit(path: Path) -> None:
    ledger = JevCostLedger.create(path, **SMALL)
    ledger.admit_unit("u", 1, p95_input_tokens=1)
    with pytest.raises(JevBudgetRefused, match="unit_not_admitted"):
        ledger.reserve("ghost")
    with pytest.raises(JevBudgetRefused, match="reservation_exceeds_cost_limit"):
        ledger.reserve("u", 1, input_tokens_per_call=1001)
    full = ledger.reserve("u", 1, input_tokens_per_call=1000)
    assert _committed(ledger) == SMALL["cost_limit_usd"]
    records = len(_records(path))
    with pytest.raises(JevBudgetRefused, match="committed_at_or_above_stop_limit") as refused:
        ledger.reserve("u", 1, input_tokens_per_call=1)
    assert refused.value.record is None
    assert len(_records(path)) == records
    ledger.settle(full, [{"call_id": None, "input_tokens": 10}])

    for tokens in (300, 300, 300, 300, 90, 1):
        with contextlib.suppress(JevBudgetRefused):
            ledger.reserve("u", 1, input_tokens_per_call=tokens)
        assert _committed(ledger) <= SMALL["cost_limit_usd"]
    assert _committed(ledger) == SMALL["cost_limit_usd"]
    assert ledger.status()["open_reservations"] == 4


def test_settlement_splits_estimate_and_reserve_columns(path: Path) -> None:
    ledger = JevCostLedger.create(path)
    ledger.admit_unit("U0a", 3)
    reservation = ledger.reserve("U0a", 3)
    before = ledger.status()
    assert Decimal(before["open_reserved_usd"]) == 3 * RESERVE_USD
    assert before["reserve_usd_total"] == before["committed_usd"] == "0.003150000"

    record = ledger.settle(
        reservation,
        [{"call_id": "a:attempt-1", "input_tokens": 1000}, {"call_id": None, "input_tokens": None}],
    )
    assert record["calls"] == [
        {
            "call_id": "a:attempt-1",
            "input_tokens": 1000,
            "estimate_usd": "0.000042000",
            "reserve_usd": None,
        },
        {"call_id": None, "input_tokens": None, "estimate_usd": None, "reserve_usd": "0.001050000"},
    ]
    assert record["released_usd"] == "0.003150000"
    status = ledger.status()
    assert status["estimate_usd_total"] == "0.000042000"
    assert status["reserve_usd_total"] == status["settled_reserve_usd"] == "0.001050000"
    assert status["open_reserved_usd"] == "0.000000000"
    assert status["committed_usd"] == "0.001092000"
    assert (status["known_token_calls"], status["missing_token_calls"]) == (1, 1)
    assert status["units"]["U0a"]["missing_token_calls"] == 1
    for key in ("committed_usd", "remaining_to_stop_usd", "remaining_to_cap_usd"):
        assert MONEY.fullmatch(status[key])

    released = ledger.settle(ledger.reserve("U0a", 2), [])
    assert released["calls"] == []
    assert ledger.status()["committed_usd"] == "0.001092000"


def test_stop_limit_records_a_sticky_stop_and_refuses_later_spend(path: Path) -> None:
    ledger = JevCostLedger.create(path, **SMALL)
    ledger.admit_unit("u", 2, p95_input_tokens=1)
    first = ledger.reserve("u", 1, input_tokens_per_call=480)
    in_flight = ledger.reserve("u", 1, input_tokens_per_call=470)

    with pytest.raises(JevBudgetExhausted) as exhausted:
        ledger.settle(first, [{"call_id": "a", "input_tokens": 480}])
    assert exhausted.value.reason == "stop_limit_reached"
    assert exhausted.value.record is not None
    assert exhausted.value.record["kind"] == "settlement"
    assert exhausted.value.status["stopped"] is True
    assert _records(path)[-1]["kind"] == "stop"
    assert _committed(ledger) == usd(950)

    with pytest.raises(JevBudgetRefused, match="ledger_stopped") as refused:
        ledger.reserve("u", 1, input_tokens_per_call=1)
    assert refused.value.stopped is True
    with pytest.raises(JevBudgetRefused, match="ledger_stopped"):
        ledger.admit_unit("next", 0)

    # A call already in flight still settles, and the ledger stays stopped.
    with pytest.raises(JevBudgetExhausted, match="already stopped"):
        ledger.settle(in_flight, [{"call_id": "b", "input_tokens": 10}])
    status = JevCostLedger.open(path).status()
    assert Decimal(status["committed_usd"]) == usd(490)
    assert status["stopped"] is True
    assert status["stop_reasons"] == ["stop_limit_reached"]
    assert status["open_reservations"] == 0


def test_settling_more_calls_than_reserved_stops_the_ledger(path: Path) -> None:
    ledger = JevCostLedger.create(path)
    ledger.admit_unit("U0a", 1)
    reservation = ledger.reserve("U0a", 1)
    with pytest.raises(JevBudgetExhausted) as exhausted:
        ledger.settle(
            reservation,
            [{"call_id": "a", "input_tokens": 1000}, {"call_id": "b", "input_tokens": 2000}],
        )
    assert exhausted.value.reason == "reservation_overrun"
    assert exhausted.value.record is not None
    assert exhausted.value.record["overrun_calls"] == 1
    status = ledger.status()
    assert Decimal(status["estimate_usd_total"]) == usd(3000)
    assert status["stop_reasons"] == ["reservation_overrun"]
    with pytest.raises(JevBudgetRefused, match="ledger_stopped"):
        ledger.reserve("U0a")


@pytest.mark.parametrize(
    "calls",
    [
        [{"call_id": "dup", "input_tokens": 1}, {"call_id": "dup", "input_tokens": 2}],
        [{"input_tokens": 5}],
        [{"call_id": "x", "input_tokens": 5, "output_tokens": 3}],
        [{"call_id": "x", "input_tokens": -1}],
        [{"call_id": "x", "input_tokens": True}],
        [{"call_id": "x", "input_tokens": 1.5}],
        [{"call_id": "has space", "input_tokens": 1}],
        ["not-a-call"],
    ],
)
def test_settle_rejects_malformed_calls_without_writing(path: Path, calls: list[Any]) -> None:
    ledger = JevCostLedger.create(path)
    ledger.admit_unit("U0a", 2)
    reservation = ledger.reserve("U0a", 2)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ledger.settle(reservation, calls)
    assert path.read_bytes() == before
    assert ledger.status()["open_reservations"] == 1


def test_settle_rejects_unknown_repeated_reservations_and_reused_call_ids(path: Path) -> None:
    ledger = JevCostLedger.create(path)
    ledger.admit_unit("U0a", 3)
    with pytest.raises(ValueError, match="already admitted"):
        ledger.admit_unit("U0a", 3)
    with pytest.raises(ValueError, match="not open"):
        ledger.settle("0" * 32, [])
    reservation = ledger.reserve("U0a")
    ledger.settle(reservation, [{"call_id": "c1:attempt-1", "input_tokens": 10}])
    records = len(_records(path))
    with pytest.raises(ValueError, match="not open"):
        ledger.settle(reservation, [])
    with pytest.raises(ValueError, match="already settled"):
        ledger.settle(ledger.reserve("U0a"), [{"call_id": "c1:attempt-1", "input_tokens": 10}])
    assert len(_records(path)) == records + 1  # only the second reservation was written


def _edit_middle_amount(lines: list[bytes]) -> list[bytes]:
    lines[3] = lines[3].replace(b'"0.000042000"', b'"0.000041000"', 1)
    return lines


def _edit_last_line(lines: list[bytes]) -> list[bytes]:
    # A replayable edit: only the head anchor covers the newest line.
    lines[-1] = re.sub(rb'"ts":"[^"]+"', b'"ts":"2000-01-01T00:00:00.000000Z"', lines[-1])
    return lines


def _swap_lines(lines: list[bytes]) -> list[bytes]:
    lines[1], lines[2] = lines[2], lines[1]
    return lines


@pytest.mark.parametrize(
    "tamper",
    [
        _edit_middle_amount,
        _edit_last_line,
        _swap_lines,
        lambda lines: lines[:-1],
        lambda lines: [*lines[:2], *lines[3:]],
        lambda lines: [*lines[:2], lines[1], *lines[2:]],
        lambda lines: [*lines[:2], b"", *lines[2:]],
        lambda lines: [*lines[:2], lines[2].replace(b'"seq":2', b'"seq":3'), *lines[3:]],
    ],
    ids=[
        "edited-amount",
        "edited-last-line",
        "reordered",
        "dropped-last-record",
        "dropped-middle-record",
        "duplicated-line",
        "blank-line",
        "bad-seq",
    ],
)
def test_open_detects_edited_truncated_or_reordered_lines(
    path: Path, tamper: Callable[[list[bytes]], list[bytes]]
) -> None:
    ledger = _sample(path)
    lines = path.read_bytes().split(b"\n")[:-1]
    path.write_bytes(b"".join(line + b"\n" for line in tamper(lines)))
    with pytest.raises(JevLedgerIntegrityError):
        JevCostLedger.open(path)
    with pytest.raises(JevLedgerIntegrityError):
        ledger.status()
    with pytest.raises(JevLedgerIntegrityError):
        ledger.reserve("U0a")


def test_open_detects_a_torn_final_line_and_a_missing_anchor(path: Path) -> None:
    _sample(path)
    data = path.read_bytes()
    path.write_bytes(data[:-10])
    with pytest.raises(JevLedgerIntegrityError, match="truncated"):
        JevCostLedger.open(path)
    path.write_bytes(data)
    JevCostLedger.open(path)
    Path(f"{path}.head").unlink()
    with pytest.raises(JevLedgerIntegrityError, match="anchor is missing"):
        JevCostLedger.open(path)


def test_anchor_may_lag_one_record_after_a_crash(path: Path) -> None:
    ledger = _sample(path)
    anchor = Path(f"{path}.head")
    stale = anchor.read_bytes()
    ledger.reserve("U0a")
    anchor.write_bytes(stale)
    assert JevCostLedger.open(path).status()["open_reservations"] == 2


def test_a_process_detects_a_rollback_that_a_fresh_open_cannot(path: Path) -> None:
    ledger = _sample(path)
    _rewrite(path, _records(path)[:-1])
    assert JevCostLedger.open(path).status()["open_reservations"] == 0
    with pytest.raises(JevLedgerIntegrityError, match="already verified"):
        ledger.status()


def test_replay_rejects_consistently_rehashed_forgeries(path: Path) -> None:
    JevCostLedger.create(path, **SMALL).admit_unit("u", 1, p95_input_tokens=1)
    ledger = JevCostLedger.open(path)
    reservation = ledger.reserve("u", 1, input_tokens_per_call=960)
    with pytest.raises(JevBudgetExhausted):
        ledger.settle(reservation, [{"call_id": "a", "input_tokens": 960}])
    genuine = _records(path)
    _rewrite(path, genuine)
    assert JevCostLedger.open(path).status()["stopped"] is True

    _rewrite(path, genuine[:-1])  # drop the stop so spending could resume
    with pytest.raises(JevLedgerIntegrityError, match="stop record"):
        JevCostLedger.open(path)

    cheaper = [dict(record) for record in genuine]
    cheaper[3] = {**cheaper[3], "calls": [{**cheaper[3]["calls"][0], "input_tokens": 9}]}
    _rewrite(path, cheaper)
    with pytest.raises(JevLedgerIntegrityError, match="call amounts do not replay"):
        JevCostLedger.open(path)

    greedy = [dict(record) for record in genuine[:2]]
    greedy[1].update(planned_jev_calls=10**6, projection_usd="0.042000000")
    _rewrite(path, greedy)
    with pytest.raises(JevLedgerIntegrityError):
        JevCostLedger.open(path)

    typed = [dict(record) for record in genuine[:2]]
    typed[1]["p95_source"] = ["explicit"]
    _rewrite(path, typed)
    with pytest.raises(JevLedgerIntegrityError):
        JevCostLedger.open(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input_usd_per_million", "0.050", "header mismatch: input_usd_per_million"),
        ("reserve_input_tokens", 20_000, "header mismatch: reserve_input_tokens"),
        ("reserve_input_tokens", 25_000.0, "header mismatch: reserve_input_tokens"),
        ("price_reference_checked_at", "2026-01-01", "header mismatch"),
        ("schema_id", "geode.jev-cost-ledger@2", "header mismatch: schema_id"),
        ("cost_limit_usd", "0.000000000", "header limits refused"),
        ("cost_limit_usd", "2.000000000", "header limits refused"),
        ("stop_limit_usd", "0.800000000", "header limits refused"),
        ("cost_limit_usd", "1.0", "not canonical"),
    ],
)
def test_open_verifies_the_header(path: Path, field: str, value: Any, message: str) -> None:
    JevCostLedger.create(path)
    (header,) = _records(path)
    _rewrite(path, [{**header, field: value}])
    with pytest.raises(JevLedgerIntegrityError, match=message):
        JevCostLedger.open(path)


def test_open_refuses_group_writable_or_symlinked_ledgers(path: Path, tmp_path: Path) -> None:
    JevCostLedger.create(path)
    link = tmp_path / "link.jsonl"
    link.symlink_to(path)
    with pytest.raises(OSError):
        JevCostLedger.open(link)
    path.chmod(0o620)
    with pytest.raises(JevLedgerIntegrityError, match="group/world-writable"):
        JevCostLedger.open(path)


_WORKER = """
import os, sys, time
from evals.benchmarks.jev_cost_ledger import JevCostLedger

path, go, worker, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
ledger = JevCostLedger.open(path)
while not os.path.exists(go):
    time.sleep(0.005)
for index in range(rounds):
    reservation = ledger.reserve("U-concurrent", 1, input_tokens_per_call=1000)
    ledger.settle(reservation, [{"call_id": f"w{worker}-{index}", "input_tokens": 100 + worker}])
"""


def test_flock_serializes_appends_from_concurrent_processes(path: Path, tmp_path: Path) -> None:
    workers, rounds = 4, 25
    JevCostLedger.create(path).admit_unit("U-concurrent", workers * rounds)
    go = tmp_path / "go"
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    processes = [
        subprocess.Popen(  # noqa: S603 - this interpreter running the fixed worker above
            [sys.executable, "-c", _WORKER, str(path), str(go), str(worker), str(rounds)],
            cwd=REPO_ROOT,
            env=env,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker in range(workers)
    ]
    time.sleep(0.5)
    go.touch()
    for process in processes:
        _, stderr = process.communicate(timeout=120)
        assert process.returncode == 0, stderr

    status = JevCostLedger.open(path).status()
    tokens = sum((100 + worker) * rounds for worker in range(workers))
    assert status["settled_calls"] == workers * rounds
    assert status["input_tokens_observed_sum"] == tokens
    assert Decimal(status["committed_usd"]) == usd(tokens)
    assert status["open_reservations"] == 0
    records = _records(path)
    assert [record["seq"] for record in records] == list(range(2 + 2 * workers * rounds))
    settled = [
        call["call_id"] for row in records if row["kind"] == "settlement" for call in row["calls"]
    ]
    assert len(set(settled)) == workers * rounds


def test_threads_share_the_call_context_manager(path: Path) -> None:
    shared = JevCostLedger.create(path)
    shared.admit_unit("U-panel", 40)

    def one_call(index: int) -> None:
        ledger = shared if index % 2 else JevCostLedger.open(path)
        with ledger.call("U-panel") as handle:
            handle.call_id = f"t{index}:attempt-1"
            handle.input_tokens = 50

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one_call, range(40)))
    status = shared.status()
    assert status["settled_calls"] == 40
    assert status["input_tokens_observed_sum"] == 2000
    assert status["open_reservations"] == 0


def test_call_context_settles_success_failure_and_exhaustion(path: Path) -> None:
    ledger = JevCostLedger.create(path)
    ledger.admit_unit("u", 4)
    with ledger.call("u", input_tokens_per_call=100) as handle:
        handle.call_id = "ok:attempt-1"
        handle.input_tokens = 40
    with (
        pytest.raises(RuntimeError, match="transport"),
        ledger.call("u", input_tokens_per_call=100),
    ):
        raise RuntimeError("transport failed without usage")
    with pytest.raises(ValueError), ledger.call("u", input_tokens_per_call=100) as handle:
        handle.input_tokens = -1
    with pytest.raises(JevBudgetRefused, match="unit_not_admitted"), ledger.call("ghost"):
        pass
    status = ledger.status()
    assert Decimal(status["estimate_usd_total"]) == usd(40)
    assert Decimal(status["settled_reserve_usd"]) == 2 * RESERVE_USD
    assert status["open_reservations"] == 0
    assert status["units"]["u"]["missing_token_calls"] == 2

    fresh = JevCostLedger.create(path.with_name("fresh.jsonl"), **SMALL)
    fresh.admit_unit("u", 1, p95_input_tokens=1)
    with pytest.raises(JevBudgetExhausted), fresh.call("u", input_tokens_per_call=960) as handle:
        handle.input_tokens = 960
    assert fresh.status()["stopped"] is True


def test_jev_calls_from_call_accounting_selects_jev_rows() -> None:
    real_row = {
        "purpose": "turn_verification",
        "model": JEV_MODEL,
        "llm_attempt_id": "v1:attempt-1",
        **_accounting({"response_model": JEV_MODEL, "usage": {"input_tokens": 700}}),
    }
    rows: list[Any] = [
        {
            "model": MODEL,
            "response_model": MODEL,
            "llm_attempt_id": "a:1",
            "usage": {"input_tokens": 9},
        },
        real_row,
        {"model": None, "response_model": JEV_MODEL, "llm_attempt_id": "j2", "usage": {}},
        {"model": JEV_MODEL, "llm_attempt_id": "", "usage": {}, "error_type": "timeout"},
        {"model": JEV_MODEL, "llm_attempt_id": "j4", "usage": {"input_tokens": True}},
        {"model": JEV_MODEL, "llm_attempt_id": "j5", "usage": {"input_tokens": -5}},
        {"model": JEV_MODEL, "llm_attempt_id": "j6"},
    ]
    assert jev_calls_from_call_accounting(rows) == [
        {"call_id": "v1:attempt-1", "input_tokens": 700},
        {"call_id": "j2", "input_tokens": None},
        {"call_id": None, "input_tokens": None},
        {"call_id": "j4", "input_tokens": None},
        {"call_id": "j5", "input_tokens": None},
        {"call_id": "j6", "input_tokens": None},
    ]
    with pytest.raises(ValueError):
        jev_calls_from_call_accounting(["not-a-row"])


def test_cli_exit_codes(capsys: pytest.CaptureFixture[str], path: Path) -> None:
    code, out = _cli(capsys, "init", path, "--cost-limit-usd", "0")
    assert (code, out["ok"], out["error"]) == (EXIT_INVALID, False, "invalid")
    assert not path.exists()
    code, out = _cli(capsys, "init", path, *SMALL_CLI)
    assert (code, out["ok"], out["status"]["cost_limit_usd"]) == (EXIT_OK, True, "0.000042000")
    code, out = _cli(capsys, "init", path)
    assert (code, out["error"]) == (EXIT_INTEGRITY, "integrity")
    assert str(path.parent) not in json.dumps(out)

    code, out = _cli(
        capsys, "admit", path, "--unit-id", "U", "--planned-jev-calls", 1, "--p95-input-tokens", 1
    )
    assert (code, out["record"]["kind"]) == (EXIT_OK, "unit_admitted")
    code, out = _cli(
        capsys, "admit", path, "--unit-id", "V", "--planned-jev-calls", 1, "--p95-input-tokens", 901
    )
    assert (code, out["error"], out["reason"]) == (
        EXIT_REFUSED,
        "refused",
        "projection_exceeds_start_limit",
    )
    assert out["record"]["kind"] == "unit_refused"
    code, out = _cli(capsys, "reserve", path, "--unit-id", "V")
    assert (code, out["reason"]) == (EXIT_REFUSED, "unit_not_admitted")

    code, out = _cli(capsys, "reserve", path, "--unit-id", "U", "--input-tokens-per-call", 960)
    assert code == EXIT_OK
    calls = path.with_name("calls.json")
    calls.write_text(json.dumps([{"call_id": "c1:attempt-1", "input_tokens": 960}]))
    code, out = _cli(
        capsys, "settle", path, "--reservation-id", out["reservation_id"], "--calls-json", calls
    )
    assert (code, out["error"], out["reason"]) == (EXIT_STOPPED, "stopped", "stop_limit_reached")
    assert out["record"]["kind"] == "settlement"
    code, out = _cli(capsys, "reserve", path, "--unit-id", "U")
    assert (code, out["reason"], out["status"]["stopped"]) == (EXIT_STOPPED, "ledger_stopped", True)
    code, out = _cli(capsys, "status", path)
    assert (code, out["status"]["stopped"]) == (EXIT_OK, True)

    code, out = _cli(capsys, "bogus")
    assert (code, out["error"]) == (EXIT_INVALID, "invalid")
    code, out = _cli(capsys, "settle", path, "--reservation-id", "x")
    assert (code, out["error"]) == (EXIT_INVALID, "invalid")
    code, out = _cli(capsys, "status", path.with_name("missing.jsonl"))
    assert (code, out["error"]) == (EXIT_INTEGRITY, "integrity")
    assert str(path.parent) not in out["message"]
    path.write_bytes(path.read_bytes().replace(b'"U"', b'"W"'))
    code, out = _cli(capsys, "status", path)
    assert (code, out["error"]) == (EXIT_INTEGRITY, "integrity")


def test_cli_settles_from_a_handoff_result(capsys: pytest.CaptureFixture[str], path: Path) -> None:
    assert _cli(capsys, "init", path)[0] == EXIT_OK
    assert _cli(capsys, "admit", path, "--unit-id", "U7", "--planned-jev-calls", 6)[0] == EXIT_OK
    rows = [
        {
            "model": MODEL,
            "response_model": MODEL,
            "llm_attempt_id": "r:attempt-1",
            "usage": {"input_tokens": 5},
        },
        {
            "model": JEV_MODEL,
            "response_model": JEV_MODEL,
            "llm_attempt_id": "j:attempt-1",
            "usage": {"input_tokens": 1200},
        },
    ]
    result = path.with_name("handoff-result.json")
    usage = {"attempt_pairing_complete": True, "observation_status": "no_known_faults"}
    result.write_text(json.dumps({"call_accounting": rows, "usage": usage}))
    code, out = _cli(capsys, "reserve", path, "--unit-id", "U7", "--max-calls", 2)
    code, out = _cli(
        capsys,
        "settle",
        path,
        "--reservation-id",
        out["reservation_id"],
        "--call-accounting",
        result,
    )
    assert code == EXIT_OK
    assert [call["input_tokens"] for call in out["record"]["calls"]] == [1200]

    rows[1] = {**rows[1], "llm_attempt_id": "j:attempt-2"}  # the next trial's own attempt
    result.write_text(
        json.dumps({"call_accounting": rows, "usage": {**usage, "attempt_pairing_complete": False}})
    )
    reservation = _cli(capsys, "reserve", path, "--unit-id", "U7", "--max-calls", 2)[1][
        "reservation_id"
    ]
    before = path.read_bytes()
    code, out = _cli(
        capsys, "settle", path, "--reservation-id", reservation, "--call-accounting", result
    )
    assert (code, out["error"]) == (EXIT_INVALID, "invalid")
    assert path.read_bytes() == before
    code, out = _cli(
        capsys,
        "settle",
        path,
        "--reservation-id",
        reservation,
        "--call-accounting",
        result,
        "--unknown-calls",
        1,
    )
    assert code == EXIT_OK
    assert [call["input_tokens"] for call in out["record"]["calls"]] == [1200, None]

    reservation = _cli(capsys, "reserve", path, "--unit-id", "U7", "--max-calls", 2)[1][
        "reservation_id"
    ]
    code, out = _cli(capsys, "settle", path, "--reservation-id", reservation, "--unknown-calls", 2)
    assert (code, out["record"]["reserve_usd"]) == (EXIT_OK, "0.002100000")


def test_module_entry_point(path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    command = [sys.executable, "-m", "evals.benchmarks.jev_cost_ledger"]

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - this interpreter, fixed module, temporary ledger
            [*command, *argv], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False
        )

    init = run("init", str(path))
    assert init.returncode == EXIT_OK, init.stderr
    refused = run("admit", str(path), "--unit-id", "U", "--planned-jev-calls", "900")
    assert refused.returncode == EXIT_REFUSED
    assert json.loads(refused.stdout)["reason"] == "projection_exceeds_start_limit"
