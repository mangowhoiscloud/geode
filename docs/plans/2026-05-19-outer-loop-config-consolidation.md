# Plan — Outer-Loop Config Consolidation + Subscription Guard + FE Warning UX

**Date**: 2026-05-19
**Status**: Approved (decisions confirmed 2026-05-19)
**Owner**: mangowhoiscloud
**Driving directive**: 2026-05-19 user directive — subscription 소진 시 PAYG 자동 폴백 차단 + 설정 SoT 단일화 + GEODE FE 에 경고 UX 추가
**Predecessor**: `docs/plans/2026-05-19-outer-loop-wiring-sprint.md` (Phase A + B 완료; Phase C smoke 진입 전 본 plan 의 5 PR 완료 필요)
**Reference report**: 2026-05-19 conversation, P1/P2/P3 syntheses (Hermes auxiliary + Codex forced_login_method + prompt_toolkit bottom_toolbar)

## Goal

세 문제를 동시에 해결:

1. **설정 SoT 단일화** — 현재 8개 surface 에 분산된 outer-loop 설정을 `~/.geode/config.toml` 의 `[outer_loop.*]` section 으로 통합. 사용자가 한 파일만 보면 어디서 무엇을 바꿀지 안다.
2. **Subscription 소진 시 hard abort** — Codex CLI 의 `forced_login_method` 패턴 채택. 기본 동작은 stricter (subscription 소진 시 abort + 안내), PAYG fallback 은 explicit opt-in.
3. **FE 경고 UX** — prompt_toolkit `bottom_toolbar` 3-tier banner (green <50% / yellow 50-90% / red >90% or abort) + abort 시 full-screen dialog. 운영 주체인 사용자가 quota 상태를 항상 본다.

## Settled decisions

| # | Item | Decision | Rationale / source |
|---|------|----------|--------------------|
| 1 | Config 파일 위치 | `~/.geode/config.toml` 의 `[outer_loop.*]` section | 단일 SoT 원칙 — 모든 GEODE 설정 한 파일 |
| 2 | Subscription 소진 시 기본 동작 | Stricter (abort + 안내), `fallback_to_payg = false` default | 사용자 directive + frontier 모든 사례가 silent fallback 을 footgun 으로 검증 |
| 3 | Fallback opt-in 방법 | `[outer_loop] fallback_to_payg = true` (전역) 또는 per-component `[outer_loop.<comp>] fallback_to_payg = true` | Codex `forced_login_method` 의 직접 변형 |
| 4 | FE UX | `bottom_toolbar` 3-tier banner + abort dialog | prompt_toolkit issue #277 패턴, Hermes TUI 유사 |
| 5 | Quota signal 출처 | agent 의 last response usage field (provider polling 금지) | rate-limit / cost overhead 회피 |
| 6 | Migration 방식 | autoresearch/train.py module 상수 → config 로 lazy fallback; 기존 `~/.geode/petri.toml` 의 `[petri.<role>]` 은 `[outer_loop.petri.<role>]` 로 1-shot 이전 (backwards-compat shim 없음, CANNOT 규칙) | 깨끗한 hard cut |
| 7 | Config schema 검증 | pydantic v2 model + JSON schema 자동 export → 사용자가 `geode config doctor` 로 검증 | type-safe loader |
| 8 | banner refresh 주기 | 5초 background thread + `app.invalidate()` | issue #277 documented pattern |

## Config schema 초안 (`~/.geode/config.toml`)

```toml
# 기존 GEODE config (변경 없음)
[settings]
# ...

[anthropic]
# ...

# ===== 신규 [outer_loop.*] section =====

[outer_loop]
# subscription 소진 시 PAYG 자동 폴백 차단. true 로 바꿔야 fallback 허용.
fallback_to_payg = false
# 0.0-1.0. 이 비율 이상 사용 시 banner yellow → red 전환.
warn_threshold = 0.5
abort_threshold = 0.9

[outer_loop.autoresearch]
# 기존 autoresearch/train.py module 상수의 SoT 이전
budget_minutes = 5
target_model   = "geode/gpt-5.5"
judge_model    = "claude-code/opus"
use_oauth      = true
seed_limit     = 10
seed_select    = "plugins/petri_audit/seeds"
dim_set        = "5axes"
max_turns      = 10
# 옵션: per-component fallback override
# fallback_to_payg = true

[outer_loop.petri.auditor]
model  = "claude-sonnet-4-6"
source = "claude-cli"

[outer_loop.petri.target]
model  = "geode/gpt-5.5"
source = "openai-codex"

[outer_loop.petri.judge]
model  = "claude-opus-4-7"
source = "claude-cli"

[outer_loop.seed_pipeline]
candidates_default = 15
default_gen_tag    = "gen1"
# 7 role × source binding 도 명시 가능
# [outer_loop.seed_pipeline.roles.generator]
# model = "gpt-5.5"
# source = "openai-codex"
```

남는 surface (책임 분리 — 명시적):
- `~/.geode/auth.toml` — Claude OAuth 토큰 (Claude Code 가 자동 관리, 사람이 만지지 않음)
- `~/.codex/auth.json` — Codex OAuth (codex CLI 자동 관리)
- `env: AUTORESEARCH_{SESSION_ID, GEN_TAG, DESCRIPTION, VERDICT, SEED_SELECT}` — **ephemeral per-run override**. 배치 스크립트 / CI 용. config.toml 값 override 가능

폐기:
- `~/.geode/petri.toml` (`GEODE_PETRI_TOML`) — `[outer_loop.petri.<role>]` 로 흡수
- `autoresearch/train.py` 의 module 상수 — config loader 의 default fallback 으로만 유지 (lazy)
- `plugins/seed_pipeline/auth_coverage.py` 의 `TEST_SETUP_PROFILE` — `[outer_loop.test_profile]` section 또는 test fixture 로 이전

## PR ledger (5 PR + 1 backfill)

```
Phase α — config schema (foundation, 다른 PR 의 의존)
  PR-α1 — config schema + loader + pydantic model       (~250 LOC)
                                  ↓
Phase β — subscription guard (urgent: 돈 새는 위험 직접 차단)
  PR-β1 — petri source allowed 단일화 + abort path     (~150 LOC)
                                  ↓
Phase γ — FE warning UX
  PR-γ1 — bottom_toolbar 3-tier banner + abort dialog   (~200 LOC)
                                  ↓
Phase δ — caller migration (autoresearch/train.py + seed-pipeline)
  PR-δ1 — autoresearch loader integration                (~150 LOC)
  PR-δ2 — seed-pipeline + petri user_overrides 흡수    (~200 LOC)
                                  ↓
Phase ε — backfill (필요 시)
  PR-ε1 — 잔존 결손 / 2nd audit pass / docs sync       (~100 LOC)
                                  ↓
Phase ζ — checkpoint + resume on credential rollout
  (ADR: docs/architecture/outer-loop-resume-decision.md)
  PR-ζ1 — SessionCheckpoint schema 확장 (outer-loop 필드)  (~200 LOC)
  PR-ζ2 — seed-pipeline _load_state() + `audit-seeds resume`  (~300 LOC)
  PR-ζ3 — autoresearch _load_pending_audit() + --resume flag (~200 LOC)
  PR-ζ4 — idempotency-key + 로컬 response cache (~/.geode/outer-loop/<s>/idempotency.db)  (~350 LOC)
  PR-ζ5 — credential-rollover detection + journal event (~150 LOC)
  PR-ζ6 — docs + runbook                                       (~100 LOC)
                                  ↓
[Phase C of wiring sprint] — gen-0 baseline smoke (~$5)
```

| PR | Title | Defects / scope | LOC | Files (예상) | Blocking |
|---|---|---|---|---|---|
| **PR-α1** ✅ | feat(config): outer_loop schema + loader (pydantic) | 신규 | ~360 | `core/config/outer_loop.py` (NEW), `tests/test_outer_loop_config.py` (NEW, 16 tests) | — |
| **PR-β1** | feat(petri): subscription-only guard + abort path | 사용자 directive | ~150 | `plugins/petri_audit/petri.plugin.toml` (allowed 단일화), `plugins/petri_audit/credential_source.py` (fallback flag 점검), abort msg formatter, tests | PR-α1 |
| **PR-γ1** | feat(cli): 3-tier quota banner + abort dialog | UX | ~200 | `core/cli/quota_banner.py` (NEW), `core/cli/repl.py` integration, abort dialog template, tests | PR-β1 |
| **PR-δ1** | refactor(autoresearch): consume outer_loop config | migration | ~150 | `autoresearch/train.py` (module 상수 → config lazy load with default fallback), tests, program.md doc sync | PR-α1 |
| **PR-δ2** | refactor(seed-pipeline+petri): consume outer_loop config | migration | ~200 | `plugins/seed_pipeline/{cli.py, picker.py}`, `plugins/petri_audit/user_overrides.py` (deprecate `~/.geode/petri.toml`, redirect to outer_loop), migration helper, tests | PR-α1 + PR-δ1 |
| **PR-ε1** | docs + backfill | post-merge audit | ~100 | sync `program.md` / `README` / CLAUDE.md, sample config.toml fixture | Phase β+γ+δ |
| **PR-ζ1** | feat(checkpoint): SessionCheckpoint outer-loop schema 확장 | ADR settled | ~200 | `core/runtime_state/session_checkpoint.py` 확장 (active_sources / completed_units / next_unit / fallback_to_payg field), tests | PR-α1 + PR-β1 |
| **PR-ζ2** | feat(seed-pipeline): `_load_state` + `audit-seeds resume <run_id>` | ADR settled | ~300 | `plugins/seed_pipeline/orchestrator.py` (_load_state companion to _persist_state), `plugins/seed_pipeline/cli.py` (resume sub-app), idempotency-key check at phase boundary, tests | PR-ζ1 + PR-δ2 |
| **PR-ζ3** | feat(autoresearch): `_load_pending_audit` + `--resume <session>` | ADR settled | ~200 | `autoresearch/train.py` (resume entry point + active-source check), tests | PR-ζ1 + PR-δ1 |
| **PR-ζ4** | feat(checkpoint): idempotency-key + local response cache | ADR settled | ~350 | `core/runtime_state/idempotency.py` (NEW, SQLite-backed cache at `~/.geode/outer-loop/<s>/idempotency.db`), LLM call wrapper checks cache pre-call, writes post-call, tests | PR-ζ1 |
| **PR-ζ5** | feat(observability): credential-rollover detection + journal event | ADR settled | ~150 | resume path comparison: checkpoint.active_sources vs current resolved sources → emit `credential_rolled_over` event to journal (P1c), tests | PR-ζ1 + PR-γ1 |
| **PR-ζ6** | docs + runbook | wrap-up | ~100 | `docs/audits/2026-05-19-resume-rollout-runbook.md` (NEW, operator manual), CHANGELOG entries, plan doc finalisation | Phase ζ |

**Total estimate**: ~2,350 LOC (Phase α-ε ~1,050 + Phase ζ ~1,300) + 1 ADR + 1 schema doc + 1 runbook + 1 sample fixture.
**Sprint estimate**: 4-5 sprint (per-PR Codex MCP audit 포함).

## Phase α (PR-α1) — config schema 상세

신규 모듈 `core/config/outer_loop.py`:

```python
"""Outer-loop config — single SoT loader.

Reads ``~/.geode/config.toml`` [outer_loop.*] sections into a typed
pydantic v2 model. The loader is the SoT consumed by autoresearch,
seed-pipeline, petri_audit, and geode_main wherever outer-loop
runtime decisions are made.
"""

from typing import Literal
from pydantic import BaseModel, Field

Source = Literal["claude-cli", "openai-codex", "api_key", "auto"]

class OuterLoopBindings(BaseModel):
    model_config = {"extra": "forbid"}  # typo guard
    model: str
    source: Source
    fallback_to_payg: bool | None = None  # None → inherit global

class AutoresearchConfig(BaseModel):
    model_config = {"extra": "forbid"}
    budget_minutes: int = 5
    target_model: str = "geode/gpt-5.5"
    judge_model: str = "claude-code/opus"
    use_oauth: bool = True
    seed_limit: int = 10
    seed_select: str = "plugins/petri_audit/seeds"
    dim_set: str = "5axes"
    max_turns: int = 10
    fallback_to_payg: bool | None = None

class OuterLoopConfig(BaseModel):
    model_config = {"extra": "forbid"}
    fallback_to_payg: bool = False
    warn_threshold: float = Field(0.5, ge=0.0, le=1.0)
    abort_threshold: float = Field(0.9, ge=0.0, le=1.0)
    autoresearch: AutoresearchConfig = AutoresearchConfig()
    petri: dict[str, OuterLoopBindings] = {}  # role → bindings
    seed_pipeline: dict[str, ...] = {}

def load_outer_loop_config(path: Path | None = None) -> OuterLoopConfig:
    """Load + validate ``~/.geode/config.toml`` [outer_loop.*] section."""
    ...
```

Precedence (Codex / OpenAI Agents 패턴):
1. env var override (e.g. `AUTORESEARCH_TARGET_MODEL`)
2. `~/.geode/config.toml` `[outer_loop.*]`
3. autoresearch/train.py module 상수 (deprecated default)
4. pydantic model default

## Phase β (PR-β1) — subscription guard 상세

변경:
1. `plugins/petri_audit/petri.plugin.toml`:
   ```toml
   [petri.source.anthropic]
   default = "claude-cli"   # was "auto"
   allowed = ["claude-cli"]  # was ["claude-cli", "api_key", "auto"]

   [petri.source.openai]
   default = "openai-codex"
   allowed = ["openai-codex"]
   ```
   PAYG fallback 은 `[outer_loop] fallback_to_payg = true` 일 때만 manifest override 로 `api_key` 추가.

2. `plugins/petri_audit/credential_source.py`:
   - `resolve_credential_source(fallback_to_payg: bool)` 신규 인자
   - `fallback_to_payg=False` (default): 첫 source 가 unavailable 또는 실패 시 즉시 `CredentialResolutionError` raise
   - error message: actionable 안내 (Stripe-style)
     ```
     Subscription quota exhausted for family=anthropic.

     Active source: claude-cli (Claude Max OAuth)
     Quota state: 50/50 used; resets 2026-05-19T22:00Z

     To continue NOW:
       1. Wait until the reset window.
       2. Or enable PAYG fallback (will incur cost):
          ~/.geode/config.toml:
            [outer_loop]
            fallback_to_payg = true
       3. Or pin a different model in [outer_loop.petri.judge].

     Doc: https://docs.geode.dev/outer-loop/subscription-mode
     ```

3. abort path 가 어디서든 발화하도록 `core/observability/session_journal.py` 에 `subscription_exhausted` event 추가. P1c 의 journal 이 capture.

## Phase γ (PR-γ1) — FE banner + abort dialog 상세

신규 `core/cli/quota_banner.py`:

```python
"""3-tier quota banner for the GEODE REPL bottom_toolbar.

States:
- green  (<warn_threshold): subscription healthy
- yellow (warn → abort): approaching limit
- red    (>= abort_threshold OR aborted): hard stop

Refresh: background thread, 5s cadence. Reads from the
SessionJournal's last usage event (no provider polling).
"""
```

prompt_toolkit `bottom_toolbar` callable + background thread + `app.invalidate()` (issue #277 pattern). REPL 통합 위치: `core/cli/repl.py`.

abort dialog: full-screen prompt_toolkit dialog with:
- title: "Subscription quota exhausted"
- body: actionable error message (위 §β1 의 안내문)
- button: "Open ~/.geode/config.toml" (호환 가능한 경우 $EDITOR launch) / "Dismiss"

## Phase δ (PR-δ1, PR-δ2) — caller migration

PR-δ1 (autoresearch/train.py):
- `BUDGET_MINUTES`, `TARGET_MODEL`, ... module 상수를 lazy property 로:
  ```python
  def get_config() -> AutoresearchConfig:
      try:
          return load_outer_loop_config().autoresearch
      except FileNotFoundError:
          return AutoresearchConfig()  # module-default fallback
  ```
- `_build_audit_command()` 가 config 통해 값 조회
- 기존 module 상수는 deprecation comment + 1 release 후 제거

PR-δ2 (seed-pipeline + petri user_overrides):
- `plugins/seed_pipeline/picker.py` 의 default bindings 가 `[outer_loop.seed_pipeline.role.<X>]` 로 lookup
- `plugins/petri_audit/user_overrides.py` 의 `~/.geode/petri.toml` reader → `[outer_loop.petri.<role>]` 로 redirect
- migration helper: `geode config migrate-petri-toml` 1회성 명령 (기존 petri.toml → config.toml 이전)
- 이전 후 `~/.geode/petri.toml` 은 deprecated warning + N+1 release 후 제거

## GAP 점검 / 대조 protocol

각 PR phase 진입 시:

1. **Pre-implementation GAP** (cycle skill Phase A): 본 plan 의 해당 PR 항목 + reference report 의 인용 패턴 검증. 이미 구현됐으면 skip.
2. **Post-implementation GAP** (cycle skill Phase E): 본 plan 의 scope close 됐는지 codex MCP audit.
3. **Phase 종료 시 plan 갱신**: 본 doc 의 PR ledger 행에 `✅ #<PR-number>` 추가.

기본적으로 `seed-pipeline-cycle` skill 의 Phase A-F 그대로 적용.

## Risk register

| Risk | Mitigation |
|---|---|
| pydantic v2 의 strict 모드가 기존 config.toml 의 미지 필드 reject | `extra="forbid"` 는 `[outer_loop.*]` section 에만 적용; 다른 section 의 미지 필드 무시 |
| `~/.geode/petri.toml` 사용자가 직접 수정한 상태 | migration helper 가 dry-run 으로 diff 보여준 후 confirm; 사용자가 yes 누를 때까지 변환 안 함 |
| FE banner 의 background thread 가 REPL exit 시 안 닫힘 | `atexit` + signal handler 로 thread join |
| Codex CLI 처럼 abort 가 이미 stream 중인 generation 을 중간에 끊으면 사용자 confusion | abort 는 NEXT turn 의 진입 직전 시점에만 발화; 진행 중인 turn 은 끝까지 완료 |
| 기존 autoresearch/train.py 의 module 상수 사용 사이트 누락 → behaviour drift | PR-δ1 의 codex MCP audit 에서 "all usages of TARGET_MODEL / JUDGE_MODEL / BUDGET_MINUTES" grep 검증 |
| Phase ζ resume 시 active_source 가 변경됐으나 idempotency-key 가 매칭되어 잘못된 cached response 재사용 | idempotency-key 가 `(run_id, unit_id, agent_role)` 만으로 구성 — source 가 바뀌어도 의미상 같은 unit. 단 critical 변경 (e.g. judge=opus → judge=sonnet) 은 caller 가 새 key 발급 책임 (config.toml hash 를 key 에 prefix) |
| Phase ζ 의 SQLite idempotency.db 가 disk full 로 write 실패 | atomic_write_io 패턴 채택, write 실패 시 in-memory only fallback + journal 에 `idempotency_disabled` event |
| co-scientist 원본/reference impl 모두 production-ready resume 미제공 → 우리가 first-class implementer | ADR 의 reference table 에 명시. LangGraph + Inspect_ai + Stripe 의 검증된 패턴 합성, novel design 아님 |

## Reference

- Frontier reference report: 2026-05-19 conversation P1/P2/P3 syntheses
- Phase ζ ADR: `docs/architecture/outer-loop-resume-decision.md`
- Predecessor: `docs/plans/2026-05-19-outer-loop-wiring-sprint.md`
- Memory: `feedback_local_quality_gates_full.md` (CI ratchet)
- 사용자 directive 2026-05-19:
  - "subscription 이 다 되면 종료하고 안내 문구만 출력해주는게 맞아"
  - "별도의 fallback 체인은 걸지마"
  - "운영 주체일 GEODE 의 FE 에도 경고문이 출력되도록 UI/UX 추가"
  - "설정은 SOT 로 단일화해서 묶고"
  - "outer loop 가 subscription 초과로 끊겨도 계정 롤아웃해서 이어갈 수 있게 체크포인트와 같은 replay-resume 조치"
  - "ADR 들어가기 전에 관련 레퍼런스 디깅 + 원본인 co-scientist 의 패키지 구현본 살피기"
- Codex CLI `forced_login_method`: https://developers.openai.com/codex/config-reference
- prompt_toolkit `bottom_toolbar` + refresh: https://github.com/prompt-toolkit/python-prompt-toolkit/issues/277
- Hermes auxiliary roles: https://hermes-agent.nousresearch.com/docs/user-guide/configuration
- gh auth status precedence: https://cli.github.com/manual/gh_auth_status
- LangGraph Checkpointer: https://reference.langchain.com/python/langgraph/checkpoints
- Inspect_ai eval-retry: https://inspect.aisi.org.uk/reference/inspect_eval-retry.html
- Stripe idempotency keys: https://docs.stripe.com/api/idempotent_requests
- co-scientist paper: https://arxiv.org/abs/2502.18864 (§4.5 + §5)
- AI-CoScientist reference impl: https://github.com/The-Swarm-Corporation/AI-CoScientist

## Post-completion exit

본 plan 의 6 PR 완료 시 — Phase C (gen-0 baseline smoke) 진입 가능. wiring sprint plan 의 Phase C 체크리스트 그대로 적용. cost ~$5, 5 분 소요. subscription quota 사용 (PAYG 0).
