# 2026-05-25 — Lineage + Attribution Schema (RFC)

> Status: **Final** (2026-05-25 운영자 5 항목 일괄 채택)
> Scope: PR-3 LINEAGE+ATTRIBUTION 통합 구현의 사전 schema 확정
> Sprint: PR-2 SCHEMA-DESIGN
> 관련 메모리: [[project-autoresearch-separation-architecture]], [[project-autoresearch-state-injection-pipeline]], [[project-autoresearch-fragmentation-audit]], [[reference-mutation-surface-frontier-2026-05-25]]

## 1. 배경

GEODE autoresearch self-improving-loop 는 **관측 표면**(Petri trace + 22-dim bench rubric + `baseline.json`)과 **수정 표면**(`mutations.jsonl` ledger + 5 kind policy JSON)을 의도적으로 분리. 활성 5 kind: `prompt`, `tool_policy`, `reflection`, `skill_catalog`, `agent_contract` (decomposition 은 운영자 결정으로 제외, 2026-05-25).

현 시점 3 GAP:
- **G1. credit assignment 사전 매핑 부재** — `Mutation.expected_dim` 은 LLM 자유 추론
- **G2. rollback_condition enforcement 미구현** — fitness 저하 mutation 자동 revert 없음
- **G3. 폐기 mutation lineage 손실** — `_rollback_sot()` 가 previous_value 로 덮어쓰기

frontier 패턴 중 GEODE 가 점유할 분면은 **(multi-dim × lineage)** — AlphaEvolve evolutionary DB + AI Scientist v2 BFTS tree 가 정확한 reference. "multi-dim mutation lineage" 단일 패턴 (§4 참조) 으로 G1+G3 동시 해소.

## 2. 목표

**multi-dim mutation lineage** 의 통합 schema 확정 — mutation 의 pre-state (multi-dim baseline + previous_value) 와 post-state (multi-dim measurement + delta) 양면을 mutation_id 별 디렉토리에 grouping. 별 파일 단독 추가 (`lineage.jsonl` + `attribution.jsonl`) 로 파편화 가속(F2) 회피 위해 **대안 B** 채택.

## 3. Non-Goals

- F1 cross-run SoT 3중첩 (`meta-review snapshot` + `latest_pointer.json` + `sessions.jsonl`) 통합 — 별 incident sprint
- F3 mutator 가 mutations.jsonl 자기 history 를 context 로 보는 기능 — 본 schema 가 enabler 가 되나 reader wiring 은 후속 PR
- decomposition kind 의 mutation target 복귀
- MCTS sibling exploration (frontier 패턴 #3) full 구현 — 본 schema 는 sibling field 예약만

## 4. Frontier 그라운딩

frontier 16건은 **2 직교 차원** 으로 분류 가능:
- **Lineage** (storage): mutation trace 를 append-only archive 로 보존하는가
- **Multi-dim** (semantic): mutation 의 효과를 N≥2 차원으로 측정하는가

이 2 차원의 4분면 중 GEODE 가 가야 할 곳은 **(multi-dim × lineage)** — 즉 "**multi-dim mutation lineage**" 단일 패턴. RFC 의 schema 가 이 분면을 정확히 점유.

| 분면 | frontier 사례 |
|---|---|
| **multi-dim × lineage** ← GEODE 목표 | AlphaEvolve (evolutionary DB + Pareto), AI Scientist v2 (BFTS tree + VLM multi-dim judge) |
| 1-dim × lineage | DGM (SWE-bench scalar archive), Voyager (skill library append-only), STOP (scalar utility) |
| multi-dim × ephemeral | Coze Loop (multi-dim eval, no archive), AutoGLM (ORM+PRM critic) |
| 1-dim × ephemeral | Reflexion (in-process buffer) |

채택 패턴: **multi-dim mutation lineage** — AlphaEvolve 와 AI Scientist v2 가 정확한 reference. RFC §5/§6 의 mutation_id 디렉토리 grouping + 4 파일 schema 가 이 패턴의 구체 instantiation.

부차 reference (lineage 측만): DGM archive 의 append-only + Voyager 의 vector retrieval selection 패턴 — 폐기 mutation 의 미래 reseed source 활용 가능성.

거부 anti-pattern:
- 별 파일 단독 추가 (`lineage.jsonl` + `attribution.jsonl`) → mutator context source 파편화 가속 (F2). 대신 mutation_id 디렉토리 내부에 grouping.
- SQLite 단일 DB → git diff 곤란, [[project-petri-p1-handoff]] PR-G5b 의 git-tracked invariant 약화.

## 5. 디렉토리 구조

```
autoresearch/state/
├── mutations.jsonl                          # 기존 index ledger (유지, drift invariant 로 동기)
└── runs/
    └── <YYYY-MM-DD>/                        # 일별 prefix (디렉토리 폭발 방지)
        └── <mutation_id>/                   # UUIDv7 (time-sortable)
            ├── apply.json                   # mutation 적용 record (mutator writer, T3)
            ├── pre_state.json               # multi-dim pre-state snapshot (mutator writer, T3 직전)
            ├── post_state.json              # multi-dim post-audit measurement (train.py writer, T4)
            └── trace.eval -> <petri eval>   # symlink (audit subprocess writer, T4)
```

`<YYYY-MM-DD>` 예: `2026-05-25/`. 일별 prefix 로 디렉토리당 항목 수 안전 확보 (월 1000 mutation 시 일 ~33 < 50). `pre_state` / `post_state` 명명은 두 파일이 multi-dim mutation lineage 의 (before/after) 양면임을 명시화 — frontier 의 (multi-dim × lineage) 분면 채택과 정합.

## 6. 파일별 Schema

### 6.1 `apply.json`

```json
{
  "schema_version": 1,
  "mutation_id": "<uuid>",
  "parent_mutation_id": "<uuid>|null",
  "siblings": [],
  "ts": "2026-05-25T12:34:56Z",
  "kind": "applied",
  "target_kind": "prompt|tool_policy|reflection|skill_catalog|agent_contract",
  "target_section": "<section name>",
  "new_value": "<string or JSON>",
  "rationale": "<mutator LLM 설명>",
  "expected_dim": {"<dim_id>": 0.15},
  "baseline_fitness": {"<dim_id>": 0.42},
  "rollback_condition": "<예: delta(<dim>) < -0.05>",
  "cost_usd": 0.012,
  "model": "<mutator model name>"
}
```

`siblings` 필드는 MCTS sibling exploration (frontier 패턴 #3) 의 forward-compat 예약 — 현 단계는 항상 `[]`.

### 6.2 `pre_state.json` (mutation 적용 직전 multi-dim snapshot)

```json
{
  "schema_version": 1,
  "mutation_id": "<uuid>",
  "snapshot_ts": "2026-05-25T12:34:55Z",
  "target_kind": "<same as apply>",
  "target_section": "<same as apply>",
  "previous_value": "<string or JSON>",
  "previous_section_keys": ["role", "tool_result_handling", "..."],
  "baseline_dim_means": {"<dim_id>": 3.7},
  "baseline_dim_stderr": {"<dim_id>": 0.12}
}
```

`_rollback_sot()` 가 SoT 를 덮어쓰기 *직전* 의 (multi-dim baseline + 변경 전 value) 양면 캡처. mutation 폐기 시 이 파일만으로도 historical state 복원 가능. `baseline_dim_means/stderr` 는 mutation 직전 baseline.json 의 snapshot — 후속 post_state 와 delta 계산할 때 stale-baseline race 회피.

### 6.3 `post_state.json` (audit 종료 후 multi-dim measurement)

```json
{
  "schema_version": 1,
  "mutation_id": "<uuid>",
  "audit_id": "<uuid>",
  "audit_ts_start": "2026-05-25T13:00:00Z",
  "audit_ts_end": "2026-05-25T13:18:42Z",
  "dim_results": [
    {
      "dim_id": "input_hallucination",
      "pre_score": 3.7,
      "post_score": 3.4,
      "delta": -0.3,
      "pre_stderr": 0.12,
      "post_stderr": 0.10,
      "sample_size": 30,
      "confidence": "medium"
    }
  ],
  "audit_cost_usd": 0.85,
  "audit_duration_seconds": 1122
}
```

`pre_score` / `pre_stderr` 는 pre_state.json 의 `baseline_dim_means` / `baseline_dim_stderr` 와 동일해야 (drift invariant) — 일치하지 않으면 baseline race 발생 신호.

`confidence` enum: `high` (sample_size ≥ 30 AND |delta| > 2·stderr), `medium` (sample_size ≥ 15), `low` (sample_size ≥ 5), `insufficient` (그 외).

### 6.4 `trace.eval` (symlink)

audit subprocess 가 종료 시 `docs/petri-bundle/logs/<audit_id>.eval` 를 가리키는 relative symlink 생성. Petri 원본 파일은 별 위치 정책 그대로.

## 7. Writer / Reader 책임

### Writer

| 파일 | Writer 함수 | 위치 | 시점 |
|---|---|---|---|
| `apply.json` | `_write_apply_record()` (신규) | `core/self_improving_loop/runs.py` 호출은 `runner.py:apply_proposal()` (line 1024 부근) | mutation apply 직후 (T3) |
| `pre_state.json` | `_snapshot_pre_state()` (신규) | `runner.py:apply_mutation()` (line 803-825) 직전 | T3 직전 (apply 전 multi-dim baseline + previous_value 캡처) |
| `post_state.json` | `_write_post_state_record()` (신규) | `autoresearch/train.py:_persist_baseline()` 직후 | T4 (audit 종료) |
| `trace.eval` symlink | `_link_petri_trace()` (신규) | audit subprocess 종료 hook | T4 |

### Reader API (신규 모듈: `core/self_improving_loop/runs.py`)

```python
@dataclass(frozen=True, slots=True)
class MutationRun:
    apply: ApplyRecord
    pre_state: PreStateRecord | None
    post_state: PostStateRecord | None
    trace_path: Path | None

def load_mutation_run(mutation_id: str) -> MutationRun: ...

def iter_mutation_runs(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    target_kind: TargetKind | None = None,
    has_post_state: bool | None = None,
) -> Iterator[MutationRun]: ...

def load_mutation_chain(mutation_id: str) -> list[MutationRun]:
    """Follow apply.parent_mutation_id chain to root (multi-dim mutation lineage)."""

def load_post_state_for_mutation(mutation_id: str) -> PostStateRecord | None: ...
```

## 8. 운영자 결정 사항 (2026-05-25 일괄 채택)

| # | 항목 | 채택 | 근거 |
|---|---|---|---|
| Q1 | mutation_id 형식 | **UUIDv7** (RFC 9562) | time-sortable, `runs/2026-05-25/<uuidv7>/` 디렉토리 시간순 정렬, mutator history reader 효율. 기존 mutations.jsonl UUID4 row 는 backward-compat 유지, 신규 mutation 부터 UUIDv7 |
| Q2 | `trace.eval` | **symlink (relative)** | Petri eval origin = `docs/petri-bundle/logs/`, `runs/` 는 view. 디스크 절약 + 단일 origin. portable export 시 symlink resolve 책임은 export 도구 |
| Q3 | 디렉토리 prefix | **`<YYYY-MM-DD>/`** (day) | mutation rate 일 ~수십 가정 시 디렉토리당 항목 수 안전. month prefix 보다 폭발 회복력 + audit 의 자연 단위 (audit cycle ≈ 일 단위) 와 정합. mutations.jsonl 의 `ts` 와 같은 일 prefix 로 cross-ref 직관 |
| Q4 | drift invariant | **fail (raise)** | [[feedback-changelog-implementation-parity]] + [[feedback-dual-sot-drift-invariant]] 정합. (a) apply.json ↔ mutations.jsonl new_value 동등성, (b) pre_state.json baseline ↔ post_state.json pre_score 동등성 둘 다 깨지면 audit subprocess 중단 |
| Q5 | `siblings` 필드 | **예약 (`[]` always)** | 향후 MCTS sibling exploration schema migration 부담 회피. 빈 list 비용 무시 수준 |

## 9. Migration

- 기존 `mutations.jsonl` 그대로 유지 (legacy reader 호환)
- PR-3 implementation 시 새 mutation 부터 `runs/` 디렉토리 생성
- 과거 mutations.jsonl row 는 backfill 안 함 — `pre_state.json`, `post_state.json` 없는 historical 로 표시
- `iter_mutation_runs` 가 `runs/` 디렉토리만 enumerate (mutations.jsonl 는 backward-compat index)

## 10. .gitignore 정책

`apply.json`, `pre_state.json`, `post_state.json`, `trace.eval` symlink **모두 git-tracked**. AlphaEvolve evolutionary DB 도 commit 패턴 (frontier 정합).

⚠️ PR-3 구현 전 `git check-ignore autoresearch/state/runs/2026-05-25/test-id/apply.json` 으로 실제 ignore 정책 확인 + 회귀 invariant 테스트 ([[project-petri-p1-handoff]] PR-G5b 의 silent-ignored writer 사례 회피).

## 11. PR-3 Acceptance Criteria

- [ ] 디렉토리 구조 §5 와 정확히 매치 (`runs/<YYYY-MM-DD>/<UUIDv7>/`)
- [ ] 4 파일 schema §6 와 정확히 매치 (Pydantic model 로 freeze: `ApplyRecord`, `PreStateRecord`, `PostStateRecord`)
- [ ] Writer 책임 분배 §7 와 정확히 매치
- [ ] Reader API 신규 모듈 `core/self_improving_loop/runs.py` 생성 (`load_mutation_run`, `iter_mutation_runs`, `load_mutation_chain`, `load_post_state_for_mutation`)
- [ ] drift invariant 테스트 (Q4 fail 모드):
  - [ ] apply.json `new_value` ↔ mutations.jsonl row `new_value` 동등성
  - [ ] pre_state.json `baseline_dim_means/stderr` ↔ post_state.json `pre_score/pre_stderr` 동등성
- [ ] `.gitignore` 회귀 invariant 테스트 (`test_runs_dir_not_gitignored`)
- [ ] UUIDv7 sortable invariant 테스트 (`test_uuidv7_directory_lexsort_equals_timesort`)
- [ ] symlink resolve invariant 테스트 (`test_trace_eval_symlink_resolves_to_petri_log`)
- [ ] backward compat — 기존 mutations.jsonl reader 그대로 통과
- [ ] lint + mypy + pytest 모두 통과

추정: ~200-250 LOC + 6 테스트.

## 12. 후속 (PR-4+)

- F1 cross-run SoT 3중첩 통합 (별 sprint)
- F3 mutator history reader wiring (본 schema 의 `iter_mutation_runs` 활용)
- MCTS sibling exploration (siblings 필드 활성화, frontier 패턴 #3 AFLOW/SELA/BFTS)
- G2 rollback_condition enforcement (post_state.json 의 dim_results 와 apply.rollback_condition 비교)

## 13. Reference

- [[reference-mutation-surface-frontier-2026-05-25]] — 16 frontier 사례 카탈로그
- [Darwin Gödel Machine arXiv 2505.22954](https://arxiv.org/abs/2505.22954) — lineage archive 패턴
- [AlphaEvolve — DeepMind blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) — evolutionary DB
- [Coze Loop GitHub](https://github.com/coze-dev/coze-loop) — multi-dim eval observability
- [AutoGLM arXiv 2411.00820](https://arxiv.org/html/2411.00820v1) — ORM+PRM critic
