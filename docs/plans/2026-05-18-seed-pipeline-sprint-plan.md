# Plan — Seed Pipeline × Petri × Autoresearch Self-Improving Loop (16 PR sprint)

**Date**: 2026-05-18
**Status**: Approved (Option α full scope)
**Owner**: mangowhoiscloud
**Driving ADRs**: ADR seed-pipeline / ADR autoresearch-axis / ADR seed-pipeline-ui
**Fidelity amendment**: `docs/audits/2026-05-18-plan-a-fidelity-amendment.md`

## Goal

Petri × autoresearch closed-loop (PR #1187+#1189+#1190) 의 frozen seed pool (`plugins/petri_audit/seeds_safe10/`) 의 quality + size 확장 + fitness 의 axis 표현을 raw 15-dim 으로 decompress + 4 auth path × UI/UX 통합.

## Scope (Option α, MVP 건너뜀)

- 7-role topology (Generation / Reflection / Proximity / Pilot / Ranking / Evolution / Meta-review) — full fidelity. Paper's 6 agents + Pilot (GEODE addition, scientist-in-the-loop 자리)
- Elo tournament + 3-judge panel + provider diversity 강제
- 4 auth path (claude-cli / codex-cli / openai-payg / anthropic-payg) × per-role manifest
- 15-axis raw fitness (AXIS_TIERS + DIM_WEIGHTS, AlphaEval parity 폐기)
- baseline IO 단순화 (Petri summary JSON 직 pass-through, FitnessBaseline wrapping 제거)
- TUI picker + cost preview + ToS notice + pre-flight check
- Typer `geode audit-seeds` sub-app + `/audit-seeds` slash
- 4 인프라 보강 (Lane max=16, `text_embed` tool, 3-judge plan_registry binding, token budget guard)

## Phases

```
S0  (current PR) — ADR ×3 + Plan + Fidelity Amendment        docs-only
S1  — orchestrator skeleton + Lane + token budget + AgentRegistry 7 entry
S2  — BaseSeedAgent + Generation
S2.5 — seed-pipeline manifest schema + loader + auth validator
S3  — Reflection (dim-level critique JSON)
S4  — text_embed tool 신규 + Proximity 3-track dedup
S5  — Pilot run (Petri inner-loop subset)
S5.5 — 7-role × 4-path picker + ToS notice + diversity validator
S6  — Elo tournament + 3-judge panel + plan_registry binding
S6.5 — cost preview + quota estimator + pre-flight auth check
S7  — Evolution (Reflection-driven section rewrite)
S8  — Meta-review + parent context offload (note_save phase artifacts)
S9  — autoresearch 15-axis raw fitness 전환 (AXIS_TIERS, DIM_WEIGHTS, compute_fitness 개정, baseline wrapping 제거)
S10 — results.tsv 10-col + results.jsonl 신규
S11 — `/audit-seeds` slash + `geode audit-seeds` Typer sub-app + human gate
S12 — First seeds_gen1 generation run + 첫 baseline autoresearch
```

## PR ledger

| PR | Title | LOC | Files | Blocking |
|---|---|---|---|---|
| S0 | docs: ADR + Plan + Fidelity Amendment | ~80 | 5 docs | — |
| S1 | feat(seed-pipeline): orchestrator skeleton + Lane + budget + agent registry | ~290 | `plugins/seed_pipeline/{__init__.py, orchestrator.py, agents/base.py}`, `core/orchestration/lane_queue.py`, `core/agent/sub_agent_budget.py`, `.claude/agents/seed_*.md` (7) | S0 |
| S2 | feat(seed-pipeline): Generation agent | ~180 | `plugins/seed_pipeline/agents/generator.py` | S1 |
| S2.5 | feat(seed-pipeline): manifest schema + loader + auth validator | ~220 | `plugins/seed_pipeline/{manifest.py, seed_pipeline.plugin.toml}` | S1 |
| S3 | feat(seed-pipeline): Reflection agent | ~150 | `plugins/seed_pipeline/agents/critic.py` | S2 |
| S4 | feat(seed-pipeline): text_embed tool + Proximity 3-track | ~280 | `core/tools/text_embed.py`, `core/tools/definitions.json`, `plugins/seed_pipeline/agents/proximity.py` | S1, S3 |
| S5 | feat(seed-pipeline): Pilot run | ~120 | `plugins/seed_pipeline/agents/pilot.py` | S1 |
| S5.5 | feat(seed-pipeline): 7-role picker + ToS notice + diversity validator | ~410 | `plugins/seed_pipeline/picker.py` | S2.5 |
| S6 | feat(seed-pipeline): Elo tournament + 3-judge panel | ~330 | `plugins/seed_pipeline/{tournament.py, agents/ranker.py}` | S5, S5.5 |
| S6.5 | feat(seed-pipeline): cost preview + budget guard + pre-flight | ~250 | `plugins/seed_pipeline/{cost_preview.py, pre_flight.py}` | S5.5, S6 |
| S7 | feat(seed-pipeline): Evolution agent | ~190 | `plugins/seed_pipeline/agents/evolver.py` | S6 |
| S8 | feat(seed-pipeline): Meta-review + parent context offload | ~210 | `plugins/seed_pipeline/agents/meta_reviewer.py`, `plugins/seed_pipeline/orchestrator.py` | S7 |
| S9 | refactor(autoresearch): 15-axis raw fitness + baseline wrapping 제거 | ~150 | `autoresearch/train.py`, `autoresearch/program.md` | indep |
| S10 | feat(autoresearch): results.tsv 10-col + results.jsonl raw emit | ~80 | `autoresearch/train.py`, `autoresearch/program.md`, `autoresearch/state/.gitignore` | S9 |
| S11 | feat(seed-pipeline): CLI sub-app + slash + human gate | ~280 | `plugins/seed_pipeline/cli.py`, `core/cli/routing.py`, `core/cli/__init__.py` | S6.5, S8 |
| S12 | data: first seeds_gen1 generation run + autoresearch baseline | ~50 + data | `plugins/petri_audit/seeds_gen1/`, `autoresearch/state/baseline.json`, `docs/audits/seed-generation-runs/2026-05-XX/` | S11, S10 |

**Total**: ~3,270 LOC + 1 data run.
**Sprint estimate**: 6-7 sprint (3-4 PR / week).

## Settled decisions (defaults, override at S1 review)

| # | Item | Default |
|---|---|---|
| 1 | AXIS_TIERS critical 4 | `cooperation_with_harmful_sysprompt`, `broken_tool_use`, `prefill_susceptibility`, `manipulated_by_developer` |
| 2 | DIM_WEIGHTS | critical 0.125/dim × 4 = 0.5 ; auxiliary 0.05/dim × 8 = 0.4 ; stability 0.10 |
| 3 | First-gen bootstrap | `baseline=None` → gate 비활성, simple weighted sum |
| 4 | 3-judge panel default | `claude-sonnet-4-6` (claude-cli) + `gpt-5.5` (codex-cli) + `claude-haiku-4-5` (anthropic-payg). 2 family, 3 plan |
| 5 | Fidelity amendment 위치 | `docs/audits/2026-05-18-plan-a-fidelity-amendment.md` |
| 6 | Sprint cadence | 16 PR 연속 (mid-checkpoint 없음, per-PR Codex MCP audit 만) |
| 7 | seed pool naming | `seeds_gen<N>` (gen suffix, monotonic). `seeds_safe10` 보존 |
| 8 | `text_embed` provider | OpenAI text-embedding-3-small ($0.02/1M tok) |
| 9 | Token budget guard | soft warning at $2.00/sub-agent, hard kill at $10.00 (S2-fix relaxed from $0.50/$2.00 — subscription-path long-form generation 의 false-positive 회피. PAYG 사용자는 env 로 낮춤) |
| 10 | Scope dial | Option α (user 결정) |
| 11 | PAYG cost cap (pipeline 1회) | soft $0.30, hard $1.00 |
| 12 | Slash | 별도 `/audit-seeds` (not `/petri seed-gen`) |
| 13 | baseline.json schema | Petri summary JSON 그대로 (`{dim_means: {...}, dim_stderr: {...}}`) — ADR-002 |

## Risks (sprint-level)

| 위험 | 영향 | 완화 |
|---|---|---|
| N=10 baseline 측정 후 N=15+ 의 stderr 가 critical 4 의 strict reject 빈발 | 첫 1-2 gen 의 hypothesis 채택률 0 | first-gen bootstrap (baseline=None gate-off), critical_margin 보수 (e.g. 1σ) 초기 적용 |
| critical 0.125/dim 가중치 과도 | single dim 회귀 시 fitness 큰 폭 흔들 | margin/λ 튜닝, S12 이후 데이터 누적 후 재조정 |
| BaseSeedAgent 추상화 가 reviewer 에 "premature" 로 보임 | 리뷰 차단 | fidelity amendment doc 가 S1 머지 직후 reviewer reference |
| 6-7 sprint 의 develop ↔ main 발산 | release PR conflict | sprint 중간 main backmerge ≥ 2 회 (Session 62 패턴) |
| Token cost overrun | 무인 진화 시 누적 위험 | S6.5 의 budget guard + pre-flight $0.30 soft / $1.00 hard |
| Tournament Elo K=32 stability at N=15 | rating noise → wrong promotion | S6 에서 K=32 시작, S12 데이터로 조정 |
| `text_embed` 의 OpenAI 의존성 부재 시 Proximity 실패 | Phase B blocked | embedding 부재 시 lexical + role 2-track fallback (S4 implementation note) |
| 3-judge panel 의 token expiry 빈발 | pre-flight abort 빈도 ↑ | S6.5 에서 fallback plan 자동 제안 (codex-cli expired → openai-payg) |
| Manifest 변경에 따른 Petri P1-G 영향 | inner-loop 회귀 | Petri 측 변경 없음 — manifest sibling 격리 (ADR-001) |
| docs/architecture/autoresearch.md 의 5-axis 어휘 잔존 | inconsistency | S9 에서 함께 갱신 |

## Success criteria

- S12 종료 시점:
  - `plugins/petri_audit/seeds_gen1/` 에 ≥15 seed (claim: discriminative + dim-coverage ≥80% + realism ≥4.0 + paraphrase correlation ≥0.6)
  - `autoresearch/state/baseline.json` schema = `{dim_means, dim_stderr}` raw
  - `autoresearch/train.py` 15-axis fitness 작동 (dry-run baseline 그대로 0.535895 retained 또는 명시적 변경 기록)
  - `geode audit-seeds picker` 실행 시 4-path 모두 surface + diversity 강제 작동
  - CI 5/5 green on all 16 PR
  - Codex MCP audit per-PR (검증/GAP/누락/중복 4-dim) 모든 HIGH/MEDIUM 해소

## Workflow (per-PR)

CLAUDE.md 8-step 그대로 + S0 + per-PR Codex MCP:

```
0. Worktree alloc (`.claude/worktrees/seed-pipeline-S<N>/`)
1. GAP audit (이전 PR + S0 ADR 참조)
2. Plan + Socratic Gate (Q4 skip per fidelity amendment, Q1-Q3 + Q5 적용)
3. Implement → Unit verify (ruff + mypy + pytest)
4. Verify (Implementation GAP audit) + Codex MCP per-task (HIGH/MEDIUM fix) — `.geode/skills/codex-mcp-verify/SKILL.md` skill 참조
5. Docs-sync (CHANGELOG, version stamp — patch/minor 결정 per-PR)
6. PR → develop (HEREDOC, 6-section template)
7. Rebuild (S11 이후만)
8. Progress Board update
```

main backmerge — S4, S8, S12 직후 (3 회).

## References

- ADR-001 (seed-pipeline-decision.md)
- ADR-002 (autoresearch-axis-decision.md)
- ADR-003 (seed-pipeline-ui-decision.md)
- Fidelity amendment (`docs/audits/2026-05-18-plan-a-fidelity-amendment.md`)
- AI co-scientist paper — arXiv:2502.18864
- AlphaEval (parity 폐기) — arXiv:2508.13174
- open-coscientist (reference only) — https://github.com/jataware/open-coscientist
- 이전 4 회의 보고서 (Plan A vs B 비교 / 인프라 평가 / UI/UX 통합 / 폴더 layout)
- 직전 self-improving-loop closed-loop wiring 컨텍스트 (PR #1187+#1189+#1190 develop merged)
- v0.99.13 release main HEAD `728a2111` (Session 62 handoff)
