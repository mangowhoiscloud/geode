# τ²-bench (Sierra)

## 개요

Multi-turn tool-agent-user 시뮬레이션 벤치. 에이전트와 LLM 시뮬 유저가 공유 world state를 tool로 변경하며 대화. **pass^k의 발상지**.

- **Repo**: [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench) — 1.1k★
- **마지막 commit**: 2026-05-05 (live submissions PR, 매주 갱신)
- **라이센스**: 확인 필요 (Apache-2.0 추정)
- **버전 히스토리**: v1 NeurIPS '24 → v² 2025 (telecom dual-control) → v0.2.0 2025-10-06 (web leaderboard) → v0.2.1 2025-11 (RL support). τ³(banking+voice)은 paper만, 코드 미공개
- **Frontier 인용**: GPT-5.5 system card (**telecom 98.0%**), Anthropic 인용

## 사례

### Case 1 — Sierra가 발견한 user-simulator drift (NeurIPS '24 → v² 2025)

원래 τ-bench는 GPT-4o를 user simulator로 사용. SOTA GPT-4o 자체가 retail에서 ~61%, airline에서 ~35%. Sierra autopsy 결과 **점수 분산의 절반이 simulator 모델 선택에서 옴**. v²의 telecom dual-control 도메인은 agent와 user가 같은 world state를 함께 변경하게 만들어 이 문제를 차단.

출처: [τ-bench paper](https://arxiv.org/pdf/2406.12045), [τ²-bench paper](https://arxiv.org/pdf/2506.07982)

### Case 2 — Telecom 리더보드 역전 — Z.ai GLM-4.7-Flash 1위

[Artificial Analysis tau²-bench](https://artificialanalysis.ai/evaluations/tau2-bench) (2026-05 기준):
- **Z.ai GLM-4.7-Flash (Reasoning) 98.8%**
- GLM 5V Turbo / GLM-5-Turbo 98.5%
- GPT-5.x, Opus 4.x는 telecom에서 더 낮음

Sierra 분석: telecom은 **patient diagnostic dialog**를 보상 — Chinese reasoning model이 tool call 전 long step-by-step plan을 emit하기 때문에 이김. **공격적 tool-caller는 telecom에서 손해**라는 교훈.

### Case 3 — HAL Generalist + Claude 3.7 Sonnet — airline 1위 56% / $42

[HAL tau-bench airline](https://hal.cs.princeton.edu/taubench_airline) Pareto:
- **HAL Generalist + Sonnet 3.7**: 56% / $42.11
- **o4-mini High**: 56% / $11.36
- TAU-bench Tool Calling baseline + Opus 4.1: 50% / $69.78

교훈: **얇은 generalist scaffold가 hand-tuned tool-calling loop을 이김**. "Opus에 더 쓰기"는 reliability 안 사줌. airline은 50-56%가 천장 — 50대 후반에 정체.

## 필요 Eval 인프라

| 항목 | 값 |
|---|---|
| Install | `git clone … && uv sync` (텍스트 only) / `uv sync --all-extras` (voice+banking) |
| macOS extras | `brew install portaudio ffmpeg` (voice 옵션) |
| Python | `>=3.12,<3.14` |
| Sandbox | **순수 Python in-process** — Docker 불필요 |
| Scoring | Pydantic world state diff (oracle) — LLM judge 미사용 |
| Trace | `results/<run_id>/` JSONL (메시지+tool call+task reward) |
| External | LLM keys (LiteLLM). User simulator 모델 명시 필수 — leaderboard는 v0.2.0부터 **`gpt-4.1` 고정** |
| Cost — smoke | 5-task airline @ Sonnet 4.5 ≈ **<$3** |
| Cost — full | 4-domain × 4 trial @ Sonnet 4.5 ≈ **$200-400** |
| CI 적합도 | 5-task smoke GHA 가능 (~10-15분), full은 VM |

### Agent Contract

[`src/tau2/agent/README.md`](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/agent/README.md):

```python
class HalfDuplexAgent:
    def __init__(self, tools, domain_policy): ...
    def get_init_state(self, message_history) -> StateType: ...
    def generate_next_message(
        self, message, state
    ) -> tuple[AssistantMessage, StateType]: ...

def create_agent(tools, domain_policy, **kwargs) -> HalfDuplexAgent: ...
```

`LLMAgent`는 reference impl이지 강제 base 아님. `tools`는 domain tool registry, `domain_policy`는 system prompt prefix.

## GEODE 진행 시나리오

### Phase 0 — Smoke (≤30분, cost <$1)

```bash
tau2 run --domain mock --agent-llm <ours> --num-tasks 1 --num-trials 1
```

`mock` 도메인은 LLM cost 거의 없이 `core/agent/loop.py::AgenticLoop` 와이어업만 검증.

**Pass criteria**: results/ 폴더에 JSONL 생성, agent contract 호출 trace 확인.

### Phase 1 — PoC 어댑터 (~6-10시간)

신규 파일:
- `eval/tau2/__init__.py`
- `eval/tau2/adapter.py` — `class GeodeTau2Agent(HalfDuplexAgent)`
- `eval/tau2/factory.py` — `create_agent()` factory
- `eval/tau2/README.md` — 실행 방법

매핑:
- `generate_next_message(message, state)` → 한 번의 `AgenticLoop.step()`
- `tools` constructor 인자 → GEODE tool registry에 wrap (LangGraph tool node 형태)
- `domain_policy` → AgenticLoop system prompt prefix
- `state` → AgenticLoop의 conversation state를 Pydantic으로 직렬화

### Phase 2 — First Real Run

- **대상**: telecom 24 tasks × 1 trial × **Sonnet 4.5**
- **선정 사유**: dual-control 도메인이 Slack/MCP execution path에 가장 가까움
- **예상 baseline**: **35-45% pass^1** (비특화 scaffold 평균치 기준)
- **예상 cost**: $25-40
- **출력 보관**: `artifacts/eval/tau2/<date>/`

### Phase 3 — CI / 운영 Ratchet

| 트리거 | 실행 | 임계 | 비용 |
|---|---|---|---|
| Per-PR | airline 5-task smoke | pass^1 −3pp → 차단 | <$3 |
| Weekly (develop) | 4-domain × 1 trial | telecom −3pp → Slack 알림 | ~$50 |
| Monthly (main) | telecom × 4 trial pass^k | pass^4 −5pp → release block | ~$80 |

선정 사유: telecom = GEODE Slack-ops day job에 가장 근접.

## 참고

- [τ-bench paper (NeurIPS '24)](https://arxiv.org/pdf/2406.12045)
- [τ²-Bench paper](https://arxiv.org/pdf/2506.07982)
- [GitHub repo](https://github.com/sierra-research/tau2-bench)
- [Live leaderboard](https://taubench.com/)
- [Artificial Analysis mirror](https://artificialanalysis.ai/evaluations/tau2-bench)
- [HAL airline dashboard (cost-aware)](https://hal.cs.princeton.edu/taubench_airline)
