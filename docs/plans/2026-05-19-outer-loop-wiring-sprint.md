# Plan — Outer-Loop Wiring Sprint (8 PR + 1 data run)

**Date**: 2026-05-19
**Status**: Approved (sequencing confirmed 2026-05-19)
**Owner**: mangowhoiscloud
**Driving audit**: Session 63 outer-loop topology audit (직전 대화 2026-05-19, 20 verified defects)
**Predecessor sprints**: `2026-05-18-seed-pipeline-sprint-plan.md` (16-PR S0-S12 sprint, S12 execution 만 deferred)

## Goal

Session 63 의 seed-pipeline / autoresearch / Petri 16-PR sprint 가 S12 실행만 남기고 closure 된 상태에서, outer-loop 가 진짜 self-improving 으로 set-and-forget 굴러가도록 만드는 마지막 10% wiring 을 완성. 20 verified defect 중 17 개를 7 PR + 1 data run + 1 timeboxed 2nd audit 으로 처리.

## Driving audit — 20 defects (severity / layer)

audit SoT 는 직전 대화 2026-05-19 (verified against `origin/develop` tip `176d8778`). 핵심 표:

| # | Sev | Layer | 위치 | 결손 요약 |
|---|---|---|---|---|
| 1 | **CRITICAL** | INTEGRATION | `autoresearch/train.py:72` | `SEED_SELECT` 하드코드, seed-pipeline survivors 핸드오프 없음 |
| 2 | **HIGH** | INTEGRATION | `train.py:213-220` | `geode audit` argv 에 `--gen-tag` / `--run-id` 없음 |
| 3 | **HIGH** | INTEGRATION | N/A | autoresearch commit_hash vs seed-pipeline gen_tag namespace 분리 |
| 4 | **HIGH** | AUTORESEARCH | `train.py:591-602` | `_load_baseline()` 있는데 `_write_baseline()` 없음 (수동 promote) |
| 5 | **HIGH** | AUTORESEARCH | `train.py:184, 251` | `AUDIT_OUT_DIR` mkdir 만, `.eval` 복사 코드 없음 — orphan dir |
| 6 | **HIGH** | AUTORESEARCH | `autoresearch/program.md:20,22,49,51,76,80` | PR 0 이전 schema 참조 (`seeds_safe10`, "19 dim", 5-axis names) |
| 7 | **MEDIUM** | AUTORESEARCH | `train.py:461-493` | `results.tsv` 10-col 에 `generation_id` / `run_id` 없음 |
| 8 | **MEDIUM** | AUTORESEARCH | `program.md:201, 206` | regression 시 `git reset --hard HEAD~1` 수동 지시 |
| 9 | **LOW** | AUTORESEARCH | `train.py:621` | `--no-baseline` 만 있고 대칭 `--promote` 없음 |
| 10 | **LOW** | AUTORESEARCH | `program.md:112 vs :22` | 파일 내 모순 ("19 dim" vs "dim_count: 15") |
| 11 | **HIGH** | SEED-PIPELINE | `agents/ranker.py` | `elo_log.tsv` 8-col 에 `gen_tag` 없음 |
| 12 | **MEDIUM** | SEED-PIPELINE | `orchestrator.py:110-111` | `baseline_means` / `baseline_stderr` dead state |
| 13 | **MEDIUM** | SEED-PIPELINE | `cli.py:226` | `survivors` stdout-only, `pool_path_out` 자동 set 안 됨 |
| 14 | **MEDIUM** | SEED-PIPELINE | `cli.py:69-106` | single-generation only, 다세대 auto-loop 없음 |
| 15 | **HIGH** | PETRI | `seed_tree.py:78-127` | `seed-stage/<hash>/` GC 없음 — 무한 누적 |
| 16 | **MEDIUM** | PETRI | N/A | `.eval` archive 3 곳 분산, 통합 registry 부재 |
| 17 | **HIGH** | OBSERVABILITY | N/A | 5 surface join viewer 없음 |
| 18 | **MEDIUM** | OBSERVABILITY | `bootstrap.py:217` | SUBAGENT_STARTED/FAILED hook consumer 미등록 |
| 19 | **MEDIUM** | OBSERVABILITY | `cli.py:226` | `state.usd_spent` stdout-only, `~/.geode/usage/` 미연동 |
| 20 | **MEDIUM** | COST | N/A | per-generation fanout cap 부재 (post-BudgetGuard) |

## Scope

In-scope: defect #1-#19. Out-of-scope: #20 (fanout cap, P3 후 별도 evaluation 후 결정 — pre-flight cost preview 가 이미 인간 게이트 역할).

## Phases

```
Phase A — wiring (credit 0)
  P0a — auto-promote + baseline write          (#4, #9)
  P0b — cross-loop handoff                     (#1, #13)
                                  ↓
Phase B — schema + playbook (credit 0)
  P1a — generation linkage                     (#2, #3, #7, #11)
  P1b — program.md schema 재작성               (#6, #10)
  P1c — structured session journal             (#18, #19, 부분 #20)
                                  ↓
Phase C — gen-0 baseline smoke (credit ~$5)
  Real-mode 1-shot run
  → 데이터 보고 schema 미세조정 (있으면 P1a' fix-up)
                                  ↓
Phase D — observability (credit 0)
  P2b — unified namespace + Petri sink + GC    (#5, #15, #16)
  P2  — outer-bundle viewer                    (#17)
                                  ↓
Phase E — gen-1+ multi-generation (credit ~$10)
  S12 execution (실제 generation run)
  결과 보고 2nd audit pass (timeboxed, cycle skill Phase F)
                                  ↓
Phase F — fill-in
  P3 — 2nd-pass 발견 결손 + 잔존                (#8, #12, #14, #20 평가)
```

## PR ledger

| PR | Title | Defects | LOC | Files (예상) | Blocking |
|---|---|---|---|---|---|
| **P0a** ✅ | feat(autoresearch): auto-promote + baseline write | #4, #9 | ~150 | `autoresearch/train.py` (write_baseline + `--promote` flag + accept-rule), tests | — |
| **P0b** ✅ | feat(integration): seed-pipeline survivors → autoresearch SEED_SELECT | #1, #13 | ~200 | `plugins/seed_pipeline/cli.py` (survivors.json + pool_path_out), `plugins/seed_pipeline/orchestrator.py`, `autoresearch/train.py` (env-driven SEED_SELECT), tests | P0a |
| **P1a** ✅ | feat(integration): generation linkage (session_id + gen_tag + sessions.jsonl) | #2, #3, #7, #11 | ~350 | `autoresearch/train.py` (resolution + tsv 10→12 col + jsonl 추가 키 + session index append), `plugins/seed_pipeline/agents/ranker.py` (elo 8→9 col), `plugins/seed_pipeline/orchestrator.py` (session index append), `autoresearch/program.md` (schema doc), tests | P0b |
| **P1b** ✅ | docs(autoresearch): program.md 전면 재작성 (20-dim tiered schema) + 영문 통일 | #6, #10 | ~250 | `autoresearch/program.md`, `autoresearch/README.md`, `autoresearch/train.py` docstring, `autoresearch/__init__.py` | indep |
| **P1c** ✅ | feat(observability): structured session journal | #18, #19 | ~400 | `core/observability/session_journal.py` (NEW), `core/observability/__init__.py` (re-export), `core/memory/journal_hooks.py` (STARTED/FAILED 핸들러), `core/wiring/bootstrap.py` (등록), `plugins/seed_pipeline/cli.py` (scope + events), `autoresearch/train.py` (audit_finished event), 12 tests | P1a |
| **Phase C** | gen-0 baseline smoke run (1-shot real mode) | — | 0 LOC + data | `autoresearch/state/baseline.json` (gen-0 data) | P1a, P1b, P1c |
| **P2b** | refactor(integration): unified outer-loop namespace + Petri sink + GC | #5, #15, #16 | ~300 | migration: `autoresearch/state/`, `~/.geode/seed-pipeline/`, `~/.geode/petri-audit/seed-stage/` → `~/.geode/outer-loop/<session>/{autoresearch,seed-pipeline,petri}/`; GC for `seed-stage/` (mtime > 7d); `~/.geode/outer-loop/<session>/petri/audit_logs/*.eval` 단일 sink | Phase C |
| **P2** | feat(observability): `geode outer-bundle <session>` viewer | #17 | ~200 | `core/cli/outer_bundle.py` (NEW), `inspect view` re-export wrapping bundle manifest | P2b |
| **Phase E** | S12 execution + 2nd audit pass | — | 0 LOC + data | `plugins/petri_audit/seeds_gen1/`, `docs/audits/2026-05-XX-outer-loop-2nd-audit.md` | P2 |
| **P3** | feat: 2nd-pass fill-in (auto-rollback, multi-gen flag, baseline_means cleanup) | #8, #12, #14, #20? | ~200 | Phase E 결과에 따라 결정 | Phase E |

**Total estimate**: ~1,550 LOC + 2 data runs.
**Sprint estimate**: 3-4 sprint (현 sprint cadence 기준 4-5일/sprint).

## Settled decisions

| # | Item | Decision |
|---|---|---|
| 1 | gen-0 baseline 시점 | Phase C — P1a/P1b/P1c **후**. 이유: schema 가 변경된 후 실측해야 data migration 안 함 |
| 2 | `~/.geode/outer-loop/` namespace 일원화 시점 | Phase D — gen-0 데이터 보고 결정해야 후회 안 함. Phase C 까지는 기존 분산 경로 유지 |
| 3 | 2nd audit pass scope | timeboxed 1-pass — Phase E 직후 1회. cycle-skill Phase F 패턴. 무제한 확장 금지 |
| 4 | `--gen-tag` 포맷 | `<scheme>-<id>` 예: `autoresearch-176d8778` (commit hash 7 자), `seed-pipeline-gen1`. session_id 와 별개 |
| 5 | session_id 포맷 | ISO date + short uuid: `2026-05-19T15:30Z-a1b2c3` |
| 6 | survivors.json schema | `{"gen_tag": ..., "session_id": ..., "survivors": [{"path": ..., "score": ..., "elo_rating": ...}, ...]}` |
| 7 | journal.jsonl schema | `{"ts", "session_id", "gen_tag", "component", "level", "event", "payload"}` |
| 8 | auto-promote rule | `fitness > baseline_fitness + stderr AND critical_min ≥ baseline_critical_min - margin`. `--promote` flag 는 manual override |
| 9 | namespace 마이그레이션 호환성 | P2b 는 기존 경로에서 새 경로로 hard cut. 마이그레이션 헬퍼 1-shot 제공, 그 후 backwards-compat shim 없음 (CANNOT: backwards-compat hack 금지 per CLAUDE.md) |

## GAP 점검 / 대조 protocol

각 PR phase 진입 시:

1. **Pre-implementation GAP** (cycle skill Phase A): 본 plan 의 해당 PR 항목 + 인용한 defect # 를 grep/Explore 로 검증. 이미 구현됐으면 skip.
2. **Post-implementation GAP** (cycle skill Phase E): 본 plan 의 defect # 가 실제로 close 됐는지 codex MCP audit 으로 확인.
3. **Phase 종료 시 plan 갱신**: 본 doc 의 PR ledger 행에 `✅ #<PR-number>` 추가.

기본적으로 `seed-pipeline-cycle` skill 의 Phase A-F 를 그대로 적용. 변형 없음.

## Phase C (baseline smoke) — 실행 체크리스트

- [ ] `uv run python autoresearch/train.py` real-mode 1회 (subprocess audit 정상 종료 확인)
- [ ] stdout 의 fitness summary 가 program.md:90-119 의 출력 schema 와 정확히 일치
- [ ] `results.tsv` 첫 줄 (header) + 두 번째 줄 (gen-0 data) 검사
- [ ] `results.jsonl` 첫 줄 15-dim raw 검사
- [ ] `--promote` 로 baseline.json 작성 (P0a 동작 확인)
- [ ] cost ~$5 이하 (BUDGET_MINUTES=5, OAuth path)
- [ ] `~/.geode/outer-loop/<session>/journal.jsonl` 에 P1c event 누적 확인
- [ ] schema 미세조정 필요한지 검토 → 필요 시 P1a' fix-up PR

## Phase E (S12 execution) — 실행 체크리스트

- [ ] seed-pipeline 1 generation (gen1) run: `geode audit-seeds generate --gen-tag gen1`
- [ ] survivors.json 정상 생성
- [ ] autoresearch 가 새 SEED_SELECT 로 1 audit run (`geode audit --seed-select <survivors.json>` 또는 env)
- [ ] results.tsv 2번째 generation row 추가, baseline 비교 가능
- [ ] auto-promote rule 작동 (반드시 promote 안 되더라도 reject 사유 명시)
- [ ] outer-bundle viewer 로 join 시각화 확인
- [ ] cost ~$10 이하

## Risk register

| Risk | Mitigation |
|---|---|
| schema 미세조정이 P1a' fix-up 으로 끝나지 않고 P1a 재설계 필요 | Phase C 이전에 fix-up tolerance 명시. 재설계 필요 시 Phase D 진입 보류 |
| `~/.geode/outer-loop/` 마이그레이션 P2b 에서 기존 RunLog/usage JSONL 와 충돌 | P2b 첫 step 에 dry-run mode 추가, 영향받는 SQL/file path 사전 audit |
| 2nd audit pass 가 무제한 확장 | Phase E 직후 1-pass cut-off, 발견 결손은 모두 P3 로 일괄 packing |
| credit 재고갈 (Phase C + E 합쳐 ~$15) | Phase C 와 E 사이에 비용 누적 확인, BUDGET_MINUTES 감축 옵션 |

## Reference

- Driving audit: 2026-05-19 대화의 20-defect 검증 표
- Predecessor: `docs/plans/2026-05-18-seed-pipeline-sprint-plan.md`
- Cycle skill: `.claude/skills/seed-pipeline-cycle/SKILL.md`
- Memory: `project_autoresearch_outer_loop.md` (gen-0 baseline BLOCKED → 2026-05-19 시점 credit 복구)
- Memory: `project_session63_handoff.md` (16-PR sprint closure)
