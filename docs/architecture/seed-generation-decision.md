# ADR — Seed Generation Architecture

> **Status**: Accepted (2026-05-18)
> **Scope**: GEODE seed regeneration pipeline. co-scientist (arXiv:2502.18864) 의 6-agent generate-debate-evolve loop 를 GEODE sub-agent 인프라 위에 port. Petri × autoresearch 의 frozen seed pool (`plugins/petri_audit/seeds_safe10/`) 의 quality + size 확장.

## Context

Petri × autoresearch closed-loop (PR #1187+#1189+#1190) 가 wire 되었으나 fitness 의 입력 신호 = N=10 seed × 19 dim rubric. N=10 의 stderr 가 mean 의 10–30%, 15 substantive dim 중 fitness 입력은 5 dim 뿐. seed pool 의 quality (discriminative power + dim coverage + realism + stability) 와 size 모두 확장 필요.

AI co-scientist paper 의 6-agent topology (Generation / Reflection / Ranking / Evolution / Proximity / Meta-review) + Elo tournament 가 본 문제와 1:1 매핑. open-coscientist (Jataware, LangGraph 1.0) 가 동등 구현 보유 (MIT + Commons Clause).

## Decision

**Port (자체 구현), vendor 안 함**. GEODE 의 `SubAgentManager` + `IsolatedRunner` + `AgentRegistry` + `HookSystem` + `TaskGraph` 인프라 위에 **7-role topology** (paper 의 6-agent + Pilot — paper 의 scientist-in-the-loop 자리를 automated Petri audit 으로 치환) 자체 구현. LangGraph / litellm / LangSmith 의존성 추가 없음.

**위치**: `plugins/seed_generation/` (sibling to `plugins/petri_audit/`, not nested). 명시적 `depends = ["petri-audit"]` 으로 sibling 의존 표명.

**Full-fidelity**: 7 role 모두 실제 구현 (Meta-review stub 금지). Elo tournament + 3-judge panel + provider diversity 강제. CLAUDE.md 의 Socratic Q4 simplicity 제약은 본 sprint 한정 해제 (별도 fidelity amendment doc 참조).

### Operational defaults (settled, 본 ADR 의 binding)

| Item | Default | 사유 |
|---|---|---|
| Token budget guard | soft warning at $0.50 / sub-agent (cumulative), hard kill at $2.00 | 무인 진화 시 runaway 회피. config 가능 (`SEED_PIPELINE_BUDGET_SOFT_USD` / `_HARD_USD` env). |
| Pipeline run budget cap | soft $0.30 / gen, hard $1.00 / gen | tournament 60 match × 3 judge × ~$0.02 = ~$3.6 의 worst-case 제어. config 가능. |
| Concurrency Lane | `seed-generation` Lane, `max_concurrent=16` (기본 `global` Lane 의 max=8 별도) | 15-20 candidate parallel + tournament match 의 wall-time 감소 |
| Sub-agent recursion depth | `max_depth=1` (현 SubAgentManager 기본) | parent AgenticLoop central supervisor. 6-phase 모두 표현 가능 |
| Bootstrap (첫 generation) | `baseline=None` → cross-axis gate 비활성, simple weighted sum 반환 | baseline 측정 자체가 첫 gen 의 결과. ADR-002 §5 참조 |

## Decision Drivers

- **No external dep**: GEODE 본체에 LangGraph 없음. seed-generation 만 LangGraph 추가 시 본체 분리 어색. self-host SubAgentManager 가 이미 6-phase 의 90% 받침.
- **Frozen ground-truth contract**: seed pool 은 self-improving-loop agent 가 mutate 불가. pipeline 은 user-trigger only, autoresearch loop 외부 별도 phase.
- **Co-evolution risk 완화**: Generator + Pilot judge 가 다른 family. 3-judge panel 의 provider diversity 강제 (최소 2 family).
- **Karpathy 단일 file pattern 호환**: pipeline 결과 = `plugins/petri_audit/seeds_gen<N>/` 새 디렉토리. autoresearch 의 `program.md` Setup §3 가 seed pool path 만 갱신.

## Topology

```
[user trigger] geode audit-seeds generate --target <dim> --budget 30m --gen <N>
       ↓
[Phase A] Generation × 15 (parallel sub-agent spawn)
       ↓
[Phase B] Proximity dedup (embedding + lexical + role 3-track)
       ↓
[Phase C] Reflection × survivors (per-candidate critique, dim-level)
       ↓
[Phase D] Pilot run (1 candidate × 2 model × 1 paraphrase, Petri inner-loop subset)
       ↓
[Phase E] Elo tournament (pairwise match, K=32, 3-judge panel with diversity)
       ↓
[Phase F] Evolution × top-K (Reflection-driven section rewrite) → re-pilot
       ↓
[Phase G] Meta-review (batch coverage + dim gap + 다음 gen prior)
       ↓
[Human gate] user 가 top-N 명시 승인 → `plugins/petri_audit/seeds_gen<N>/` 저장
```

Parent `AgenticLoop` 가 central orchestrator. `depth=1` 한계 내에서 phase 별 `delegate(tasks=[…])` 호출. depth=2 불필요 (LangGraph supervisor 패턴과 동일).

## Considered Options

1. **Port + GEODE-native** (✓ Accepted): 자체 구현, 0 dep, sibling plugin.
2. Vendor `open-coscientist`: ~150 LOC bridge, langgraph+litellm+langsmith 4 dep. License Commons Clause 제약. Rejected — GEODE 본체에 LangGraph 도입 부담 + license 회색지대.
3. Nested under `petri_audit`: `plugins/petri_audit/seed_generation/`. Rejected — manifest 비대화, 향후 분리 가능성 차단.
4. MVP (Generation + Pilot 만): Rejected — co-scientist 의 generate-debate-evolve 가 분리 작동해야 effect. partial port = stub disguise.

## Consequences

### 긍정

- GEODE 본체 의존성 영향 0.
- HookSystem / TaskGraph / IsolatedRunner / AgentRegistry 의 기존 무기 그대로 활용 — observability + budget + sandbox 의 frontier-level 기능 즉시 적용.
- `geode audit-seeds` Typer sub-app 으로 user-facing surface 명확.
- 향후 별도 PyPI 배포 가능 (paperclip-style).

### 부정

- ~2,000 LOC 신규 코드 + 600 LOC UI/UX. 6-7 sprint 분량.
- depth=1 한계로 parent context 누적 — phase 마다 결과를 disk 저장 + summary 만 conversation 에 keep 필요 (`note_save` tool 활용).
- 4 항목 인프라 보강 사전 필요 (Lane max=16 신규, `text_embed` tool 신규, 3-judge plan_registry binding, token budget guard).

### 중립

- 7-role topology 의 BaseSeedAgent 추상화 도입 (paper 6-agent symmetry + GEODE Pilot). premature abstraction 으로 보일 수 있으나 paper 의 multi-way role symmetry 가 정당화. fidelity amendment doc 에 명시.

## Implementation pointers

- 디렉토리 layout: `plugins/seed_generation/{manifest.py, cli.py, orchestrator.py, agents/, fitness.py, tournament.py, cost_preview.py, picker.py, pre_flight.py}`
- AgentDefinition: `plugins/seed_generation/agents/{generator,critic,proximity,pilot,ranker,evolver,meta_reviewer,supervisor}.md` YAML 8 file (CSP-9, 2026-05-22)
- Pool storage: `plugins/petri_audit/seeds_gen<N>/` (frozen, monotonic gen-suffix). `seeds_safe10` 보존.
- Runtime artifacts: `~/.geode/seed-generation/<run_id>/` (gitignored).
- Audit trail: `docs/audits/seed-generation-runs/<YYYY-MM-DD>/` (committed).

## References

- AI co-scientist paper — arXiv:2502.18864 (Google Research, 2025-02-26)
- open-coscientist v0.2.0 — https://github.com/jataware/open-coscientist (reference only, not vendored)
- AlphaEval 5-axis (parity 폐기 — ADR-002 참조) — arXiv:2508.13174
- GEODE SubAgentManager — `core/agent/sub_agent.py:1-114`
- Petri inner-loop — `plugins/petri_audit/` (P1-A~G manifest pattern)
- Outer-loop SOT — `autoresearch/program.md`
- Petri × autoresearch closed-loop — `[[project_autoresearch_self_improving_loop]]`
- Plan A revised 누적 회의록 — 직전 4 보고서 (Plan A vs B, 인프라 평가, UI/UX 통합, 폴더 layout)
