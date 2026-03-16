"""Live audit runner — test tool handlers via AgenticLoop with real LLM.

Usage:
    python tests/_live_audit_runner.py <group>
    Groups: info, analysis, data, admin
"""

from __future__ import annotations

import io
import json
import os
import sys

os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_PROJECT", "geode")

from core.ui.console import console

console.file = io.StringIO()

from core.cli import _build_tool_handlers, _set_readiness  # noqa: E402
from core.cli.agentic_loop import AgenticLoop  # noqa: E402
from core.cli.conversation import ConversationContext  # noqa: E402
from core.cli.startup import check_readiness  # noqa: E402
from core.cli.tool_executor import ToolExecutor  # noqa: E402

readiness = check_readiness()
readiness.force_dry_run = True
readiness.has_api_key = True
_set_readiness(readiness)
_handlers = _build_tool_handlers(verbose=False)

GROUPS: dict[str, list[tuple[str, str]]] = {
    "info": [
        ("list_ips", "사용 가능한 IP 목록 보여줘"),
        ("search_ips", "다크 판타지 장르 IP 찾아줘"),
        ("show_help", "어떤 명령어를 사용할 수 있어?"),
        ("check_status", "시스템 상태 확인해줘"),
        ("switch_model", "모델을 앙상블 모드로 전환해줘"),
    ],
    "analysis": [
        ("analyze_ip", "Berserk IP 분석해줘"),
        ("compare_ips", "Berserk이랑 Cowboy Bebop 비교해줘"),
        ("generate_report", "Berserk 리포트 만들어줘"),
        ("batch_analyze", "상위 3개 IP 배치 분석해줘"),
    ],
    "data": [
        ("memory_search", "이전에 분석한 Berserk 기록 찾아줘"),
        ("memory_save", "Berserk은 S티어 IP라고 기억해줘"),
        ("manage_rule", "현재 분석 규칙 목록 보여줘"),
        ("generate_data", "테스트용 샘플 데이터 1개 생성해줘"),
    ],
    "admin": [
        ("set_api_key", "API 키 설정 상태 확인해줘"),
        ("manage_auth", "인증 프로필 목록 보여줘"),
        ("schedule_job", "스케줄 목록 보여줘"),
        ("trigger_event", "트리거 목록 보여줘"),
    ],
}


def run_case(expected_tool: str, prompt: str) -> dict:
    ctx = ConversationContext()
    executor = ToolExecutor(action_handlers=_handlers, auto_approve=True)
    loop = AgenticLoop(ctx, executor, max_rounds=4)
    r = loop.run(prompt)

    called = [tc["tool"] for tc in r.tool_calls]
    errors = [
        tc["tool"]
        for tc in r.tool_calls
        if isinstance(tc.get("result"), dict) and "error" in tc["result"]
    ]

    status = "PASS"
    issues = []

    if expected_tool not in called:
        status = "FAIL"
        issues.append(f"expected={expected_tool}, got={called}")
    if errors:
        issues.append(f"tool_errors={errors}")
        if status == "PASS":
            status = "WARN"
    if not r.text or len(r.text) < 10:
        status = "FAIL"
        issues.append("empty_text")
    if r.error:
        status = "FAIL"
        issues.append(f"error={r.error}")

    # Extract tool result data richness
    data_keys = []
    for tc in r.tool_calls:
        if isinstance(tc.get("result"), dict):
            data_keys = list(tc["result"].keys())
            break

    return {
        "tool": expected_tool,
        "status": status,
        "rounds": r.rounds,
        "called": called,
        "text_len": len(r.text),
        "text_preview": r.text[:150].replace("\n", " "),
        "data_keys": data_keys,
        "issues": issues,
    }


def main():
    group = sys.argv[1] if len(sys.argv) > 1 else "info"
    cases = GROUPS.get(group, [])
    print(f"[{group.upper()}] Running {len(cases)} cases...")

    results = []
    for i, (tool, prompt) in enumerate(cases):
        print(f"  [{i + 1}/{len(cases)}] {tool} ...", end=" ", flush=True)
        result = run_case(tool, prompt)
        print(result["status"])
        results.append(result)

    # Output JSON for collection
    print(f"\n--- {group.upper()} RESULTS ---")
    for r in results:
        mark = "✓" if r["status"] == "PASS" else "!" if r["status"] == "WARN" else "✗"
        issues_str = f" | {', '.join(r['issues'])}" if r["issues"] else ""
        print(
            f"  {mark} {r['tool']:20s} [{r['status']}] rounds={r['rounds']} called={r['called']} "
            f"keys={r['data_keys']} text={r['text_len']}{issues_str}"
        )
        print(f"    preview: {r['text_preview'][:120]}")

    # Write JSON for aggregation
    import tempfile

    out_path = os.path.join(tempfile.gettempdir(), f"geode_audit_{group}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
