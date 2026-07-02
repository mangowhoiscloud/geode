# GEODE Eval Roadmap

> Action/tool-execution 4종 벤치마크. GEODE의 quality ratchet(P4)에 통합 예정.
> 각 문서는 **사례 + 필요 인프라 + 4-Phase 진행 시나리오**를 담음.
> 마지막 갱신: 2026-05-07

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

참고: [frontier-agentic-tool-use-benchmark-cases.md](frontier-agentic-tool-use-benchmark-cases.md)

## 의존성 그래프

```
τ²-bench 어댑터 (Phase 1)
    ↓ 재사용
HAL Reliability (τ-bench airline rerun) ← 절반 무료
```

τ² 어댑터를 먼저 만들면 HAL Reliability의 tau-bench 부분이 그대로 따라옴. 우선순위:
**τ² → HAL Reliability → Terminal-Bench → Toolathlon** (lift 가벼운 순).

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
| 2026-07-03 | MCPMark filesystem easy에서 GEODE + GPT-5.5 xhigh 10/10 실측 및 EOF offload 결과 기록 |
| 2026-07-02 | GPT-5.5 subscription 측정 준비용 MCPMark/BFCL V4/tau2 공개 사례 ledger 추가 |
| 2026-05-07 | 초기 작성 — 4종 채택, 각 벤치별 사례/인프라/시나리오 |
