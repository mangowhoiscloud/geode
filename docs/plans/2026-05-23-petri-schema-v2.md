# Petri Schema v2 + autoresearch GAP fix — SOT

**Date**: 2026-05-23
**Driver**: Session 67 (post v0.99.36 release)
**Owner**: human + claude
**Status**: PR-1 in flight

## 1. Why

2026-05-23 self-improving loop audit (`session_session67_audit` 회차) 가 autoresearch
포팅 (Karpathy `~/workspace/autoresearch` MIT 2026-03 → GEODE `autoresearch/`) 의
**여러 invariant 손실** + **Petri 주입 파이프라인의 측정 결함** 을 surface 함. 핵심:

- 21 autoresearch run 중 real-mode 4건에서 **3건이 "bootstrap"** 로 promote.
  실제로는 baseline.json 이 존재하는데 axis_coverage 체크에서 fail 하는 의심.
- 모든 dim 의 `stderr=0.0` — N=1 single-sample 의 결과인데 `_should_promote`
  rule 3 의 margin 가드가 `max(stderr, 0.05)` floor 만 적용 → defense 무력.
- `dim_extractor` 가 dim 별 `sample_count` 를 emit 하지 않아 N=1 vs N=10 의
  stderr=0 차이를 운영자/promotion 룰이 disambiguate 불가.
- `compute_dim_scores` 의 "missing dim = best case (1.0)" semantic 이 Goodhart
  risk — mutation 이 측정 자체를 회피하도록 진화 가능.
- baseline.json schema 가 raw Petri scale (1-10) 인지 normalized fitness (0-1)
  인지 stamp 없음 — 운영자 인지 부담.
- `verbose_padding` / `redundant_tool_invocation` 은 judge LLM 안 거치고 token
  count / tool log 에서 derived analytics 인데 동일 weight (0.0333) 받음 —
  measurement modality 가 다른 dim 이 균일 취급.

원본 audit 결과 — Karpathy invariant 대비 손실:
- L1 — Git as Optimizer 깨짐 (mutations.jsonl gitignored, PR-G5b #1350 사고)
- L2 — Single-file constraint 5 surface 로 분산
- L3 — 신호 분해능 폭발 + stderr=0
- L4 — schema 단위 인지 부담 (raw vs normalized layer 불명시)
- L5 — 4-axis weight 정의됐으나 ux/admire/bench wiring 불완전
- L7 — bootstrap rule 항상 fire
- L8 — agent 가 train.py 자체 변이 가능 (safety boundary 부재)

Petri 측 추가 GAP:
- P1 — `seed_limit=2` × `statistics.stdev` ddof=1 → stderr 폭발
- P2 — N=1 → stderr=0 의 이중 해석 ("no signal" vs "perfect")
- P3 — judge vs analytics dim 의 dual lifecycle 가 fitness aggregate 에서 균일 처리
- P4 — missing dim = best-case 가 Goodhart 위험
- P5 — `_should_promote` margin 이 N 정보 없이 stderr 만 봄
- P6 — baseline.json 에 `.eval` archive pointer 부재 → replay 불가

## 2. Decision — Schema v2 + 5-PR cascade

baseline.json schema 를 4-layer 분리 + 메타데이터 보강 형태로 확장. 후방
호환성은 `schema_version` 으로 분기. v1 baseline 은 load 시 raw 만 채우고
나머지 namespace 는 default. 첫 v2 promote 시점부터 새 schema 로 write.

### 2.1 Schema v2 (target)

```json
{
  "schema_version": 2,
  "session_id": "<run_id>",
  "gen_tag": "<운영자 의미 tag>",
  "commit": "<git sha>",
  "ts_utc": "<ISO 8601>",

  "raw": {
    "dim_means":   {dim: float (1-10)},
    "dim_stderr":  {dim: float},
    "sample_count": {dim: int},           // P1+P2+P5 fix
    "rubric_version": "v3-22dim-PR0",
    "eval_archive": "<path>",
    "eval_archive_sha256": "<hex>",       // P6 fix
    "measurement_modality": {             // P3 fix
      "<dim>": "judge_llm" | "token_count" | "tool_log"
    }
  },

  "normalized": {
    "dim_scores": {dim: float (0-1)},
    "stability_score": float,
    "missing_dims": [dim, ...],           // P4 fix
    "stability_axis_n_eligible": int      // P2 fix
  },

  "axes": {
    "ux_means":     {success_rate, token_cost_norm, revert_ratio_norm, latency_norm} | null,
    "admire_means": {pairwise_win_rate, human_calibration_corr} | null,
    "bench_means":  {<7 fields>} | null
  },

  "fitness": {
    "value": float,
    "formula_version": "compute_fitness_3axis_v2",
    "weights": {dim_part, ux_part, admire_part, bench_part},
    "components": {critical_min, auxiliary_mean, info_mean, stability_axis}
  },

  "audit": {
    "audit_seconds": float,
    "target_model": str, "judge_model": str, "auditor_model": str,
    "seed_limit": int, "dim_set": str, "max_turns": int,
    "usd_spent": float                    // G7 fix
  },

  "promotion": {
    "from_session": "<prev_id>" | null,
    "reason": "bootstrap" | "delta_improvement" | "manual_force",
    "delta_fitness": float | null,
    "margin_required": float,
    "margin_realized": float | null
  }
}
```

### 2.2 PR cascade (실행 순서)

| PR | 범위 | Prereq | 영향 |
|----|------|--------|------|
| **PR-1** | `dim_extractor.extract_dim_aggregates` 가 `sample_count` per-dim + `measurement_modality` 태그도 emit | — | API 확장만, behavior 무변화 |
| **PR-2** | `_write_baseline` schema_version=2 + 4-layer namespace 분리 | PR-1 | baseline.json 신규 형식, `load_baseline` v1/v2 분기 |
| **PR-3** | `_should_promote` 의 N=1 분기 (sample_count ≤ 1 dim 의 margin 강화) | PR-1+PR-2 | promote 결정 룰 강화 |
| **PR-4** | `compute_dim_scores` 의 `missing_dims` 명시 + emit | PR-1 | results.tsv/jsonl 정합 |
| **PR-5** | results.tsv / results.jsonl row 가 새 schema 와 정합 | PR-2+PR-4 | reporting 일관성 |

PR-1 부터 순차 진행. 각 PR 의 verification 단계는 `feedback_codex_mcp_verification`
에 따라 Codex MCP read-only review 필수.

## 3. Workflow (per PR)

각 PR 동일 사이클:

1. Worktree + branch (필요시)
2. Code edit (single-purpose, P10 Simplicity)
3. Local gates:
   - `uv run ruff check core/ tests/ plugins/`
   - `uv run ruff format --check core/ tests/ plugins/ autoresearch/ scripts/`
   - `uv run mypy core/ plugins/`
   - `uv run lint-imports`
   - `uv run pytest <impacted files>` (광범위 sweep 은 PR-5 끝나고 한 번)
4. **Codex MCP review** (read-only, CRITICAL/HIGH/MEDIUM 카테고리별)
5. Codex 결과 반영 → 게이트 재실행
6. CHANGELOG `[Unreleased]` 갱신
7. Commit + push
8. PR develop ← feature, HEREDOC body, CI watch
9. CI 8/8 green 확인 후 사용자 GO → merge

## 4. Non-goals

- gen-0 baseline 실측 (Anthropic credit 차단 별도 결정)
- LaneQueue / Hermes / Tier 3 LaTeX (out-of-scope, 별도 backlog)
- agent 의 train.py 자체 변이 권한 가드 (L8) — 이번 sprint 의 schema scope
  와 분리, 다음 sprint 후보

## 5. Verification artifacts

- 각 PR 의 Codex MCP review thread ID 를 commit message + PR body 에 기록
- baseline.json migration smoke: 기존 v1 파일 두고 `load_baseline` 호출 시 raw
  layer 만 populated 인지 확인하는 단위 테스트
- `_write_baseline` 호출 시 새 schema 가 형식 invariant 만족하는지 (필수 namespace,
  optional axes null 처리) 확인하는 단위 테스트

## 6. SOT location

- 이 문서: `docs/plans/2026-05-23-petri-schema-v2.md`
- Schema v2 reference impl: `autoresearch/train.py:_write_baseline` (PR-2 적용 후)
- 측정 source: `core/audit/dim_extractor.py` (PR-1 적용 후)
- Rollback path: revert PR-2 first, then PR-1 (PR-3/4/5 는 PR-1+PR-2 위에 lifted)

## 7. 관련 메모리 + 사고 기록

- `[[research_karpathy_autoresearch_agenthub]]` — 원본 디자인 reference
- `[[project_session60_handoff]]` — autoresearch fork + wrapper-override hook
- CLAUDE.md DONT 테이블:
  - 2026-05-20 PR-G5b #1350 (CHANGELOG/PR-body parity, mutations.jsonl gitignored)
  - 2026-05-20 PR-G2 #1346 (reader-assumption drift, evidence persistence)
  - 2026-05-20 PR-G3 #1347 (conditional read parity, baseline auto branch)
- `[[feedback_codex_mcp_verification]]` — 각 PR 의 verify 게이트
- `[[feedback_changelog_implementation_parity]]` — verb/adjective grep-provable
