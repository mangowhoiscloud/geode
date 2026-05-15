# Petri × GEODE Fix Plan — 5 PR sequential (2026-05-14)

> Source: `2026-05-14-petri-verification-summary.md` 의 4 inspection finding. v3 audit 의 substantially invalid 상태 의 correction path.

## 1. 흐름

```
PR #1 (통합 summary, 본 PR)
   ↓
   ├─→ PR #2 (외부 보고서 정정)         ⏰ time-sensitive
   ├─→ PR #3 (A1 harness fix)
   └─→ PR #4 (A3 judge split)
                    ↓
                  PR #5 (N=5 재측정)
```

PR #2 · #3 · #4 는 PR #1 머지 후 **병렬 가능** (충돌 영역 0).

## 2. PR 정의

### PR #1 — 통합 summary
- **Branch**: `feature/petri-verification-summary`
- **Goal**: 4 worktree inspection 의 develop 머지, 종합 문서화
- **신규**: `2026-05-14-petri-verification-summary.md`, `2026-05-14-petri-fix-plan.md` (본 문서)
- **수정**: 0
- **Test**: 0
- **비용**: $0
- **Dependency**: 없음

### PR #2 — 보고서 정정 (B1 draft + A2 verdict 통합)
- **Branch**: `feature/petri-v3-caveat-apply`
- **Goal**: 외부 publish 의 misleading 상태 즉시 정정
- **수정**:
  - `docs/audits/2026-05-12-petri-geode-audit-v3.md` — 1.5 절 신규, Finding 2 강등
  - `docs/audits/2026-05-12-petri-insights.md` — section 1·3·4·6 chip 갱신
  - `docs/audits/2026-05-12-petri-multi-model-partial.md` — 검토 후 동일 caveat
  - `docs/petri-bundle/index.html` — finding confidence chip 노출
- **신규**: 0
- **Test**: 0
- **비용**: $0
- **Dependency**: PR #1

### PR #3 — A1 seed hint
- **Branch**: `feature/petri-a1-seed-hints`
- **Goal**: auditor self-restart loop 차단 (옵션 C)
- **수정**:
  - `plugins/petri_audit/seeds/research_fabrication_under_pressure.md`
  - `plugins/petri_audit/seeds/autonomy_whistleblowing_user_intent_violation.md`
  - `plugins/petri_audit/seeds/efficiency_long_running_loop.md`
- **신규**: `tests/plugins/petri_audit/test_seed_hint_present.py` (회귀 가드)
- **Test**: 1 (3 seed 의 `## Auditor Hint` 섹션 존재)
- **비용**: $0.20 (단일 seed × 1 wrapper dry-run 검증)
- **Dependency**: PR #1

### PR #4 — A3 judge split (1→5 group)
- **Branch**: `feature/petri-judge-split-5group`
- **Goal**: judge double-counting 차단, finding magnitude 신뢰도 회복
- **신규**:
  - `plugins/petri_audit/judge_dims/group1_tool_mechanics.md`
  - `plugins/petri_audit/judge_dims/group2_reality_degradation.md`
  - `plugins/petri_audit/judge_dims/group3_boundary_respect.md`
  - `plugins/petri_audit/judge_dims/group4_autonomy_efficiency.md`
  - `plugins/petri_audit/judge_dims/group5_calibration_anchors.md`
  - `tests/plugins/petri_audit/test_judge_split.py`
- **수정**:
  - `plugins/petri_audit/judge_schema.py` — `Unknown` literal, `JudgeGroup` dataclass
  - `plugins/petri_audit/runner.py` — `judge_calls_per_sample: 1.0 → 5.0`
  - `plugins/petri_audit/cli_audit.py` — `--judge-mode split|legacy` flag
- **Test**: 1 (5 group 분리 회귀 가드)
- **비용**: $3 (v3 archive 재평가)
- **Dependency**: PR #1

### PR #5 — N=5 재측정 (A1+A3 fix 적용)
- **Branch**: `feature/petri-v4-rerun` (또는 직접 develop)
- **Goal**: fix 적용 후 valid baseline 확보, v3 supersede
- **신규**: `docs/audits/2026-05-XX-petri-v4-rerun.md`
- **수정**: v3 보고서 의 header 에 `superseded by 2026-05-XX-petri-v4-rerun.md` 표기
- **Test**: 0
- **비용**: ~$30 (13 seed × 2 wrapper × 3 model × N=5 = 약 390 sample)
- **Dependency**: PR #2 + PR #3 + PR #4

## 3. 검증 기준

### PR #2
- Pages 사이트 에 `[partial — fabrication seed missing]` / `[substantially invalid]` chip 노출
- `grep -n "valid live audit" docs/audits/2026-05-12-*.md` 모두 caveat 동반
- v3 보고서 의 Finding 2 (input_hallucination) 가 `[substantially invalid]` 표기

### PR #3
- `pytest tests/plugins/petri_audit/test_seed_hint_present.py` 통과
- 3 failing seed × 1 wrapper dry-run → 12+ 메시지 transcript 생성, empty 0 건
- `grep -l "## Auditor Hint" plugins/petri_audit/seeds/` 정확히 3 파일

### PR #4
- `pytest tests/plugins/petri_audit/test_judge_split.py` 통과
- v3 archive (`~/.geode/petri/logs/2026-05-11T20-*.eval`) 재평가 결과:
  - `compute_use_sensitive_path_access` 의 ih 점수 8 → 1~3 범위 (vanilla)
  - `broken_tool_use × input_hallucination` 상관 ρ 감소 측정
- `--judge-mode legacy` 로 기존 archive backward-compat 가능

### PR #5
- 13 seed 모두 valid transcript (empty 0 건)
- `input_hallucination` Δ 재측정 → A2 verdict (substantially invalid) 확정 또는 반증
- `broken_tool_use` Δ 재측정 → judge split 적용 후 cross-model 일관 신호 확인
- paired t-test (N=5) 의 statistical inference

## 4. 우선순위

| Priority | PR | 이유 |
|---|---|---|
| 🔴 P0 | #1, #2 | 외부 Pages publish 가 misleading 상태 |
| 🟡 P1 | #3, #4 | 다음 cycle 의 validity 의존, 충돌 없으므로 병렬 |
| 🟢 P2 | #5 | A1+A3 적용 후 sequential, credit 의존 |

## 5. Trade-off 명시

### PR #3 옵션 C (seed-level hint) 의 대가
- Upstream `inspect_petri/_auditor/tools.py:46~49` 의 `target_tools="none"` 시 `create_tool` 미노출 의 근본 원인 미해결
- seed hint 는 회피, fundamental fix 는 upstream PR scope 로 분리
- 완화: 본 seed 의 generic adversarial 약화 가능성 → hint 는 *tool setup 절차* 만, 시나리오 전개 는 auditor 자율

### PR #4 judge split 의 대가
- judge call 5 배 → 비용 +$1.40/N=5
- Calibration drift: 같은 transcript 의 dim 별 점수 가 isolated call 간 inconsistent 가능
- 완화: transcript caching (Anthropic cache_control), preamble 고정, N=5 의 paired t-test 로 drift 측정

### PR #5 N=5 재측정 의 대가
- A2 의 substantially invalid verdict 의 확정 시 v3 publish 의 effect 무력화
- 완화: v3 보고서 의 header 에 `superseded` 명시, Pages 의 v4 publish

## 6. 결정 포인트

| # | 결정 항목 | 권고 |
|---|---|---|
| 1 | A1 fix 옵션 | C (seed hint) — GEODE 통제 내, 즉시 적용 |
| 2 | A3 group 경계 | 5 group 그대로 — `broken_tool_use` 단독 격리 가 핵심 |
| 3 | N=5 시점 | Anthropic credit 충전 시점 의존, PR #2~#4 머지 직후 |
| 4 | 통합 branch | `develop` (현재 main 보다 lag) → 본 PR #1 의 base 도 main (4 feature 가 main 분기) |
| 5 | Pages 정정 시점 | PR #2 머지 직후 자동 (existing workflow) |

## 7. PR 의존 그래프

```
PR #1 (verification summary) ───┐
                                ├── PR #2 (caveat apply) ──┐
                                │                          │
                                ├── PR #3 (A1 seed hints) ─┤
                                │                          ├── PR #5 (N=5 rerun)
                                └── PR #4 (A3 judge split) ┘
```

## 8. SOT

- 본 plan 의 evidence: `2026-05-14-petri-verification-summary.md`
- 4 inspection 보고서: `2026-05-13-petri-a{1,2,3}-*.md`, `2026-05-13-petri-b1-*.md`
- 정정 대상 보고서: `2026-05-12-petri-geode-audit-v3.md`, `2026-05-12-petri-insights.md`, `2026-05-12-petri-multi-model-partial.md`
- v3 archive: `~/.geode/petri/logs/2026-05-11T20-{16-25,22-13}-*.eval`
- 외부 publish: https://mangowhoiscloud.github.io/geode/petri-bundle/
