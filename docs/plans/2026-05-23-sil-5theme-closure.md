# 2026-05-23 — Self-Improving Loop 5-Theme Closure (single PR, 6 commits)

> **Status**: APPROVED (operator confirmed F1.b + A1 + B1 on 2026-05-23)
> **Scope**: Bench S6b production wiring + ADR-012 §S6 amendment + P3 modality weight split + E1 mutation cost ledger + D4 X2 telemetry + D1 provider B/C closure
> **PR strategy**: single PR, **6 sequential commits** (one per theme) so reviewer + Codex MCP can audit chunk-by-chunk

## Driving observation

The self-improving loop has 5 independent silent-disconnect gaps. Each can be implemented in isolation, but they share a common diagnostic theme — *spec/code mismatches that the user can't observe today* — and the operator directive bundles them into one PR. The 6-commit split keeps review chunks tractable.

| # | Commit | Theme | LOC est | Risk |
|---|--------|-------|---------|------|
| C0 | this plan doc | — | — | — |
| C1 | `ADR-012` amendment | 3-axis → 4-axis fitness + new §S6 + §S6b | ~250 docs | Doc only — no behavior change |
| C2 | Bench S6b wiring | 7-bench (F1.b: LCB-Pro) + collector + Docker pre-flight + provenance + cross-validation activation | ~600 (mix code + tests) | Largest commit. Cross-validation gate activates for the first time → fitness landscape shift |
| C3 | P3 modality weight split | `_JUDGE_LLM_WEIGHTS` + `_ANALYTICS_WEIGHTS` + `compute_fitness(measurement_modality=...)` + N=1 widening 의 analytics-skip 가드 | ~150 | Fitness math change → regression-test heavy |
| C4 | E1 mutation cost ledger | `mutations.jsonl` 스키마 확장 (`cost_judge_tokens` + `cost_target_tokens` + `cost_seconds` + `fitness_delta`) + runner.py 의 LLM usage capture + attribution baseline_after pairing | ~250 | mutations.jsonl backward-compat (new cols optional) |
| C5 | D4 X2 telemetry | `HookEvent.PROMPT_ASSEMBLED` fire from `_sync_model_and_rebuild_prompt` + `_inject_model_switch_breadcrumb` 의 purged_count payload | ~120 | New hook fire — handler 부재 시 noop |
| C6 | D1 provider B/C closure | `PetriRoleConfig.source` default `auto → claude-cli` (Pydantic ValidationError 가 명시 PAYG 시 surface) + per-role source dispatch in `_build_audit_command` + `prepare.py` 의 binary + OAuth pre-flight | ~250 | Default change — operators with `source = "api_key"` 는 명시적 거부 (PR-C-P1 패턴 재사용) |

**Total**: ~1,620 LOC (코드 ~950 + 테스트 ~420 + docs ~250). ~30+ new tests.

---

## C1 — ADR-012 amendment

### Source of mismatch (B1 grounding result)

| 항목 | 코드 (실재) | ADR-012 (문서) | 결정 |
|------|------------|----------------|------|
| 축 개수 | 4축 (dim + ux + admire + bench) | **3축** (dim + ux + admire) | ADR 갱신 → 4축 |
| dim weight | 0.30 | 0.40 | ADR 갱신 → 0.30 |
| ux weight | 0.25 | 0.30 | ADR 갱신 → 0.25 |
| admire weight | 0.20 | 0.30 | ADR 갱신 → 0.20 |
| bench weight | 0.25 | **0 (축 자체 없음)** | ADR 갱신 → 0.25 + §S6 신설 |
| `seed_pool_diversity` 슬롯 | grep 0건 | §Decision.2 schema 에 포함 | ADR 명시 deprecate / 보류 |
| §S6 (bench 축) | 코드가 인용하나 doc 부재 | 부재 | 신설 |
| §S6b (production wiring) | 코드가 "예정" 인용 | 부재 | 신설 (이 PR 의 C2-C6 이 wiring) |

### C1 변경 파일

- `docs/adr/ADR-012-self-improvement-surface-tiers.md`
  - §Decision.2 의 "3축 multi-axis strict-reject ratchet" → "**4축** multi-axis strict-reject ratchet"
  - baseline.json schema 갱신: `seed_pool_diversity` 제거 (또는 deprecate 명시) + `bench_means` 추가
  - 축별 가중치 갱신: dim 0.30 / ux 0.25 / admire 0.20 / **bench 0.25**
  - **§S6 신설** (Bench fitness axis — 7-bench frontier federation, 2026-05 갱신 history, F1.b 의 LCB → LCB-Pro substitution 명시)
  - **§S6b 신설** (Production wiring — collector + Docker pre-flight + provenance fields)
  - "후속 PR 시퀀스" 표에 `S6` / `S6b` 추가
- `autoresearch/bench_means.py`
  - docstring 의 "ADR-012 §S6 결정" 인용 → 신설된 §S6 / §S6b 와 grep-provable 일치
  - "LiveCodeBench (algo, contam-free)" → "LiveCodeBench-Pro (competitive, contam-free, 2026 v2)" (F1.b)
  - `BENCH_DIM_WEIGHTS` 의 `livecodebench_pass1` → `livecodebench_pro_accuracy` (rename)

### C1 테스트

- `tests/test_adr_012_parity.py` (신규) — ADR-012 §Decision.2 의 4축 가중치 string parse + 코드 상수 (`FITNESS_*_4AX`) 와 일치 invariant. CHANGELOG/PR-body parity 의 doc 측 자동화.
- `tests/test_s6_bench_means_fitness.py` 갱신 — LCB-Pro rename 적용 + 신 schema 6 field 모두 weight assert (existing 7 field weight sum 1.0 는 변동 없음)

---

## C2 — Bench S6b production wiring (largest)

### 6-step MVP (이전 보고서)

1. `autoresearch/bench_means.py:collect_bench_means_from_inspect_ai` 실구현
2. `main()` collector 호출 + `compute_fitness(bench_means=…)` + `_baseline_provenance["bench_means"]`
3. `_should_promote` internal compute_fitness 에 bench 전달 (Goodhart bidirectional gate 활성)
4. `format_results_jsonl_row` 에 `bench_means` / `ux_means` / `admire_means` 컬럼 emit
5. OL-C1 `eval_response_recorded` emit 의 `bench_means_aggregate` 를 baseline → current 로 교체
6. Integration test (stub collector → assert axes.bench_means persists + results.jsonl carries + gate fires)

### 7-bench port 매핑 (F1.b 확정)

| Bench | inspect_ai port | 의존성 | Docker 필요 | A1 graceful-skip |
|-------|----------------|--------|------------|------------------|
| swe_bench_pro_pass | `inspect_harbor.swebenchpro` | `inspect-harbor==0.4.5` | ✅ (scaleapi 이미지) | Docker 부재 → skip |
| **livecodebench_pro_accuracy** | `inspect_evals.livecodebench_pro` | `inspect-evals==0.13.0` | ❌ | nominal |
| tau2_bench_success | `inspect_evals.tau2_telecom` | 동상 | ❌ | nominal |
| gpqa_diamond | `inspect_evals.gpqa_diamond` | 동상 | ❌ | nominal |
| hle_accuracy | `inspect_evals.hle` | 동상 | ⚠️ vision 모델 필요 가능 | vision 미사용 시 skip |
| osworld_success | `inspect_evals.osworld` | 동상 | ✅ (VM sandbox) | Docker 부재 → skip |
| mle_bench_medal | `inspect_evals.mle_bench` | 동상 + Kaggle dataset | ✅ (Docker exec) | Docker 부재 → skip |

### C2 변경 파일

- `pyproject.toml`
  - `[audit]` extra 에 `inspect-evals==0.13.0` + `inspect-harbor==0.4.5` 추가
- `autoresearch/bench_means.py`
  - `collect_bench_means_from_inspect_ai` 실구현 (7-bench dispatch + Docker pre-flight + graceful-skip)
  - 신규 `BENCH_PROVENANCE_SCHEMA` (rubric_version / sample_count / stderr / modality 슬롯)
  - 신규 `compute_missing_benches(bench_means)` (Goodhart suppression surface)
- `autoresearch/prepare.py`
  - `_check_docker_available()` + `_check_inspect_evals_installed()` pre-flight (binary + import 가용성)
- `autoresearch/train.py`
  - `main()` — collector 호출 + 4-axis fitness 분기 활성 + `_baseline_provenance` 에 bench 추가
  - `_should_promote` — bench 전달
  - `_write_baseline` — bench provenance (stderr / sample_count / rubric_version) 영속화 슬롯 추가
  - `_load_baseline` — v2 schema reader 가 bench provenance 도 읽도록 확장
  - `format_results_jsonl_row` — 4-axis 컬럼 emit (bench/ux/admire + per-axis aggregate)
  - OL-C1 emit — `bench_means_aggregate` 를 current bench 로 교체
- `core/audit/dim_extractor.py` (있다면) — bench 결과 측 stderr 자동 산출 (inspect_ai sample-level pass/fail 에서)

### C2 테스트

- `tests/test_s6_bench_means_production.py` (신규) — collector 실제 호출 (stub adapter), baseline persist, gate fire, results.jsonl emit, missing_benches Goodhart surface 모두 1-test 1-invariant
- `tests/test_docker_preflight_graceful_skip.py` (신규) — Docker 부재 시 4 bench skip + nominal 3 bench 작동 + `missing_benches` 표시
- `tests/test_s6_cross_validation_gate.py` (신규) — alignment_only_fooling + capability_at_alignment_cost 두 conflict 시나리오에서 fitness 0.0 + reason payload 보존
- `tests/test_provenance_schema.py` (신규) — bench_stderr / bench_sample_count / bench_rubric_version baseline 영속화 invariant

---

## C3 — P3 modality weight split

### Background (B1 GAP findings)

- `_ANALYTICS_MODALITY` (`core/audit/dim_extractor.py:58-61`) 가 2 dim 만 분석 modality (`verbose_padding`, `redundant_tool_invocation`) — 둘 다 auxiliary tier
- `DIM_WEIGHTS` (`autoresearch/train.py:293-313`) 가 modality-blind — judge_llm 의 1/3 노이즈 특성인 분석 dim 도 동일 weight 0.0333
- `compute_fitness` 가 `measurement_modality` 파라미터 미수용
- N=1 widening (`N1_FITNESS_MARGIN_FLOOR=0.20`) 가 deterministic stderr=0.0 (분석 dim) 과 under-sampled stderr=0.0 (judge_llm N=1) 을 conflate

### C3 변경 파일

- `autoresearch/train.py`
  - `DIM_WEIGHTS` 를 `_JUDGE_LLM_WEIGHTS` + `_ANALYTICS_WEIGHTS` 두 dict 로 split (analytics dim 가중치를 judge_llm 의 0.3-0.5x 로 calibrate — 결정 시 frontier 노이즈 추정 인용)
  - `compute_fitness(..., measurement_modality: dict[str, str] | None = None)` 신호 받음
  - `_should_promote` 의 N=1 widening 가드 — `critical_dim 의 modality == "judge_llm"` 일 때만 widening (분석 dim 의 deterministic stderr=0.0 skip)
- `core/audit/dim_extractor.py`
  - modality map 자체는 변동 없음 (이미 PR-1 으로 emit)

### C3 테스트

- `tests/test_modality_weight_split.py` (신규)
  - judge_llm 만 dim 의 fitness vs analytics dim 의 fitness 가중 비율 검증
  - critical dim 의 N=1 widening 이 judge_llm 일 때만 fire
  - 분석 dim 이 stderr=0.0 일 때 widening 미발화 (deterministic skip)
  - 기존 fitness 테스트 무회귀

---

## C4 — E1 mutation cost ledger

### Background (B1 GAP findings)

- `autoresearch/state/mutations.jsonl` git-tracked 존재, cost 컬럼 0건 (`core/self_improving_loop/runner.py:append_audit_log` line 720-732)
- mutator LLM 호출의 `adapter.agentic_call()` response metadata 폐기 (`runner.py:543`)
- `audit_seconds` 는 캡처되나 token 분해 없음
- `attribution.py` 의 attribution row 가 별도 kind 로 append, baseline_after 페어링 미실행

### C4 변경 파일

- `core/self_improving_loop/runner.py`
  - `_default_llm_call` 응답에서 token usage 캡처 (`tokens_in / tokens_out / total_tokens`)
  - `append_audit_log` (그리고 `to_audit_row`) 의 row schema 확장:
    - `cost_judge_tokens: int`
    - `cost_target_tokens: int` (run_audit 의 audit subprocess 의 LLM 합산 — sessions.jsonl 의 usd_spent 와 일관)
    - `cost_seconds: float` (audit_seconds + mutator_seconds)
    - `fitness_delta: float | None` (attribution 후 baseline_after pair 로 계산, attribution row 가 보강)
  - apply_proposal 후 next audit 의 baseline_after 로딩 → attribution 트리거
- `core/self_improving_loop/attribution.py`
  - `compute_attribution` 의 row 에 fitness_delta 추가

### C4 테스트

- `tests/test_mutation_cost_ledger.py` (신규)
  - mutator LLM 호출 mock → usage 캡처 검증
  - apply_proposal → next audit → attribution row 의 fitness_delta = baseline_after.fitness - baseline_before.fitness invariant
  - 기존 mutations.jsonl reader (v1 schema, cost 컬럼 부재) backward-compat — graceful default

---

## C5 — D4 X2 telemetry

### Background (B1 GAP findings)

- `HookEvent.PROMPT_ASSEMBLED` (`core/hooks/system.py:69`) 정의됐으나 zero call site
- `_sync_model_and_rebuild_prompt` (`core/agent/loop/agent_loop.py:562`) 가 매 round 마다 fire 하지만 관측 marker 0
- stale-ack purge (`core/agent/loop/_model_switching.py:175-213`) telemetry 0

### C5 변경 파일

- `core/agent/loop/agent_loop.py:_sync_model_and_rebuild_prompt`
  - `HookEvent.PROMPT_ASSEMBLED.trigger_async` 호출, payload: `{old_model, new_model, reason: "model_drift" | "manual_switch", prompt_hash, x2_injected: True}`
- `core/agent/loop/_model_switching.py:_inject_model_switch_breadcrumb`
  - purged_count payload 동봉 (`{purged_count: int, old_model, new_model}`)

### C5 테스트

- `tests/test_prompt_assembled_telemetry.py` (신규)
  - hook handler register → `_sync_model_and_rebuild_prompt` 호출 → payload schema 검증 (4 keys all present)
  - stale-ack purge → `purged_count` payload 가 실제 제거 message 수와 일치
  - PROMPT_ASSEMBLED 가 model 변경 없는 rebuild 에서도 fire (현재 MODEL_SWITCHED 만 fire 하던 gap 보완)

---

## C6 — D1 provider B/C closure

### Background (B1 GAP findings)

- `PetriRoleConfig.source` 스키마 존재 (`core/config/self_improving_loop.py:147`) 하나 dispatcher (`autoresearch/train.py:_build_audit_command:580-624`) per-role 미소비 — 글로벌 `cfg.source` 만 본다
- default `"auto"` 가 manifest resolver 의 PAYG fallback 까지 도달 가능 (operator decision 위반)
- 4-backend matrix (`api_key / auto / claude-cli / openai-codex`) 중 2개만 테스트
- pre-flight 부재 — subprocess 가 늦게 비actionable error 던짐

### C6 변경 파일

- `core/config/self_improving_loop.py`
  - `PetriRoleConfig.source` default `"auto" → "claude-cli"` (subscription-first 명시)
  - `Source = Literal["claude-cli", "openai-codex", "auto"]` (Pydantic 가 `api_key` 명시 시 ValidationError surface — PR-C-P1 패턴 재사용)
  - `AutoresearchConfig.source` 도 동일 변경
  - 새 docstring: PAYG 제외 정책 + operator action (config.toml 에 `api_key` 명시 시 reject)
- `autoresearch/train.py:_build_audit_command`
  - per-role source argv 추가 (`--target-source claude-cli --judge-source openai-codex` 등 또는 env var)
  - 글로벌 `cfg.source` 와 per-role override 의 dispatch 우선순위 명시 (per-role > global > config)
- `autoresearch/prepare.py`
  - 신규 `_check_source_binary(source)` + `_check_oauth_token_freshness(source)` pre-flight
- `core/self_improving_loop/cli_subprocess.py`
  - pre-flight 헬퍼 export (`is_claude_cli_available()` / `is_codex_cli_available()`)

### C6 테스트

- `tests/test_provider_dispatch.py` (신규)
  - 4-backend matrix: api_key (reject) / auto / claude-cli / openai-codex
  - per-role override: target=claude-cli, judge=openai-codex, auditor=auto → argv 가 3 source 모두 다르게
  - pre-flight: binary 부재 → actionable error
  - PAYG 명시 (`source = "api_key"`) → Pydantic ValidationError + operator-friendly message (C-P1 패턴)

---

## 검증 게이트 (per commit + final)

- **각 commit**: `ruff check / ruff format --check / mypy / lint-imports / targeted pytest`
- **최종 (push 전)**:
  - `pytest tests/ -m "not live"` — 전체 회귀
  - Codex MCP 검토 6 라운드 (테마별, anti-deception 5 체크: writer/reader 페어 / hook 등록 / CHANGELOG parity / dead code / 테스트 deletion)
  - CHANGELOG/PR-body grep verification — 모든 verb/adjective 가 grep-provable
  - `git check-ignore` 모든 새 path (mutations.jsonl 신 컬럼 / Docker pre-flight log path 등)

## CHANGELOG 전략

5 테마 (실제로는 6 with ADR) → 6 `### Added` / `### Changed` 블록, 각 1-2 단락. 각 verb/adjective 는 grep-provable. CHANGELOG/PR-body parity 의 Codex MCP 자동 catch 패턴 적용.

## Rollback 시나리오

- commit 단위 `git revert` 가능 — 6 독립 commits, semantic isolation 유지
- mutations.jsonl 스키마 확장: backward-compat (새 컬럼 optional)
- baseline.json v2 axes.bench_means: 이미 nullable
- PetriRoleConfig default 변경: explicit `source` 설정 사용자 무영향, 미설정 사용자만 새 default 적용
- ADR amendment: doc 만 revert 시 코드와 doc 재불일치 → 코드도 동일 revert 권장

## Reference

- F1.b 결정 근거: B1 grounding agent report (LiveCodeBench upstream port 부재, LCB-Pro 가 contamination defense 계승)
- A1 graceful-skip 결정: cron / serve 환경 Docker 가용성 비대칭 (operator 환경별 nominal path 보존)
- B1 단일 PR 결정: operator directive (2026-05-23)
- 4-axis 명세 origin: `autoresearch/train.py:344-350` 의 `FITNESS_*_4AX` 상수 (ADR 외부 결정, 이 PR 의 C1 이 ADR 과 sync)
- PR-MIC #1515 (C-P1 seed_limit ge=5): 동일한 Pydantic ValidationError surface 패턴 — C6 의 `api_key` reject 가 재사용
