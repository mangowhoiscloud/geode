from __future__ import annotations

import inspect

from core.agent.capability_graph import build_capability_graph, graph_summary, supported_features
from core.agent.evidence_ledger import EvidenceLedger
from core.agent.loop import _response, agent_loop
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
    assert "source_url" in preflight["required_evidence"]
    assert "gui_trajectory" in preflight["required_evidence"]
    assert "computer_use" in render_preflight_hint(preflight)


def test_evidence_ledger_redacts_and_hashes_payload(tmp_path) -> None:
    ledger = EvidenceLedger(session_id="s-test", path=tmp_path / "evidence.jsonl")

    row = ledger.append(
        kind="tool_result",
        summary="Sensitive row",
        payload={"token": "secret-token", "nested": {"text": "typed password"}},
    )

    assert row["payload"]["token"].startswith("<redacted:length=")
    assert row["payload"]["nested"]["text"].startswith("<redacted:length=")
    assert row["seq"] == 1
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


def test_agentic_loop_wires_preflight_and_capability_refresh() -> None:
    arun_src = inspect.getsource(agent_loop.AgenticLoop.arun)
    helper_src = inspect.getsource(agent_loop.AgenticLoop._prepare_task_preflight)
    refresh_src = inspect.getsource(_response.refresh_tools)

    assert "_prepare_task_preflight" in arun_src
    assert "plan_task_preflight" in helper_src
    assert "append_preflight" in helper_src
    assert "render_preflight_hint" in helper_src
    assert "build_capability_graph" in refresh_src
