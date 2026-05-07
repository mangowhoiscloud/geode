# HAL Reliability (Princeton, ICLR 2026)

## 개요

벤치마크가 아니라 **벤치 위에 얹는 reliability layer**. GAIA + tau-bench airline 등 9개 underlying bench를 다중 rerun 해서 **consistency / robustness / safety / predictability / self-awareness** 5개 차원 산출. Princeton이 2025-10부로 **신규 모델 accuracy 등록을 일시 중단**하고 reliability에만 집중.

- **Repo**: [princeton-pli/hal-harness](https://github.com/princeton-pli/hal-harness) — 274★
- **Paper**: [arXiv 2510.11977](https://arxiv.org/pdf/2510.11977), **ICLR 2026 채택**
- **Dashboard**: [hal.cs.princeton.edu/reliability/](https://hal.cs.princeton.edu/reliability/)
- **라이센스**: 확인 필요 (LICENSE 파일 없음 — Princeton 학계 디폴트 = All Rights Reserved 가능성, 로컬 실행은 OK)
- **검증 규모**: 21,730 rollout × 9 모델 × 9 bench / $40K / 2.5B token (paper)

## 사례

### Case 1 — GAIA에서 Reliability ≠ Accuracy

[HAL GAIA Reliability dashboard](https://hal.cs.princeton.edu/reliability/benchmark/gaia/):

| 모델 | Accuracy | Consistency | Robustness |
|---|---|---|---|
| Claude Sonnet 4.5 | **74.7%** (1위) | 0.63 | 0.69 |
| Claude Opus 4.5 | 71.5% | **0.67** | — |
| Gemini 2.5 Pro | 50.1% | — | **0.74** (1위) |

→ Sonnet 4.5의 GAIA 헤드라인 숫자만 보고 ship하면 **brittle한 걸 ship**하는 셈. Opus가 정확도 낮은데 consistency 더 높음. HAL의 thesis = "stop chasing accuracy alone."

### Case 2 — Tau-bench airline cost-aware Pareto

[HAL airline](https://hal.cs.princeton.edu/taubench_airline) Pareto 선정 모델: **o4-mini High, DeepSeek V3, Gemini 2.0 Flash High**. Claude Opus 4.1은 정확도 비슷한데 **$69-180/run**이라 frontier 밖.

→ HAL은 **이 리스트 4종 중 유일하게 cost-per-task를 1급 컬럼으로 publish**. `accuracy@k$`가 `accuracy@1`보다 ship 결정에 더 유용함을 데이터로 보여줌.

### Case 3 — Princeton이 신규 모델 등록을 멈춤

Airline dashboard footer: "the HAL team has paused updating with new models" — reliability 메트릭에 집중. **이 분야에서 가장 강한 시그널**: accuracy on N benches가 plateau, 가치는 *how* models fail로 이동. Paper가 5개 차원을 formally 정의 + 9 bench(GAIA, AssistantBench, CORE-Bench Hard, Online Mind2Web, SciCode, ScienceAgentBench, **SWE-bench Verified Mini**, **TAU-bench Airline**, USACO)에 적용.

## 필요 Eval 인프라

| 항목 | 값 |
|---|---|
| Install | `conda create -n hal python=3.12 && conda activate hal && pip install -e .` |
| Python | 3.12 |
| 실행 모드 | (a) **local Python**, (b) **Azure VM** (subscription ID + resource group + NSG + SSH key) |
| Inspect AI 통합 | `-I` 플래그 |
| Sandbox | HAL 자체는 underlying bench로 shell out — bench 자체의 sandbox에 의존 |
| Scoring | HAL은 score 안 함 — underlying bench가 함. HAL은 trajectory를 **post-process**해서 5 reliability 메트릭 산출 |
| 5개 차원 | consistency (rerun 분산), predictability (self-assessment 편차), robustness (perturbation 후 perf), safety (jailbreak/PII), self-awareness (calibration) — 각 [0,1] normalize |
| External | LLM API key. tau-bench airline는 추가 cred 불필요 (모두 simulated) |
| Cost — smoke | 2-task tau-bench airline single-rerun on gpt-4o-mini ≈ **<$2** |
| Cost — Reliability run | underlying bench cost × N rerun. **5-rerun consistency = 5×**. tau-bench airline @ $11-$42/run × 5 = **$55-210**. GAIA @ ~$30 × 5 = **~$150** |
| Trace | per-rerun trajectory JSON + `reliability_report.json` (5 차원 + cost) |
| CI 적합도 | full reliability는 GHA 불가. tau-bench airline subset single-rerun은 GHA 가능 |

### Agent Contract

`agents/<your_agent>/main.py`:

```python
def run(input: dict[str, dict], **kwargs) -> dict[str, dict]:
    # input:  {task_id: task_config}
    # kwargs: {"model_name": "...", optional "reasoning_effort": "..."}
    return {
        task_id: {
            "reward": float,
            "taken_actions": [...],
            "task": {...},
        }
    }
```

CLI 등록: `--agent_function main.run`. Reference: [`agents/taubench_example_agent/main.py`](https://github.com/princeton-pli/hal-harness/tree/main/agents/taubench_example_agent).

### 실행 명령 예시

```bash
hal-eval \
  --benchmark taubench_airline \
  --agent_dir agents/geode_taubench \
  --agent_function main.run \
  --agent_name "geode-sonnet-4.5" \
  -A model_name=claude-sonnet-4.5 \
  --num_runs 5
```

## GEODE 진행 시나리오

> **의존성**: τ²-bench Phase 1 어댑터를 먼저 끝내면 HAL의 tau-bench airline 부분은 그대로 재사용 가능 → **HAL 작업이 가장 가벼워짐 (~6-8h)**.

### Phase 0 — Smoke (≤20분, cost <$2)

```bash
hal-eval --benchmark taubench_airline \
  --agent_dir agents/taubench_example_agent \
  --agent_function main.run \
  --agent_name "smoke" \
  -A model_name=gpt-4o-mini \
  --max_tasks 2 --num_runs 1
```

HAL CLI + report shape 검증, GEODE infra에서 conda env 설치 확인.

### Phase 1 — PoC 어댑터 (~6-8시간, τ² Phase 1 재사용)

신규 파일:
- `eval/hal/agents/geode_taubench/main.py` — `run(input, **kwargs)` 가 τ² Phase 1 어댑터를 wrap
- `eval/hal/agents/geode_taubench/requirements.txt` — uv 외부 의존
- (옵션) `eval/hal/agents/geode_gaia/main.py` — GAIA용 별도 어댑터 (research/QA 측정 시)

매핑 (tau-bench airline):
- HAL의 `input` dict → tau-bench env params
- HAL의 `model_name` kwarg → AgenticLoop LLM 선택
- 반환의 `reward` → tau-bench oracle state-diff 결과

### Phase 2 — First Real Run

- **대상**: tau-bench airline **10-task × 3 rerun on Sonnet 4.5**
- **선정 사유**: 가장 저렴한 signal-rich Reliability 숫자, GEODE의 action-execution path와 직결
- **예상 출력**:
  - accuracy 35-50% (Sonnet 4.5의 다른 bench 추세 기준)
  - consistency 0.55-0.65
  - cost-per-task: $1-4
- **예상 cost**: **$30-60**
- **출력 보관**: `artifacts/eval/hal/<date>/reliability_report.json`

### Phase 3 — CI / 운영 Ratchet

> **HAL의 역할 = ratchet의 reliability 축**. τ²(accuracy) + Toolathlon(long-horizon) + HAL(reliability) 3축 trio.

| 트리거 | 실행 | 임계 |
|---|---|---|
| Monthly (main, VM) | 5-rerun on tau-bench airline + GAIA subset | accuracy −3pp **OR** consistency −0.05 **OR** robustness −0.05 → release block |
| Quarterly | 5-rerun on 4종 bench (airline, GAIA, AssistantBench, USACO subset) | 베이스라인 갱신 |

이게 잡는 regression: "더 eager한 tool-caller로 한 trial은 이기는데 oscillate하는" — 순수 accuracy bench가 못 잡는 패턴.

## 참고

- [HAL paper (arXiv 2510.11977)](https://arxiv.org/pdf/2510.11977)
- [HAL Reliability dashboard](https://hal.cs.princeton.edu/reliability/)
- [GAIA Reliability](https://hal.cs.princeton.edu/reliability/benchmark/gaia/)
- [Tau-bench airline (cost-aware)](https://hal.cs.princeton.edu/taubench_airline)
- [hal-harness GitHub](https://github.com/princeton-pli/hal-harness)
- [Reference agent (taubench_example_agent)](https://github.com/princeton-pli/hal-harness/tree/main/agents/taubench_example_agent)
