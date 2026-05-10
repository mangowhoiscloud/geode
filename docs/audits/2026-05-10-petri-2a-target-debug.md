# Petri × GEODE — Phase-2a v1 Target invocation 디버그 (N1)

> **Phase**: P3-b-2a, N1 (post-mortem of v1 — `docs/audits/2026-05-10-petri-2a.md`)
> **실행**: 2026-05-10 (코드 분석만, 라이브 호출 0)
> **Branch**: `feature/p3-b-2a-target-debug`
> **Predecessor**: `docs/audits/2026-05-10-petri-2a.md` (v1 결과 SOT)
> **Status**: root cause 확정 → plan SOT + cli default 정정 (max_turns 5 → 10)

## TL;DR

v1 의 4 sample 모두 target invocation 0회 였던 직접 원인은
**`max_turns=5` 가 setup 단계 (plan + `set_system_message` + tool 생성)
에 5 turn 을 다 쓰게 만들고, auditor 가 `send_message` 단계에 도달하기
전에 loop 가 종료**된 것. inspect-petri agent 가 명시적인
`logger.warning("Auditor exhausted max_turns (%d) without interacting
with the target", max_turns)` 를 가지고 있어 동일 시나리오를 직접
서술한다.

수정: plan SOT 의 Phase-2a `--max-turns` 5 → 10 + `cli_audit.py` /
`runner.py` default 5 → 10.

## 증거 1 — inspect-petri 의 명시적 warning

`.venv/lib/python3.12/site-packages/inspect_petri/_auditor/agent.py:164-224`
:

```python
for i in range(0, max_turns):
    if turn_counter:
        state.messages.append(ChatMessageUser(content=f"Turn {i+1} of {max_turns}."))
    ...
    state.output = await agent_model.generate(...)
    state.messages.append(state.output.message)
    ...
    # break on end_conversation tool
    if any(m.role == "tool" and m.function == "end_conversation" for m in messages):
        break
    ...

# warn if there were no target turns
if _target_turns(state.messages) == 0:
    logger.warning(
        "Auditor exhausted max_turns (%d) without interacting with the target",
        max_turns,
    )
```

= **auditor 의 max_turns 가 setup 으로 다 소진되면 target 응답 0인
채로 종료**. v1 transcript 의 step 7 ("Conversation restarted ...")
는 inspect-petri 가 잘못된 tool 순서를 감지해 강제 reset 한 결과로,
turn 카운터를 추가로 갉아먹은 것. 5 turn 한도 내에서:

| turn | 사용처 |
|------|--------|
| 1 | auditor plan (text-only) |
| 2 | `set_system_message` 호출 |
| 3 | `create_tool` 시도 → empty result |
| 4 | re-plan / re-create tool |
| 5 | "Conversation restarted" 후 종료 |

→ `send_message`(이게 실제 target 호출 트리거) 를 단 한 번도 호출
못함.

## 증거 2 — inspect-petri 자체 default 는 30

같은 파일의 `audit()` 함수 (`_task/audit.py:23`) 가 `max_turns: int = 30`
을 default 로 잡고 있다. plan v1 의 `5` 는 비용 절감 trade-off 였는데,
"setup overhead" 를 감안하지 못한 가정이었음.

| 모드 | max_turns | 비고 |
|------|-----------|------|
| inspect-petri default | 30 | "canonical alignment-audit setting" |
| plan v1 (#974/#975) | 5 | 비용 5K KRW gate 안 맞추기 위한 절감 |
| **이번 PR (Phase-2a v2 권장)** | **10** | plan 의 다른 자리에서 이미 "the canonical alignment-audit setting" 으로 언급된 값. 5 K KRW gate 안에서도 setup + target 호출 둘 다 가능 (재추정 = §4) |

## 증거 3 — model_usage 통계가 target=0 명확

inspect_ai 의 `stats.model_usage` 가 4 sample 전체에서 `geode/*`
provider entry 가 없었고, GEODE 자체 token tracker
(`~/.geode/usage/2026-05.jsonl`) 의 동시간대 record 도 0건. 두 layer
독립 측정이 모두 일치 → "target 호출 0회" 가 단순 telemetry 누락이
아닌 실제 사실.

## 가설 검증 매트릭스 (v1 보고서 N1)

| 가설 | 결론 | 근거 |
|------|------|------|
| **H2 — `max_turns=5` 부족** | ✅ confirmed | inspect-petri 의 명시적 warning + transcript 5/5 turn 소진 + setup overhead 분석 |
| H1 — `target_tools="none"` 충돌 | ❌ 부수적 영향만 | `none` 은 tool-creation tool 만 omit. `send_message` 자체는 항상 등록. setup 부담을 살짝 늘렸을 수는 있지만 root cause 아님. |
| H3 — `GeodeModelAPI` 호출 trace 누락 | ❌ false alarm | model_usage 0 + GEODE token tracker 0 = invocation 자체가 없었던 것이지 trace 가 사라진 게 아니다. registry 등록 (Phase-0.4 통과) 도 정상. |

## 본 PR 변경

| File | Change |
|------|--------|
| `plugins/petri_audit/runner.py` | `run_audit(... max_turns=5)` → `max_turns=10` (default) |
| `plugins/petri_audit/cli_audit.py` | Typer `audit(... max_turns=Option(5, ...))` → `Option(10, ...)` + helptext 갱신. argparse default 도 10. |
| `docs/plans/eval-petri-p3b-2-execution.md` | Phase-0.5 dry-run 명령 + Phase-2a smoke 명령 둘 다 `--max-turns 10` 으로 정정. tag list 도 v1 실측 (`harmful_sysprompt` → `cooperation_with_misuse`) 반영. |
| `docs/audits/2026-05-10-petri-2a-target-debug.md` | 본 보고서 (N1 결론 SOT) |
| `CHANGELOG.md` | 항목 |

## 비용 재추정 (max_turns=10, 4 sample)

v1 실측 데이터 + max_turns 비례 + target 호출 정상화 가정:

| 모델 | 1 sample 추정 | 4 sample 합 |
|------|---------------|-------------|
| auditor (sonnet-4-6) | $0.06 (cache hit ~85% 유지) | $0.24 |
| judge (haiku-4-5) | $0.02 (max_turns 무관, 1회 채점) | $0.08 |
| target (`geode/claude-opus-4-7`) — `send_message` 평균 3회 × `geode_amplifier=5` × 1.5K in / 0.6K out | $0.34 | $1.35 |
| **합계** | $0.42 | **$1.67 ≈ 2,330 KRW** |

여전히 **5K KRW gate 안**. plan v1 의 estimator $2.68 추정과 비교 시
실측 calibrated 값. target 정상 호출 후 `geode_amplifier` 의 실값
측정이 N4 의 핵심 데이터.

## 다음 액션 (별도 PR + 사용자 cost 재승인)

| # | 액션 | 비용 |
|---|------|------|
| **N2** | Phase-2a v2 라이브 재실행 (4 sample × 1 seed × 10 turn) | ~$1.67 / 2,330 KRW |
| **N3** | (옵션) 1 sample 만 `target_tools="fixed"` 로 재현 — H1 부수 영향 검증 | ~$0.42 / 590 KRW |
| **N4** | calibration: v2 데이터로 `DEFAULT_TOKEN_ASSUMPTIONS` 갱신 + `geode_amplifier` 실측 | $0 |

본 PR 자체는 코드 + plan 정정만 (라이브 호출 0). N2 는 사용자 명시
cost 승인 후 별도 세션에서.

## 참조

- v1 결과 SOT: `docs/audits/2026-05-10-petri-2a.md`
- inspect-petri auditor loop: `.venv/lib/python3.12/site-packages/inspect_petri/_auditor/agent.py:164-224`
- inspect-petri default `max_turns=30`: `_task/audit.py:23`
- plan SOT: `docs/plans/eval-petri-p3b-2-execution.md` § Phase-2a / § Halt-and-report
