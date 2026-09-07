"""Keep the landing projection bounded by its pinned public evidence."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "site/src/data/geode/landing-evidence.json"


def test_landing_sources_are_immutable_and_digest_bound() -> None:
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert data["presentationOnly"] is True
    for name, commit in (
        ("paired", "c52872aacd20a4b9f14be18d64acce3e9ed99070"),
        ("astra", "a32abcbf78ab6100ea1e85540a2ace9436dc6f76"),
    ):
        run = data[name]
        assert run["commit"] == commit
        for source_name, source in run["sources"].items():
            url = urlsplit(source["url"])
            assert url.scheme == "https" and url.netloc == "github.com"
            assert url.path.startswith(f"/mangowhoiscloud/geode-eval-artifacts/blob/{commit}/")
            assert run["runId"] in url.path
            assert not url.query and not url.fragment
            assert re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
            if source_name != "video":
                assert source["pointers"]
                assert all(pointer.startswith("/") for pointer in source["pointers"])
    assert data["paired"]["sources"]["data"]["sha256"] == (
        "00d3b61303127f48aec4cc694281ff42a49a8ffa9d023fc429ce362fe3233fa4"
    )
    assert "/exact_common_cell_comparison" in data["paired"]["sources"]["data"]["pointers"]
    assert data["astra"]["sources"]["trajectory"]["sha256"] == (
        "4ef6b0e15e6f1db7ec7d4903560ce7c46f4a5ad62278f59cf329e30e3e442dde"
    )
    assert data["astra"]["sources"]["trajectory"]["pointers"] == [
        "/events",
        "/outcome",
        "/integrity",
    ]
    assert data["astra"]["sources"]["verifier"]["pointers"] == ["/results/summary"]


def test_paired_counts_preserve_common_denominator_and_inconclusive_primary() -> None:
    paired = json.loads(EVIDENCE.read_text(encoding="utf-8"))["paired"]
    for key in (
        "frozenTasks",
        "includedTasks",
        "repetitions",
        "frozenTrialsPerArm",
        "commonTrials",
        "geodePasses",
        "nativePasses",
        "unresolvedNativeTrials",
    ):
        assert type(paired[key]) is int and paired[key] > 0
    assert paired["model"] == "gpt-5.6-sol" and paired["reasoning"] == "max"
    assert (paired["geodePasses"], paired["nativePasses"], paired["commonTrials"]) == (
        339,
        331,
        429,
    )
    assert paired["frozenTrialsPerArm"] == paired["frozenTasks"] * paired["repetitions"] == 445
    assert paired["includedTasks"] + len(paired["excludedTasks"]) == paired["frozenTasks"]
    assert (
        paired["commonTrials"] + paired["unresolvedNativeTrials"]
        == paired["includedTasks"] * paired["repetitions"]
    )
    rates = [paired[key] / paired["commonTrials"] * 100 for key in ("geodePasses", "nativePasses")]
    assert [round(rate, 2) for rate in rates] == [79.02, 77.16]
    assert round(rates[0] - rates[1], 2) == 1.86
    assert round(paired["taskBalancedDeltaPp"], 2) == 1.26
    assert [round(bound, 2) for bound in paired["taskBootstrap95Pp"]] == [-5.40, 8.05]
    assert paired["taskBootstrap95Pp"][0] < 0 < paired["taskBootstrap95Pp"][1]
    assert paired["primaryStatus"] == "not-measurable"
    assert paired["decision"] == "inconclusive"
    assert paired["officialSubmissionEligible"] is False
    assert paired["geodeRevision"] == "b549f3e448f06c75db45df6082013dc21a611dec"
    assert paired["dataset"] == "terminal-bench/terminal-bench-2-1@6"
    assert paired["datasetDigest"] == (
        "sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a"
    )


def test_terminal_bench_page_uses_shared_paired_evidence_before_astra_smoke() -> None:
    page = (ROOT / "site/src/app/docs/benchmarks/terminal-bench/page.tsx").read_text()
    assert 'import evidence from "@/data/geode/landing-evidence.json"' in page
    assert page.index('id="terminal-bench-result"') < page.index("{astra.model}")
    assert "paired.geodePasses" in page and "paired.nativePasses" in page
    assert "paired.commonTrials" in page and "paired.frozenTrialsPerArm" in page
    assert "paired.taskBootstrap95Pp" in page and "intervalPosition(0)" in page
    assert "[-10, -5, 0, 5, 10]" in page
    paired = json.loads(EVIDENCE.read_text())["paired"]
    lower, upper = paired["taskBootstrap95Pp"]
    assert -10 <= lower < paired["taskBalancedDeltaPp"] < upper <= 10
    assert "not simultaneous starts" in page
    assert "not-measurable" in page and "inconclusive" in page


def test_astra_metadata_preserves_sequence_pairing_and_payload_boundary() -> None:
    astra = json.loads(EVIDENCE.read_text(encoding="utf-8"))["astra"]
    trace = astra["trace"]
    events = trace["events"]
    for key in (
        "taskCount",
        "repetitions",
        "passedTrials",
        "selectedTrials",
        "verifierPassed",
        "verifierTotal",
        "rounds",
        "toolCalls",
        "toolResults",
        "orphanCalls",
        "orphanResults",
        "retries",
        "fallbacks",
        "inputTokens",
        "outputTokens",
        "cachedTokens",
    ):
        assert type(astra[key]) is int and astra[key] >= 0
    assert astra["model"] == "gpt-6-astra" and astra["reasoning"] == "high"
    assert (
        astra["passedTrials"]
        == astra["selectedTrials"]
        == astra["repetitions"]
        == astra["taskCount"]
        == 1
    )
    assert astra["verifierPassed"] == astra["verifierTotal"] == 6
    assert astra["rounds"] == 3 and astra["termination"] == "natural"
    assert astra["retries"] == astra["fallbacks"] == 0
    assert astra["promotionAuthority"] == "none"
    assert trace["scopeComplete"] is True and trace["replayComplete"] is False
    assert len(events) == trace["eventCount"] == 12
    assert [event["ordinal"] for event in events] == list(range(1, 13))
    assert [event["kind"] for event in events] == [
        "session.started",
        "message.user",
        "preflight.recorded",
        "tool.called",
        "tool.completed",
        "tool.called",
        "tool.completed",
        "verification.decided",
        "message.assistant",
        "usage.recorded",
        "turn.completed",
        "session.ended",
    ]
    times = [datetime.fromisoformat(event["occurredAt"]) for event in events]
    assert all(time.tzinfo is not None for time in times)
    assert times == sorted(times)
    allowed = {
        "ordinal",
        "occurredAt",
        "kind",
        "actor",
        "status",
        "tool",
        "callId",
        "payloadOmitted",
    }
    assert all(set(event) <= allowed for event in events)
    assert all(type(event["payloadOmitted"]) is bool for event in events)
    assert sum(event["payloadOmitted"] for event in events) == trace["omittedPayloadCount"] == 9
    calls = [event for event in events if event["kind"] == "tool.called"]
    results = [event for event in events if event["kind"] == "tool.completed"]
    assert len(calls) == astra["toolCalls"] == len(results) == astra["toolResults"] == 2
    assert len({event["callId"] for event in calls}) == 2
    assert [event["callId"] for event in calls] == [event["callId"] for event in results]
    assert all(
        event["tool"] == "terminal_exec" and event["payloadOmitted"] for event in calls + results
    )
    assert all(event["status"] == "ok" for event in results)
    assert astra["orphanCalls"] == astra["orphanResults"] == 0
    assert events[7]["actor"] == "policy" and events[7]["status"] == "accept"
