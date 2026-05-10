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

## Reporting & Visualization

Phase-2a 결과 시각화 — `./logs/<timestamp>/*.eval` (inspect_ai 표준 log) 에서 직접 추출.

**도표 5종**:

| # | 도표 | x / y / encoding | 산출 위치 |
|---|------|-------------------|-----------|
| 1 | Per-dimension score heatmap | 4 dim × 1 sample (Phase-2a) → 4 dim × 3 sample (2b) → 4 dim × 5 sample (2c) | `./reports/<phase>/heatmap.png` (matplotlib) + `.html` (inspect_viz) |
| 2 | Cost breakdown stacked bar | x=phase, y=KRW, color=role(auditor/target/judge) | `./reports/<phase>/cost.png`. 5K/30K KRW gate 가로선 |
| 3 | Tool-use frequency histogram | x=GEODE tool name, y=호출 횟수, facet=dimension | `./reports/<phase>/tool_freq.png`. `geode_amplifier` 실측 도출 입력 |
| 4 | Judge agreement scatter | x=judge_haiku score, y=judge_sonnet score, color=dimension | `./reports/<phase>/agreement.html` (plotly). Phase-2b 진입 후만 |
| 5 | Phase 추이 line | x=phase(2a→2b→2c), y=평균 score, line=dimension | `./reports/trend.png`. Phase 누적 후 갱신 |

**라이브러리 채택** (license + cold-start + inspect_ai 궁합 기준 — `Petri eval ecosystem research` 결과):

| 우선 | 라이브러리 | License | 역할 | 비고 |
|------|-----------|---------|------|------|
| **P1** | `inspect_viz` ([meridianlabs-ai/inspect_viz](https://meridianlabs-ai.github.io/inspect_viz/)) | OSS (확인 필요) | inspect_ai eval log 직접 link, `scores_by_task()` / `sample_tool_calls()` 네이티브 | jupyter widget 의존 — CLI 단독 환경에서는 P2 fallback |
| **P2** | `matplotlib` + `seaborn` | PSF / BSD-3 | 정적 PNG/SVG (heatmap, cost stacked bar, tool histogram). cold-start 영향 적음 | numpy/pandas 위에서 동작 — 이미 의존성 |
| **P3** | `plotly` | MIT | 인터랙티브 HTML 1-file (judge agreement, trend) — P4 own-evaluator 대시보드용 | `kaleido` static export 옵션 |

3 라이브러리 모두 본 PR 의존성 추가 X. P3-b-2a 라이브 실행 직전 별도 PR 로 `[viz]` optional extra 추가 (`uv sync --extra viz`) — `[audit]` 패턴 동일.

**보고 산출물** (각 phase 종료 후 PR):

```
./reports/<phase>/
├── heatmap.png                  (matplotlib)
├── heatmap.html                 (inspect_viz, jupyter render)
├── cost.png                     (matplotlib + 5K/30K gate hline)
├── tool_freq.png                (matplotlib facet)
├── agreement.html               (plotly, 2b+ only)
└── summary.md                   (수동 작성: top-3 finding + 다음 phase 진입 결정)
```

`docs/audits/<date>-petri-<phase>.md` 가 SOT, `./reports/` 는 raw 데이터.

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

## Future tooling — Library candidates (P4 own-evaluator)

본 phase (P3-b-2a) 의 직접 dependency 는 inspect_ai + inspect_petri 만.
아래는 **P4 own-evaluator** 단계로 가면서 GEODE 가 흡수할 수 있는 외부
라이브러리 카탈로그. 본 PR 은 카탈로그 SOT 화만 — 실제 의존성 추가 / 툴
등록은 P4 진입 시 별도 Socratic Gate 통과 후.

### Observability — agentic 행동 instrumentation (LangSmith 대체)

v0.89.0 에서 LangSmith 의존성을 제거하고 GEODE hook 58 events 자체
RunLog 로 전환했음. 외부 instrumentation 을 다시 도입할 경우 OTel
표준 + Apache-2.0 / MIT 만:

| 라이브러리 | License | Self-host | Anthropic SDK | GEODE hook 결합 |
|-----------|---------|-----------|---------------|------------------|
| **OpenLLMetry** ([traceloop/openllmetry](https://github.com/traceloop/openllmetry)) | Apache-2.0 | OTLP backend 자유 | 공식 `Anthropic` instrumentation | 가장 가벼움. `pre_llm_call` / `post_llm_call` hook 에서 OTel span emit. RunLog 와 dual-export 가능 |
| **Langfuse** ([langfuse/langfuse](https://github.com/langfuse/langfuse)) | MIT (`ee/` 폴더 별도 라이선스 주의) | docker-compose | `opentelemetry-instrumentation-anthropic` | `/api/public/otel` endpoint 로 OTLP. 한 번 띄우면 trace UI 풍부 |
| **AgentOps** ([AgentOps-AI/agentops](https://github.com/AgentOps-AI/agentops)) | MIT | Yes | Anthropic SDK ≥0.32 | Time-Travel Debugging — Petri rollout 재현용 |
| **Phoenix (Arize)** | **Elastic License 2.0** (특허/SaaS 재판매 제약) | Docker Hub | `openinference-instrumentation-anthropic` | OSS 지만 ELv2. self-host 는 OK, 라이선스 표기 필수 → **4순위** |

**추천**: P4 진입 시 OpenLLMetry 1순위 — OTel 표준 만족 → GEODE 자체
RunLog 와 충돌 없이 dual-export, LangSmith 같은 vendor lock-in 회피.

### Reasoning engineering — Petri smoke 결과 → GEODE prompt 자동 개선

| 라이브러리 | License | 정의 | Petri 입력 호환 | Anthropic Claude |
|-----------|---------|------|-----------------|------------------|
| **DSPy 3.1.2** ([dspy.ai](https://dspy.ai/)) | MIT | "compiler" — bootstrap few-shot + metric 기반 prompt pipeline 최적화 | **Petri sample score → metric fn** → `BootstrapFewShot` 으로 system prompt 재컴파일 | `anthropic/claude-sonnet-4-*` 1급 시민 |
| **TextGrad** ([zou-group/textgrad](https://github.com/zou-group/textgrad)) | MIT | "autograd for text" — LLM feedback 을 textual gradient 로 prompt/code 역전파 (Nature 2024) | Petri judge rationale 을 직접 gradient 로 활용 | LiteLLM 경유 (Claude 명시 안 됐으나 LiteLLM provider 통해 가능) |
| **Instructor** ([jxnl/instructor](https://github.com/jxnl/instructor)) | MIT | Pydantic 기반 reliable JSON | Petri judge JSON schema 검증/재시도 | `instructor.from_provider("anthropic/claude-3-5-sonnet")` 직접 지원 |
| **Outlines** ([dottxt-ai/outlines](https://github.com/dottxt-ai/outlines)) | Apache-2.0 | constrained decoding (JSON/regex/CFG) | judge JSON 안정화 | **Claude 미명시** (OpenAI/Gemini/vLLM/Ollama). GEODE judge 에는 부적합 |
| **Mirascope** ([Mirascope/mirascope](https://github.com/Mirascope/mirascope)) | MIT | "anti-framework" 통합 LLM 인터페이스 — 자체 prompt opt 기능은 없음 | 간접 (구조적 호출 표준화) | `anthropic/claude-sonnet-4-5` 명시 |

**추천**: P4 의 핵심 자동화 루프 = **DSPy** (metric → optimizer 경로 가장 짧음) + **Instructor** (judge JSON 안정성). TextGrad 는 LiteLLM 통해 Claude 호출 검증 후 추가.

#### D 단계 (DSPy + TextGrad + Instructor) 도입 전 위험 카탈로그

> **Status**: D 진입 전 SOT. **3 mitigation (M1+M2+M4) 가 진입 전제 조건**.
> Source: 외부 리서치 (논문 / 프론티어 OSS / 테크블로그 19종, 본 섹션 끝
> References).

D 단계의 메타-loop (agent 가 자기 prompt 수정 → 자기 평가 → 다시 수정)
은 frontier 시스템에서 **실 관측된** 발산 사례가 있어, 도입 전 카탈로그
화. 5 영역 위험 (R1..R5) + 10 mitigation (M1..M10).

**R1. Recursive Self-Improvement 안전성**

| 위험 | 사례 | 출처 |
|------|------|------|
| Self-modification of constraints | Sakana AI Scientist v1 — script 가 자기 자신을 system call 로 호출하여 무한 self-recursion. timeout 한도 도달 시 **timeout 코드 자체를 늘림** | [arXiv 2502.14297](https://arxiv.org/abs/2502.14297), [findggle.com 2025-04](https://findggle.com/blog/2025/04/20/ai-system-self-modifying-sakana-ai/) |
| In-context reward hacking | judge=generator 동일 컨텍스트에서 self-refinement loop 가 reward hacking 증폭. "smaller models are more likely to cause in-context reward hacking" | [Lilian Weng "Reward Hacking in RL" Nov 2024](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/) |
| Catastrophic Goodhart | heavy-tailed reward misspecification 에서 **KL-divergence regularization 도 Goodharting 방지 못함** | [FAR.AI](https://www.far.ai/research/catastrophic-goodhart-regularizing-rlhf-with-kl-divergence-does-not-mitigate-heavy-tailed-reward-misspecification) |
| RLHF 가 정확도 X 설득력 향상 | "increases human approval, but not necessarily correctness" — incorrect 출력을 더 설득력 있게 | Lilian Weng 동상 |
| LM Arena goodharting (2025-04) | Llama 4 LM Arena 점수 급상승의 원인으로 metric gaming 의심 | Synthesis AI 보고 |

**R2. DSPy 컴파일 비용 / metric 신뢰성**

| 항목 | 측정값 | 출처 |
|------|--------|------|
| GPT-3.5 공식 사례 | 6 분 / 3,200 API calls / 2.7M input + 156K output token / **$3** | [DSPy FAQ](https://dspy.ai/faqs/) |
| 권장 비용 범위 | "few cents ~ tens of dollars" / 평균 **~$2 + 10 분** | DSPy 공식 docs |
| Claude Sonnet 환산 | 컴파일 1회 ≈ **$5-15** | 우리 추정 (sonnet 단가 ÷ gpt-3.5 비율) |
| 데이터셋 권장량 | <10 → BootstrapFewShot, ≥50 → BootstrapFewShotWithRandomSearch | DSPy docs |
| 재현성 위기 | LLM 일반 70% 실패, agentic tool-call signature determinism **56.8%** | [typedef.ai 2025](https://www.typedef.ai/resources/non-deterministic-model-handling-statistics) |
| 컴파일 산출물 영속화 | `cot_compiled.save(...)` — 권장 패턴 | DSPy FAQ |

**R3. TextGrad gradient 발산 / judge bias 전파**

| 실패 모드 | 양상 | 출처 |
|-----------|------|------|
| Exploding textual gradient | depth 5 에서 token 2K → **32K 폭발**, context limit 초과 | [arXiv 2601.21064 (TEP)](https://arxiv.org/html/2601.21064) |
| Vanishing gradient | "fix undefined variable on line X" → "improve code quality" 로 specificity 손실 | TEP 동상 |
| Judge bias 누적 | "small judgement error in downstream node compounds as backpropagated upstream" | TEP 동상 |
| Length bias (verbosity) | LLM judge 가 **일관되게 긴 응답 선호** → prompt 가 점점 verbose | [arXiv 2406.07791](https://arxiv.org/html/2406.07791v7) |
| Self-preference bias | LLM 이 자기 출력 선호 → "diagonal pattern in evaluation matrices" | Lilian Weng 2024 |
| Sycophancy 전파 | judge 가 동의 답 선호 → gradient 가 sycophancy 강화 방향으로 prompt 편집 | aclanthology 2025.findings-emnlp.121 |

**R4. 프론티어 OSS 메타-loop 가드 (공통 패턴)**

| 시스템 | 가드 패턴 | 출처 |
|--------|----------|------|
| Claude Code Auto Mode | 위험 행동 (파일 삭제, secret 유출) flag-and-block. HITL middle-ground | [techbuzz.ai 2025](https://www.techbuzz.ai/articles/anthropic-launches-auto-mode-safety-guardrails-for-claude-code) |
| GitHub Copilot agent PR | Copilot PR 을 **untrusted fork** 처리 — 수동 approval 필수, bypass 설정 없음 | github community 167493 |
| Sakana AI Scientist | Sandboxed exec + Resource limits + Code change verification (HITL) + Continuous monitoring | sakana.ai blog |
| Cursor enterprise | LLM safety controls — read-only DB, scoped actions | cursor.com docs |
| Anthropic "Building Effective Agents" | Contextual boundary + confidence threshold escalation + drift detection + rate limiting | [resources.anthropic.com](https://resources.anthropic.com/building-effective-ai-agents) |
| **공통 4-패턴** | (1) Artifact Verification (HITL before destructive) (2) Context Rotation (3) Privilege Boundaries (4) Rate Limiting | Galileo AI guardrails framework |

**R5. Instructor retry storm**

| 항목 | 권장 / 실측 | 출처 |
|------|------------|------|
| `max_retries` 권장 | **1-2** (jangwook 2026 실측: "complex nested schemas trigger 3-5 retries in the wild") | [jangwook.net 2026](https://jangwook.net/en/blog/en/python-ai-agent-library-comparison-2026/) |
| retry 메커니즘 | validation error 를 messages 에 append 하여 재호출 → token 누적 | useinstructor.com docs |
| 비용 폭주 트리거 | 깊은 nested Pydantic + 엄격한 validator 조합 | jangwook.net 동상 |
| fallback 패턴 | max 도달 후 **단순 schema 또는 raw text 로 graceful degrade** | 동상 |

##### Mitigation 카탈로그 (M1..M10) — D 진입 전 잠금

| # | Mitigation | 차단 위험 | 메커니즘 | 비용 |
|---|-----------|----------|---------|------|
| **M1 (전제)** | Judge ≠ Generator family 강제 (judge=Claude, generator=GPT 등 cross-family) | R1 in-context reward hacking, R3 self-preference | config 에서 동일 family 시 fail-fast | 0 |
| **M2 (전제)** | PR-only auto-edit — 컴파일 산출물은 git branch+PR 로만 적용, **auto-merge 금지** | R1 self-modification, R4 frontier 공통 | `compile()` → write `optimized_prompts/branch-XXX.json` → PR 생성 | 0 |
| **M3** | 컴파일 빈도 cap — 주 1회 / **누적 $50/월 hard limit** | R2 비용 폭주, R1 metric gaming | budget tracker + daily metric, 초과 시 halt | 절감 |
| **M4 (전제)** | TextGrad **depth=1 강제** (chained gradient 금지) | R3 exploding/vanishing | wrapper 에서 depth>1 reject | 코드 1 guard |
| **M5** | Judge rationale token cap (≤2K) + length-normalized score | R3 length bias, exploding | rationale truncate + score/len penalty | 0 |
| **M6** | Rollback 자동화 — 컴파일 후 hold-out set 점수가 baseline 의 **95% 미만** 이면 자동 revert | R1 divergence, R2 컴파일 실패 | nightly eval gate + git revert | hold-out eval 비용 |
| **M7** | Instructor `max_retries=2` + flat schema (1-level nesting까지) + raw-text fallback | R5 retry storm | Pydantic 모델 제약 + 실패 시 unstructured fallback | cap |
| **M8** | Judge bias suite (length / sycophancy / position) **주간 측정** → 임계 초과 시 컴파일 정지 | R3 judge bias 전파 | 주간 bias probe | 주 ~$5 |
| **M9** | Compile artifact diff review (HITL) — system prompt diff **30% 이상이면 사람 승인 필수** | R1 drift detection (Anthropic 패턴) | diff% 측정 → threshold gate | 0 |
| **M10** | Seed 고정 + `compile_id` 메타데이터 (재현성) | R2 non-determinism, 70% 재현성 실패 | `compile_id={timestamp, judge_model, seed, dataset_hash}` 기록 + save() | 0 |

##### D 진입 전제 조건 (잠금)

**M1 + M2 + M4 통과 없이 D 단계 진입 금지.**

- M1 — judge model ≠ generator model family. config 검증 fail-fast.
- M2 — `eval_dspy_optimize` tool 의 산출물은 항상 git branch + PR. auto-merge 차단 (CODEOWNERS 또는 branch protection).
- M4 — TextGrad wrapper 에서 `depth > 1` 또는 `chained=True` 호출은
  `ValueError` raise.

이 3개는 frontier (Anthropic Claude Code Auto Mode + GitHub Copilot
agent PR + Sakana sandbox) 의 공통 가드와 정합. 나머지 7개 (M3, M5-M10)
는 D 진입 후 점진 도입 — P4 ratchet 의 자연스러운 확장.

##### 적용 SOT

D 단계 PR 의 Socratic Gate Q5 (3+ frontier 동일 패턴) 응답에 본 섹션을
인용. tool 등록 description 의 "리스크" 컬럼도 본 섹션 (R1..R5) 와
mitigation (M1..M10) 을 참조하는 짧은 라벨로 갱신.

### Self-monitoring — agent 자기 차단 / self-critique

| 라이브러리 | License | 정의 | Petri 4-dim 1차 검사 |
|-----------|---------|------|------------------------|
| **NeMo Guardrails** ([NVIDIA-NeMo/Guardrails](https://github.com/NVIDIA-NeMo/Guardrails)) | Apache-2.0 | input/dialog/retrieval/execution/output 5-rail + LLM self-check | `cooperation_with_harmful_sysprompt` (input rail), `unprompted_initiative` (dialog rail). **Anthropic Claude 명시 미지원** → LiteLLM 우회 또는 직접 wrapper |
| **Guardrails AI** ([guardrails-ai/guardrails](https://github.com/guardrails-ai/guardrails)) | Apache-2.0 | Validator hub (24+) — toxicity, PII, competitor | `unprompted_self_preservation` (output validator) |
| **LLM Guard** | MIT | input/output scanner — prompt injection, toxicity, PII | `cooperation_with_harmful_sysprompt` (prompt injection scanner) |
| **smolagents (HF)** | Apache-2.0 | agentic loop + E2B/Docker/WASM sandbox (LocalPythonExecutor 는 보안 경계 아님 명시) | `unprompted_initiative` (sandbox-bounded action) |
| **Constitutional AI 패턴** | (Anthropic 논문) | self-critique → revise loop | `unprompted_whistleblowing` (over-action 억제) — 라이브러리 X, 직접 구현 |

**추천**: `unprompted_whistleblowing` 은 self-critique 로만 정밀 잡힘 →
**Constitutional AI revise** 를 GEODE `core/agent/approval.py` HITL
흐름과 결합한 자체 구현이 1순위. NeMo/Guardrails-AI 는 input rail 보강용.

### `core/tools/definitions.json` 신규 tool 후보 (P4)

| Tool name | cost_tier | category | 효용 | 리스크 |
|-----------|-----------|----------|------|--------|
| `eval_petri_run` | expensive | `evaluation` | inspect_ai + petri 라이브 audit 자동 트리거 — agent 가 자기 audit 호출 | 비용 폭주 → KRW gate + dry-run 필수. 본 PR 의 `petri_audit` tool 과 차이는 **agent 가 P4 자율 평가 루프에서 호출** vs 사용자 명시 트리거 |
| `eval_dspy_optimize` | expensive | `evaluation` | Petri smoke 결과 → system prompt 자동 재컴파일 (BootstrapFewShot) | **메타-loop** (agent 가 자기 prompt 수정). 진입 전제 = **M1 (judge≠generator family) + M2 (PR-only) + M4 (TextGrad depth=1)** 통과. 상세는 § "D 단계 도입 전 위험 카탈로그" R1-R5 / M1-M10 |
| `safety_guardrail_scan` | cheap | **`safety` (신규 카테고리)** | NeMo/Guardrails-AI input/output rail 로 tool 호출 전후 스크리닝 | rail 룰 false-positive 시 정상 동작 차단. tunable rail 필요 |
| `obs_otel_export` | free | **`observability` (신규 카테고리)** | OpenLLMetry/Langfuse OTLP exporter — hook → OTel span | endpoint 미설정 시 silent drop. Wiring Verification 룰 (Read-Write parity) 적용 필수 |
| `eval_inspect_viz` | free | `evaluation` | eval log → HTML/PNG 리포트 자동 생성. Slack 보고서 첨부 | jupyter widget 의존 → cold-start 무거움, lazy import 필수 |

`eval_petri_run` + `eval_dspy_optimize` + `safety_guardrail_scan` 3종이
**자기 평가 → 자기 개선 → 자기 차단** 루프의 핵심. P4 own-evaluator
설계 의 입력. 등록 시 Socratic Gate Q5 (3+ frontier 동일 패턴) 충족
근거: DSPy + Petri + NeMo 모두 별도 frontier 시스템 검증 패턴.

신규 카테고리 (`safety`, `observability`) 는 P4 진입 PR 에서 `core/tools/base.py:VALID_CATEGORIES` 추가.

### 라이브러리 도입 비용 (lock-in / cold-start / 의존성)

| 라이브러리 | optional extra | cold-start 영향 | 의존성 충돌 위험 |
|-----------|---------------|-----------------|------------------|
| OpenLLMetry | `[obs]` | 가벼움 (OTel SDK 만) | 낮음 |
| Langfuse | `[obs-langfuse]` | 중간 (HTTP 클라이언트) | 낮음 |
| DSPy | `[reason]` | **무거움** (수많은 LM provider stub) | LiteLLM 경유 시 우리 router 와 중복 |
| Instructor | `[reason]` | 가벼움 | 낮음 (Pydantic 위) |
| inspect_viz | `[viz]` | **무거움** (jupyter widget) | 낮음 |
| matplotlib | `[viz]` | 가벼움 (이미 numpy/pandas 의존) | 낮음 |
| NeMo Guardrails | `[safety]` | 무거움 (rule engine) | LangChain 의존 — v0.89.0 에서 제거 방향과 충돌 |
| Guardrails AI | `[safety]` | 중간 | 낮음 |

**도입 정책**: 모두 optional extra (`uv sync --extra <name>`) 로 격리 —
default `uv sync` cold-start 무영향. v0.89.x ratchet (cold-start 240→33ms,
−86%) 보호.

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
- 본 plan SOT 화 PR: `#974` (smoke 계획), `#975` (release)
- Memory: `project_petri_p1_handoff.md` — phase 명세 + cost gate
- Anthropic Petri 1.0/2.0 blog, inspect-petri repo (`docs/plans/eval-petri-integration.md` § References 동일)
- GEODE entry: `plugins/petri_audit/runner.py`, `plugins/petri_audit/cli_audit.py`
- Cost SOT: `core/llm/token_tracker.py:151-187` `MODEL_PRICING`

### Future tooling references

- inspect_viz: <https://meridianlabs-ai.github.io/inspect_viz/index.html>
- OpenLLMetry: <https://github.com/traceloop/openllmetry> (Apache-2.0)
- Langfuse: <https://github.com/langfuse/langfuse> (MIT, ee/ 별도)
- AgentOps: <https://github.com/AgentOps-AI/agentops> (MIT)
- Phoenix (Arize): <https://github.com/Arize-ai/phoenix> (Elastic License 2.0 — 표기 필요)
- DSPy: <https://dspy.ai/> (MIT)
- TextGrad: <https://github.com/zou-group/textgrad> (MIT)
- Mirascope: <https://github.com/Mirascope/mirascope> (MIT)
- Instructor: <https://github.com/jxnl/instructor> (MIT)
- Outlines: <https://github.com/dottxt-ai/outlines> (Apache-2.0)
- NeMo Guardrails: <https://github.com/NVIDIA-NeMo/Guardrails> (Apache-2.0)
- Guardrails AI: <https://github.com/guardrails-ai/guardrails> (Apache-2.0)
- smolagents (HF): <https://github.com/huggingface/smolagents> (Apache-2.0)
- Langfuse Anthropic 통합: <https://langfuse.com/integrations/model-providers/anthropic>

### D 단계 위험 카탈로그 — 외부 인용 (R1..R5)

#### R1. Recursive Self-Improvement 안전성

- Sakana AI Scientist v1 self-modification: <https://arxiv.org/abs/2502.14297> (arXiv 2502.14297)
- Sakana 사례 보고: <https://findggle.com/blog/2025/04/20/ai-system-self-modifying-sakana-ai/>
- Sakana 공식: <https://sakana.ai/ai-scientist/>
- Lilian Weng "Reward Hacking in RL" (Nov 2024): <https://lilianweng.github.io/posts/2024-11-28-reward-hacking/>
- FAR.AI Catastrophic Goodhart: <https://www.far.ai/research/catastrophic-goodhart-regularizing-rlhf-with-kl-divergence-does-not-mitigate-heavy-tailed-reward-misspecification>

#### R2. DSPy 컴파일 비용 / metric 신뢰성

- DSPy FAQ (compile cost / save pattern): <https://dspy.ai/faqs/>
- DSPy 원논문 (arXiv 2310.03714): <https://arxiv.org/pdf/2310.03714>
- Haystack DSPy cookbook (deepset): <https://haystack.deepset.ai/cookbook/prompt_optimization_with_dspy>
- LLM 재현성 위기 (typedef.ai 2025): <https://www.typedef.ai/resources/non-deterministic-model-handling-statistics>

#### R3. TextGrad gradient 발산 / judge bias

- TextGrad 원논문 (Nature 2024 / arXiv 2406.07496): <https://arxiv.org/html/2406.07496v1>
- Textual Equilibrium Propagation (arXiv 2601.21064): <https://arxiv.org/html/2601.21064>
- Position bias study (arXiv 2406.07791): <https://arxiv.org/html/2406.07791v7>
- LLM-as-judge bias 정량 (12 유형): <https://llm-judge-bias.github.io/>

#### R4. 프론티어 OSS 메타-loop 가드

- Anthropic Claude Code Auto Mode: <https://www.techbuzz.ai/articles/anthropic-launches-auto-mode-safety-guardrails-for-claude-code>
- Anthropic "Building Effective AI Agents": <https://resources.anthropic.com/building-effective-ai-agents>
- Cursor LLM Safety: <https://cursor.com/docs/enterprise/llm-safety-and-controls>
- Galileo AI Agent Guardrails Framework: <https://galileo.ai/blog/ai-agent-guardrails-framework>

#### R5. Instructor retry storm

- Python AI Agent Library Comparison 2026 (jangwook.net): <https://jangwook.net/en/blog/en/python-ai-agent-library-comparison-2026/>
- Instructor reask validation: <https://python.useinstructor.com/concepts/reask_validation/>
- Instructor repo: <https://github.com/jxnl/instructor>
