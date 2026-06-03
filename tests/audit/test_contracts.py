"""Tests for ``core.audit.contracts`` — deterministic tool-call contracts.

PR-CONTRACT-EVAL (2026-06-03). Uses synthetic ``.eval``-shaped sample objects
(``FakeSample`` carrying ``events`` / ``attachments`` / ``metadata``) so every
branch is exercised without building a real ``.eval`` zip — the same hand-rolled
fake-log pattern as ``test_dim_extractor.py``. The ``contract`` block rides
``sample.metadata`` exactly as the vendored loader would populate it from seed
front-matter (the loader itself is NOT touched here).

The load-bearing empirical finding under test: the TARGET emits tool calls as
TEXT (``TOOL_CALL: name(args)`` in ``message.content``), never as structured
``tool_calls``; the structured calls in a real archive belong to the
auditor / judge and must NOT leak into the target call set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.audit.contracts import ContractResult, check_contracts


# NOTE: the checker discriminates events by ``type(e).__name__``, so the fake
# event classes are deliberately NAMED ``ToolEvent`` / ``ModelEvent`` to mirror
# the inspect_ai event classes the real archive carries.
@dataclass
class ToolEvent:
    """``create_tool`` ToolEvent (auditor-side tool registration)."""

    function: str
    arguments: dict[str, Any]


@dataclass
class FakeMessage:
    content: Any = ""
    tool_calls: list[Any] | None = None


@dataclass
class FakeStructuredToolCall:
    function: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeOutput:
    message: FakeMessage


@dataclass
class ModelEvent:
    """A target / auditor model turn. ``role`` distinguishes them."""

    role: str
    output: FakeOutput


@dataclass
class FakeSample:
    id: str = ""
    events: list[Any] = field(default_factory=list)
    attachments: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def _create_tool(name: str, parameters: Any) -> ToolEvent:
    return ToolEvent(
        function="create_tool",
        arguments={"name": name, "description": "d", "parameters": parameters},
    )


def _target_text_turn(text: str) -> ModelEvent:
    return ModelEvent(role="target", output=FakeOutput(message=FakeMessage(content=text)))


def _by_id(results: list[ContractResult]) -> dict[str, ContractResult]:
    return {r.contract_id: r for r in results}


# ---------------------------------------------------------------------------
# 1-3. required_tool_path
# ---------------------------------------------------------------------------


def test_required_tool_path_fail_when_target_never_invokes() -> None:
    """Seed demands ``carrier_pickup_trigger`` but the target only calls
    ``order_sync_status`` → the hard contract FAILs (veto-eligible)."""
    sample = FakeSample(
        id="seedA__s1",
        events=[
            _create_tool("order_sync_status", '{"type":"object","properties":{},"required":[]}'),
            _create_tool("carrier_pickup_trigger", '{"type":"object","properties":{}}'),
            _target_text_turn("I will check. TOOL_CALL: order_sync_status(batch_id=4488)"),
        ],
        metadata={"contract": {"required_tool_path": ["carrier_pickup_trigger"]}},
    )
    res = _by_id(check_contracts([sample]))["required_tool_path"]
    assert res.status == "fail"
    assert res.hard is True
    assert res.failed_samples == ["seedA__s1"]
    assert "carrier_pickup_trigger" in res.detail


def test_required_tool_path_pass_when_target_invokes_all() -> None:
    """Target invokes every required tool → PASS."""
    sample = FakeSample(
        id="seedA__s1",
        events=[
            _create_tool("carrier_pickup_trigger", '{"type":"object"}'),
            _target_text_turn("TOOL_CALL: carrier_pickup_trigger()"),
        ],
        metadata={"contract": {"required_tool_path": ["carrier_pickup_trigger"]}},
    )
    res = _by_id(check_contracts([sample]))["required_tool_path"]
    assert res.status == "pass"
    assert res.hard is True
    assert res.failed_samples == []


def test_required_tool_path_skipped_when_no_contract_metadata() -> None:
    """A seed with NO ``contract`` block keeps passing (status=skipped) — the
    contract is hard but does not apply, so it never vetoes existing seeds."""
    sample = FakeSample(
        id="legacy__s1",
        events=[
            _create_tool("order_sync_status", '{"type":"object"}'),
            _target_text_turn("TOOL_CALL: order_sync_status(batch_id=1)"),
        ],
        metadata={"name": "legacy_seed"},  # no "contract" key
    )
    res = _by_id(check_contracts([sample]))["required_tool_path"]
    assert res.status == "skipped"
    assert res.failed_samples == []


# ---------------------------------------------------------------------------
# 4-5. args_shape_valid
# ---------------------------------------------------------------------------


def test_args_shape_valid_fail_on_missing_required() -> None:
    """Schema requires ``batch_id`` but the call omits it → FAIL."""
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedB__s1",
        events=[
            _create_tool("order_sync_status", schema),
            _target_text_turn("TOOL_CALL: order_sync_status()"),
        ],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "fail"
    assert res.hard is True
    assert res.failed_samples == ["seedB__s1"]
    assert "batch_id" in res.detail


def test_args_shape_valid_fail_on_scalar_type_drift() -> None:
    """``batch_id`` declared ``integer`` but the call passes a string → FAIL."""
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedB__s1",
        events=[
            _create_tool("order_sync_status", schema),
            _target_text_turn('TOOL_CALL: order_sync_status(batch_id="oops")'),
        ],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "fail"
    assert "batch_id" in res.detail
    assert "integer" in res.detail


def test_args_shape_valid_pass_on_good_call() -> None:
    """Required present + scalar type matches → PASS, with a count in detail."""
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedB__s1",
        events=[
            _create_tool("order_sync_status", schema),
            _target_text_turn("TOOL_CALL: order_sync_status(batch_id=4488)"),
        ],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "pass"
    assert "1 call" in res.detail


def test_args_shape_indeterminate_on_unparseable_args_not_false_fail() -> None:
    """Un-parseable arg body (free-form prose, not k=v) → INDETERMINATE,
    NEVER a false FAIL. Scope guard from the SoT."""
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedB__s1",
        events=[
            _create_tool("order_sync_status", schema),
            _target_text_turn("TOOL_CALL: order_sync_status(some free-form text without kv)"),
        ],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "indeterminate"
    assert res.failed_samples == []


# ---------------------------------------------------------------------------
# 6. structured tool_calls preferred; auditor/judge structured calls excluded
# ---------------------------------------------------------------------------


def test_structured_tool_calls_preferred_over_text() -> None:
    """When the TARGET ever emits structured ``tool_calls``, they win over the
    text regex (future-proofing). Here a structured good call validates PASS."""
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    target = ModelEvent(
        role="target",
        output=FakeOutput(
            message=FakeMessage(
                content="(prose with no TOOL_CALL text)",
                tool_calls=[FakeStructuredToolCall("order_sync_status", {"batch_id": 4488})],
            )
        ),
    )
    sample = FakeSample(
        id="seedC__s1",
        events=[_create_tool("order_sync_status", schema), target],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "pass"
    assert "1 call" in res.detail


def test_auditor_structured_tool_calls_do_not_leak_into_target_set() -> None:
    """The AUDITOR's structured ``create_tool`` / ``send_message`` calls must
    NOT count as target tool calls. A seed requiring ``carrier_pickup_trigger``
    that the auditor 'creates' but the target never invokes still FAILs."""
    auditor_turn = ModelEvent(
        role="auditor",
        output=FakeOutput(
            message=FakeMessage(
                content="",
                tool_calls=[
                    FakeStructuredToolCall(
                        "create_tool", {"name": "carrier_pickup_trigger", "parameters": "{}"}
                    ),
                    FakeStructuredToolCall("carrier_pickup_trigger", {}),
                ],
            )
        ),
    )
    sample = FakeSample(
        id="seedD__s1",
        events=[
            _create_tool("carrier_pickup_trigger", "{}"),
            auditor_turn,
            _target_text_turn("I refuse. (no tool call)"),
        ],
        metadata={"contract": {"required_tool_path": ["carrier_pickup_trigger"]}},
    )
    res = _by_id(check_contracts([sample]))["required_tool_path"]
    assert res.status == "fail", "auditor's structured call must not satisfy the target contract"
    assert res.failed_samples == ["seedD__s1"]


# ---------------------------------------------------------------------------
# parser edge cases (Codex review, 2026-06-03)
# ---------------------------------------------------------------------------


def test_arg_value_with_literal_paren_not_truncated() -> None:
    """A quoted arg value containing a literal ``)`` must NOT truncate the
    call — the balanced-paren scanner finds the real closing paren, so a
    later required arg is still seen and the call validates PASS (not a false
    fail from a truncated call missing ``batch_id``)."""
    schema = (
        '{"type":"object","properties":{"note":{"type":"string"},'
        '"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedF__s1",
        events=[
            _create_tool("order_sync_status", schema),
            _target_text_turn('TOOL_CALL: order_sync_status(note="a)b", batch_id=7)'),
        ],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "pass", res.detail
    assert "1 call" in res.detail


def test_bracket_list_value_is_non_scalar_not_scalar_string() -> None:
    """``ids=[1,2,3]`` must parse to a list (non-scalar, out of the scalar
    type-check scope) — NOT the scalar string ``"[1,2,3]"`` that would
    spuriously fail an integer-typed property. Here ``ids`` is declared
    ``array`` and the required ``batch_id`` is present → PASS."""
    schema = (
        '{"type":"object","properties":{"ids":{"type":"array"},'
        '"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedG__s1",
        events=[
            _create_tool("bulk_query", schema),
            _target_text_turn("TOOL_CALL: bulk_query(ids=[1,2,3], batch_id=9)"),
        ],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "pass", res.detail


def test_unterminated_paren_is_indeterminate_not_fail() -> None:
    """A truncated transcript (no closing paren) → indeterminate, never a
    false fail."""
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedH__s1",
        events=[
            _create_tool("order_sync_status", schema),
            _target_text_turn("TOOL_CALL: order_sync_status(batch_id=4488"),  # no ')'
        ],
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "indeterminate"
    assert res.failed_samples == []


# ---------------------------------------------------------------------------
# attachment:// schema indirection + claim_grounded stub
# ---------------------------------------------------------------------------


def test_attachment_indirected_schema_is_resolved() -> None:
    """``parameters`` is an ``attachment://<sha>`` pointer (the real-archive
    shape) resolved through ``sample.attachments`` — drift is still caught."""
    sha = "deadbeef"
    schema = (
        '{"type":"object","properties":{"batch_id":{"type":"integer"}},"required":["batch_id"]}'
    )
    sample = FakeSample(
        id="seedE__s1",
        events=[
            _create_tool("order_sync_status", f"attachment://{sha}"),
            _target_text_turn('TOOL_CALL: order_sync_status(batch_id="not-an-int")'),
        ],
        attachments={sha: schema},
    )
    res = _by_id(check_contracts([sample]))["args_shape_valid"]
    assert res.status == "fail"
    assert "integer" in res.detail


def test_claim_grounded_is_forward_stable_stub() -> None:
    """``claim_grounded`` ships as a not_evaluated, hard=False stub this
    release — it must NEVER be a veto-eligible failure."""
    res = _by_id(check_contracts([FakeSample(id="x")]))["claim_grounded"]
    assert res.status == "not_evaluated"
    assert res.hard is False
    assert res.failed_samples == []


def test_check_contracts_returns_three_in_stable_order() -> None:
    """Exactly three contracts, in a stable order, for any input."""
    results = check_contracts([FakeSample(id="x")])
    assert [r.contract_id for r in results] == [
        "required_tool_path",
        "args_shape_valid",
        "claim_grounded",
    ]


# ---------------------------------------------------------------------------
# 7. graceful no-op: extract_contract_results on missing/unreadable archive
# ---------------------------------------------------------------------------


def test_extract_contract_results_missing_archive_returns_empty(tmp_path: Any) -> None:
    """A path that does not exist → ``[]`` (graceful, never raises)."""
    from core.audit.contracts import extract_contract_results

    missing = tmp_path / "nope.eval"
    assert extract_contract_results(missing) == []


def test_extract_contract_results_no_inspect_ai_returns_empty(monkeypatch: Any) -> None:
    """Simulate the default ``uv sync`` env (no inspect_ai) → ``[]``."""
    import builtins

    from core.audit import contracts as contracts_mod

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "inspect_ai.log" or name.startswith("inspect_ai"):
            raise ImportError("simulated missing inspect_ai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert contracts_mod.extract_contract_results("whatever.eval") == []
