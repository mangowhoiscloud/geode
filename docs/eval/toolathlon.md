# Toolathlon (HKUST, ICLR 2026)

## 개요

108(+1) long-horizon 태스크 × **32 real apps** × **604 MCP tools**, 평균 20 tool turn. GEODE 시나리오에 가장 가까움 (Slack/Notion/Calendar/GitHub/BigQuery 등 실제 SaaS).

- **Repo**: [hkust-nlp/Toolathlon](https://github.com/hkust-nlp/Toolathlon) — 343★
- **마지막 commit**: 2026-04-28
- **Paper**: [arXiv 2510.25726](https://arxiv.org/abs/2510.25726), **ICLR 2026 채택** ([OpenReview](https://openreview.net/forum?id=z53s5p0qhf))
- **라이센스**: 확인 필요
- **현재 SOTA**: Claude-4.5-Sonnet **38.6%** — headroom 큼

## 사례

### Case 1 — Claude 4.5 Sonnet SOTA 38.6% (20.2 tool turn 평균)

[Xiang Yue 발표](https://x.com/xiangyue96/status/1983945639026368771) + [arXiv 2510.25726](https://arxiv.org/abs/2510.25726):
- **Claude 4.5 Sonnet**: 38.6% / 20.2 turns
- DeepSeek-V3.2-Exp (best open-weights): 20.1%

Failure mode 클러스터 (paper):
1. **Navigation error** — 잘못된 app 선택
2. **Tool-chain breakage** — call 사이 state 잃어버림
3. **State management drift** — 누적 컨텍스트 오염
4. **Format misinterpretation** — MCP schema 오해

→ 38.6%가 SOTA라는 건 **20-turn 시퀀스가 아무도 안 풀린다**는 뜻. GEODE처럼 진짜 SaaS 자동화하는 agent에 가장 의미 있는 신호.

### Case 2 — Decoupled agent loop = scaffold ablation 가능

Toolathlon은 [decoupled agent loop mode](https://github.com/hkust-nlp/Toolathlon)를 지원해서 host loop을 갈아끼울 수 있음:
- Default: monkey-patched `openai-agents-sdk`
- Alternative: Anthropic 공식 `claude_agent_sdk`

repo의 trajectory에 `claude-4.5-opus`, `gpt-5.1`, `gemini-3-pro`, `deepseek-v3.2-thinking` — 같은 task를 다른 scaffold/model로 diff 가능. **Sierra가 τ²에서 발견한 simulator drift 문제를 명시적으로 측정 가능**한 구조.

### Case 3 — Canvas / WooCommerce / BigQuery cross-app 태스크의 실패

[`tasks/finalpool/`](https://github.com/hkust-nlp/Toolathlon/tree/main/tasks/finalpool) (109 task):
- `canvas-do-quiz`, `canvas-art-quiz` — **모든 모델이 실패**: agent가 `submit_quiz`와 `start_quiz` MCP tool semantic을 conflate
- WooCommerce + BigQuery cross-app — Claude가 1위인데 단순히 tool name disambiguation이 더 나아서

→ MCP tool 네이밍이 점수에 직접 영향. GEODE `geode serve`의 MCP client가 이런 semantic ambiguity를 어떻게 다루는지 검증할 수 있음.

## 필요 Eval 인프라

| 항목 | 값 |
|---|---|
| Install | `bash global_preparation/install_env_minimal.sh true` 후 `bash global_preparation/pull_toolathlon_image.sh` |
| Docker image | `lockon0927/toolathlon-task-image:1016beta` |
| Python | 3.12 (uv toolchain) |
| Sandbox | **per-task Docker** (또는 Podman). 컨테이너명 `toolathlon-<task>-<timestamp>` |
| Mount | workspace dump + logs + **docker.sock** (agent가 nested container spawn — k8s.yaml MCP server 등) |
| Scoring | `TaskEvaluator.evaluate_from_log_file()` — `evaluation/` 스크립트가 post-task state에 실행 → `eval_stats.json` |
| Trace | `dumps/<model>/<task>/` (LLM chat history + MCP call/response + verdict + cost) |
| External — 32 MCP server | 12306, arxiv-latex-mcp, arxiv_local, **canvas, emails, excel, filesystem, git, github, google-cloud, google_calendar, google_forms, google_map, google_sheet**, howtocook, huggingface, k8s, **memory, notion, notion_official**, npx-fetch, pdf-tools, playwright_with_chunk, pptx, scholarly_search, snowflake, **terminal, time, wandb, woocommerce, word**, yahoo-finance, youtube, youtube_transcript |
| 실제 credential 필요 | Notion, Canvas, Google Calendar/Sheet/Forms/Maps/Cloud, GitHub, WooCommerce, Snowflake, BigQuery, W&B, HuggingFace (`how2register_accounts.md` 참조) |
| LLM key | `TOOLATHLON_OPENAI_API_KEY` + `TOOLATHLON_OPENAI_BASE_URL` (LiteLLM 호환) |
| Cost — smoke | 1 task `cooking-guidance` (howtocook MCP만) ≈ **<$1** |
| Cost — full | 108 task × 20.2 turn × Sonnet ≈ **$80-200** LLM + 외부 API quota 별도 (smoke run으로 bound 필요) |
| CI 적합도 | **VM only** — Docker + 32 MCP + real APIs는 GHA 불가. smoke는 GHA-Docker 가능 |

### 실행 명령 예시

```bash
uv run main.py \
  --eval_config scripts/formal_run_v0.json \
  --task_dir tasks/finalpool/canvas-do-quiz \
  --max_steps_under_single_turn_mode 30 \
  --model_short_name claude-sonnet-4.5 \
  --provider anthropic
```

## GEODE 진행 시나리오

### Phase 0 — Smoke (≤30분, cost <$1)

```bash
bash scripts/run_single_containerized.sh \
  tasks/finalpool/cooking-guidance \
  smoke \
  ./dumps_smoke/geode \
  anthropic/claude-sonnet-4.5
```

`howtocook` MCP만 사용 — 외부 credential 불필요. 컨테이너 + MCP plumbing 검증.

### Phase 1 — PoC 어댑터 (~16-24시간 — 4종 중 가장 무거움)

두 경로:

**(a) Host-mode** — `core/agent/loop.py::AgenticLoop`을 Toolathlon decoupled agent loop API에 plug
- 신규: `eval/toolathlon/geode_loop.py` — `claude_agent_sdk` entry shape mimic
- 장점: 깔끔, `core/`에 영향 적음
- **권장 — Phase 1은 (a)**

**(b) MCP-client mode** — Toolathlon MCP server들을 GEODE의 기존 `geode serve` MCP client로 repoint
- 장점: production path 그대로 검증
- 단점: `geode serve` 운영 영향, credentialing 두 군데로 분산

Phase 1 = (a), Phase 4 (별도) = (b) 검토.

### Phase 2 — First Real Run

- **대상**: 15-task subset, GEODE의 기존 MCP integration과 겹치는 것:
  - `google_calendar`, `notion`, `github`, `filesystem`, `terminal`, `time`, `memory`, `emails` 위주
- **모델**: Sonnet 4.5
- **예상 baseline**: **15-25% pass** (long-horizon multi-app은 GEODE 약점)
- **예상 cost**: **$15-30 LLM + 무료 tier 외부 API**
- **출력 보관**: `artifacts/eval/toolathlon/<date>/`

### Phase 3 — CI / 운영 Ratchet

| 트리거 | 실행 | 임계 |
|---|---|---|
| Per-PR | 1-task `cooking-guidance` smoke | smoke fail → 차단 (<$1) |
| Monthly (전용 VM, real creds) | 109-task full | 15-task subset −5pp → 차단 |
| Quarterly | 109-task × 3 trial pass^k | reliability 추적 |

HAL Reliability와 페어링: Toolathlon은 accuracy + headroom, HAL은 consistency.

## 참고

- [GitHub repo](https://github.com/hkust-nlp/Toolathlon)
- [arXiv paper](https://arxiv.org/abs/2510.25726)
- [ICLR 2026 OpenReview](https://openreview.net/forum?id=z53s5p0qhf)
- [Xiang Yue 발표 (X)](https://x.com/xiangyue96/status/1983945639026368771)
- [tasks/finalpool 디렉토리](https://github.com/hkust-nlp/Toolathlon/tree/main/tasks/finalpool)
- [configs/mcp_servers (32개)](https://github.com/hkust-nlp/Toolathlon/tree/main/configs/mcp_servers)
