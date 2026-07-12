# GEODE Eval Roadmap

> Action/tool-execution 4종 벤치마크. GEODE의 quality ratchet(P4)에 통합 예정.
> 각 문서는 **사례 + 필요 인프라 + 4-Phase 진행 시나리오**를 담음.
> 마지막 갱신: 2026-07-13

## Raw artifact repository

Heavy verifier output, transcripts, and Crucible campaign state live in the
separate append-only
[`mangowhoiscloud/geode-eval-artifacts`](https://github.com/mangowhoiscloud/geode-eval-artifacts)
repository. GEODE keeps interpretation, comparison boundaries, and digest
pointers under `docs/eval/`; the artifact repository keeps the bytes behind
those claims. See [External Evaluation Artifact Repository](external-artifact-repository.md)
for path mappings, disclosure rules, and the publication manifest scaffold.

## 채택 4종

| 벤치 | Trust | 측정 | GEODE에서의 역할 | 문서 |
|---|---|---|---|---|
| τ²-bench | HIGH | conversational tool-use + DB state-diff (native pass@k) | **accuracy 헤드라인** | [tau2-bench.md](tau2-bench.md) |
| Terminal-Bench 2.0 | HIGH | shell 자동화 (Docker + tmux + post-run test) | **frontier 시스템 카드 비교 신호** | [terminal-bench-2.md](terminal-bench-2.md) |
| Toolathlon | HIGH | 32 real apps × 604 MCP tools × 20턴 long-horizon | **야심 신호 (현 SOTA 38.6%)** | [toolathlon.md](toolathlon.md) |
| HAL Reliability | HIGH | accuracy 위에 consistency/robustness/safety 레이어 | **차별화 — LangGraph reliability 스토리** | [hal-reliability.md](hal-reliability.md) |

## GEODE 자체 평가 레이어

| 레이어 | 측정 | 역할 |
|---|---|---|
| GUI Trajectory Eval | observation coverage, classified failures, coordinate sanity, final screenshot availability | `computer`/`computer_use` trajectory rows를 모델 prose와 분리해 사후 평가 |
| Capability/Evidence Preflight | provider/source/tool support, required evidence classes | 작업 시작 전 route mismatch를 드러내고 evidence ledger에 남김 |
| Frontier agentic tool-use benchmark cases | MCPMark/BFCL V4/tau2 공개 사례와 GEODE 측정 계약 | GPT-5.5 subscription 결과를 공개 baseline과 섞기 전 비교 가능성 분리 |
| Benchmark Publishing Cycle | live benchmark run -> internal ledger -> official docs -> PR -> Pages deploy | 실측과 공식문서 배포를 하나의 반복 가능한 사이클로 고정 |

참고: [frontier-agentic-tool-use-benchmark-cases.md](frontier-agentic-tool-use-benchmark-cases.md)
운영 스캐폴드: [benchmark-publishing-cycle.md](benchmark-publishing-cycle.md),
[benchmark-run-record.template.md](benchmark-run-record.template.md)

## 다음 측정 큐

현재 남은 agentic tool-use benchmark는 아래 순서로 진행한다. 사용자가
`tau2-bench`를 2순위로 올리도록 지정했으므로, BFCL V4는 tau2 smoke와
Telecom small run 이후로 둔다.

| 순위 | 벤치 | 첫 목표 | 완료 기준 |
|---:|---|---|---|
| 1 | MCPMark Verified | available local standard services, then blocked services as infra follow-up | GEODE adapter로 filesystem/postgres/github verifier-backed result 생성, MCPMark Verified와 `filesystem/easy`를 분리 기록 |
| 2 | τ²-bench | `mock` smoke with `geode_agent` + `geode_user` over subscription, then Telecom small run; native tau2 `gpt-4.1` / `gpt-5.2` user-simulator runs are optional comparator tracks | tau2 result directory와 domain split을 보존하고, user route / trial 수를 public page에 명시 |
| 3 | BFCL V4 | Agentic subset first | native/prompt function-calling route와 aggregation을 고정한 뒤 result/score artifact 보존 |
| 4 | HAL Reliability | tau-bench airline single-rerun smoke | τ² adapter 재사용 여부와 rerun consistency schema 확인 |
| 5 | Terminal-Bench 2.0 | 1-task Docker/tmux smoke | post-run test artifact와 shell transcript 보존 |
| 6 | Toolathlon | credential-free or lowest-credential smoke | MCP app surface, turn cap, and credential caveats 기록 |

## Public benchmark serving contract

사용자가 검토한 `MCPMark: filesystem/easy` 페이지 구성을 표준으로 삼는다.
benchmark navigation은 짧은 suite label만 보여도 되지만, 본문은 숫자만
보여주는 dashboard가 아니라 재현 가능한 run record여야 한다.

| Section | Required content |
|---|---|
| Result summary | benchmark, suite/domain, run date, harness revision, model route, task count, headline score |
| Comparability | directly comparable / directional / not comparable targets separated |
| Run command | command, auth placeholder, subscription/API caveat |
| Artifact | raw result directory, transcript/log, verifier output |
| Task/domain rows | PASS/FAIL, reward, termination, duration, rounds/tokens when available |
| Interpretation | failure cause, adapter limitation, next measurement |

Current public routes:

| Route | Role |
|---|---|
| `/docs/benchmarks/mcpmark/filesystem-easy` | reference detailed run record |
| `/docs/benchmarks/mcpmark/verified-available` | MCPMark standard filesystem/postgres/github available-services run |
| `/docs/benchmarks/mcpmark/service-matrix` | MCP task counts, credentials, infra blockers, adapter coverage |
| `/docs/benchmarks/tau2/mock-smoke` | single mock verifier-backed run |
| `/docs/benchmarks/tau2/domain-smoke` | multi-domain smoke matrix and caveats |

## 의존성 그래프

```
τ²-bench 어댑터 (Phase 1)
    ↓ 재사용
HAL Reliability (τ-bench airline rerun) ← 절반 무료
```

τ² 어댑터를 먼저 만들면 HAL Reliability의 tau-bench 부분이 그대로 따라옴.
장기 로드맵의 lift 순서는 **τ² → HAL Reliability → Terminal-Bench →
Toolathlon**이지만, 현재 agentic tool-use 3종 측정 큐에서는 MCPMark
Verified 다음에 τ²-bench를 둔다.

## 채택 안 한 것

| 벤치 | 사유 |
|---|---|
| AgentBench (THUDM) | 2024 이후 신규 task 없음, 사실상 죽음 |
| WebArena / VWA | 2026-04 UC Berkeley CRDI가 8개 web-agent 벤치 모두 `file://` reward-hack 입증 |
| SWE-Lancer | 2025-07 이후 commit 없음, OpenAI도 GDPval로 이전 |
| MLE-Bench | 2026-04-24 v2 대비로 leaderboard 일시 중단 |
| AppWorld | 2026-02 이후 maintenance only, frontier 거의 풀어버림 |
| BrowseComp / GAIA / SimpleQA | QA — GEODE 행동 기반 루프와 미스핏 |
| OSWorld-Verified | GUI trajectory schema added; adapter pending live sandbox/browser-desktop E2E |
| BFCL V4 | 보조 회귀 게이트 후보 — 1차 4종에서 제외, 필요 시 5번째로 |
| GDPval / MCP-Atlas | OpenAI/Anthropic 내부 전용, 못 돌림 |

## Cross-Bench Cost & CI 요약

| 벤치 | Smoke 비용 | Full run 비용 | CI 적합도 |
|---|---|---|---|
| τ²-bench | <$3 | $200-400 | GHA (smoke), VM (full) |
| Terminal-Bench 2.0 | <$5 | $30-400 | VM (Docker 필요) |
| Toolathlon | <$1 | $80-200+ | **VM only** (32 MCP + real creds) |
| HAL Reliability | <$2 | $150-500 (5×) | VM (full), GHA (single rerun) |

## Quality Ratchet 통합 안 (Phase 3 통합 후)

| 트리거 | 실행 | 임계 |
|---|---|---|
| Per-PR | τ² airline 5-task smoke | pass^1 −3pp 시 차단 |
| Weekly (develop) | τ² 4-domain × 1 trial | telecom −3pp 시 알림 |
| Monthly (main) | HAL Reliability 5-rerun + Toolathlon 15-task | accuracy −3pp / consistency −0.05 / robustness −0.05 시 release block |
| Quarterly | Terminal-Bench 2.0 89-task full + Toolathlon 109-task full | 베이스라인 갱신 |

## 변경 이력

| 일자 | 변경 |
|---|---|
| 2026-07-10 | MCPMark blocked 사례 해소: notion 세션 만료 원인 확정·재발급 후 easy smoke 1/1, github `GITHUB_EVAL_ORG` 영속화(State Duplication Error 6건 원인 제거), postgres 컨테이너 복구, `--agent geode` 커밋 런처 추가, playwright 실행 준비 확인. 잔여 blocked=`playwright_webarena`(WebArena 이미지 ~100GB, 로컬 디스크 초과). Agent-World 비교 런북 추가 |
| 2026-07-03 | 남은 벤치마크 측정 큐를 추가하고 `tau2-bench`를 2순위로 승격 |
| 2026-07-04 | MCPMark standard available-services run 추가: filesystem 25/30, postgres 20/21, github 19/23, measured total 64/74 |
| 2026-07-03 | Benchmark serving page contract와 MCPMark/tau2 coverage 페이지 계획 추가 |
| 2026-07-03 | 최신 tau2 하네스의 `gpt-5.2` user simulator 권장 설정을 별도 비교군으로 보정 |
| 2026-07-03 | Benchmark Publishing Cycle 스캐폴드와 run-record 템플릿 추가 |
| 2026-07-03 | MCPMark filesystem easy에서 GEODE + GPT-5.5 xhigh 10/10 실측 및 EOF offload 결과 기록 |
| 2026-07-02 | GPT-5.5 subscription 측정 준비용 MCPMark/BFCL V4/tau2 공개 사례 ledger 추가 |
| 2026-05-07 | 초기 작성 — 4종 채택, 각 벤치별 사례/인프라/시나리오 |
