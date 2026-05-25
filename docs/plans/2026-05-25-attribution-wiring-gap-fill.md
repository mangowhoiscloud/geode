# 2026-05-25 — Attribution Wiring Gap Fill (Cognitive-Loop Uplift PR-5 후속)

> Status: **Draft** (사용자 검토 대기)
> Framing: **wiring gap fill** — cognitive-loop-uplift sprint 의 dead-framework debt 중 attribution.py 만 처리
> 관련 메모리: [[project-autoresearch-separation-architecture]], [[project-autoresearch-state-injection-pipeline]], [[project-autoresearch-fragmentation-audit]], [[reference-mutation-surface-frontier-2026-05-25]], [[feedback-post-implementation-verification]]
> 정정 대상: PR #1626 RFC (`docs/plans/2026-05-25-lineage-attribution-schema.md`)

## 1. Background

Cognitive-loop-uplift sprint (`docs/plans/2026-05-21-cognitive-loop-uplift.md`) 의 PR-1~PR-6 모두 main merge 완료 (2026-05-20):
- PR-1 G-A~G-E (mutator manifest) — LIVE
- PR-2 C-1+C-6 (CognitiveState + 6 HookEvent telemetry) — LIVE
- PR-3 C-2 (reflection node) — LIVE
- PR-4 C-3 (episodic memory) — LIVE
- PR-5 C-4 (causal attribution) — **framework only, production caller 0**
- PR-6 C-5 (5-kind policy dispatcher) — LIVE 하나 `expected_dim` 생성 부재로 closed loop 미완성

`self_improving_loop/` 17 모듈 분류:

| 분류 | 모듈 수 | 비고 |
|---|---|---|
| LIVE | 11 | runner / policies / in_context_wiring / 외 8 |
| WIRED-COLD | 1 | auto_trigger (config flag off default) |
| FRAMEWORK-ONLY | **5** | attribution + DPO 4종 (pack/publisher/redaction/stats) |

즉 wiring debt 는 attribution 만의 isolated 문제가 아니라 systemic — sprint 가 framework 깔고 wiring 을 후속에 미루는 패턴이 반복됨. 본 plan 은 그 중 attribution 만 다룬다.

## 2. Frame — "wiring gap fill"

| 위치 | dead-framework | 본 plan scope? |
|---|---|---|
| (A) `attribution.py` (PR-5 C-4) | caller 0, `compute_attribution` 호출 없음 | ✅ 본 plan |
| (B) DPO M4 파이프라인 (`dpo_pack/publisher/redaction/stats`) | CLI endpoint 부재로 unreachable | ❌ 별 sprint |
| (C) `auto_trigger.py` cold wiring | config flag off default | ❌ operator decision |

본 plan 은 (A) 만 처리. (B)/(C) 는 GAP 자체는 인지하나 별 sprint.

## 3. Goal

**PR-5 attribution 의 closed loop 완성**:

1. mutation 적용 시 `expected_dim` 명시 생성 (현재 LLM 이 빠뜨릴 수 있음)
2. audit 종료 후 `compute_attribution` 호출 → mutations.jsonl 에 `kind="attribution"` row 실제 append
3. mutation row ↔ attribution row 의 within-ledger cross-ref (`audit_run_id` correlation id) 추가. **Petri eval archive path 와의 명시 link 는 본 PR scope 밖** — 후속 PR 에서 `eval_archive` field 추가
4. (선택) apply + attribution row 의 Pydantic schema freeze

결과로 mutation → expected_dim → audit → observed_dim → attribution_score → (후속 PR 의) policy 선택 인과사슬 완성. PR-6 의 5-kind policy dispatcher 가 이 신호 기반으로 mutation 채택률을 학습할 수 있게 됨.

## 4. Out of Scope

- PR #1626 RFC 의 디렉토리 grouping / UUIDv7 / 4 파일 schema / day prefix — **over-engineering 으로 폐기** (§7 RFC amend 에서 명시적 drop)
- DPO M4 wiring (dpo_pack/publisher/redaction/stats)
- auto_trigger 활성화
- F1 cross-run SoT 3중첩 통합 ([[project-autoresearch-fragmentation-audit]])
- F3 mutator 가 자기 mutations.jsonl history 를 context 로 받기 (단, attribution wiring 후 자연 가능 — 후속)
- frontier 디렉토리 grouping 패턴의 실제 채택 ([[reference-mutation-surface-frontier-2026-05-25]] 의 (multi-dim × lineage) 분면은 RFC 정정 후 single-ledger 패턴으로 재해석)

## 5. 4 Wiring 작업 정의

| # | Wiring | 위치 | LOC | 검증 테스트 |
|---|---|---|---|---|
| **W1** | mutation prompt 가 `expected_dim` 명시 요청 + parse | `core/self_improving_loop/runner.py` 의 mutator system prompt + `parse_mutation()` (line 743 부근) | ~30 | `test_mutation_prompt_requests_expected_dim`, `test_apply_row_includes_expected_dim` |
| **W2** | `compute_attribution` caller (post-audit hook) | `autoresearch/train.py:_persist_baseline()` 직후 (T4 timing) | ~50 | `test_post_audit_writes_attribution_row`, `test_attribution_row_has_observed_dim` |
| **W3** | `audit_run_id` field 추가 (mutation + attribution row) | `runner.py:Mutation.to_audit_row()` + `attribution.py:write_attribution()` + 호출자 chain | ~30 | `test_mutation_row_includes_audit_run_id`, `test_audit_run_id_cross_ref_works` |
| **W4** | Pydantic schema freeze | `attribution.py:AttributionRecord` + `runner.py:ApplyRecord` 별 Pydantic | ~80 | `test_apply_record_roundtrip`, `test_attribution_record_roundtrip` |

총 ~270 LOC + 8 테스트 (2026-05-25 운영자 결정 — 4 wiring 완전 묶음).

### W1 상세

현재 `parse_mutation()` (`runner.py:743`) 는 LLM response 에서 `expected_dim` 을 optional 로 추출 — LLM 이 빠뜨리면 빈 dict. mutation prompt 자체가 `expected_dim` 을 명시 요청하지 않음 (mutator 가 "어떤 파일의 어떤 부분 바꿔" 만 묻고, "그래서 어떤 dim 이 어떻게 움직일 거라고 기대해?" 는 안 물음).

수정:
- mutator system prompt 에 `expected_dim` 명시 요청 추가 ("for each dim you expect to move, output {dim: signed_delta_in_[-1,1]}")
- `parse_mutation()` 에서 `expected_dim` 비어 있으면 WARNING log (validation 강화)

### W2 상세

`autoresearch/train.py` 의 audit 종료 시점 (`_persist_baseline()` 직후) 에:
```python
from core.self_improving_loop.attribution import compute_attribution, append_attribution_log
payload = compute_attribution(
    mutation_id=current_mutation_id,
    expected_dim=current_mutation_expected_dim,
    baseline_before=baseline_snapshot_before,
    baseline_after=baseline_snapshot_after,
    fitness_before=fitness_before,
    fitness_after=fitness_after,
)
append_attribution_log(payload, log_path=MUTATION_AUDIT_LOG_PATH)
```

`current_mutation_id` + `current_mutation_expected_dim` 은 audit subprocess 의 진입 context 에서 받음 (env 또는 stdin) — 또는 가장 최근 `kind="applied"` row 를 mutations.jsonl 에서 tail 로 읽기.

후자가 단순 (외부 의존 없음, JSONL tail 로 충분).

### W3 상세

apply row + attribution row 에 `audit_run_id` 추가 — runner 가 propose-apply-audit 한 cycle 안에서 mint 하는 **correlation id** (`uuid.uuid4().hex[:12]`). 본 PR 의 audit_run_id 는 Petri eval archive 의 path/hash 와 link 되지 않음 — 단지 within-ledger 의 (apply, attribution) row pair 를 join 하는 second key.

`Mutation.to_audit_row(audit_run_id=...)` parameter 로 전달 (Mutation 자체는 frozen). attribution row 도 같은 audit_run_id carry. mutations.jsonl 단일 ledger 안에서 mutation_id (primary) + audit_run_id (secondary) 두 키로 row pair 식별.

Petri eval archive path 와의 명시 link (`eval_archive` field) 는 후속 PR — `train.py:_resolve_eval_archive_path()` 의 결과를 attribution row 의 새 field 로 추가하면 됨 (~10 LOC).

### W4 상세

기존 dict-based row → Pydantic `ApplyRecord` + `AttributionRecord` 모델로 freeze. validation 강화 + IDE autocomplete + JSON schema export. 마이그레이션: 기존 reader 코드 (`outer_bundle.py`, `cli/commands/self_improving.py`) 의 dict 접근을 `.model_dump()` 호환 layer 로 wrap (backward-compat 보존). writer 는 `model.model_dump_json()` 으로 직렬화.

## 6. PR 분할 옵션

### α-1: PR-2.1 (RFC amend) + PR-3 (wiring)

- PR-2.1: RFC #1626 amend (~50 LOC RFC 변경) → develop
- PR-3: 4 wiring 구현 (~190 LOC + 6 테스트)
- 2 PR sequential, PR-3 는 PR-2.1 merge 후 시작

장점: RFC amend 와 wiring 의 의도가 명확히 분리 (문서 PR vs 코드 PR), 각 PR scope 작음
단점: 2 PR 분리 비용, PR-3 worktree 가 RFC amend 반영을 위해 rebase 필요

### α-2: PR-3 단일 PR (RFC amend + wiring 통합)

- 단일 PR: RFC amend + 4 wiring 구현 (~240 LOC + 6 테스트 + RFC 1장)

장점: RFC amend 의 동기 (wiring 으로 정정) 가 같은 PR 안에서 명백, sprint 1 회로 끝
단점: PR scope 크고 review 부담 ↑

**추천: α-2** — RFC amend 의 의도가 wiring 자체이므로 한 패키지로 묶는 게 자연스러움. RFC amend 만 따로 PR 으로 분리하면 reviewer 가 "왜 이렇게 amend 하나" 를 wiring 의 motivation 없이 판단해야 함.

## 7. RFC amend 내용 (PR #1626 의 정정)

기존 RFC `docs/plans/2026-05-25-lineage-attribution-schema.md` 의 amend 사항:

| § | 기존 | amend |
|---|---|---|
| §0 | (Status: Final) | "Status: **Amended 2026-05-25** — 디렉토리 grouping 폐기, single-ledger 패턴으로 정정. 정정 사유: PR-5 C-4 attribution.py 의 dead-framework 발견" 추가 |
| §4 Frontier | (multi-dim × lineage) 분면 채택 | "GEODE 의 기존 single-ledger 패턴 (`mutations.jsonl` 의 `kind` discriminator) 이 이미 (lineage × multi-dim) 두 측면을 단일 ledger 로 통합. frontier 의 디렉토리 grouping 패턴 (AlphaEvolve evolutionary DB) 은 GEODE 의 single-ledger 와 정합 안 됨 — 패턴 적용 거부" |
| §5 디렉토리 구조 | `runs/<YYYY-MM-DD>/<UUIDv7>/{apply,pre_state,post_state}.json + trace.eval` | **폐기**. `mutations.jsonl` single-ledger 유지, `audit_run_id` field 추가로 Petri trace link 만 명시 |
| §6 4 파일 schema | apply / pre_state / post_state / trace.eval | **폐기**. 기존 `Mutation.to_audit_row()` (16 fields) + `compute_attribution()` (13 fields) row schema 유지. `audit_run_id` field 만 추가. (선택) Pydantic freeze 는 W4 |
| §7 Writer/Reader | runs.py 신규 모듈 | **폐기**. 기존 `runner.py:append_audit_log` + `attribution.py:append_attribution_log` writer 유지. reader 는 mutations.jsonl tail / mutation_id join |
| §8 운영자 결정 5 항목 | UUIDv7 / symlink / day prefix / drift / siblings | **drop**: UUIDv7 (단순 hex[12] 유지), symlink (audit_run_id 로 대체), day prefix (해당없음), siblings (해당없음). **유지**: drift invariant (apply ↔ attribution 의 mutation_id 동등성 + expected_dim ↔ observed_dim 정합) |
| §11 Acceptance Criteria | 디렉토리 / Pydantic / UUIDv7 / symlink invariant | 4 wiring 의 6 invariant 테스트로 재정의 (W1-W4) |
| §13 Reference | AlphaEvolve / AI Scientist v2 / DGM / Voyager | frontier 그라운딩 정정 — single-ledger 패턴은 GEODE 만의 것 (openclaw/hermes/autoresearch 검증 0건). DGM/AlphaEvolve 는 lineage 측만 부차 reference |

새 §0 "정정 history" 추가 — 2026-05-25 정정 사유 + 이전 결정의 어느 부분 무효 명시 ([[feedback-changelog-implementation-parity]] 정합).

## 8. Acceptance Criteria

### Implementation
- [ ] W1: mutation prompt 에 `expected_dim` 요청이 명시됨, mutation row 의 `expected_dim` 이 non-empty 로 append
- [ ] W2: audit 종료 후 `compute_attribution` 호출 + attribution row append
- [ ] W3: mutation row + attribution row 모두 `audit_run_id` field 가짐, mutation_id + audit_run_id 두 키로 row pair 식별 가능 (Petri eval archive link 는 후속 PR)
- [ ] W4: Pydantic ApplyRecord / AttributionRecord schema roundtrip 통과 + backward-compat dict reader wrap

### Invariant tests (6)
- [ ] `test_mutation_prompt_requests_expected_dim`
- [ ] `test_apply_row_includes_expected_dim_after_parse`
- [ ] `test_post_audit_writes_attribution_row`
- [ ] `test_mutation_id_join_apply_to_attribution`
- [ ] `test_audit_run_id_cross_ref_with_petri_eval`
- [ ] `test_backward_compat_dict_row_reader_unchanged`

### Quality gates
- [ ] `uv run ruff check core/ tests/ plugins/`
- [ ] `uv run ruff format --check core/ tests/ plugins/`
- [ ] `uv run mypy core/ plugins/`
- [ ] `uv run pytest tests/core/self_improving_loop/ tests/test_attribution_belief.py tests/test_causal_attribution.py -q`
- [ ] `uv run lint-imports`
- [ ] CLI smoke: `uv run geode version`

### Codex MCP verification
- [ ] Diff cross-LLM 검증 — 4 wiring 의 production caller chain 완성, dead code 없음
- [ ] Closed loop 검증 — mutation → expected_dim → audit → observed_dim → attribution_score 인과사슬
- [ ] RFC amend 정정 사항이 diff 와 1:1 매치 ([[feedback-changelog-implementation-parity]])
- [ ] Out-of-scope leak 없음 (DPO M4 framework 등 isolated 변경이 없도록 scope confine)

## 9. Codex MCP 검증 단계

[[feedback-codex-mcp-verification]] 따라 PR push 직전 Codex MCP (`mcp__codex__codex`) 호출:

```
prompt:
  GEODE self-improving-loop 의 attribution wiring gap fill PR-3 diff 를 검증해줘.
  4 wiring (W1-W4) 의 production caller chain 이 끊김 없이 연결되는지 + closed loop
  (mutation → expected_dim → audit → observed_dim → attribution_score) 가 완성되는지 +
  RFC #1626 amend 사항이 diff 의 변경과 정합하는지 cross-check.

  특히 다음 anti-deception 패턴 확인:
  - mutation_id 가 attribution row 에 실제 propagate 되는가 (silent disconnect?)
  - compute_attribution 호출 시 baseline_before/after 가 stale 가능성 (T4 race)
  - expected_dim parse 가 fail 시 fallback behavior 가 quota 낭비를 방지하는가
  - DPO M4 framework 같은 isolated 변경이 포함됐는가 (scope leak)
```

sandbox=read-only, approval-policy=never.

## 10. Sprint 추정

| 단계 | 시간 | LOC |
|---|---|---|
| Plan 검토 + 승인 (현재) | — | — |
| Worktree 할당 | 1 min | — |
| RFC amend draft | 15 min | RFC ±50 |
| W1 mutation prompt + parse | 20 min | ~30 |
| W2 compute_attribution caller | 30 min | ~50 |
| W3 audit_run_id field | 20 min | ~30 |
| W4 Pydantic freeze | 40 min | ~80 |
| 8 invariant 테스트 작성 | 50 min | ~200 (테스트) |
| Local quality gates | 5 min | — |
| Codex MCP 검증 | 15 min | — |
| PR 생성 + CI watch + merge | 15 min | — |
| **Total** | **~3시간** | **~340** |

## 11. 후속 작업 (본 PR scope 밖, Codex MCP 검증 #5/#6 잔존 항목 포함)

- **F1 cross-run SoT 3중첩 통합** (별 sprint) — [[project-autoresearch-fragmentation-audit]] F1
- **F3 mutator history reader wiring** — mutations.jsonl tail + mutation_id join 으로 mutator context 풍부화 (~20 LOC)
- **G2 rollback_condition enforcement** — attribution row 의 observed_dim 과 apply row 의 rollback_condition 비교, fitness 저하 시 자동 revert
- **audit_run_id ↔ Petri eval_archive 명시 link** (Codex MCP 검증 #5 잔존) — attribution row 에 `eval_archive` field 추가 (`train.py:_resolve_eval_archive_path()` 결과 forward, ~10 LOC)
- **baseline_before T3 snapshot 캡처** (Codex MCP 검증 #6 잔존) — train.py 가 T4 시점 baseline.json 을 read 하므로 T3↔T4 사이 다른 mutation 이 baseline 을 promote 했으면 stale 위험. `core/llm/audit_lane.py` 의 OL-P2 audit_lane=1 가 host 단위 mitigate (host 당 동시 audit 1개), multi-host scenario 는 별 incident. T3 snapshot 을 env 또는 임시 파일로 propagate 하면 race 자체 제거 (~30 LOC)
- **self-improving runner concurrent run 방지** (Codex MCP 검증 #6 잔존) — file lock (`fcntl.LOCK_EX` on mutations.jsonl) 또는 host-level pid file 로 두 runner 동시 실행 차단
- **MCTS sibling exploration** — frontier 패턴 #3 (AFLOW/SELA/BFTS), siblings field 활성화

## 12. Reference

- 2026-05-21 plan: `docs/plans/2026-05-21-cognitive-loop-uplift.md` (PR-1~PR-6 cognitive uplift sprint)
- 2026-05-25 RFC: `docs/plans/2026-05-25-lineage-attribution-schema.md` (PR #1626 — 본 plan 으로 amend)
- Memory:
  - [[project-autoresearch-separation-architecture]] — 5 kind mutation surface 의 분리 구조
  - [[project-autoresearch-state-injection-pipeline]] — env propagation + 12-kind STRICT 모드
  - [[project-autoresearch-fragmentation-audit]] — F1/F2/F3 파편화 신호 (본 wiring 으로 F3 enabler)
  - [[reference-mutation-surface-frontier-2026-05-25]] — frontier 16건 (정정 후 single-ledger 가 GEODE 만의 패턴)
  - [[feedback-post-implementation-verification]] — 본 plan 작성 자체가 이 feedback 의 3번째 사례 (PR-1 ENV-PROPAGATION drop + 이번 attribution.py + DPO M4 framework 발견)
  - [[feedback-codex-mcp-verification]] — §9 Codex MCP 검증 단계
  - [[feedback-changelog-implementation-parity]] — §7 RFC amend 의 정정 history + §8 Codex verification 포함 사유
