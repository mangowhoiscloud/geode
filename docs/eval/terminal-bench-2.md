# Terminal-Bench 2.0 (Stanford + Laude Institute)

## 개요

89개의 manually verified 터미널 태스크. Docker 컨테이너 안의 tmux 세션을 에이전트가 직접 조작 → post-run pytest로 검증. v1의 reward-hack 가능 태스크들을 솎아내고 큐레이션.

- **Repo**: [laude-institute/terminal-bench](https://github.com/laude-institute/terminal-bench) — 2.1k★
- **Leaderboard**: [tbench.ai/leaderboard/terminal-bench/2.0](https://www.tbench.ai/leaderboard/terminal-bench/2.0) — 2026-04-23 갱신, 124 entries
- **Frontier 인용**: **GPT-5.5 system card 82.7%**, Opus 4.7 발표글
- **라이센스**: Apache-2.0

## 사례

### Case 1 — Forge Code + Gemini 3.1 Pro — 78.4% 1위

[Morph LLM 2.0 mirror](https://www.morphllm.com/terminal-bench-2):
- **Forge Code + Gemini 3.1 Pro**: 78.4% (±1.8)
- Factory Droid + GPT-5.3-Codex: 77.3%

Forge가 이긴 이유: **tool error 발생할 때마다 aggressive re-plan**. 모델의 plan을 stream으로 끝까지 따르는 대신, 에러마다 plan을 다시 그림. 21-22%의 천장은 Linux kernel-level work (`build-linux-kernel`은 source patch + qemu 필요), FastText 정확도 타깃 등.

### Case 2 — Terminus-KIRA가 모델을 평준화

Stanford reference scaffold "Terminus-KIRA":
- + Claude Opus 4.6 = **74.7%** (±2.6)
- + Gemini 3.1 Pro = **74.8%** (±??)

같은 scaffold가 다른 frontier 모델로도 **동일한 점수** → [Snorkel 분석](https://snorkel.ai/blog/terminal-bench-2-0-raising-the-bar-for-ai-agent-evaluation/) thesis: **모델은 baseline 위에서 거의 fungible, scaffold가 lever**. 이게 GEODE가 자체 scaffold를 제출하는 가장 강한 동기.

### Case 3 — Danau5tin RL fine-tune + v1의 게임된 태스크 제거

[terminal-bench-rl](https://github.com/Danau5tin/terminal-bench-rl): 32×H100 GRPO로 Qwen3 fine-tune하여 **v1 top open-weights** 달성 — 벤치가 RL-optimizable임을 입증.

반례: v1의 "Hello World" 디버깅 태스크는 frontier 모델이 verifier를 game할 수 있어서 2.0에서 **제거**. 2.0의 89개 태스크 큐레이션 기준 = "agent가 일을 안 하고 패턴 매칭으로 풀 수 없어야 함."

## 필요 Eval 인프라

| 항목 | 값 |
|---|---|
| Install | `uv tool install terminal-bench` 또는 `pip install terminal-bench` |
| 전제 조건 | **Docker daemon 실행 중** |
| Python | 3.10+ (uv-managed, 3.12 권장) |
| Sandbox | **per-task Docker** (`tasks/<id>/Dockerfile`) + tmux 세션 attach |
| 동시성 | `--n-concurrent 8` 등 |
| Scoring | `tasks/<id>/tests/test_outputs.py` pytest — 순수 execution-based, LLM judge 없음 |
| Trace | `logs/<id>/agent.log`, full tmux scrollback, test verdict JSON |
| External | LLM API keys (built-in agent 사용 시: `claude_code`/`codex`/`gemini_cli` 등은 해당 CLI를 subprocess로 호출) |
| Cost — smoke | 3-task on Sonnet ≈ **<$5** |
| Cost — full | 89-task on Sonnet ≈ **$30-80** / Opus ≈ **$150-400** |
| CI 적합도 | full은 **VM only** (Docker + 5-20분/task). smoke는 GHA-Docker 가능 |

### Agent Contract

[`base_agent.py`](https://github.com/laude-institute/terminal-bench/blob/main/terminal_bench/agents/base_agent.py):

```python
class BaseAgent(ABC):
    @staticmethod
    @abstractmethod
    def name() -> str: ...

    @abstractmethod
    def perform_task(
        self,
        instruction: str,
        session: TmuxSession,
        logging_dir: Path | None = None,
    ) -> AgentResult: ...
```

에이전트는 라이브 `TmuxSession`을 받아서 **keystroke를 직접 type**. 검증은 harness가 컨테이너 안에서 test 명령 실행. 즉 **structured tool call이 아니라 raw keystroke stream**이 surface.

내장 에이전트: `aider`, `claude_code`, `codex`, `cursor_cli`, `gemini_cli`, `goose`, `grok_cli`, `mini_swe_agent`, `opencode`, `openhands`, `qwen_code`.

## GEODE 진행 시나리오

### Phase 0 — Smoke (≤15분, LLM cost 0)

```bash
tb run --agent oracle --task-ids hello-world --n-concurrent 1
```

Oracle agent는 정답 솔루션을 사용 → Docker + harness + tmux가 GEODE 빌드 머신에서 동작하는지만 검증.

**Pass criteria**: container build 성공, oracle pass 1/1, logs 생성.

### Phase 1 — PoC 어댑터 (~8-12시간)

신규 파일:
- `eval/terminal_bench/geode_agent.py` — `class GeodeTerminalAgent(BaseAgent)`
- `core/agent/tools/tmux_tool.py` — **`TmuxToolAdapter` 신규** (raw keystroke를 GEODE tool registry에 등록)
- `eval/terminal_bench/README.md`

핵심 어려움: GEODE는 structured tool call 모델로 설계됨, 그런데 tmux는 raw stream → `TmuxToolAdapter`가 `send_keys` / `read_screen`을 GEODE tool로 노출. Loop 자체는 건드리지 말고 tool layer에서 해결.

매핑:
- `instruction` → `geode serve` MCP path 입력
- `TmuxSession.send_keys` → `TmuxToolAdapter.send` (GEODE tool 호출)
- `TmuxSession.capture_pane` → `TmuxToolAdapter.read`
- 종료 조건: AgenticLoop가 자체 종료 또는 timeout

### Phase 2 — First Real Run

- **대상**: 12-task `system-administration` 서브셋 (Linux kernel + git-webserver class) on **Sonnet 4.5**
- **선정 사유**: GEODE `geode serve` 운영 프로필에 가장 근접
- **예상 baseline**: **30-45%** (frontier 75%보다 한참 낮음 — GEODE 루프가 tmux native 아니라서)
- **예상 cost**: $8-15
- **출력 보관**: `artifacts/eval/terminal_bench/<date>/`

### Phase 3 — CI / 운영 Ratchet

| 트리거 | 실행 | 임계 |
|---|---|---|
| Per-PR | 3-task oracle smoke (LLM 미사용) | smoke fail → 차단 |
| Weekly (develop nightly VM) | system-administration 12-task | 서브셋 −5pp → 차단 |
| Quarterly | 89-task full | 베이스라인 업데이트 |

서브셋이 50% 넘으면 89개 전체로 확장.

## 참고

- [GitHub repo](https://github.com/laude-institute/terminal-bench)
- [Leaderboard 2.0](https://www.tbench.ai/leaderboard/terminal-bench/2.0)
- [Snorkel 2.0 blog](https://snorkel.ai/blog/terminal-bench-2-0-raising-the-bar-for-ai-agent-evaluation/)
- [Morph LLM mirror](https://www.morphllm.com/terminal-bench-2)
- [terminal-bench-rl (Danau5tin)](https://github.com/Danau5tin/terminal-bench-rl)
- [GPT-5.5 system card](https://openai.com/index/gpt-5-5-system-card/)
- [Opus 4.7 launch](https://www.anthropic.com/news/claude-opus-4-7)
