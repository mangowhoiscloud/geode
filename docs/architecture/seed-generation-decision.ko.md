# ADR -- Seed Generation 아키텍처

> [English](seed-generation-decision.md) | **한국어**

> **Status**: Accepted (2026-05-18)
> **Scope**: GEODE seed 재생성 pipeline. co-scientist(arXiv:2502.18864)의 6-agent generate-debate-evolve loop를 GEODE sub-agent 인프라 위에 port합니다. Petri × autoresearch의 frozen seed pool(`plugins/petri_audit/seeds_safe10/`)의 quality + size를 확장합니다.

## 컨텍스트

Petri × autoresearch closed-loop(PR #1187+#1189+#1190)가 wire되었으나, fitness의 입력 신호는 N=10 seed × 19 dim rubric입니다. N=10의 stderr가 mean의 10–30%이고, 15개 substantive dim 중 fitness 입력은 5 dim뿐입니다. seed pool의 quality(discriminative power + dim coverage + realism + stability)와 size 모두 확장이 필요합니다.

AI co-scientist 논문의 6-agent topology(Generation / Reflection / Ranking / Evolution / Proximity / Meta-review) + Elo tournament가 이 문제와 1:1로 매핑됩니다. open-coscientist(Jataware, LangGraph 1.0)가 동등한 구현을 보유합니다 (MIT + Commons Clause).

## 결정

**Port(자체 구현)하며, vendor하지 않습니다**. GEODE의 `SubAgentManager` + `IsolatedRunner` + `AgentRegistry` + `HookSystem` + `TaskGraph` 인프라 위에 **7-role topology**를 자체 구현합니다 (논문의 6-agent + Pilot. 논문의 scientist-in-the-loop 자리를 automated Petri audit으로 치환). LangGraph / litellm / LangSmith 의존성 추가는 없습니다.

**위치**: `plugins/seed_generation/` (`plugins/petri_audit/`의 sibling, nested 아님). 명시적 `depends = ["petri-audit"]`으로 sibling 의존을 표명합니다.

**Full-fidelity**: 7 role 모두 실제로 구현합니다 (Meta-review stub 금지). Elo tournament + 3-judge panel + provider diversity 강제. CLAUDE.md의 Socratic Q4 simplicity 제약은 본 sprint에 한해 해제합니다 (별도 fidelity amendment doc 참조).

### 운영 기본값 (확정, 본 ADR의 binding)

| Item | Default | 사유 |
|---|---|---|
| Token budget guard | soft warning at $0.50 / sub-agent (cumulative), hard kill at $2.00 | 무인 진화 시 runaway 회피. config 가능 (`SEED_PIPELINE_BUDGET_SOFT_USD` / `_HARD_USD` env). |
| Pipeline run budget cap | soft $0.30 / gen, hard $1.00 / gen | tournament 60 match × 3 judge × ~$0.02 = ~$3.6의 worst-case 제어. config 가능. |
| Concurrency Lane | `seed-generation` Lane, `DEFAULT_SEED_PIPELINE_CONCURRENCY` (currently 50, raised from 16 by PR-LANE-CAP-50 2026-05-27); `global` Lane과 ceiling 공유 (`DEFAULT_GLOBAL_CONCURRENCY`도 50) | 50 candidate 병렬 + tournament match의 wall-time 감소. per-adapter lanes 50도 동일 ceiling |
| Sub-agent recursion depth | `max_depth=1` (현 SubAgentManager 기본) | parent AgenticLoop이 central supervisor. 6-phase 모두 표현 가능 |
| Bootstrap (첫 generation) | `baseline=None` → cross-axis gate 비활성, simple weighted sum 반환 | baseline 측정 자체가 첫 gen의 결과. ADR-002 §5 참조 |

## 결정 동인

- **No external dep**: GEODE 본체에 LangGraph가 없습니다. seed-generation만 LangGraph를 추가하면 본체 분리가 어색해집니다. self-host SubAgentManager가 이미 6-phase의 90%를 지원합니다.
- **Frozen ground-truth contract**: seed pool은 self-improving-loop agent가 mutate할 수 없습니다. pipeline은 user-trigger 전용이며, autoresearch loop 외부의 별도 phase입니다.
- **Co-evolution risk 완화**: Generator + Pilot judge가 서로 다른 family입니다. 3-judge panel의 provider diversity를 강제합니다 (최소 2 family).
- **Karpathy 단일 file 패턴 호환**: pipeline 결과는 `plugins/petri_audit/seeds_gen<N>/` 새 디렉토리입니다. autoresearch의 `program.md` Setup §3는 seed pool path만 갱신합니다.

## 토폴로지

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
[Human gate] user가 top-N 명시 승인 → `plugins/petri_audit/seeds_gen<N>/` 저장
```

Parent `AgenticLoop`이 central orchestrator입니다. `depth=1` 한계 내에서 phase별로 `delegate(tasks=[…])`를 호출합니다. depth=2는 불필요합니다 (LangGraph supervisor 패턴과 동일).

## 검토한 옵션

1. **Port + GEODE-native** (✓ Accepted): 자체 구현, 0 dep, sibling plugin.
2. Vendor `open-coscientist`: ~150 LOC bridge, langgraph+litellm+langsmith 4 dep. License는 Commons Clause 제약. Rejected. GEODE 본체에 LangGraph 도입 부담 + license 회색지대.
3. `petri_audit` 아래 nested: `plugins/petri_audit/seed_generation/`. Rejected. manifest 비대화, 향후 분리 가능성 차단.
4. MVP (Generation + Pilot만): Rejected. co-scientist의 generate-debate-evolve가 분리 작동해야 효과가 있습니다. partial port = stub disguise.

## 결과

### 긍정

- GEODE 본체 의존성 영향 0.
- HookSystem / TaskGraph / IsolatedRunner / AgentRegistry의 기존 무기를 그대로 활용합니다. observability + budget + sandbox의 frontier급 기능이 즉시 적용됩니다.
- `geode audit-seeds` Typer sub-app으로 user-facing surface가 명확합니다.
- 향후 별도 PyPI 배포가 가능합니다 (paperclip-style).

### 부정

- ~2,000 LOC 신규 코드 + 600 LOC UI/UX. 6-7 sprint 분량.
- depth=1 한계로 parent context가 누적됩니다. phase마다 결과를 disk에 저장하고 summary만 conversation에 keep해야 합니다 (`note_save` tool 활용).
- 4개 항목의 인프라 보강이 사전에 필요합니다 (Lane max=16 신규, `text_embed` tool 신규, 3-judge plan_registry binding, token budget guard).

### 중립

- 7-role topology의 BaseSeedAgent 추상화를 도입합니다 (논문 6-agent symmetry + GEODE Pilot). premature abstraction으로 보일 수 있으나 논문의 multi-way role symmetry가 정당화합니다. fidelity amendment doc에 명시합니다.

## 구현 포인터

- 디렉토리 layout: `plugins/seed_generation/{manifest.py, cli.py, orchestrator.py, agents/, fitness.py, tournament.py, cost_preview.py, picker.py, pre_flight.py}`
- AgentDefinition: `plugins/seed_generation/agents/{generator,critic,proximity,pilot,ranker,evolver,meta_reviewer,supervisor}.md` YAML 8 file (CSP-9, 2026-05-22)
- Pool storage: `plugins/petri_audit/seeds_gen<N>/` (frozen, monotonic gen-suffix). `seeds_safe10`은 보존합니다.
- Runtime artifacts: `~/.geode/seed-generation/<run_id>/` (gitignored).
- Audit trail: `https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/main/sil/audit-reports/seed-generation-runs/<YYYY-MM-DD>/` (committed).

## 참고 자료

- AI co-scientist 논문 -- arXiv:2502.18864 (Google Research, 2025-02-26)
- open-coscientist v0.2.0 -- https://github.com/jataware/open-coscientist (reference only, not vendored)
- AlphaEval 5-axis (parity 폐기, ADR-002 참조) -- arXiv:2508.13174
- GEODE SubAgentManager -- `core/agent/sub_agent.py:1-114`
- Petri inner-loop -- `plugins/petri_audit/` (P1-A~G manifest 패턴)
- Outer-loop SOT -- `core/self_improving/program.md`
- Petri × autoresearch closed-loop -- `[[project_autoresearch_self_improving_loop]]`
- Plan A revised 누적 회의록 -- 직전 4개 보고서 (Plan A vs B, 인프라 평가, UI/UX 통합, 폴더 layout)
