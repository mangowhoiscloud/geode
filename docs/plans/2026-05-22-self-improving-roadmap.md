# Self-Improving Roadmap — 30 항목 3-tier 진행 계획

> Created: 2026-05-22
> Status: Active
> Driving directive: outer (co-scientist → petri → autoresearch) → inner (Hermes) → cognitive (agentic loop) 순서

## Driving observation

이번 세션 retrospective 결과 (PR #1438 M4 sprint 종료 이후 PR #1439-#1440 Hermes 진입 전환점에서 분석):

- **표면 확장**은 강함 — 6 TARGET_KINDS + DPO pipeline 형식 완성
- **Hermes-style memory** 진행 중 — Phase 1 거의 완료
- **Cognitive 개선 (A1-A9)** 거의 손 안 댐 — agent 가 어떻게 *생각* 하나는 미진행
- **Loop closure** writer wiring 2건 미해결 — M4 sprint 의 deception
- **Auto-trigger** 부재 — mutator 가 operator-guided

→ 진짜 self-improving 으로 가기 위해 30 항목 정리.

## Tier 0 — Housekeeping (병행, 진행 시점 융통적)

| ID | 작업 | 의존 | 비고 |
|---|---|---|---|
| **HK-1** | `[Unreleased]` CHANGELOG 14+ entry 정리 + v0.99.27 release (develop → main) | OL-G 후 권장 | CLAUDE.md "No [Unreleased] on main" |
| **HK-2** | Release packaging — Homebrew formula + HuggingFace Hub README | HK-1 | release-packaging.md |
| **HK-3** | OPS-2b dashboard UI (`/self-improving` 슬래시 panel) | UI/UX option 결정 (사용자) | gated |
| **HK-4** | M5 plugin code mutation (Tier 2 ADR 사전 검토) | Tier 2 ADR | gated |

## Tier 1 — Outer Loop closure + autonomy (12 항목)

### A. Loop closure (M4 sprint deception 해소) — 최우선

#### OL-C1 — `emit_eval_response_recorded` 호출자 wiring

| 항목 | 내용 |
|---|---|
| 영향 파일 | `plugins/petri_audit/runner.py` 또는 동등 audit 진입점 (`emit` 1지점) + `core/agent/loop/` 의 turn-end (`emit` 2지점) |
| Fitness 측정 | Petri audit = audit 의 per-turn dim_means subset / AgenticLoop turn = ux heuristic (token / latency / error binary 의 weighted avg, 0.0~1.0) |
| Rollback 신호 | 운영자가 `/clear` / `/rerun` / "그거 말고" 입력 시 직전 turn 의 rollback_flag=True 로 마킹. 명시 트리거 패턴 — slash command + 휴리스틱 keyword. Phase 2 에서 정밀화 |
| 테스트 | mock SessionJournal scope + emit 호출 1회 확인 + payload schema 검증 + 2 호출지점 모두 hit |
| 추정 LOC | ~120 + ADR |
| 의존 | OL-C1.ADR (fitness 측정 method 사전 확정) |
| 차단 효과 해소 | DPO 파이프라인의 raw stream 활성화 — M4.1/2/3 가 진짜 작동 |

#### OL-C2 — Few-shot pool writer

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/llm/few_shot_pool.py` (writer 함수 + `append_exemplar` 추가) + `autoresearch/train.py` 의 promote 직후 hook |
| Trigger | fitness gate 통과 (promote=True) 시 직전 turn 의 `(user_msg, assistant_msg, fitness_delta, source)` 를 pool 에 append |
| File | `autoresearch/state/policies/few-shot-pool.jsonl` (기존 SoT) — append-only, idempotent (signature dedup) |
| 테스트 | gate-trigger fixture + append + reader round-trip + max-size cap (1000 entries) |
| 추정 LOC | ~100 |
| 의존 | 없음 (independent) |
| 차단 효과 해소 | exemplars in-context slot active — M4.4 의 첫 wired slot 이 진짜 작동 |

#### OL-C3 — memory_recall dir 자동 writer

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/memory/recall_writer.py` (신규) + `core/agent/loop/` 의 session-end hook |
| Trigger | session 종료 시 (또는 N turn마다) LLM-as-cuator 가 transcript 에서 surfaceable insight 1-3개 추출 → frontmatter MD 로 `~/.geode/memory/recall/` 에 write |
| Schema | M4.4.1 의 frontmatter format 정확히 일치 (name / description / metadata.type / body) |
| 테스트 | mock transcript → curator LLM mock → file write verification |
| 추정 LOC | ~150 |
| 의존 | 없음 |
| 차단 효과 해소 | memory_recall slot 의 input 신뢰성 향상 |

### B. Autoresearch 자동화

#### OL-A1 — Mutator auto-trigger (cron-based 우선)

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/scheduler/predefined.py` (AutomationTemplate 추가) + `core/wiring/startup.py` (background runner 등록) + `core/self_improving_loop/auto_trigger.py` (신규 lockfile + runner wrapper) |
| Config | `[self_improving_loop.scheduler] enabled=false, cron="0 */12 * * *", max_iterations_per_run=1, dry_run=false` |
| Lockfile | `~/.geode/self-improving-loop/.mutator.lock` (PID + start_ts; stale 30분 후 회수) |
| Safety | quota guard (`abort_threshold` 위반 → abort), `_git_commit_audit_log` 로 매 mutation rollback 가능 |
| 테스트 | cron parse + lockfile contention + auto trigger fixture (mock runner) |
| 추정 LOC | ~150 |
| 의존 | OL-C1 권장 (mutator 가 자동 돌면 fitness 측정 input 도 자동 흘러야 의미 있음) + OL-G |
| 차단 효과 해소 | outer loop autonomous — operator-guided 종료 |

**인프라 의존성 (cron 실행 환경별 backend matrix)**

OL-A1 의 cron-fired runner 는 기존 mutator entry-point 의 `_default_llm_call` (PAPERCLIP #1433) 를 그대로 호출. 이미 4 backend 추상화 완료 — 새 추상화 layer 불필요. 단, **cron / serve background context 에서 각 backend 가 작동하는지** 별도 검증 필요.

| Backend (`MutatorConfig.source`) | Dispatch 경로 | 빌링 채널 | Cron 작동 조건 |
|---|---|---|---|
| `api_key` (default) | `call_with_failover` → `resolve_agentic_adapter(provider)` — `_ADAPTER_MAP` 의 4 entry (anthropic / openai / glm / openai-codex) | Anthropic PAYG (ANTHROPIC_API_KEY) / OpenAI PAYG (OPENAI_API_KEY) / GLM PAYG / **OpenAI subscription via OAuth** (`~/.codex/auth.json` — `CodexAgenticAdapter` 가 HTTP 로 chatgpt.com/backend-api/codex 호출) | API key env var 또는 OAuth token file 존재 |
| `auto` | 동상 (model id 로 `infer_provider_from_model` 자동 매핑) | 동상 | 동상 |
| `claude-cli` | `cli_subprocess.invoke_claude_cli` — `claude --print --output-format text --append-system-prompt <SYS> <USER>` subprocess | Claude Code Max **subscription** (CLI 의 OAuth) | (a) `claude` binary on `$PATH` (b) Claude Code CLI 가 로그인 상태 (c) TTY-less 환경에서 `--print` 모드 작동 (subprocess.run 의 `stdin=` 기본 안전) |
| `openai-codex` (subprocess form) | `cli_subprocess.invoke_codex_cli` — `codex exec --skip-git-repo-check <combined>` subprocess | ChatGPT Plus/Pro **subscription** (CLI 의 OAuth) | (a) `codex` binary on `$PATH` (b) Codex CLI 가 로그인 상태 (c) `--skip-git-repo-check` flag 로 worktree 외부 실행 허용 |

**Cron 환경의 검증 포인트 (OL-A1 구현 시 필수 테스트)**

1. **PATH inheritance** — cron job 의 `$PATH` 가 사용자 셸과 다름. `which claude` / `which codex` 가 cron context 에서 실패 가능 → `GEODE_CLAUDE_CLI_BIN` / `GEODE_CODEX_CLI_BIN` env var override 권장 (이미 `cli_subprocess.py` 지원)
2. **OAuth token freshness** — Claude Code / Codex 의 OAuth token 은 자동 갱신 안 됨. 갱신 만료 시 subscription path fail → `fallback_to_payg` knob (이미 `[self_improving_loop] fallback_to_payg = false` default) 활성화 시 API key 로 폴백 (subscription 소진 graceful)
3. **No TTY** — `claude --print` 가 non-interactive 시 작동 검증 필요. 만약 stdin prompt 발생 시 cron 멈춤 — timeout (180s 기존) 이 회수
4. **Subprocess capture** — `serve` background runner 의 subprocess 출력이 logger 로 가는지 확인 — 안 가면 silent fail risk
5. **autoresearch 별도 인프라 의존성** — `autoresearch/train.py` 가 SubAgent / Petri 같은 GEODE 인프라를 그대로 사용하므로 별도 backend layer 안 필요. 사용자 확정: "autoresearch 는 기존 GEODE 인프라 따라감"

**구현 시 추가 작업**

- `auto_trigger.py` 가 lockfile 획득 후 `SelfImprovingLoopRunner().run_once()` 호출
- runner 가 `_default_llm_call` 호출 → source dispatch 자동
- `tests/test_mutator_auto_trigger.py` 에 4 backend mock 모두 fixture 화 (api_key / auto / claude-cli / openai-codex) 후 lockfile + cron tick 검증

**defer 결정**

D2 (data-threshold trigger) + D3 (`/self-improving run` manual override) 은 D1 (cron) 안정 후 OL-A1.2 follow-up. 4 backend 검증을 D1 단독으로 끝내면 D2/D3 는 trigger 채널만 추가, backend 검증 재실행 불필요.

#### OL-A2 — Phase E 2nd audit pass (wiring sprint)

| 항목 | 내용 |
|---|---|
| 영향 | data run (코드 변경 ~0). gen-1 seed cohort 평가 + baseline 회귀 검증. wiring sprint 의 final closure |
| 의존 | OL-A1 활성 권장 (auto trigger 가 첫 mutation iteration 생성 후 평가) |
| 차단 효과 해소 | 2026-05-19 wiring sprint plan 완결 |

#### OL-A3 — `geode outer-bundle <session>` viewer (P2)

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/cli/outer_bundle.py` (신규) + `inspect view` re-export wrapping |
| 출력 | mutation ledger + baseline diff + audit log + session journal 의 통합 viewer |
| 추정 LOC | ~200 |
| 의존 | OL-A1 후 권장 (auto trigger 가 충분한 데이터 생성 후 viewer 유용) |

### C. Cognitive uplift (cognitive-loop-uplift.md 잔여)

#### OL-G — config drift 정렬 (3건 통합)

| 항목 | 내용 |
|---|---|
| G-B | `autoresearch/train.py` 의 `TARGET` / `JUDGE` 하드코드 → `[self_improving_loop.autoresearch] target / judge` config knob |
| G-D | `llm_extract_learning` hook 의 `"glm"` 리터럴 → mutator role manifest |
| G-E | `settings.model` (4-6) vs `routing.toml` (4-7) drift 정렬 |
| 추정 LOC | ~200 통합 |
| 의존 | OL-A1 선행 권장 (scheduler config 와 같은 namespace 정리) |

#### OL-C2' — Reflection node 의 자립 모듈화

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/agent/reflection.py` (신규) — episodic.py 의 docstring 이 "reflection node populates hypotheses" 언급하지만 별도 모듈 부재 |
| 책임 | observe → summarize → update belief → decide 의 명시적 step |
| 추정 LOC | ~180 |
| 의존 | 없음 |

#### OL-C6 — Cognitive loop telemetry

| 항목 | 내용 |
|---|---|
| 영향 | `core/hooks/events.py` 의 HookEvent enum 에 `PERCEIVE / PLAN / ACT / OBSERVE / REFLECT / UPDATE_MEMORY` 6종 추가 + agentic loop 의 해당 지점에서 emit |
| 추정 LOC | ~100 |
| 의존 | OL-C2' 후 권장 |

### D. Petri 잔여

#### OL-P1 — P3-b 후속 (4-dimension real-mode run)

| 항목 | 내용 |
|---|---|
| 상태 | 이전 세션 BLOCKED (Anthropic credit) — credit 회복 시 진행 |
| 의존 | external (operator credit) |

#### OL-P2 — Petri quota knobs 실제 wiring

| 항목 | 내용 |
|---|---|
| 영향 | `[self_improving_loop] warn_threshold / abort_threshold` 가 현재 schema 만 있고 enforcement 없음 — `core/llm/quota.py` 에 actual gate 추가 |
| 추정 LOC | ~100 |

## Tier 2 — Inner Loop (Hermes-style memory/recall, 5 항목)

#### IL-1 — Phase 2 platform-aware system prompt

| 항목 | 내용 |
|---|---|
| 상태 | **WIP 보존** — `feature/hermes-2-platform-aware` 브랜치에 `platform_hints.py` + `model_guidance.py` 작성 완료 (commit c7958296). 잔여: `system_prompt.py` wiring + tests |
| 추정 LOC 잔여 | ~100 |

#### IL-2 — Phase 1d.2 cross-project global.db + async indexer

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/memory/search_index.py` (신규) + `core/wiring/bootstrap.py` (SearchIndexer 라이프사이클) + `core/cli/commands/reindex.py` (신규) |
| 추정 LOC | ~500 |

#### IL-3 — Phase 3 4-phase compaction

| 항목 | 내용 |
|---|---|
| 영향 | `core/context/compactor.py` 전체 교체. orphan tool result + boundary + summarize + carry-forward |
| 추정 LOC | ~500 |

#### IL-4 — Phase 4 Multi-proc WAL

| 항목 | 내용 |
|---|---|
| 영향 | `PRAGMA journal_mode=WAL` + multi-process safe pattern + lock acquisition |
| 추정 LOC | ~150 |

#### IL-5 — Phase 5+ 임베딩 검색 (deferred)

| 항목 | 내용 |
|---|---|
| 우선순위 | trigram + bm25 가 충분한지 1d.2 활성 후 4주 측정. 불충분 시 진입 |

## Tier 3 — Cognitive Loop (agentic-loop-evolution.md A1-A9, 9 항목)

#### CL-A7 — Wall-clock + Token Budget Forcing

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/agent/budget.py` (신규) + `AgenticLoop` 통합 |
| Knobs | `max_wall_seconds` + `max_thinking_tokens` + s1-style "Wait" injection |
| 측정 | P95 latency under cap |
| 추정 LOC | ~80 |
| 의존 | 없음 (independent foundation) |

#### CL-A6 — Plan/Action Model Separation

| 항목 | 내용 |
|---|---|
| 영향 | `core/llm/router.py` + `core/config.py` + `AgenticLoop` model dispatch |
| Pattern | Plan=Opus, Action=Sonnet/Haiku (Cursor Composer 13x, Aider architect/editor) |
| 추정 LOC | ~80 + cost/quality regression tests |
| 의존 | 없음 |

#### CL-A4 — Failure Memory (verbal RL)

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/agent/memory.py` (신규) 또는 `core/memory/session.py` 확장 |
| 핵심 | Self-Reflexion summary 를 episodic 에 누적 + 다음 plan prompt 에 inject. `ConvergenceDetector.recent_errors` partial 위에 build |
| 측정 | iterations-to-resolution 분포 shift left |
| 추정 LOC | ~100 |
| 의존 | EpisodicStore (있음) |

#### CL-A3 — In-loop Verify (Reflexion)

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/agent/verify.py` (신규) + `AgenticLoop` action-end wire |
| 핵심 | LLM judge 가 observed result 를 plan.expected 와 비교 → pass/fail/retry |
| 측정 | 10-task fixture success rate |
| 추정 LOC | ~120 |
| 의존 | 없음 |

#### CL-A1 — Dynamic Replan

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/agent/plan.py` (신규) + `core/cli/agentic_loop.py` 통합 + `core/agent/state.py` plan field |
| 핵심 | 명시적 `Plan{steps, current, completed, abandoned}` + N step 마다 replan |
| 측정 | tokens/task |
| 추정 LOC | ~150 |
| 의존 | CL-A3 권장 (verify result 가 replan trigger) |

#### CL-A2 — Tool Selection as Search

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/agent/tool_search.py` (신규) |
| 핵심 | A*-style policy over tool decision tree (ToolChain* 7.35x speedup) |
| 측정 | total tool calls / task + latency |
| 추정 LOC | ~200 |
| 의존 | CL-A1 + EpisodicStore success_rate signal |

#### CL-A5 — Skill Library Growth (Voyager)

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/skills/auto_skill.py` (신규) + `LOOP_COMPLETE` hook 연결 |
| 핵심 | 성공한 multi-tool sequence detect → SkillRegistry composite skill 자동 등록 |
| 측정 | skill count growth + reuse rate |
| 추정 LOC | ~250 |
| 의존 | CL-A1 (Plan structure) + CL-A4 (success/failure memory) |

#### CL-A9 — External Verifier Integration

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/verification/external.py` (신규) + adapter 들 |
| 핵심 | `VerifierResult{source, verdict, evidence}` first-class. linter / CI / security-scanner consumer |
| 추정 LOC | ~150 + adapters |
| 의존 | CL-A3 (verify hook extension) |

#### CL-A8 — Best-First Tree Search (LATS / AIDE)

| 항목 | 내용 |
|---|---|
| 단계 | **Spike first** — 200 LOC throwaway → 측정 → 채택 결정. 채택 시 ~500-800 LOC full |
| 측정 | success rate × token cost Pareto frontier |
| 의존 | CL-A1 (Plan) + CL-A3 (Verify) + CL-A6 (model separation 으로 비용 제어) 안정 |

## 진행 순서 (recommended)

```
Phase 1 — Outer closure (12 항목, 최우선)
  OL-C1 (emit_eval) → OL-C2 (few-shot writer) → OL-C3 (memory_recall writer)
  → OL-G (config drift) → OL-A1 (auto-trigger) → OL-A2 (Phase E) → OL-A3 (viewer)
  → OL-C2' (Reflection module) → OL-C6 (telemetry) → OL-P2 (quota wiring)
  → [OL-P1 external] → HK-1 release v0.99.27

Phase 2 — Inner Hermes (5 항목)
  IL-1 (Phase 2 finish from WIP) → IL-2 (1d.2) → IL-3 (compaction) → IL-4 (WAL)
  → [IL-5 measure-then-decide]

Phase 3 — Cognitive (9 항목)
  CL-A7 (Budget) → CL-A6 (Plan/Action) → CL-A4 (Failure Memory)
  → CL-A3 (Verify) → CL-A1 (Replan) → CL-A2 (Tool Search)
  → CL-A5 (Skill Library) → CL-A9 (External Verifier)
  → [CL-A8 spike → decision → full]

Housekeeping 병행 — HK-2/3/4 적절 시점
```

## 추정 총합

| Tier | 항목 | 추정 PR | 추정 LOC |
|---|---|---|---|
| Tier 0 | 4 | 3-4 | ~600 (release infra) |
| Tier 1 | 12 | 8-10 | ~1,600 |
| Tier 2 | 5 | 4-5 | ~1,250 |
| Tier 3 | 9 | 9-12 | ~1,500-2,000 |
| **합계** | **30** | **24-31 PR** | **~5,000 LOC** |

## Reference

- ADR-012 (self-improvement surface tiers)
- ADR-013 (mutation surface JSON schema)
- `docs/plans/2026-05-14-hermes-strengths-absorption.md`
- `docs/plans/2026-05-21-cognitive-loop-uplift.md`
- `docs/plans/agentic-loop-evolution.md`
- `docs/plans/2026-05-19-self-improving-loop-wiring-sprint.md`
- `docs/plans/eval-petri-integration.md`
