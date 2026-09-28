from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core.agent.capability_graph import build_capability_graph, graph_summary, supported_features
from core.agent.evidence_ledger import EvidenceLedger
from core.agent.loop import _context, _lifecycle, agent_loop
from core.agent.loop.models import AgenticResult
from core.agent.task_preflight import classify_task, plan_task_preflight, render_preflight_hint
from core.memory.atomic_write import read_jsonl
from core.tools.computer_observation import build_action_event, evaluate_trajectory


def test_capability_graph_exposes_subscription_computer_emulation() -> None:
    graph = build_capability_graph(
        model="gpt-5.5",
        provider="openai",
        source="subscription",
        visible_tool_names={"computer_use", "ingest_pdf"},
        computer_use_enabled=True,
    )

    assert "emulated_computer_use" in supported_features(graph)
    assert "native_computer_use" not in supported_features(graph)
    assert graph["features"]["pdf_tool_ingest"]["supported"] is True
    assert graph_summary(graph)["provider"] == "openai"


def test_capability_graph_keeps_anthropic_native_computer_use() -> None:
    graph = build_capability_graph(
        model="claude-opus-4-8",
        provider="anthropic",
        source="payg",
        visible_tool_names={"read_document"},
        computer_use_enabled=True,
    )

    assert graph["features"]["native_computer_use"]["supported"] is True
    assert graph["features"]["native_computer_use"]["mode"] == "hosted_provider_tool"


def test_task_preflight_routes_pdf_gui_research_code() -> None:
    graph = build_capability_graph(
        model="gpt-5.5",
        provider="openai",
        source="subscription",
        visible_tool_names={
            "computer_use",
            "ui_probe",
            "browser_snapshot",
            "ingest_pdf",
            "general_web_search",
            "web_fetch",
            "grep_files",
            "edit_file",
        },
        computer_use_enabled=True,
    )
    preflight = plan_task_preflight(
        "최신 논문 PDF를 보고 화면에서 결과를 클릭한 다음 코드 수정해줘",
        graph,
    )

    assert classify_task("open report.pdf and click the button") == ["pdf", "gui"]
    assert preflight["task_kinds"] == ["pdf", "gui", "research", "code"]
    assert "ingest_pdf" in preflight["recommended_tools"]
    assert "computer_use" in preflight["recommended_tools"]
    assert "ui_probe" in preflight["recommended_tools"]
    assert "browser_snapshot" in preflight["recommended_tools"]
    assert preflight["schema_version"] == 2
    assert "source_url" in preflight["suggested_evidence"]
    assert "gui_trajectory" in preflight["suggested_evidence"]
    assert "required_evidence" not in preflight
    rendered = render_preflight_hint(preflight)
    assert "computer_use" in rendered
    assert "visual locate is not source-safe" in rendered
    assert "ui_probe" in rendered


def test_task_preflight_keeps_locate_only_when_visual_grounding_supported() -> None:
    graph = build_capability_graph(
        model="glm-5",
        provider="glm",
        source="payg",
        visible_tool_names={"computer_use", "ui_probe"},
        computer_use_enabled=True,
    )

    preflight = plan_task_preflight("화면에서 Submit 버튼 클릭해줘", graph)

    assert "computer_use" in preflight["recommended_tools"]
    assert "ui_probe" in preflight["recommended_tools"]
    assert any("capture -> locate -> action -> verify" in n for n in preflight["route_notes"])


def test_evidence_ledger_redacts_and_hashes_payload(tmp_path) -> None:
    ledger = EvidenceLedger(
        session_id="s-test",
        path=tmp_path / "evidence.jsonl",
        turn_id_provider=lambda: "turn-7",
    )

    row = ledger.append(
        kind="tool_result",
        summary="Sensitive row",
        payload={"token": "secret-token", "nested": {"text": "typed password"}},
    )

    assert row["payload"]["token"].startswith("<redacted:length=")
    assert row["payload"]["nested"]["text"].startswith("<redacted:length=")
    assert row["seq"] == 1
    assert row["schema_version"] == 2
    assert row["session_id"] == "s-test"
    assert row["turn_id"] == "turn-7"
    assert row["call_id"] == ""
    assert row["component"] == "agentic_loop"
    assert row["event"] == "tool_result"
    written = read_jsonl(ledger.path)
    assert written[0]["payload_hash"] == row["payload_hash"]
    assert written[0]["event"] == "tool_result"


def test_gui_trajectory_eval_scores_recoverable_trace() -> None:
    ok = build_action_event(
        index=0,
        action="click",
        params={"x": 10, "y": 10},
        result={"observation": {"observation_id": "screen:1"}},
    )
    bad = build_action_event(
        index=1,
        action="click",
        params={"x": 5000, "y": 10},
        result={"error": "boom", "error_kind": "execution_error"},
    )

    strong = evaluate_trajectory([ok], target_size=(100, 100), final_has_screenshot=True)
    weak = evaluate_trajectory([ok, bad], target_size=(100, 100), final_has_screenshot=False)

    assert strong["verdict"] == "strong"
    assert weak["score"] < strong["score"]
    assert (
        "Remap or re-ground coordinates before dispatching more pointer actions."
        in weak["recommendations"]
    )


@pytest.mark.parametrize(
    ("user_input", "suggested_kind", "suggested_evidence"),
    [
        ("Update the requirements document", "pdf", "document_ingest"),
        ("Explain the context window", "gui", "gui_trajectory"),
    ],
)
def test_preflight_keyword_matches_remain_advisory_in_prompt_and_ledger(
    user_input: str, suggested_kind: str, suggested_evidence: str
) -> None:
    """A lexical match cannot supply the user's requirements or a verdict."""
    loop = object.__new__(agent_loop.AgenticLoop)
    loop._capability_graph = build_capability_graph(
        model="gpt-5.5",
        provider="openai",
        source="subscription",
        visible_tool_names={"ingest_pdf"},
        computer_use_enabled=False,
    )
    loop._evidence_ledger = EvidenceLedger(session_id="s-preflight")
    loop._timeline = None

    hint = loop._prepare_task_preflight(user_input)
    prompt = _context.inject_runtime_hints("<dynamic_context>\n</dynamic_context>", hint)
    row = loop._evidence_ledger.rows[0]
    recorded = row["payload"]["preflight"]

    assert row["kind"] == "task_preflight"
    assert recorded["schema_version"] == 2
    assert recorded["task_kinds"] == [suggested_kind]
    assert suggested_evidence in recorded["suggested_evidence"]
    assert "required_evidence" not in recorded
    assert "suggested_evidence:" in prompt
    assert "keyword-based routing suggestions, not task requirements or verification" in prompt
    assert prompt.index(hint) < prompt.index("</dynamic_context>")


@pytest.mark.parametrize(
    ("termination_reason", "error"), [("natural", None), ("billing_error", "billing_error")]
)
def test_finalize_records_outcome_without_inferring_evidence_coverage(
    tmp_path, termination_reason: str, error: str | None
) -> None:
    graph = build_capability_graph(
        model="gpt-5.5",
        provider="openai",
        source="subscription",
        visible_tool_names={"web_fetch"},
        computer_use_enabled=False,
    )
    preflight = plan_task_preflight("최신 에이전트 트렌드 조사해줘", graph)
    ledger = EvidenceLedger(
        session_id="s-final", path=tmp_path / "evidence.jsonl", turn_id_provider=lambda: "turn-2"
    )
    # Historical names and failed rows remain records, not current-turn proof.
    ledger.append(
        kind="task_preflight",
        summary="Historical preflight",
        payload={"preflight": {"schema_version": 1, "required_evidence": ["source_url"]}},
        turn_id="turn-1",
    )
    ledger.append(
        kind="source_url",
        summary="Prior failed fetch",
        payload={"error": "fetch_failed"},
        turn_id="turn-1",
    )
    ledger.append_preflight(capability_graph=graph_summary(graph), preflight=preflight)
    prior_rows = read_jsonl(ledger.path)
    loop = SimpleNamespace(
        _evidence_ledger=ledger,
        _task_preflight=preflight,
        _timeline=MagicMock(),
        _save_checkpoint=MagicMock(),
    )
    result = AgenticResult(
        text="Unverified claim", rounds=1, termination_reason=termination_reason, error=error
    )
    verify_payload = {"passed": False, "rubric_misses": ["verification_error"]}

    _lifecycle._persist_final_result(loop, result, "조사해줘", 1, verify_payload)

    written = read_jsonl(ledger.path)
    assert written[:-1] == prior_rows
    assert written[-1]["kind"] == "final_result"
    assert written[-1]["turn_id"] == "turn-2"
    assert written[-1]["payload"] == {
        "termination_reason": termination_reason,
        "rounds": 1,
        "tool_count": 0,
        "error": error,
    }
    assert loop._timeline.record_turn_complete.call_args.kwargs["verify"] == verify_payload
    loop._save_checkpoint.assert_called_once_with("조사해줘", round_idx=1)
