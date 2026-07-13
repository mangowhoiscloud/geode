# Fallback chain/layer 전역 제거 + quota-exhausted UI 전환

> **Date**: 2026-05-21 · **Author**: Claude Opus 4.7 (1M) · **Driving decisions** (사용자):
>
> 1. 2026-05-20: *"silent fallback은 오히려 지워야하는 사안이야. 현재 사용하는 provider/요금제로 시스템 운영이 되지 않으면 사용자에게 명시적으로 알리고 시스템을 중단하는게 맞아."*
> 2. 2026-05-21: *"FALLBACK 체인과 레이어를 제거해. Self-improving Loop + Agentic Loop(GEODE) 스코프에 전역으로 지켜야할 사안이야."*
>
> 결정 (2) 가 결정 (1) 의 scope 를 확장. 빈 list shim 만 두는 게 아니라 chain/layer 코드 *자체* 를 전역 제거한다.

## Why

`docs/research/model-ux-governance.md` (2026-04-27 자) 의 §"Addendum — Fallback chain redesign (fail-fast on quota)" 가 *Phase F1 (cross-provider 제거) ~ F4 (quota_exhausted event)* 까지 결정해 두었으나, 실제 GEODE 코드에 잔존하는 fallback 표면이 **3 layer** 에 걸쳐 남아있고, 핵심 권장 (Phase F3 "same-provider chain 단순화") 도 옵션 (A/B/C) 중 미선정 상태였다. 사용자가 2026-05-20 에 **옵션 (C) 완전 제거** 를 명시적으로 확정.

따라서 본 plan 의 ground:

1. **silent fallback 자체 제거** — provider-internal chain 도 포함 (옵션 C)
2. **quota 소진 시 system stop** — 명시적 UI 메시지 + 다음 LLM 호출 차단
3. **관련 문서 정정** — fallback 권장이 *유지* 되는 부분은 모두 제거 또는 fail-fast 로 갱신

## Surface — silent fallback 잔존 위치

### A. Empty-dict shim (이미 dead, 즉시 제거 가능)

| File | Line | 상태 |
|------|------|------|
| `core/llm/adapters.py` | `209` `CROSS_PROVIDER_FALLBACK: dict[str, list[tuple[str, str]]] = {"anthropic": [], "openai": [], "glm": [], "openai-codex": []}` | Empty dict back-compat shim. 호출 안 됨. **삭제** |
| `core/llm/router/__init__.py` | `51` `from core.llm.adapters import CROSS_PROVIDER_FALLBACK as CROSS_PROVIDER_FALLBACK` | 위 shim 의 re-export. 외부 import 없음 확인 후 **삭제** |

### B. Same-provider model chain (실제 동작 중 — 제거 대상)

| File | Line | 동작 |
|------|------|------|
| `core/config.py` | `ANTHROPIC_FALLBACK_CHAIN`, `OPENAI_FALLBACK_CHAIN`, `GLM_FALLBACK_CHAIN`, `CODEX_FALLBACK_CHAIN` | 상수 정의. 각 provider 의 primary → secondary → tertiary chain |
| `core/llm/provider_dispatch.py` | `13-15`, `112-142`, `173-209` | `_get_fallback_chain(provider)` + 라우팅 layer 에서 `models_to_try = [model] + fallback` |
| `core/llm/fallback.py` | `195-236`, `405-423` | `retry_with_backoff_generic(fallback_models=...)` — primary 실패 시 chain 의 다음 모델 시도 |
| `core/llm/providers/anthropic.py` | `318` `FALLBACK_MODELS = ANTHROPIC_FALLBACK_CHAIN`, `538`, `578`, `689-690` `fallback_chain` property, `737` `failover_models = [model] + ...` | 호출 site 4 곳 |
| `core/llm/providers/openai.py` | `47` `OPENAI_FALLBACK_MODELS = OPENAI_FALLBACK_CHAIN`, `417` | 호출 site 1 곳 |
| `core/llm/providers/codex.py` | `30` `CODEX_FALLBACK_MODELS = CODEX_FALLBACK_CHAIN`, `211-212`, `303` | 호출 site 3 곳 |
| `core/llm/providers/glm.py` | `26` `GLM_FALLBACK_MODELS = GLM_FALLBACK_CHAIN`, `259-260`, `300` | 호출 site 3 곳 |

### C. Loop-level escalation (이미 제거 / 잔재 확인)

| File | Line | 상태 |
|------|------|------|
| `core/agent/loop/*` | `_try_model_escalation`, `_try_cross_provider_escalation` | docs 가 `_try_cross_provider_escalation` 는 "제거 완료" 로 명시했지만 `_try_model_escalation` 잔재 가능. **별도 grep 으로 확인 + 잔재 시 제거** |
| `core/config/_settings.py` | `llm_cross_provider_failover`, `llm_cross_provider_order` | 이미 제거 (`#TBD` per docs) — **재확인** |

### D. Tests with silent-fallback expectations

`tests/` 에 fallback chain 동작 의존 테스트가 있을 가능성. grep 후 삭제 또는 fail-fast 검증으로 재작성.

## Target outcome

### Code state — invariants

1. **단일 모델 시도**: `retry_with_backoff_generic` 는 primary 모델 한 번 (필요 시 transient-error 재시도) 만. `fallback_models` 인자 자체를 제거하거나 무시.
2. **Provider-level chain 빈 list**: `ANTHROPIC_FALLBACK_CHAIN = []` 등 — 상수는 유지 (외부 import 호환) but 빈 list. 가능하면 다음 PR 에서 상수 완전 삭제.
3. **`CROSS_PROVIDER_FALLBACK` 완전 삭제**: empty-dict shim 제거.
4. **`fallback_chain` property 빈 list**: provider adapters 의 property 가 `return []`. 호출 site 의 `failover_models = [model] + [m for m in self.fallback_chain if m != model]` 는 `failover_models = [model]` 등가.
5. **BillingError → system stop**: `is_billing_fatal` 가 발생하면 즉시 `BillingError` raise. 재시도 X. 다음 호출까지 차단 (별도 sentinel 또는 IPC event).

### UI state — quota-exhausted 문구

`BillingError.user_message()` 가 이미 v0.53.0 에서 multi-line plan-aware 메시지를 렌더링 — *이미 구현됨* (`core/llm/errors.py:155-186`). 본 plan 에서는 **렌더링 경로 검증** + **agentic_ui 의 panel 강화**:

```
⚠ <plan_display_name 또는 provider> quota exhausted
  <message>
  Resets in: <ttl>

Options:
  1. Wait for quota reset
  2. Switch auth: /login set-key <provider> <api-key>
  3. Switch provider: /model <other-model>
  [4. Upgrade plan: <upgrade_url>]
```

### Doc state

1. `docs/research/model-ux-governance.md` 의 §"Addendum — Fallback chain redesign":
   - Phase F1: "Done — empty-dict shim 도 제거됨" 으로 갱신
   - Phase F3: 옵션 (C) 완전 제거 채택. (A)/(B) 옵션 삭제
   - Phase F4: quota_exhausted IPC event 가 actually 구현됐는지 확인 + 미구현이면 본 plan 의 후속 PR 로 분리
2. `docs/architecture/self-improving-loop-resume-decision.md` — fallback 관련 언급 검토
3. `https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/main/sil/audit-reports/2026-05-12-llm-provider-matrix-gaps.md` — gap 권장 사항 중 fallback 관련 항목 정정
4. `CHANGELOG.md` 의 `[Unreleased] Removed` 섹션에 본 변경 entry

## 사용자 결정 변경 (2026-05-21 후속 대화)

본 plan 초안은 *옵션 (C) 완전 제거* 로 시작했으나, 사용자가 *튜닝 여지 보존* 을 명시 (verbatim): *"model fallback을 남겨두는 이유에 대해 파악하자. 사용자가 명시적으로 튜닝할 여지를 남겨두는거면 찬성이야."* — 따라서 *코드 path 는 유지* + *shipped default 는 no-chain* 의 **opt-in knob** 으로 최종 확정.

## 적용 범위 명확화 — "fallback" 의 두 가지 의미

코드에는 두 종류의 "fallback" 이 있다:

| 종류 | 의미 | 본 plan 의 대상? |
|------|------|------------------|
| (A) **LLM model chain fallback** | primary 모델 실패 시 다음 모델 자동 시도 (`*_FALLBACK_CHAIN`, `failover_models`, `fallback_chain` property) | **YES — knob 으로 전환** (default empty) |
| (B) Prompt fallback | 설정 파일 (e.g. `autoresearch/program.md`) 누락 시 inline 기본 prompt 사용 (`core/self_improving_loop/runner.py:200`) | **NO** — graceful degradation, 사용자 결정의 범주 밖 |

## 최종 변경 surface — opt-in knob

### Config layer (shipped default 만 변경, 코드 path 유지)
1. `core/config/routing.toml`: `[model.fallbacks]` 의 4개 list 를 `[]` 로 변경 + 섹션 헤더에 knob 설명 주석 추가
2. `core/config/routing_manifest.py:_consistency`: "fallback chain is empty" → `raise` 였던 검증을 *완화* (빈 list = opt-out 로 허용). drift 검증은 *non-empty 일 때만* 적용

### Cross-provider shim 제거 (이건 잔재, knob 의 범주 밖)
3. `core/llm/adapters.py`: `CROSS_PROVIDER_FALLBACK` empty-dict shim 완전 삭제
4. `core/llm/router/__init__.py`: 위 shim 의 re-export 삭제

### Tests — invariant 갱신
5. `tests/test_failover.py`: `FALLBACK_MODELS` 의 default empty 검증으로 갱신 + `test_no_silent_fallback_to_other_models` 추가 (default knob 동작 검증)
6. `tests/test_model_failover.py`: `TestFallbackChainConfig` 가 *type-safe list + default empty* 를 검증하도록 갱신
7. `tests/test_routing_manifest.py`: `test_default_manifest_fallback_chains_empty` 로 갱신 + `test_empty_fallback_is_accepted` (empty = opt-out 가 ValueError 아님)
8. `tests/test_codex_provider.py`: `CODEX_FALLBACK_CHAIN` 의 default empty 검증 + `CROSS_PROVIDER_FALLBACK` reference 제거
9. `tests/test_quota_fail_fast.py`: Contract 1 의 "empty for every provider" → "shim removed" 로 갱신
10. `tests/test_provider_label_consistency.py`: `CROSS_PROVIDER_FALLBACK` reference 제거

### Docs + CHANGELOG
11. `docs/research/model-ux-governance.md`: Phase F1 (cross-provider Done) / F3 (옵션 C → knob 으로 조정) / F4 (Done) 갱신
12. `CHANGELOG.md`: `[Unreleased] Removed` entry 작성 — knob 의도 + 변경 surface 명시

## 변경하지 않은 surface (knob 유지)

다음은 *코드 path* 가 그대로 유지됨 — user-tunable knob 의 동작 path:

- `core/config/__init__.py`: `*_FALLBACK_CHAIN: list[str] = list(_routing.fallbacks.<provider>)` *유지*
- `core/config/routing_manifest.py:ModelFallbacks` class + `RoutingManifest.fallbacks` field + `get_fallback_chain` accessor *유지*
- `core/llm/fallback.py:retry_with_backoff_generic` 의 `fallback_models: list[str]` 매개변수 *유지*
- `core/llm/provider_dispatch.py:_get_fallback_chain` + `_PROVIDER_DISPATCH` 의 `fallback_chain` key *유지*
- `core/llm/adapters.py:AgenticLLMPort.fallback_chain` Protocol method *유지*
- 4 provider adapters 의 `fallback_chain` property + `failover_models = [model] + [...]` *유지*
- `core/llm/router/calls/_failover.py:call_with_failover` 시그니처 + 이름 *유지*
- `core/agent/system_prompt.py` fallback chain hint block *유지* (user-tuned chain 이 있으면 system prompt 에 노출됨)
- `core/agent/loop/agent_loop.py:_fallback_chain_suggestions` + `core/agent/loop/_model_switching.py:fallback_chain_suggestions` *유지*

→ user 가 `~/.geode/routing.toml` 에 `[model.fallbacks] anthropic = ["claude-opus-4-7", "claude-sonnet-4-6"]` 를 적으면 *그 chain 대로 동작*. shipped default 만 비어있어서 *기본 사용자* 는 chain 없이 fail-fast.

## Anti-deception checklist (CLAUDE.md DONT 표 적용)

- [ ] `grep -rn "CROSS_PROVIDER_FALLBACK\|_try_cross_provider\|_try_model_escalation" core/` returns 0 hits (또는 explicit removal marker comment)
- [ ] `grep -rn "fallback_chain\|fallback_models" core/llm/` 에 PR-α2 후 호출 site 0
- [ ] CHANGELOG 의 "removed" claim 이 grep-provable
- [ ] `docs/research/model-ux-governance.md` 의 Phase F 권장 사항 모두 *현재 코드 상태와 일치*
- [ ] silent fallback 관련 권장이 *유지* 되는 문서 위치 0

## Karpathy patterns 참조

- **P1 Constraint-based design**: silent fallback 제거 = "what cannot be done" 한 줄 추가 (provider 변경 silently happen 금지)
- **P10 Simplicity Selection**: 코드 deletion 우선 (cost surprise 제거)
- **CLAUDE.md `DONT — Real Incidents` 표 row 추가 예정**: "silent fallback 가 fail-fast 보다 안전해 보이지만 실제 incident 2건 (v0.52.3 GLM, v0.52.5 provider-switch session) 의 root cause" — 이 plan 의 후속 PR 가 row 추가.

## Reference

- `docs/research/model-ux-governance.md` (2026-04-27) — original Phase F1-F4 결정
- v0.52.3 incident transcript (CHANGELOG) — "GLM 잔액 부족 → 5×4 retry storm ~40s"
- v0.52.5 incident — escalation 후 모델 정체성 혼동 (gpt-5.4-mini → gpt-5.5 silent switch)
- `feedback_codex_mcp_verification` — fail-fast 의 정신적 자매 원칙
