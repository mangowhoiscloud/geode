# 에이전틱 루프 최적화 — 1차 출처 종합 + GEODE GAP

> **목적**: Furiosa Agent System 면접 보강 + GEODE 다음 단계 도구 설계.
> **범위**: plan → gather → action → verify 4단계 에이전틱 루프의 학술 foundation, autoresearch 원전, ML 엔지니어링 자율 에이전트 사례, 프로덕션 코딩 에이전트 패턴.
> **작성일**: 2026-05-06
> **조사 방법**: 4개 병렬 리서치 에이전트로 1차 출처(arxiv/repo/공식 블로그/트윗) 직접 검증.

---

## 0. Executive Summary

이전 면접에서 약점이었던 "autoresearch와 같은 방법론" 명확성을 채우기 위해, 에이전틱 루프 최적화의 4개 영역을 1차 출처 기반으로 정리한다.

| 영역 | 결론 |
|------|------|
| 학술 foundation | plan/gather/action/verify 각 단계마다 SOTA 논문 명확. 통합은 **search 패러다임**(LATS, Koh, Snell)으로 수렴 중 |
| autoresearch | Karpathy 본인이 인정한 한계는 **single-thread + local optima**. GEODE의 현재 응답은 AgenticLoop + SubAgentManager 병렬 위임 + 턴 검증이다 |
| ML 엔지니어링 자율 에이전트 | **AIDE / MLE-STAR / AlphaEvolve**가 SOTA. 공통 패턴은 tree search + automatic verifier + best-so-far ratchet |
| 프로덕션 코딩 에이전트 | **plan/action 모델 분리(Cursor), repo-map graph rank(Aider), max_iter hard cap(Computer Use), prompt caching(Claude Code)** 5대 패턴 |

**핵심 인사이트**: "longer DAG"가 아니라 **"search over a thinner loop with verifier-driven ratchet"** 이 차세대 방향. GEODE는 현재 AgenticLoop 위에 동적 plan/verify/replan을 강화하는 쪽으로 진화해야 한다.

---

## 1. 4단계 학술 Foundation

### 1.1 Plan

| 논문 | arxiv | 핵심 기여 | GEODE 매핑 |
|------|-------|-----------|------------|
| Plan-and-Solve Prompting (Wang 2023) | [2305.04091](https://arxiv.org/abs/2305.04091) | Zero-shot CoT를 plan / solve 2-phase로 분해 | router의 정적 plan을 동적으로 |
| ReWOO (Xu 2023) | [2305.18323](https://arxiv.org/abs/2305.18323) | plan을 관찰과 decouple — **5x 토큰 효율, +4% HotpotQA accuracy** | 현재 ReAct 스타일 interleaving 미사용. plan-then-gather 채택 시 토큰 절감 |
| RAP (Hao 2023) | [2305.14992](https://arxiv.org/abs/2305.14992) | LLM을 world model + agent, MCTS로 reasoning tree 탐색 | 검증 단계의 search 적용 근거 |
| Tree of Thoughts (Yao 2023) | [2305.10601](https://arxiv.org/abs/2305.10601) | thoughts를 node로 BFS/DFS + self-eval. Game of 24 4% → 74% | dynamic plan에 직접 응용 |
| Self-Discover (Zhou 2024) | [2402.03620](https://arxiv.org/abs/2402.03620) | meta-reasoning을 task당 1회 사전 결정. **+32% BBH, 10–40x fewer inferences** vs Self-Consistency/ToT | **시도 횟수 절감 1순위 인용** |

### 1.2 Gather

| 논문 | arxiv | 핵심 기여 |
|------|-------|-----------|
| ReAct (Yao 2022) | [2210.03629](https://arxiv.org/abs/2210.03629) | reasoning + acting 인터리빙. 모든 dynamic loop의 baseline |
| Toolformer (Schick 2023) | [2302.04761](https://arxiv.org/abs/2302.04761) | self-supervised tool selection 학습 |
| Self-Ask (Press 2022) | [2210.03350](https://arxiv.org/abs/2210.03350) | "compositionality gap" 정의 + follow-up question 분해 |
| HuggingGPT (Shen 2023) | [2303.17580](https://arxiv.org/abs/2303.17580) | LLM controller가 multi-tool 오케스트레이션 |

### 1.3 Action

| 논문 | arxiv | 핵심 기여 |
|------|-------|-----------|
| Voyager (Wang 2023) | [2305.16291](https://arxiv.org/abs/2305.16291) | growing skill library + lifelong learning. **3.3x items, 15.3x faster milestones** |
| Reflexion (Shinn 2023) | [2303.11366](https://arxiv.org/abs/2303.11366) | verbal RL — episodic memory로 실패 학습. HumanEval 91% pass@1 |
| Self-Refine (Madaan 2023) | [2303.17651](https://arxiv.org/abs/2303.17651) | 동일 LLM이 generate → feedback → refine. 7 task +20% |
| CodeAct (Wang 2024) | [2402.01030](https://arxiv.org/abs/2402.01030) | JSON tool call 대신 **Python 코드를 action 단위로**. 동적 control flow |

### 1.4 Verify

| 논문 | arxiv | 핵심 기여 | GEODE 매핑 |
|------|-------|-----------|------------|
| Self-Consistency (Wang 2022) | [2203.11171](https://arxiv.org/abs/2203.11171) | sampling + majority vote. GSM8K +17.9% | Cross-LLM 검증의 단일 모델 버전 |
| GSM8K Verifier (Cobbe 2021) | [2110.14168](https://arxiv.org/abs/2110.14168) | trained verifier로 best-of-N. PRM/ORM 시조 | 추가 verifier 모델 도입 근거 |
| CRITIC (Gou 2023) | [2305.11738](https://arxiv.org/abs/2305.11738) | 외부 tool로 자기 출력 비평/revise | Guardrail G3 (Grounding) 학술 짝 |
| Constitutional AI (Bai 2022) | [2212.08073](https://arxiv.org/abs/2212.08073) | principles 기반 self-critique + RLAIF | 14-axis rubric의 학술 짝 |
| LLM-as-Judge / MT-Bench (Zheng 2023) | [2306.05685](https://arxiv.org/abs/2306.05685) | GPT-4 judge **>80% human agreement**, position/verbosity/self-enhancement bias 명시 | BiasBuster의 학술 짝 — 직접 인용 가능 |

### 1.5 통합 — search 패러다임

| 논문 | arxiv | 핵심 |
|------|-------|------|
| LATS (Zhou 2023, ICML 2024) | [2310.04406](https://arxiv.org/abs/2310.04406) | reasoning + acting + planning을 **MCTS**로 통합 |
| ToolChain* (Zhuang 2023, ICLR 2024) | [2310.13227](https://arxiv.org/abs/2310.13227) | action을 decision tree, **A\* search**. **7.35x speedup** vs DFS — "시도 횟수 절감" 정식 frame |
| Tree Search for LM Agents (Koh 2024) | [2407.01476](https://arxiv.org/abs/2407.01476) | 첫 best-first tree search for LM web agents. **VisualWebArena +39.7%, WebArena +28.0%** |
| Test-time Compute Scaling (Snell 2024) | [2408.03314](https://arxiv.org/abs/2408.03314) | compute-optimal scaling **>4x over best-of-N**. 작은 모델 + verifier search = **14x 큰 모델 동급** |

---

## 2. autoresearch 원전 + Karpathy 한계 인정

### 2.1 1차 출처 원문 인용

**Repo**: [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — "AI agents running research on single-GPU nanochat training automatically"

**program.md verbatim 핵심 4구절**:

> "Each experiment runs on a single GPU. The training script runs for a **fixed time budget of 5 minutes** (wall clock training time, excluding startup/compilation)."

> "**The goal is simple: get the lowest val_bpb.**"

> "**What you CAN do:** Modify `train.py` — this is the only file you edit. **What you CANNOT do:** Modify `prepare.py`. It is read-only. Install new packages or add dependencies."

> "If val_bpb improved (lower), you 'advance' the branch, keeping the git commit. If val_bpb is equal or worse, you git reset back to where you started."

### 2.2 Karpathy 본인 X 게시물

| 트윗 | 핵심 |
|------|------|
| [발표](https://x.com/karpathy/status/2030371219518931079) | "I packaged up the 'autoresearch' project ... ~630 lines of code" |
| [결과](https://x.com/karpathy/status/2031135152349524125) | "depth=12 model. ~20 changes that improved validation loss ... all additive and transferred to depth=24. Time-to-GPT-2: 2.02h → 1.80h, ~700 experiments" |
| [한계 인정](https://x.com/karpathy/status/2030705271627284816) | "**The next step ... has to be asynchronously massively collaborative for agents (think: SETI@home style).** ... not to emulate a single PhD student, it's to emulate a research community." |
| [성격 규정](https://x.com/karpathy/status/2031137476438548874) | "it's just a recipe/idea" |

### 2.3 외부 분석

- [Latent Space — Sparks of Recursive Self Improvement](https://www.latent.space/p/ainews-autoresearch-sparks-of-recursive) — "Codex can't run autoresearch properly in its current setup" (harness affordances 강조)
- [DataCamp 가이드](https://www.datacamp.com/tutorial/guide-to-autoresearch)

### 2.4 커뮤니티 비판 (HN [47291123](https://news.ycombinator.com/item?id=47291123))

| 비판 | GEODE의 설계적 응답 |
|------|---------------------|
| "BayesOpt vs 동일 시도 횟수 비교 없음" (abeppu) | 14-axis rubric으로 search space를 의미적으로 구조화 → BayesOpt와 다른 차원 |
| "eval set overfitting (seed 42→137)" (aix1) | Cross-LLM + Calibration check (Layer 5 Swiss Cheese) |
| "brute force ≠ research, Goodhart's law shrine" (gmerc) | G1-G4 Guardrail + BiasBuster 3-bias로 metric gaming 차단 |
| "10M params 너무 작아 emergent effect 안 나옴" (elikoga) | GEODE는 production LLM 사용 — scale 문제 무관 |
| "Local optima trap — never takes a step backward" (DataCamp) | 5-iter 안에서 weak_areas 추출 + monolake 주입으로 의미적 perturbation |

### 2.5 Fixed Time Budget (P3) 후속

- [Sutton, The Bitter Lesson](http://www.incompleteideas.net/IncIdeas/BitterLesson.html) — "search and learning ... two most important classes"
- [OpenAI o1](https://openai.com/index/learning-to-reason-with-llms/) — "performance consistently improves with ... more time spent thinking"
- [DeepSeek-R1](https://arxiv.org/abs/2501.12948) — token-budget 32,768 → 65,536
- [s1 (Stanford 2025)](https://arxiv.org/abs/2501.19393) — **budget forcing**: thinking-token 한계 시 강제 종료, "Wait" 토큰 주입으로 연장. AIME24 50→57%

비교: autoresearch = wall-clock(5min) / s1 = token budget / o1·R1 = open-ended thinking tokens.

### 2.6 Context Budget (P6) 후속

- [Lost in the Middle (Liu 2023)](https://arxiv.org/abs/2307.03172) — "performance highest when relevant info at beginning or end"
- [Anthropic Context Editing](https://platform.claude.com/docs/en/build-with-claude/context-editing) — stale tool calls 자동 클리어
- [Anthropic Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction) — summarize-then-replace
- [Anthropic Skill Compression](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — "skill description ~100 tokens at startup; full instructions (~2,000 tokens) only enter context when task matches" → **GEODE skill 라우팅과 동형**
- 60-70% 가용성 가이드라인: "200K 모델은 120-140K부터 degrade"

---

## 3. ML 엔지니어링 자율 에이전트

### 3.1 벤치마크

| 벤치마크 | 출처 | 발견 |
|----------|------|------|
| **MLE-bench** | [arxiv 2410.07095](https://arxiv.org/abs/2410.07095), [OpenAI](https://openai.com/index/mle-bench/) | Kaggle 75 task. **o1-preview + AIDE: pass@1 16.9%, pass@8 34.1% bronze** |
| **MLAgentBench** | [arxiv 2310.03302](https://arxiv.org/abs/2310.03302) | 13 ML 실험 task. Claude 3 Opus 평균 37.5% |
| **RE-Bench** | [arxiv 2411.15114](https://arxiv.org/abs/2411.15114), [METR](https://metr.org/blog/2024-11-22-evaluating-r-d-capabilities-of-llms/) | 7개 R&D task. **8h 예산: 인간 ≈ AI / 32h: 인간 2배. AI는 10x 빠르고 저렴한 시도가 강점** |

### 3.2 구현 사례

#### AIDE (Weco AI 2025) — Solution Tree Search
[arxiv 2502.13138](https://arxiv.org/abs/2502.13138) · [GitHub](https://github.com/WecoAI/aideml)

| 단계 | 구현 |
|------|------|
| Plan | 빈 root → 단일 파일 Python plan |
| Gather | **Σ(T)**: 노드별 metric + hyperparam만 추출 (prompt 폭발 방지) |
| Action | 3 연산자 — `draft`(신규) / `debug`(에러 로그 기반) / `improve`(원자적 1-change) |
| Verify | stateless objective h(s)→ℝ |
| 종료 | 고정 N iter (default 20, max 50). **argmax h(s)** |

**탐색 정책**: 순수 greedy. debug depth limit으로 자연 pruning. **MLE-bench 메달 vs 2위 3배.**

#### MLE-STAR (Google DeepMind, NeurIPS 2025)
[arxiv 2506.15692](https://arxiv.org/abs/2506.15692) · [Research Blog](https://research.google/blog/mle-star-a-state-of-the-art-machine-learning-engineering-agents/)

| 단계 | 구현 |
|------|------|
| Plan | **Web search**로 효과적 모델 retrieval → initial solution |
| Gather | Outer: ablation 코드 생성 → component별 기여도 측정 |
| Action | Outer가 지정한 1 block에 Inner가 K개 refinement |
| Verify | val metric + improvement gating |
| 종료 | T outer × K inner. R개 ensemble |

**MLE-bench Lite 메달 64%** (AIDE 대비 압도). 핵심: ablation으로 **"어디를 고칠지" 자동 결정 = 탐색 공간 절단**.

#### AI Research Agents 비교 연구 (Meta 2025)
[arxiv 2507.02554](https://arxiv.org/html/2507.02554) — AIDE vs AIRA(MCTS, evolutionary, greedy) 동일 frame 비교. 핵심 발견:
- **Greedy는 validation→test 일반화 갭 15-16.6%**
- **Final-node re-selection (마지막 best 재선택)이 60% 갭 회복** — GEODE에 1줄 추가로 큰 효과 기대

### 3.3 자율 코드 진화

#### AlphaEvolve (DeepMind 2025)
[arxiv 2506.13131](https://arxiv.org/abs/2506.13131) · [Blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) · [Results](https://github.com/google-deepmind/alphaevolve_results)

| 단계 | 구현 |
|------|------|
| Plan | Program Database에서 parent 선택 |
| Gather | 과거 best solutions를 inspiration으로 |
| Action | **Gemini Flash(broad) + Pro(depth) 앙상블** mutation |
| Verify | automated evaluator pool (다중 metric) |
| 종료 | compute budget. best-so-far 영구 보존 |

**성과**: 4×4 행렬곱 48 multiplications (Strassen 56년 만에 갱신), FlashAttention 32.5% speedup, Gemini 학습 1% 단축.

**핵심 차용 패턴**: fast/slow LLM 이중 사용 — throughput vs quality 균형.

#### FunSearch (DeepMind, Nature 2023)
[Nature](https://www.nature.com/articles/s41586-023-06924-6) · [GitHub](https://github.com/google-deepmind/funsearch)
- LLM creator + automatic evaluator. **Cap set 문제 새 해 발견** (LLM 최초 미해결 수학 기여)
- 평가자가 환각 차단 → **verify가 ratchet의 본질**

---

## 4. 프로덕션 코딩 에이전트

### 4.1 시스템 카드

#### Claude Code (Anthropic) — [docs](https://code.claude.com/docs/en/best-practices) · [caching](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching)
- **Plan**: Plan Mode (Ctrl+G) + TodoWrite. "Letting Claude jump straight to coding can produce code that solves the wrong problem"
- **Gather**: `@` 파일, gh/CLI, MCP. "CLI tools are the most context-efficient way"
- **Action**: Read/Edit/Bash + 결정론적 hooks
- **Verify**: "**Give Claude a way to verify its work** ... This is the **single highest-leverage thing** you can do." Writer/Reviewer fresh-context subagent
- **Loop-Exit**: end_turn / Esc / /clear
- **Context-Opt**: CLAUDE.md (1회 로드) + auto compaction + subagent isolation + cache_control (read 0.1x, write 1.25x, 1h TTL 2x, max 4 breakpoints)

#### Cursor (Composer 2 + Apply) — [Instant Apply](https://www.cursor.com/blog/instant-apply) · [Composer 2 Report](https://www.cursor.com/blog/composer-2-technical-report)
- **분리된 Apply 모델**: 70B fine-tuned, "**~1000 tokens/s, 13x vs vanilla Llama-3-70B**"
- speculative edits 디코딩
- Composer 2는 RL로 학습, "tasks where prompt is terse and ambiguous, solutions require hundreds of lines"
- **차용 핵심**: Plan(추론 모델) + Action(빠른 적용 모델) **물리적 분리**

#### Devin (Cognition) — [Closing Agent Loop](https://www.cognition.ai/blog/closing-the-agent-loop-devin-autofixes-review-comments)
- 4-tool: planning + terminal + editor + browser
- VM-level isolation (kernel per workload)
- **Devin Review + Autofix**: 외부 봇(linter/CI/security) 코멘트도 자동 처리 — **closed loop**
- VM snapshotting (memory + process tree + filesystem)으로 세션 재개

#### Aider — [Repo Map](https://aider.chat/docs/repomap.html) · [Edit Formats](https://aider.chat/docs/more/edit-formats.html)
- **architect/editor 분리** — architect 모델이 plan, editor 모델이 적용
- **Repo-map graph ranking**: "graph where each source file is a node and edges connect dependencies" → PageRank류로 token budget 안에서 가장 참조 많은 식별자만
- `--map-tokens=1k` (default), 동적 확장
- edit format: whole / diff (search-replace) / diff-fenced (Gemini) / udiff (GPT-4 Turbo)

#### Anthropic Computer Use — [docs](https://platform.claude.com/docs/en/docs/agents-and-tools/computer-use)
- **`max_iterations=10` 명시 hard cap** — "Add iteration limit to prevent infinite loops"
- 매 step screenshot으로 자기 검증
- 1568px downsample + zoom action으로 region만 full-res 재요청 (4.7부터 2576px)

### 4.2 비교 매트릭스

| 시스템 | Plan | Verify | 종료 | 핵심 컨텍스트 절약 |
|--------|------|--------|------|-------------------|
| Claude Code | TodoWrite + Plan Mode | tests/screenshots, subagent | end_turn / Esc | CLAUDE.md + auto compaction + subagent + cache_control |
| Cursor | Composer 2 | Apply 모델 별도 | harness | Plan/Apply 모델 분리 |
| Devin | Long-term planner | Devin Review + 외부 봇 | PR merge | VM snapshot |
| AIDE | Solution Tree Search | metric eval | steps=20 | tree pruning + Σ(T) |
| Aider | architect/editor | git commit + tests | 턴 종료 | repo-map graph rank |
| Computer Use | screenshot | screenshot diff | max_iter=10 | zoom + downsample |
| OpenHands | AgentController | runtime exec | max_iter | EventStream |

### 4.3 프로덕션 5대 공통 패턴

1. **Plan을 산출물로 외부화** (TodoWrite, architect, spec)
2. **Verify를 루프에 강제 주입** (Anthropic: "single highest-leverage thing")
3. **명시적 max_iterations hard cap** (Computer Use 10, AIDE 20, OpenHands 카운터)
4. **Plan-er와 Action-er 모델 분리** (Cursor 13x speed, Aider architect/editor, Claude Code subagent)
5. **컨텍스트 압축/요약 메커니즘** (Claude Code auto-compaction, Aider repo-map, AIDE tree pruning, Devin VM snapshot)

---

## 5. 시도/컨텍스트 절감 카탈로그

| 기법 | 출처 | 정량 효과 | 적용 단계 |
|------|------|-----------|-----------|
| ReWOO plan/observation decouple | [2305.18323](https://arxiv.org/abs/2305.18323) | **5x 토큰 효율** vs ReAct | Plan |
| Self-Discover meta-reasoning | [2402.03620](https://arxiv.org/abs/2402.03620) | **10–40x fewer inferences** | Plan |
| ToolChain* A* search | [2310.13227](https://arxiv.org/abs/2310.13227) | **7.35x speedup** vs DFS | Action |
| Test-time compute scaling | [2408.03314](https://arxiv.org/abs/2408.03314) | **14x model size 동급** with verifier | Verify |
| Cursor speculative apply | [Instant Apply](https://www.cursor.com/blog/instant-apply) | **13x speed** vs vanilla 70B | Action |
| Anthropic prompt caching | [docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching) | read 0.1x cost | 전 단계 |
| Anthropic skill compression | [engineering blog](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 100 tokens vs 2000 tokens | Plan |
| Aider repo-map PageRank | [Repo Map docs](https://aider.chat/docs/repomap.html) | 동적 token budget | Gather |
| AIDE Σ(T) summarization | [2502.13138](https://arxiv.org/abs/2502.13138) | iter N과 iter 1 동일 토큰 예산 | Gather |
| MLE-STAR ablation pruning | [2506.15692](https://arxiv.org/abs/2506.15692) | 탐색 공간 의미적 절단 | Plan/Verify |
| Final-node re-selection | [2507.02554](https://arxiv.org/html/2507.02554) | 일반화 갭 **60% 회복** | Verify |
| AlphaEvolve fast/slow LLM | [2506.13131](https://arxiv.org/abs/2506.13131) | throughput vs quality 균형 | Action |

---

## 6. GEODE GAP 분석

| # | 패턴 | 4-시스템 출처 | GEODE 현재 | GAP | 우선 |
|---|------|---------------|------------|-----|-----|
| 1 | **Dynamic Plan** (Plan-and-Solve, Self-Discover) | 4/4 | router 정적 분기만 | **plan 노드 부재** — task당 plan을 LLM이 생성하지 않음 | **P1** |
| 2 | **plan/action 모델 분리** | Cursor, Aider, Claude Code | Opus 단일 / 일부 cross-LLM | Apply용 fast 모델 미사용 | P2 |
| 3 | **Final-node re-selection** | [Meta 2025](https://arxiv.org/html/2507.02554) | 마지막 iter 결과 그대로 사용 | best iter 재선택 단계 부재 | **P1** (1줄 추가) |
| 4 | **Σ(T) tree summarization** | AIDE | 매 iter 전체 컨텍스트 재주입 | iter 5의 prompt가 iter 1과 동일 토큰 예산 안 됨 | P2 |
| 5 | **Ablation-driven refinement** | MLE-STAR | 14-axis 동시 평가 | "어디를 고칠지" 자동 결정 부재 | P2 |
| 6 | **Tree search (LATS, Koh, ToolChain*)** | 학술 SOTA | greedy 5-iter | 탐색 패러다임 미도입 | P3 |
| 7 | **Plan을 외부화 산출물로** | Claude Code, Aider, Copilot Workspace | iteration_history 누적 | plan을 파일로 저장 안 함 | P2 |
| 8 | **Verify가 루프 핵심 기여** | Anthropic 명시 | G1-G4 + BiasBuster 있음 ✓ | 학술 인용 부족 | 인용 보강 |
| 9 | **max_iter hard cap** | 4/4 | 5 iter ✓ | 이미 있음 ✓ | — |
| 10 | **Wall-clock budget** | autoresearch P3, s1 | iteration count만 | wall-clock 추가 | P3 |
| 11 | **Best-so-far ratchet** | autoresearch, AlphaEvolve, FunSearch | verify/replan telemetry 기반 | 부분 구현 ✓ | — |
| 12 | **Repo-map / 도메인 그래프 rank** | Aider | 14-axis 직접 주입 | PageRank류 도메인 엔티티 selection 부재 | P3 |
| 13 | **Subagent isolation** | Claude Code, Devin | SubAgentManager + IsolatedRunner ✓ | 컨텍스트 격리 강화 여지 | P2 |
| 14 | **prompt caching cache_control** | Claude Code | v0.65.0 messages 적용 ✓ | system/tools breakpoint 추가 | P3 |
| 15 | **외부 봇 closed loop** | Devin | linter/CI 미통합 | autofix 루프 부재 | P4 |
| 16 | **Skill compression on-match** | Anthropic | 100/2000 tokens 패턴 부분 적용 | 명시적 trigger 매칭 강화 | P3 |
| 17 | **Constitutional AI 학술 인용** | Bai 2022 | 14-axis rubric ✓ | 학술 짝 명시 | 인용 보강 |
| 18 | **MT-Bench bias 카탈로그 인용** | Zheng 2023 | BiasBuster ✓ | 학술 짝 명시 | 인용 보강 |

---

## 7. 다음 단계: GEODE에 빌드할 도구 우선순위

### P1 (즉시) — 면접 차별화 + 1줄 효과
1. **Final-node re-selection 단계 추가** — synthesizer 직전 evaluator로 iteration_history 재선택. [Meta 2025](https://arxiv.org/html/2507.02554) 인용으로 "일반화 갭 60% 회복" 정량 주장 가능.
2. **Dynamic Plan 강화** — `Plan` 객체와 replan 트리거를 더 적극적으로 사용. LLM이 task별 sub-step JSON을 만들고 현재 단계 힌트로 주입. ReWOO/Self-Discover 인용으로 5x 토큰 + 10–40x fewer inferences 정량화.

### P2 (단기) — 토큰/시도 절감 직접 효과
3. **Plan/Action 모델 분리** — Plan(Opus) → Action(Sonnet/Haiku). Cursor 13x speed 패턴 차용. analyst 4-way가 fast 모델로 전환 가능한지 판정.
4. **AIDE Σ(T) summarization** — AgenticLoop transcript/verify telemetry를 `{round, action, observation, misses, next_hint}` 형태로 압축. 장기 작업의 prompt 토큰 증가를 제한.
5. **MLE-STAR ablation** — verification 직후 14-axis ablation 1회 → 상위 3 axis만 다음 iter에 refine. 탐색 공간 의미적 절단.
6. **Plan 외부화** — `iteration_history`를 `docs/runs/<task_id>/plan.md` 파일로 영구 기록. autoresearch program.md 패턴.
7. **Subagent isolation 강화** — SubAgentManager worker가 sibling 결과를 보지 않는다는 계약을 system prompt/toolkit 수준에서 명시. Clean Context 강화.

### P3 (중기) — 아키텍처 진화
8. **Tree search 도입 검토** — 5-iter greedy → best-first search. LATS/Koh/ToolChain* 인용. AIRA 비교 연구 기준 일반화 갭 줄어듦.
9. **Wall-clock budget** — `max_wall_seconds` 파라미터 추가. autoresearch P3 + s1 budget forcing 패턴.
10. **도메인 그래프 PageRank recall** — 코드/도메인 그래프에서 top-k만 컨텍스트에 주입. Aider repo-map과 isomorphic.
11. **prompt caching system/tools breakpoint** — v0.65.0 messages caching 위에 system/tools에도 cache_control 추가. read 0.1x 비용 효과.

### P4 (장기) — 외부 시스템 통합
12. **Closed-loop with external verifiers** — Devin Autofix 패턴. lint/test/CI 결과를 자동 소비.

### 인용 보강 (코드 변경 X)
13. CAI/MT-Bench를 GEODE.md/CLAUDE.md의 verification 섹션에 명시 인용.

---

## 8. 면접 답변 talking points

### "autoresearch와 같은 방법론을 어떻게 적용했나?"
> "autoresearch는 P3 fixed wall-clock budget(5분), P4 git-ratchet, P2 single-file constraint, P6 context budget 4가지를 train.py 630줄로 압축한 recipe입니다. GEODE는 AgenticLoop의 시간/비용 예산, ConvergenceDetector, turn verify/replan, SubAgentManager 병렬 위임으로 같은 압력을 런타임에 옮겼습니다."

### "왜 ReAct만으로 부족한가?"
> "ReAct (Yao 2022, [2210.03629](https://arxiv.org/abs/2210.03629))는 reasoning과 acting을 인터리브하지만, ReWOO (Xu 2023, [2305.18323](https://arxiv.org/abs/2305.18323))는 plan을 observation과 decouple하면 **5x 토큰 효율, +4% accuracy on HotpotQA**를 보였습니다. GEODE는 현재 fixed DAG로 인터리빙을 회피했고, 다음 단계는 dynamic plan 노드 추가입니다."

### "시도 횟수를 어떻게 줄이나?"
> "Self-Discover (Zhou 2024, [2402.03620](https://arxiv.org/abs/2402.03620))는 meta-reasoning을 task당 1회 사전 결정해 **10–40x fewer inferences**를 달성했고, ToolChain* (Zhuang 2023, [2310.13227](https://arxiv.org/abs/2310.13227))는 action을 A\* search로 풀어 **7.35x speedup**을 보였습니다. GEODE는 Plan/replan 힌트와 SubAgentManager 병렬 위임으로 의미적 탐색 공간을 줄입니다."

### "verify를 어떻게 강화하는가?"
> "Anthropic Claude Code 가이드는 'verify를 루프에 묶는 것이 the single highest-leverage thing'이라고 명시합니다. GEODE는 G1-G4 가드레일 + Cross-LLM (Self-Consistency [2203.11171](https://arxiv.org/abs/2203.11171) 동형) + BiasBuster (MT-Bench [2306.05685](https://arxiv.org/abs/2306.05685) bias 카탈로그 동형) + Calibration (CAI [2212.08073](https://arxiv.org/abs/2212.08073) 동형) 4중 방어를 구현했습니다. 다음 단계는 Cobbe 2021 [2110.14168](https://arxiv.org/abs/2110.14168) 스타일의 trained verifier 추가와 Snell 2024 [2408.03314](https://arxiv.org/abs/2408.03314) test-time compute optimal allocation입니다."

### "ratchet의 한계는?"
> "Karpathy 본인이 인정한 한계는 single-thread synchronous loop와 local optima입니다. HN 비판도 'BayesOpt 비교 부재', 'eval overfitting', 'Goodhart's law'을 지적했습니다. **GEODE는 14-axis rubric으로 search space를 의미적으로 구조화**해 brute-force와 차별화했고, **G1-G4 + BiasBuster 3-bias로 metric gaming을 차단**했으며, **Cross-LLM + Calibration의 Layer 5 Swiss Cheese**로 eval overfitting을 막았습니다."

### "다음 아키텍처 방향은?"
> "LATS ([2310.04406](https://arxiv.org/abs/2310.04406))와 Koh 2024 ([2407.01476](https://arxiv.org/abs/2407.01476))가 보여준 통합 view는 **'longer DAG'가 아니라 'search over a thinner loop with verifier-driven ratchet'**입니다. VisualWebArena +39.7% 결과가 그 근거입니다. GEODE는 AgenticLoop 위에서 동적 plan + replan + tree-search 방향으로 진화 중입니다."

---

## Sources (전체 검증 URL)

### 학술 논문
- [Plan-and-Solve (2305.04091)](https://arxiv.org/abs/2305.04091) · [ReWOO (2305.18323)](https://arxiv.org/abs/2305.18323) · [RAP (2305.14992)](https://arxiv.org/abs/2305.14992) · [ToT (2305.10601)](https://arxiv.org/abs/2305.10601) · [Self-Discover (2402.03620)](https://arxiv.org/abs/2402.03620)
- [ReAct (2210.03629)](https://arxiv.org/abs/2210.03629) · [Toolformer (2302.04761)](https://arxiv.org/abs/2302.04761) · [Self-Ask (2210.03350)](https://arxiv.org/abs/2210.03350) · [HuggingGPT (2303.17580)](https://arxiv.org/abs/2303.17580)
- [Voyager (2305.16291)](https://arxiv.org/abs/2305.16291) · [Reflexion (2303.11366)](https://arxiv.org/abs/2303.11366) · [Self-Refine (2303.17651)](https://arxiv.org/abs/2303.17651) · [CodeAct (2402.01030)](https://arxiv.org/abs/2402.01030)
- [Self-Consistency (2203.11171)](https://arxiv.org/abs/2203.11171) · [GSM8K Verifier (2110.14168)](https://arxiv.org/abs/2110.14168) · [CRITIC (2305.11738)](https://arxiv.org/abs/2305.11738) · [CAI (2212.08073)](https://arxiv.org/abs/2212.08073) · [MT-Bench (2306.05685)](https://arxiv.org/abs/2306.05685)
- [LATS (2310.04406)](https://arxiv.org/abs/2310.04406) · [ToolChain* (2310.13227)](https://arxiv.org/abs/2310.13227) · [Koh 2024 (2407.01476)](https://arxiv.org/abs/2407.01476) · [Snell 2024 (2408.03314)](https://arxiv.org/abs/2408.03314) · [Skeleton-of-Thought (2307.15337)](https://arxiv.org/abs/2307.15337)
- [Lost in the Middle (2307.03172)](https://arxiv.org/abs/2307.03172) · [s1 (2501.19393)](https://arxiv.org/abs/2501.19393) · [DeepSeek-R1 (2501.12948)](https://arxiv.org/abs/2501.12948)

### autoresearch
- [karpathy/autoresearch repo](https://github.com/karpathy/autoresearch) · [program.md](https://github.com/karpathy/autoresearch/blob/master/program.md) · [README.md](https://github.com/karpathy/autoresearch/blob/master/README.md)
- 트윗: [발표](https://x.com/karpathy/status/2030371219518931079) · [결과](https://x.com/karpathy/status/2031135152349524125) · [한계 인정](https://x.com/karpathy/status/2030705271627284816) · [성격](https://x.com/karpathy/status/2031137476438548874)
- [Latent Space 분석](https://www.latent.space/p/ainews-autoresearch-sparks-of-recursive) · [DataCamp 가이드](https://www.datacamp.com/tutorial/guide-to-autoresearch) · [HN 47291123](https://news.ycombinator.com/item?id=47291123)
- [Sutton Bitter Lesson](http://www.incompleteideas.net/IncIdeas/BitterLesson.html) · [OpenAI o1](https://openai.com/index/learning-to-reason-with-llms/)

### ML 엔지니어링 자율 에이전트
- [MLE-bench (2410.07095)](https://arxiv.org/abs/2410.07095) · [OpenAI 발표](https://openai.com/index/mle-bench/) · [MLAgentBench (2310.03302)](https://arxiv.org/abs/2310.03302) · [RE-Bench (2411.15114)](https://arxiv.org/abs/2411.15114) · [METR](https://metr.org/blog/2024-11-22-evaluating-r-d-capabilities-of-llms/)
- [AIDE (2502.13138)](https://arxiv.org/abs/2502.13138) · [AIDE GitHub](https://github.com/WecoAI/aideml) · [MLE-STAR (2506.15692)](https://arxiv.org/abs/2506.15692) · [Google Research blog](https://research.google/blog/mle-star-a-state-of-the-art-machine-learning-engineering-agents/)
- [AlphaEvolve (2506.13131)](https://arxiv.org/abs/2506.13131) · [DeepMind blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) · [FunSearch Nature](https://www.nature.com/articles/s41586-023-06924-6) · [FunSearch GitHub](https://github.com/google-deepmind/funsearch)
- [AI Research Agents 비교 (2507.02554)](https://arxiv.org/html/2507.02554)

### 프로덕션 코딩 에이전트
- [Claude Code best practices](https://code.claude.com/docs/en/best-practices) · [prompt caching](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching) · [context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing) · [skill compression blog](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) · [computer use](https://platform.claude.com/docs/en/docs/agents-and-tools/computer-use)
- [Codex CLI](https://developers.openai.com/codex/cli/features) · [Codex non-interactive](https://developers.openai.com/codex/noninteractive)
- [Cursor Instant Apply](https://www.cursor.com/blog/instant-apply) · [Cursor Composer 2 Report](https://www.cursor.com/blog/composer-2-technical-report)
- [Devin closed loop](https://www.cognition.ai/blog/closing-the-agent-loop-devin-autofixes-review-comments) · [Devin cloud agents](https://www.cognition.ai/blog/what-we-learned-building-cloud-agents)
- [Aider repo-map](https://aider.chat/docs/repomap.html) · [Aider edit formats](https://aider.chat/docs/more/edit-formats.html)
- [OpenHands](https://github.com/All-Hands-AI/OpenHands) · [Replit Agent](https://docs.replit.com/replitai/agent) · [Copilot Workspace](https://github.blog/news-insights/product-news/github-copilot-workspace/)
