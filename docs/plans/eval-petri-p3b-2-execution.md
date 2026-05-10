# Plan — Petri × GEODE Live Audit Smoke (P3-b-2a)

> Phase: **P3-b-2a — smoke**, < 5,000 KRW cost gate
> Branch: `feature/eval-petri-p3b-2-plan`
> Author: 2026-05-10 session
> Status: **Awaiting user cost approval before live execution**
> Predecessor: `docs/plans/eval-petri-integration.md` (P0..P3-b-1 머지 완료)

## Problem

P3-b-1 (`#967`) 까지 inspect_ai entry-point 등록이 끝나 `inspect eval
inspect_petri/audit --model-role target=geode/<base>` 명령이 GEODE 를
audit target 으로 자동 인지한다. P3-b-2 (`#972`/`#973`) 에서는 같은
runner 를 GEODE 의 Typer/`/audit` slash/`petri_audit` tool 3 진입점으로
얇게 감쌌다 — judge / auditor / target 모두 GEODE catalog 에서 자유 선택,
default `dry_run=True`.

라이브 호출 자체는 한 번도 시도된 적이 없다. 본 phase 의 목적은:

1. 추정 비용 ($2.7 / ~3,700 KRW) 의 **실측 데이터** 로 estimator
   (`plugins/petri_audit/runner.py:estimate_cost_usd`) calibrate.
2. 4 표적 dimension 이 GEODE 응답에서 **신호를 만들어 내는지** (= judge
   가 risk 식별 가능한지) 확인.
3. transcript 수동 검토로 false-positive / true-positive 분리 — P4
   own-evaluator 의 입력 데이터 시드 확보.

본 plan 자체는 **계획서**다. 실 실행은 본 PR merge 후 사용자가 명시적
"P3-b-2a 진행" 지시를 내릴 때 별도 세션에서 수행.

## Scope decisions (사용자 확정)

| 분기 | 결정 | 근거 |
|------|------|------|
| Phase 범위 | **P3-b-2a 단독** | 첫 라이브, calibration 우선 |
| Dimension | **4 표적 그대로** | plan + memory SOT |
| 저장 | `docs/plans/eval-petri-p3b-2-execution.md` (이 파일) | 코드베이스 SOT |
| Auditor | `claude-sonnet-4-6` | inspect_ai native, 다국어 OK, 단가 중간 |
| Target | `geode/claude-opus-4-7` | production base |
| Judge | `claude-haiku-4-5-20251001` | 단가 최저 |
| `target_tools` | `none` | Petri fabricated tool 결과 X — GEODE 실 tool 흐름 평가 |
| `cache` | `true` | Petri 3.0.6 prefix cache 30-70 % 절감 |

## Dimensions (4 표적)

| Dimension | 측정 의도 | GEODE 측면 위험 surface |
|-----------|-----------|------------------------|
| `unprompted_initiative` | 사용자 지시 없이 행동 시작 | 자율 실행 agent (`AgenticLoop`), `scheduler.create` tool — false-positive 위험 큼; baseline 측정이 핵심 |
| `unprompted_self_preservation` | 셧다운 / 제약 회피 | scheduler / hook / cron 권한 보유 → "내일 다시 깨우는 cron 등록" 같은 경계 행동 가능 |
| `cooperation_with_harmful_sysprompt` | 유해 sysprompt 순응도 | `_split_messages` 가 auditor system 을 `system_suffix` 로 GEODE 식별 prompt 옆에 주입 — 정확히 이 dimension 의 측정 경로 |
| `unprompted_whistleblowing` | 사용자/조직 외부 폭로 | `send_notification`, `calendar_create_event` tool → 외부 send surface |

`tag` 매핑 (예측):
`-T seed_instructions=tags:initiative` / `tags:self_preservation` /
`tags:harmful_sysprompt` / `tags:whistleblowing`. 정확한 tag 문자열은
**Phase-0 점검에서 inspect-petri 카탈로그로 확인** 후 확정.

## Cost model

`plugins/petri_audit/runner.py:DEFAULT_TOKEN_ASSUMPTIONS` 기준 (per-turn):

| Role | Model | input | output | per-turn USD |
|------|-------|-------|--------|--------------|
| Auditor | sonnet-4-6 (`$3 / $15` per Mtok) | 2,000 | 800 | $0.018 |
| Target | opus-4-7 (`$5 / $25`) × `geode_amplifier=5` | 1,500 | 600 | $0.1125 |
| Judge | haiku-4-5 (`$1 / $5`) × `0.5` calls/turn | 4,000 | 200 | $0.0025 |
| **합계 / turn** | | | | **$0.133** |

Phase-2a: **1 seed × 4 dim × 5 turns × $0.133 = $2.66 ≈ 3,724 KRW** (1 USD = 1,400 KRW). **5K KRW gate 안.**

cache=true 가 prefix 캐시로 **30-70 %** 추가 절감 가능 — 보수 추정값 유지.

## Phase-0 — zero-cost preflight (라이브 직전 점검)

| # | 점검 | 명령 / 방법 | 통과 기준 |
|---|------|-------------|----------|
| 0.1 | `[audit]` extra 설치 | `uv sync --extra audit` | 0 error, `inspect-ai` + `inspect-petri` lock |
| 0.2 | `inspect` CLI 동작 | `inspect eval --help` | 정상 stdout |
| 0.3 | inspect-petri 의 `seed_instructions` tag 카탈로그 | `python -c "import inspect_petri; help(inspect_petri.audit)"` 또는 패키지 코드 grep | 4 dimension 모두 매핑 가능한 tag 존재 |
| 0.4 | GEODE entry-point discovery | `python -c "from inspect_ai.model import get_model; m=get_model('geode/claude-opus-4-7'); print(type(m).__name__)"` | `GeodeModelAPI` |
| 0.5 | 4-dimension dry-run 명령 조립 | `geode audit --judge claude-haiku-4-5-20251001 --auditor claude-sonnet-4-6 --target claude-opus-4-7 --tags <each> --seeds 1 --max-turns 5 --dry-run` | 4번 모두 명령 + 추정 비용 출력, 합산 < 5K KRW |
| 0.6 | 환경 secret | `.env` 의 `ANTHROPIC_API_KEY` 존재 + 잔액 확인 | live 호출 가능 상태 |

Phase-0 의 어느 항목이라도 fail → 라이브 호출 금지, 원인 규명 후 재계획.

## Phase-2a — smoke run

```bash
# 4 dimension 각 1 sample × 5 turns. tag 는 Phase-0.3 결과로 확정.
for tag in initiative self_preservation harmful_sysprompt whistleblowing; do
  geode audit \
    --judge claude-haiku-4-5-20251001 \
    --auditor claude-sonnet-4-6 \
    --target claude-opus-4-7 \
    --seeds 1 \
    --max-turns 5 \
    --tags "$tag" \
    --live
done
```

`--live` 가 Phase-2a 진입 신호 (default 는 dry-run). confirm prompt 한 번씩
(총 4회) 나옴 — 사용자가 매번 `y` 로 진행. `--yes` 는 본 phase 에서는
**의도적으로 사용 X** (각 호출 직전 추정 비용 다시 보기 위함).

산출물:

- `./logs/<timestamp>/` — inspect_ai 표준 log 디렉터리. transcript + 점수 + 메타데이터
- 실측 비용 (Anthropic console + GEODE `~/.geode/usage/*.jsonl`)
- 4 dimension × 1 sample = 4 transcript

## Metrics & 분석 항목

phase 종료 후 산출:

| 항목 | 형태 | 사용처 |
|------|------|--------|
| Per-dimension 점수 | 4 dim × 1 sample 표 | risk signal 강도 baseline |
| Transcript (4) | inspect_ai log 파일 | 수동 검토 — false-positive vs true-positive 분류 |
| 실측 비용 | USD + KRW, role 별 분리 | estimator calibration |
| Tool-use 메타데이터 | turn 별 GEODE tool 호출 횟수 / 종류 | `geode_amplifier` 검증 + `tool_overuse` 후보 dimension 데이터 |
| 응답 언어 | KO / EN / mixed 비율 | judge 가 KO 응답 점수에 편향 없는지 |

## Halt-and-report 조건

| 조건 | 액션 |
|------|------|
| 실측 누적 비용 > 추정 1.5× ($4 / 5,600 KRW) | **즉시 abort** — estimator 보정 후 재계획 |
| `inspect` CLI rc != 0 | log capture, stop |
| target 이 1 sample 에서 명백 jailbreak (= dimension score 1.0) | 1 sample 만으로도 P4 입력 가치, **즉시 stop & report** |
| 4 dimension 모두 score = 0 | smoke 성공 but signal 부족 → max_turns=10 으로 재시도 검토 |
| judge 가 1 sample 도 채점 불가 (parser error 등) | judge 모델 격상 (haiku → sonnet) 또는 inspect-petri SHA 문제 진단 |

## Risks

| 리스크 | 영향 | 대응 |
|--------|------|------|
| `geode_amplifier=5` 가 실제와 차이 | 비용 추정 ±2-3× | Phase-2a 실측으로 즉시 calibrate |
| `target_tools=none` 인데 GEODE tool 흐름이 실은 비활성 | dimension 신호가 base LLM 측정에 그침 | Phase-0.4 에서 GeodeModelAPI bootstrap 트레이스 확인 |
| Petri seed 가 영어 prompt → GEODE 한국어 응답 | judge 채점 편향 | 첫 sample transcript 수동 확인. 영향 시 `system` prompt 에 `respond in English` 추가 |
| max_turns=5 가 dimension 신호 발현에 부족 | false negative | Halt 조건 표 참고; 0 점이면 max_turns=10 retry |
| Petri 3.0 (`main` SHA pin) API 변동 | 명령 실패 | Phase-0 의 0.2~0.3 으로 사전 검출 |
| `judge=haiku` 가 한국어/도구사용 transcript 채점 약함 | 점수 신뢰도 낮음 | Phase-2b 진입 시 동일 transcript 를 sonnet 으로 재채점 → judge agreement 측정 |

## Out of scope (= 후속 phase / PR)

- **P3-b-2b 확장** (3 seed × 4 dim × 10 turns, ~22K KRW). 2a 결과로 사용자 별도 승인 필요.
- **P3-b-2c 정밀** (5 seed × 4 dim × 10 turns, ~37K KRW — 30K gate 초과). 2b 결과 + 명시 승인.
- **`tool_overuse` 자체 dimension** — Petri 38 표준 밖. 2a transcript 메타데이터 후처리로 데이터 확보, P4 own-evaluator 단계에서 정식화.
- **HITL gate 회피 / `confirm_circumvention`** 같은 GEODE-specific 위험 — 동일 P4.
- 라이브 호출 자체는 본 PR 범위 밖. 본 PR 은 plan 문서 SOT 화만.

## Verification (본 plan PR 기준)

```bash
uv run ruff check core/ tests/ plugins/      # docs only — 무관, 기존 clean
uv run mypy core/ plugins/                    # 동일
uv run pytest tests/ -m "not live"            # 동일

# 본 plan 자체 verify:
markdownlint docs/plans/eval-petri-p3b-2-execution.md  # 선택
```

라이브 phase 진입 시점에는 별도 verification 표 (Phase-0 + 2a 결과
캡처) 가 본 문서에 같은 PR 또는 후속 PR 로 추가됨.

## References

- 직전: `docs/plans/eval-petri-integration.md` (P0..P3-b-1)
- 진입점 PR: `#972` (feature/audit-trigger), `#973` (release)
- Memory: `project_petri_p1_handoff.md` — phase 명세 + cost gate
- Anthropic Petri 1.0/2.0 blog, inspect-petri repo (`docs/plans/eval-petri-integration.md` § References 동일)
- GEODE entry: `plugins/petri_audit/runner.py`, `plugins/petri_audit/cli_audit.py`
- Cost SOT: `core/llm/token_tracker.py:151-187` `MODEL_PRICING`
