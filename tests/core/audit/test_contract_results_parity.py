"""PR-CONTRACT-EVAL (2026-06-03) — persistence round-trip parity.

The contract ledger produced by ``extract_contract_results`` must survive two
write paths verbatim:

(a) the summary YAML written by ``plugins.petri_audit.eval_archive.archive_eval``
    (the committable ``docs/audits/eval-logs/*.summary.yaml``), and
(b) ``core.self_improving.loop.runner.ApplyRecord.model_validate`` — the
    ``mutations.jsonl`` writer's Pydantic schema (``extra="allow"``), which must
    accept the ledger as a typed field without a ValidationError.

This guards the writer-reader parity invariant: a ledger that the extractor
emits but a downstream schema rejects would silently vanish from the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai.log")
pytest.importorskip("yaml")


# Reuse the fake-log shapes locally so the parity test does not depend on the
# checker's own test module.
@dataclass
class FakeToolEvent:
    function: str
    arguments: dict[str, Any]


@dataclass
class FakeMessage:
    content: Any = ""
    tool_calls: list[Any] | None = None


@dataclass
class FakeOutput:
    message: FakeMessage


@dataclass
class FakeModelEvent:
    role: str
    output: FakeOutput


@dataclass
class FakeScore:
    value: Any = None


@dataclass
class FakeSample:
    id: str = ""
    events: list[Any] = field(default_factory=list)
    attachments: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, FakeScore] = field(default_factory=dict)
    input: str = ""


@dataclass
class FakeEvalModel:
    task: str = "inspect_petri/audit"
    model_roles: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeStats:
    model_usage: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    completed_at: str = ""


@dataclass
class FakeEvalLog:
    samples: list[FakeSample] = field(default_factory=list)
    status: str = "success"
    eval: FakeEvalModel = field(default_factory=FakeEvalModel)
    stats: FakeStats = field(default_factory=FakeStats)


def _required_fail_sample() -> FakeSample:
    """A sample whose target never invokes the seed's required tool → a hard
    FAIL ledger row, plus a passing args row and the claim_grounded stub."""
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    return FakeSample(
        id="seedA__s1",
        events=[
            FakeToolEvent(
                "create_tool",
                {"name": "order_sync_status", "description": "d", "parameters": schema},
            ),
            FakeToolEvent(
                "create_tool",
                {"name": "carrier_pickup_trigger", "description": "d", "parameters": "{}"},
            ),
            FakeModelEvent(
                "target",
                FakeOutput(FakeMessage(content="TOOL_CALL: order_sync_status(batch_id=4488)")),
            ),
        ],
        metadata={"contract": {"required_tool_path": ["carrier_pickup_trigger"]}},
        scores={"audit_judge": FakeScore(value={"broken_tool_use": 3})},
    )


def test_ledger_round_trips_through_summary_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``archive_eval`` writes the ledger into the summary YAML verbatim."""
    import yaml

    fake_log = FakeEvalLog(samples=[_required_fail_sample()])

    def fake_read(*_args: Any, **_kwargs: Any) -> FakeEvalLog:
        return fake_log

    monkeypatch.setattr("inspect_ai.log.read_eval_log", fake_read)

    eval_path = tmp_path / "2026-06-03T00-00-00_audit_fake.eval"
    eval_path.write_bytes(b"placeholder")

    from plugins.petri_audit.eval_archive import archive_eval

    result = archive_eval(
        eval_path,
        raw_archive_dir=tmp_path / "raw",
        summary_dir=tmp_path / "summary",
    )

    assert "contract_results" in result.summary
    ledger = result.summary["contract_results"]
    ids = {row["contract_id"]: row for row in ledger}
    assert ids["required_tool_path"]["status"] == "fail"
    assert ids["required_tool_path"]["hard"] is True
    assert ids["claim_grounded"]["status"] == "not_evaluated"

    # The on-disk YAML carries it too (the diffable, committable surface).
    on_disk = yaml.safe_load(result.summary_path.read_text(encoding="utf-8"))
    assert on_disk["contract_results"] == ledger


def test_ledger_validates_into_apply_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ledger drops into ``ApplyRecord`` (the mutations.jsonl writer
    schema) without a ValidationError + survives ``model_dump`` verbatim."""
    from core.audit.contracts import extract_contract_results

    fake_log = FakeEvalLog(samples=[_required_fail_sample()])

    def fake_read(*_args: Any, **_kwargs: Any) -> FakeEvalLog:
        return fake_log

    monkeypatch.setattr("inspect_ai.log.read_eval_log", fake_read)

    eval_path = tmp_path / "fake.eval"
    eval_path.write_bytes(b"placeholder")
    ledger = extract_contract_results(eval_path)
    assert ledger, "extractor should produce a non-empty ledger for this sample"

    from core.self_improving.loop.runner import ApplyRecord

    row = {
        "ts": 1.0,
        "kind": "applied",
        "mutation_id": "m1",
        "target_kind": "wrapper_section",
        "target_section": "tool_use",
        "previous_value": "old",
        "new_value": "new",
        "contract_results": ledger,
    }
    record = ApplyRecord.model_validate(row)
    assert record.contract_results == ledger
    # exclude_none dump (the writer's own dump) keeps the field intact.
    dumped = record.model_dump(exclude_none=True)
    assert dumped["contract_results"] == ledger


def test_ledger_lands_in_live_attribution_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The LIVE path: ``write_attribution(contract_results=…)`` writes the
    ledger into the per-cycle ``mutations.jsonl`` attribution row + it
    validates as ``AttributionRecord.contract_results`` (the apply row predates
    the audit, so the attribution row is the real live home)."""
    import json

    from core.audit.contracts import extract_contract_results

    fake_log = FakeEvalLog(samples=[_required_fail_sample()])

    def fake_read(*_args: Any, **_kwargs: Any) -> FakeEvalLog:
        return fake_log

    monkeypatch.setattr("inspect_ai.log.read_eval_log", fake_read)
    eval_path = tmp_path / "fake.eval"
    eval_path.write_bytes(b"placeholder")
    ledger = extract_contract_results(eval_path)
    assert ledger

    from core.self_improving.loop.attribution import AttributionRecord, write_attribution

    log_path = tmp_path / "mutations.jsonl"
    payload = write_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        log_path=log_path,
        contract_results=ledger,
    )
    assert payload["contract_results"] == ledger

    written = json.loads(log_path.read_text(encoding="utf-8").strip())
    record = AttributionRecord.model_validate(written)
    assert record.contract_results == ledger


def test_attribution_row_omits_empty_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dry-run / archive-missing cycle (empty ledger) omits the key — the
    legacy row shape is preserved."""
    from core.self_improving.loop.attribution import write_attribution

    log_path = tmp_path / "mutations.jsonl"
    payload = write_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        log_path=log_path,
        contract_results=[],
    )
    assert "contract_results" not in payload
