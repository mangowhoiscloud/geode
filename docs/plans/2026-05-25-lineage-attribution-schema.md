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

frontier 패턴 (DGM / AlphaEvolve / Voyager / AI Scientist v2) 의 **append-only lineage archive** + AlphaEvolve / Coze Loop / AutoGLM 의 **multi-dim attribution log** 두 패턴을 GEODE 에 차용해 G1+G3 해소.

## 2. 목표

lineage archive + attribution log 의 **통합 schema 확정**. 별 파일 추가(`lineage.jsonl` + `attribution.jsonl`)로 파편화 가속(F2) 회피 위해 **mutation_id 별 디렉토리 grouping** (대안 B) 채택.

## 3. Non-Goals

- F1 cross-run SoT 3중첩 (`meta-review snapshot` + `latest_pointer.json` + `sessions.jsonl`) 통합 — 별 incident sprint
- F3 mutator 가 mutations.jsonl 자기 history 를 context 로 보는 기능 — 본 schema 가 enabler 가 되나 reader wiring 은 후속 PR
- decomposition kind 의 mutation target 복귀
- MCTS sibling exploration (frontier 패턴 #3) full 구현 — 본 schema 는 sibling field 예약만

## 4. Frontier 그라운딩

| 채택 패턴 | 출처 |
|---|---|
| Append-only lineage archive | DGM (Sakana 2025-05), AlphaEvolve (DeepMind 2025-05), Voyager (NVIDIA 2023), AI Scientist v2 (Sakana 2025-04) |
| Multi-dim attribution log | AlphaEvolve evolutionary DB, Coze Loop multi-dim eval (ByteDance 2025-07), AutoGLM ORM+PRM (Zhipu 2024-11) |
| EVOLVE-BLOCK 마커 (fine-grained scope) | AlphaEvolve `# EVOLVE-BLOCK-START/END` |

거부 anti-pattern:
- 별 파일 attribution.jsonl 단독 추가 → 파편화 가속 (F2). 대신 mutation_id 디렉토리 내부에 grouping.
- SQLite 단일 DB → git diff 곤란, [[project-petri-p1-handoff]] PR-G5b 의 git-tracked invariant 약화.

## 5. 디렉토리 구조

```
autoresearch/state/
├── mutations.jsonl                          # 기존 index ledger (유지, drift invariant 로 동기)
└── runs/
    └── <YYYY-MM>/                           # 월별 prefix (디렉토리 폭발 방지)
        └── <mutation_id>/
            ├── apply.json                   # mutation 적용 record (mutator writer, T3)
            ├── lineage.json                 # previous_value snapshot (mutator writer, T3 직전)
            ├── attribution.json             # post-audit dim deltas (train.py writer, T4)
            └── trace.eval -> <petri eval>   # symlink (audit subprocess writer, T4)
```

`<YYYY-MM>` 예: `2026-05/`. 월 ~수십 mutation 가정 시 디렉토리당 항목 수 안전.

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

### 6.2 `lineage.json`

```json
{
  "schema_version": 1,
  "mutation_id": "<uuid>",
  "snapshot_ts": "2026-05-25T12:34:55Z",
  "target_kind": "<same as apply>",
  "target_section": "<same as apply>",
  "previous_value": "<string or JSON>",
  "previous_section_keys": ["role", "tool_result_handling", "..."]
}
```

`_rollback_sot()` 가 SoT 를 덮어쓰기 *직전* 의 상태를 캡처. mutation 폐기 시 lineage.json 만으로도 historical state 복원 가능.

### 6.3 `attribution.json`

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

`confidence` enum: `high` (sample_size ≥ 30 AND |delta| > 2·stderr), `medium` (sample_size ≥ 15), `low` (sample_size ≥ 5), `insufficient` (그 외).

### 6.4 `trace.eval` (symlink)

audit subprocess 가 종료 시 `docs/petri-bundle/logs/<audit_id>.eval` 를 가리키는 relative symlink 생성. Petri 원본 파일은 별 위치 정책 그대로.

## 7. Writer / Reader 책임

### Writer

| 파일 | Writer 함수 | 위치 | 시점 |
|---|---|---|---|
| `apply.json` | `_write_apply_record()` (신규) | `core/self_improving_loop/runs.py` 호출은 `runner.py:apply_proposal()` (line 1024 부근) | mutation apply 직후 (T3) |
| `lineage.json` | `_snapshot_lineage()` (신규) | `runner.py:apply_mutation()` (line 803-825) 직전 | T3 직전 (apply 전 previous_value 캡처) |
| `attribution.json` | `_write_attribution_record()` (신규) | `autoresearch/train.py:_persist_baseline()` 직후 | T4 (audit 종료) |
| `trace.eval` symlink | `_link_petri_trace()` (신규) | audit subprocess 종료 hook | T4 |

### Reader API (신규 모듈: `core/self_improving_loop/runs.py`)

```python
@dataclass(frozen=True, slots=True)
class MutationRun:
    apply: ApplyRecord
    lineage: LineageRecord | None
    attribution: AttributionRecord | None
    trace_path: Path | None

def load_mutation_run(mutation_id: str) -> MutationRun: ...

def iter_mutation_runs(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    target_kind: TargetKind | None = None,
    has_attribution: bool | None = None,
) -> Iterator[MutationRun]: ...

def load_lineage_chain(mutation_id: str) -> list[MutationRun]:
    """Follow parent_mutation_id chain to root."""

def load_attribution_for_mutation(mutation_id: str) -> AttributionRecord | None: ...
```

## 8. 운영자 결정 사항 (2026-05-25 일괄 채택)

| # | 항목 | 채택 | 근거 |
|---|---|---|---|
| Q1 | mutation_id 형식 | **UUIDv7** (RFC 9562) | time-sortable, `runs/2026-05/<uuidv7>/` 디렉토리 시간순 정렬, mutator history reader 효율. 기존 mutations.jsonl UUID4 row 는 backward-compat 유지, 신규 mutation 부터 UUIDv7 |
| Q2 | `trace.eval` | **symlink (relative)** | Petri eval origin = `docs/petri-bundle/logs/`, `runs/` 는 view. 디스크 절약 + 단일 origin. portable export 시 symlink resolve 책임은 export 도구 |
| Q3 | 디렉토리 prefix | **`<YYYY-MM>/`** (month) | mutation rate 일 100 미만 가정 시 디렉토리당 ~수천 항목 OK. 향후 폭발 시 day prefix 로 migrate (별 incident) |
| Q4 | drift invariant | **fail (raise)** | [[feedback-changelog-implementation-parity]] + [[feedback-dual-sot-drift-invariant]] 정합. apply.json ↔ mutations.jsonl new_value 동등성 깨지면 audit subprocess 중단 |
| Q5 | `siblings` 필드 | **예약 (`[]` always)** | 향후 MCTS sibling exploration (frontier 패턴 #3) schema migration 부담 회피. 빈 list 비용 무시 수준 |

## 9. Migration

- 기존 `mutations.jsonl` 그대로 유지 (legacy reader 호환)
- PR-3 implementation 시 새 mutation 부터 `runs/` 디렉토리 생성
- 과거 mutations.jsonl row 는 backfill 안 함 — `lineage.json`, `attribution.json` 없는 historical 로 표시
- `iter_mutation_runs` 가 `runs/` 디렉토리만 enumerate (mutations.jsonl 는 backward-compat index)

## 10. .gitignore 정책

`apply.json`, `lineage.json`, `attribution.json`, `trace.eval` symlink **모두 git-tracked**. AlphaEvolve evolutionary DB 도 commit 패턴 (frontier 정합).

⚠️ PR-3 구현 전 `git check-ignore autoresearch/state/runs/2026-05/test-id/apply.json` 으로 실제 ignore 정책 확인 + 회귀 invariant 테스트 ([[project-petri-p1-handoff]] PR-G5b 의 silent-ignored writer 사례 회피).

## 11. PR-3 Acceptance Criteria

- [ ] 디렉토리 구조 §5 와 정확히 매치
- [ ] 4 파일 schema §6 와 정확히 매치 (Pydantic model 로 freeze)
- [ ] Writer 책임 분배 §7 와 정확히 매치
- [ ] Reader API 신규 모듈 `core/self_improving_loop/runs.py` 생성
- [ ] drift invariant 테스트 — apply.json ↔ mutations.jsonl new_value 동등성, Q4 결정에 따라 warn/fail
- [ ] `.gitignore` 회귀 invariant 테스트 (`test_runs_dir_not_gitignored`)
- [ ] backward compat — 기존 mutations.jsonl reader 그대로 통과
- [ ] lint + mypy + pytest 모두 통과

추정: ~200-250 LOC + 6 테스트.

## 12. 후속 (PR-4+)

- F1 cross-run SoT 3중첩 통합 (별 sprint)
- F3 mutator history reader wiring (본 schema 의 `iter_mutation_runs` 활용)
- MCTS sibling exploration (siblings 필드 활성화, frontier 패턴 #3 AFLOW/SELA/BFTS)
- G2 rollback_condition enforcement (attribution.json 의 dim_results 와 rollback_condition 비교)

## 13. Reference

- [[reference-mutation-surface-frontier-2026-05-25]] — 16 frontier 사례 카탈로그
- [Darwin Gödel Machine arXiv 2505.22954](https://arxiv.org/abs/2505.22954) — lineage archive 패턴
- [AlphaEvolve — DeepMind blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) — evolutionary DB
- [Coze Loop GitHub](https://github.com/coze-dev/coze-loop) — multi-dim eval observability
- [AutoGLM arXiv 2411.00820](https://arxiv.org/html/2411.00820v1) — ORM+PRM critic
