# Fidelity amendment — Plan A seed-pipeline sprint 한정 (CLAUDE.md + Claude Code system-prompt 일부)

**Date**: 2026-05-18
**Scope**: Seed Pipeline sprint S1-S12 (16 PR)
**Sunset**: S12 merge to main → 본 amendment 만료, CLAUDE.md 본래 규칙 복귀.

## 배경

co-scientist (arXiv:2502.18864) 의 6-agent generate-debate-evolve loop 를 GEODE 의 sub-agent 인프라 위에 port 하는 작업 (ADR-001 ~ ADR-003 + Plan).

CLAUDE.md 의 simplicity / minimum-viable 제약을 그대로 적용하면 7 role 중 일부 (특히 Meta-review, Proximity 의 3-track dedup, Evolution 의 section-wise rewrite) 가 stub 으로 떨어질 위험. paper 의 mechanism 분리가 깨지면 generate-debate-evolve 의 효과 자체가 사라짐.

본 amendment 는 sprint 한정으로 simplicity 규칙 일부를 해제, deception-prevention 규칙은 강화.

## 해제 대상 (sprint 한정)

### CLAUDE.md 규칙

| 위치 | 원문 | 본 sprint 적용 |
|---|---|---|
| `CLAUDE.md:170` `### 2. Plan + Socratic Gate` Q4 | "What is the simplest implementation? (P10 Simplicity Selection) Adopt minimum changes only" | **Skip Q4**. 7-role topology (paper 의 6-agent + Pilot) 의 paper-defined contract 가 task scope. Q1-Q3 + Q5 만 적용. |

### Claude Code system-prompt 규칙 (CLAUDE.md 외 source)

본 sprint 의 Code agent 의 system prompt 는 본 amendment 의 해제를 인식하고 다음 행동을 정상으로 판정.

| 시스템 prompt 원문 | 본 sprint 적용 |
|---|---|
| "Don't add features, refactor, or introduce abstractions beyond what the task requires" | 본 sprint 의 task = ADR-001 의 7 role + Elo tournament + 3-judge panel + manifest + picker + cost preview + pre-flight. 본 ADR 범위 전부가 task. |
| "Three similar lines is better than premature abstraction" | `BaseSeedAgent` 추상화 (`plugins/seed_pipeline/agents/base.py`) 허용. paper 의 6-way symmetry from arXiv:2502.18864 Figure 1. premature 아닌 structural. |
| "Don't design for hypothetical future requirements" | seed pool naming `seeds_gen<N>` monotonic 은 hypothetical future 아닌 paper 의 cumulative-generation 패턴 직접 구현. |

## 강화 대상 (sprint 한정 + 영구)

| CLAUDE.md 위치 | 원문 | 본 sprint 적용 |
|---|---|---|
| `### Refactoring Deception Prevention` 의 Stub disguise | "No claiming extraction is complete with empty modules (`pass` only)" | **7 role 모두 의미 있는 output** — 6 role 은 실제 LLM 호출, Proximity 1 role 만 embedding tool (`text_embed`) 호출. 본 sprint 의 본질이 stub 회피. PR-by-PR Codex MCP audit 가 stub 검출. |
| Partial implementation disguise | 엄격 | S2-S8 의 각 agent PR 이 본체 + tests + docs 모두 포함. stub PR 금지. |
| Original residue | 엄격 | S9 의 `FitnessBaseline` dataclass 제거 후 `baseline_from_summary` + `_load_baseline` 잔존 금지. import 흔적까지 제거. |
| Zero-context verification | 엄격 + 매 PR 마다 | Codex MCP `gpt-5.2-codex` 가 PR diff + ADR 참조 + 잔존 4-dim (검증/GAP/누락/중복) 확인. |

## 유지 대상 (해제 X)

| CLAUDE.md 위치 | 원문 | 사유 |
|---|---|---|
| Git CANNOT 전 항목 | worktree, no direct push, PR → CI → merge | process safety |
| Quality CANNOT 전 항목 | lint/type/test 0 errors | ratchet |
| Docs CANNOT 전 항목 | CHANGELOG, version sync | release discipline |
| Wiring Verification | Read-Write parity, Hook registration, ContextVar injection, Singleton lifecycle | architectural integrity |
| Per-task Codex MCP verification | `.geode/skills/codex-mcp-verify/SKILL.md` | 4-dim 검증/GAP/누락/중복 |
| PR template (Summary/Why/Changes/GAP/Verification/Reference) | | |
| 5-location version stamp | pyproject + CLAUDE.md + README + README.ko + CHANGELOG | release discipline |

## Reviewer guidance

본 sprint 의 PR review (사람 또는 Codex MCP) 시 다음 패턴을 **정상**으로 판정:

1. `plugins/seed_pipeline/agents/base.py` 의 `BaseSeedAgent` 추상 클래스 — 7 role 공통 contract 표현 (paper 6 + GEODE Pilot).
2. 7 role 각자가 `BaseSeedAgent` 상속 — 본 sprint 의 핵심 architectural choice (paper 의 multi-agent symmetry + GEODE Pilot).
3. `plugins/seed_pipeline/{tournament.py, cost_preview.py, pre_flight.py}` 의 별도 모듈 분리 — orchestrator 의 책임 비대화 방지.
4. `manifest.py` 의 pydantic schema + drift validator — Petri P1-A 의 직접 차용 패턴. premature schema 가 아닌 multi-source binding 의 contract.

다음 패턴은 **비정상 (PR reject)**:

1. 7 role 중 하나라도 `pass` / `return None` 본체 — Stub disguise.
2. ADR-002 의 baseline wrapping 제거 후 `FitnessBaseline` import 잔존 — Original residue.
3. `BaseSeedAgent` 가 abstract method 만 있고 공통 로직 없음 — interface inflation.
4. manifest 가 hard-coded dict 로 시작 (TOML 로딩 우회) — 비정상 단순화.

## Sunset

- **Trigger**: S12 PR 의 develop → main 머지 완료.
- **Action**:
  1. 본 doc 의 `Status` 를 `Expired` 로 변경 (별도 PR `chore: sunset Plan A fidelity amendment`).
  2. 본 doc 의 `docs/audits/2026-05-18-plan-a-fidelity-amendment.md` 위치 유지 — git history 영구 보존.
  3. 향후 sprint 부터 CLAUDE.md 본래 simplicity 규칙 복귀.

## References

- CLAUDE.md (project root) — `### CANNOT` 전 항목, `### 2. Plan + Socratic Gate`, `### Refactoring Deception Prevention`
- ADR-001 `docs/architecture/seed-pipeline-decision.md`
- ADR-002 `docs/architecture/autoresearch-axis-decision.md`
- ADR-003 `docs/architecture/seed-pipeline-ui-decision.md`
- Plan `docs/plans/2026-05-18-seed-pipeline-sprint-plan.md`
- AI co-scientist paper — arXiv:2502.18864 (6-agent contract)
- `.geode/skills/codex-mcp-verify/SKILL.md` — per-task Codex MCP skill
