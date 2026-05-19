---
name: seed-pipeline-cycle
description: GEODE seed-pipeline sprint 의 PR cycle scaffold — worktree 할당 → 구현 → Codex MCP audit → CI → review → merge. Session 63 (PR #1272–#1276) 에서 검증된 절차를 codify. S2.5-S12 의 남은 13 PR + 모든 fix-up PR 에 동일 적용.
triggers: seed-pipeline, S0, S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11, S12, cycle, sprint, PR cycle, scaffold cycle, seed pipeline workflow
---

# Seed Pipeline PR Cycle

> Session 63 의 6-PR (S0/S1/S2/S2-wire/S2-fix/cycle-skill) 에서 수렴한 절차. 각 단계는 **실측 경험** 에 기반. 다음 PR 부터 단계를 반드시 따르되, "어떤 단계가 자기 PR 에 의미 있는가" 는 PR 성격 (skeleton / feature / fix / docs) 에 따라 가감.

## 적용 시점

다음 중 하나일 때 invoke:
- ADR-001 의 S2.5–S12 PR 시작 (`docs/plans/2026-05-18-seed-pipeline-sprint-plan.md`)
- 임의 PR review 후 fix-up consolidation (S<N>-fix 패턴)
- Wiring/dispatch 같은 cross-cutting infra PR (S<N>-wire 패턴)
- 사용자가 "sprint 진행해" / "이어서 해" 라 지시한 후

## 사이클 6 phase (A–F)

### Phase A — Allocation

**A0.** 직전 작업이 develop 에 머지되었는지 확인:
```bash
git fetch origin --quiet
git log origin/develop..origin/main --oneline   # 0건 이어야 함; >0 이면 backmerge PR 먼저
```

**A1.** Worktree 할당 (CLAUDE.md CANNOT 룰):
```bash
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> origin/develop
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

**A2.** Task 생성 + `in_progress` 설정 (TaskCreate / TaskUpdate).

### Phase B — Implement

**B1.** Plan 의 file ledger 대조해 구현 (`docs/plans/...sprint-plan.md` 의 S<N> 행).

**B2.** **Prevention checklist** 적용 (Session 63 meta-reflection 도출, 7 항목):

| # | 점검 | 적용 위치 |
|---|---|---|
| P1 | **Stub Fidelity Audit** — 새 stub 도입 시 production 측 documented invariant (ordering, side-effects) 위반 여부 + adversarial stub (worst-case order/timing) 추가 | 모든 신규 test stub |
| P2 | **Lock-Scope Lens** — `threading.Lock` 등장 시 "mutate + enforce 같은 lock 안" 검증 | concurrency primitive |
| P3 | **Error-Path Invariant Parity** — try/except 의 happy/error branch 가 동일 invariant (cost rollup, state restore) 보존 | exception handler 추가/수정 |
| P4 | **Environment Anchor Check** — Path/URL default 가 `Path("relative/path")` cwd-relative 면 BLOCK. `get_project_root()` 등 절대 경로 anchor 강제 | config/loader 신규 |
| P5 | **Placeholder Substitution Snapshot** — template `{xxx}` placeholder 가 모든 build branch 의 최종 출력에서 제거되는지 snapshot test | prompt/template 변경 |
| P6 | **WIRING-GAP Marker Discipline** — transitional comment 는 `# WIRING-GAP(<task-id>):` 형식. fix-up PR 시 grep clean 확인 | "Known gap" 류 docstring/comment |
| P7 | **Caller-Callee Contract Pair Read** — caller 의 가정 + callee 의 보장 cross-check (특히 ordering, set-membership, placeholder substitution) | API 양 끝점 변경 |

**B3.** Local quality gates (실패 시 fix loop):
```bash
uv run ruff check --fix core/ tests/ plugins/
uv run ruff format core/ tests/ plugins/
uv run mypy core/ plugins/
uv run python -m pytest tests/<scope>/ -q
```

### Phase C — Verify + Audit

**C1.** Docs-Sync — `CHANGELOG.md` 의 `[Unreleased]` 의 Added/Fixed/Changed 항목 + `CLAUDE.md` 의 Modules / Tests 측정값.

**C2.** 첫 commit + push (feature branch 생성):
```bash
git add -A
git commit -m "feat(seed-pipeline): S<N> — <짧은 description>"  # HEREDOC + Co-Authored-By
git push -u origin feature/<branch-name>
```

**C3.** **Codex MCP per-task audit** (`mcp__codex__codex` 호출):
- prompt 에 4-dim 명시: **검증 / GAP / 누락 / 중복**.
- HIGH 발견 즉시 fix-up commit → 같은 PR 재 audit.
- Round 1-4 까지 가능. 모든 HIGH/MEDIUM RESOLVED 까지 반복.

**C4.** Audit prompt 의 예시 questions (P1–P7 의 prompt 항목화):

```
(a) 검증 — invariants:
- 새 caller→callee contract 의 ordering/set-membership/placeholder/exception path 가 동일 가정 보존?
- 새 lock 의 mutate + enforce 가 같은 critical section?

(b) GAP — completeness:
- Plan ledger 의 모든 deliverable 이 diff 에 있는가?
- "Known wiring gap" 류 transitional comment 중 이번 PR 이 닫은 것이 stale 상태로 남았는가?

(c) 누락 — references:
- CHANGELOG entry 있는가?
- 테스트가 새 invariant (P1-P7 적용 결과) 를 검증하는가?

(d) 중복 — overlap:
- 신규 type/class 가 기존 type/class 와 80% 이상 overlap? Justification 코멘트 있는가?
```

### Phase D — PR & CI

**D1.** PR 생성 (HEREDOC, 6 section 필수 per CLAUDE.md):
- Summary / Why / Changes / GAP Audit / Verification / Reference

**D2.** Monitor 폴링 (Lint/Format → Test → Type Check → Build):
- CI 실패 시 fix loop (보통 ruff format / hook count assertion / mypy type-arg).
- Round 1-4 까지 가능.

### Phase E — Merge & Cleanup

**E1.** Merge to develop:
```bash
gh pr merge <N> --merge
git worktree remove .claude/worktrees/<task-name> --force
git branch -D feature/<branch-name>
```

**E2.** Task `completed` 설정.

**E3.** main backmerge 누적 ≥ 3 PR 또는 release 직전이면 별도 backmerge PR.

### Phase F — (Optional) Post-merge Review

**F1.** 매 3–5 PR 마다 또는 stage 종료 (S2 끝, S8 끝 등) 시점:
- **4-parallel-agent PR review** (general-purpose subagent × N, 각자 1 PR 검토)
- **Alignment audit** (vs 기존 frame work — `plugins/petri_audit/` / `core/agent/` 의 sibling 패턴)
- **Meta-reflection** (Session 63 패턴: 누락 발생 원인 5 그룹화 + prevention checklist 항목 추출)

**F2.** Review 결과의 HIGH/MEDIUM 을 consolidated **S<N>-fix PR** 으로 묶음 (single PR, 다중 fix).

**F3.** Meta-reflection 결과로 본 SKILL 의 prevention checklist 갱신.

## Anti-pattern (CLAUDE.md 강화 적용)

| Anti-pattern | 발생 사례 | 차단 |
|---|---|---|
| Stub 이 production invariant 위반 | S2 의 zip-order corruption — `_StubManager` 가 completion order 미흡 | P1 prevention checklist |
| Lock 외부 enforcement | S1 의 BudgetGuard hard-cap race | P2 |
| Exception path 가 invariant 우회 | S1 의 cost rollup loss | P3 |
| cwd-relative Path default | S2-wire 의 `.claude/agents` silent 0 | P4 |
| Stale "Known gap" docstring | S2-wire 가 closed 한 후 S2 docstring 미정정 | P6 |
| Codex MCP audit single-file 시야 | S2-zip 의 caller-callee 분리 검증 부재 | P7 |

## 측정 가능 성공 기준

각 PR 머지 시점:
- ✓ CI 5/5 (또는 11/11 with site lint) green
- ✓ Codex MCP audit HIGH 0건 + MEDIUM 0건 (round 1-4)
- ✓ Local pytest scope 100% pass
- ✓ CHANGELOG entry 있음
- ✓ 신규 추가 코드 가 P1-P7 checklist 통과

Stage 종료 (e.g. S2 끝, S8 끝) 시점:
- ✓ Multi-agent review 의 HIGH/MEDIUM 모두 fix-up PR 으로 정리됨
- ✓ Alignment audit 통과 (✓ / ⏳ / ⚠ / ❌ 4-rating 시스템 적용)

## 본 SKILL 의 적용 이력

| Session | PR | 단계 적용 |
|---|---|---|
| 63 | #1272 S0 | A1, B1, B3, C1, C2, **C3 (4 round)**, D1, D2, E1, E2 |
| 63 | #1273 S1 | 위 + **C3 (3 round)** |
| 63 | #1274 S2 | 위 + C3 (2 round, 1 fix-up gap 발견됨 — wiring HIGH ×2 follow-up 됨) |
| 63 | #1275 S2-wire | 위 + C3 (3 round) |
| 63 | #1276 S2-fix | 위 + **F1 (4-parallel-agent review)** + **F1-meta (reflection)** + **F2 (consolidation)** |
| 63 | #1277 cycle-skill | 본 SKILL 도입 — 이 행이 본 SKILL 의 첫 자체 적용 (B2 의 P1-P7 적용 +. C3 audit) |

## 다음 (S2.5 이후) 사용 패턴

S2.5–S12 + S6.5-wire + 각 stage 끝의 review:
- 각 PR 시작 시 본 SKILL 의 Phase A-E 진행
- 3-PR 누적 또는 stage 종료 시점에 Phase F 진행
- Phase F 결과로 본 SKILL 의 prevention checklist 갱신 (살아있는 문서)

## References

- `docs/plans/2026-05-18-seed-pipeline-sprint-plan.md` — 16 PR ledger
- `docs/audits/2026-05-18-plan-a-fidelity-amendment.md` — fidelity amendment + Stub disguise 룰
- `.geode/skills/codex-mcp-verify/SKILL.md` — Codex MCP 호출 패턴
- Session 63 meta-reflection (sprint 진행 회의록): 7-누락 5-그룹 분석 + P1-P7 도출
- CLAUDE.md `### Wiring Verification` 4-룰 (Read-Write parity / Hook registration / ContextVar injection / Singleton lifecycle) — P1, P3, P5, P7 의 확장 카테고리
