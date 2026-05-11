# GEODE Prompt Audit — 2026-05-12 cleanup 보고

> Source: 2026-05-12 Petri × GEODE audit (`docs/audits/2026-05-12-petri-geode-audit.md`) 의 결함 사안 보강 + system prompt 의 12 항목 GAP audit 의 통합 cleanup.

## 1. 한 줄 요약

Petri audit 에서 발견한 세 가지 결함 (`broken_tool_use` GEODE 우수 X (다른 두 가지가 약점) — `long_running_loop` budget self-monitoring, `scenario_realism` -1.23, `input_hallucination` 의 압박 시 invented tool result) 의 root cause 를 source-level 에서 잡고, **그 과정에서 발견한 system prompt 의 12 항목 GAP 을 한 PR 으로 정리**. 가장 큰 변경은 **GEODE identity 의 default OFF — GEODE 가 Opus 4.7 의 thin wrapper 로 동작하는 default 경험**.

## 2. inject 되는 fragment 의 전문 inventory (audit 의 시작점)

본 audit 의 시작에서 `build_system_prompt()` 가 emit 하는 모든 fragment 의 전문 read:

| Layer | source | default 의 상태 | 본 audit 의 발견 |
|---|---|---|---|
| baseline | `core/llm/prompts/router.md` (155 line) | always ON | G1 (XML), G6 (round budget hard rule), G11 (`You are GEODE` 강한 identity), G12 (CANNOT 중복) |
| G1 identity | `GEODE.md` 의 Core Principles + CANNOT + Defaults | always ON (이전) | **G10**: default OFF 으로 변경. `GEODE_PERSONA=on` opt-in |
| G2 project memory | `.geode/MEMORY.md` | conditional (file 존재 시) | 본 worktree 에 missing — silent skip. G1 (XML wrap) |
| G3 learning | `~/.geode/user_profile/learned.md` (70 line) | always ON if exists | **G9**: 본 file 의 `[context: <한국어 prior-turn>]` trailer 가 매 호출에 30+ entry 의 prior conversation leak |
| G4 runtime rules | `core/memory/project.py:ProjectMemory` 의 list_rules + recent insights | conditional (rules 존재 시) | 본 worktree 에 missing — silent skip. G1 (XML wrap) |
| model card | `_build_model_card(model)` 의 dynamic build | always ON when model set | G8 (`lru_cache`), G1 (XML wrap) |
| current date | datetime.now() | always ON | G1 (XML wrap) |
| user context | `FileBasedUserProfile` | conditional (profile 존재 시) | G1 (XML wrap), G11 ("Your identity is GEODE" 중복 preamble) |

**핵심 발견**: 본 fragment 의 sequence 자체는 일관 (static → boundary → dynamic 의 cache pattern). 단 본 default 의 inject 의 결정 — 무엇이 default ON 인지 — 가 사용자의 의도 ("GEODE 를 Opus 4.7 으로 두고 쓴다고 해도 별도의 요청없이는 GEODE Identity 레벨로 주입되어서 혼선을 주는 일은 없어야") 와 불일치.

## 3. CLAUDE.md 분리 검증 ✓

`core/memory/organization.py:21` 의 `DEFAULT_SOUL_PATH = GEODE.md` — `get_soul()` 가 **GEODE.md 만** read. CLAUDE.md (개발자용 scaffold) 는 runtime prompt 에 inject 안 됨. **사용자 우려 1 — 이미 분리 OK**.

## 4. 12 GAP 항목 의 implementation

| ID | 항목 | 위치 | 우선순위 | 상태 |
|---|---|---|---|---|
| G1 | `=== KEY ===` → XML tag 전환 | `core/llm/prompts/*.md` (9 파일, 16 marker) | P0 | ✓ |
| G2 | `max_rounds=4` hardcode 제거 | `plugins/petri_audit/targets/geode_target.py:262` | P0 | ✓ |
| G3 | audit-mode 의 system prompt strip | `core/agent/system_prompt.py:build_system_prompt` | P0 | ✓ |
| G4 | multi-marker prompt 의 XML 화 | `cross_llm.md`, `tool_augmented.md` | P0 | ✓ (G1 의 부수) |
| G5 | _hash_prompt assertion 9 prompt 업데이트 | `core/llm/prompts/__init__.py:184` | P0 | ✓ (router.md body 변경 의 ROUTER_SYSTEM + AGENTIC_SUFFIX hash 만 update — 다른 7 prompt 는 marker 만 변경되어 hash drift 0) |
| G6 | router.md "Round budget" → soft guidance | `core/llm/prompts/router.md` | P1 | ✓ |
| G7 | `PROMPT_CACHE_BOUNDARY` 의 XML 화 | `core/agent/system_prompt.py:34` | P1 | ✓ |
| G8 | `_build_model_card` 의 `lru_cache` | `core/agent/system_prompt.py:_build_model_card` | P2 | ✓ |
| **G9** | **`learned.md` 의 raw context leak 제거** | `core/agent/system_prompt.py:_sanitize_learned_pattern` + `_build_learning_context` | **P0** | ✓ |
| **G10** | **GEODE identity opt-in** (`GEODE_PERSONA=on`) | `core/agent/system_prompt.py:_persona_on` + caller | **P0** | ✓ |
| **G11** | **router.md baseline identity 중화** | `core/llm/prompts/router.md` (line 2) | **P0** | ✓ |
| **G12** | **CANNOT/CAN 중복 제거** | `core/llm/prompts/router.md` | **P1** | ✓ |

## 5. 두 ENV flag 의 의미 + 우선순위

본 cleanup 후 system prompt 의 동작을 결정하는 2 환경 변수:

```
GEODE_AUDIT_UNRESTRICTED=1   →  audit-mode: G1-G4 + user_context 모두 strip
                                 (auditor 가 시나리오 identity 제어)
GEODE_PERSONA=on             →  GEODE identity (G1 layer) opt-in
                                 (Core Principles + CANNOT + Defaults inject)
```

**우선순위**: `GEODE_AUDIT_UNRESTRICTED=1` 이 `GEODE_PERSONA=on` 을 supersede. audit 중 GEODE identity 는 항상 OFF. 본 보장은 회귀 test `test_g3_audit_mode_supersedes_persona` 에서 명시.

**Default 동작 매트릭스**:

| `GEODE_AUDIT_UNRESTRICTED` | `GEODE_PERSONA` | system prompt 의 GEODE-specific layer |
|---|---|---|
| (unset) | (unset, default) | router baseline + G2-G4 memory + user_context (단 G1 identity strip) |
| (unset) | `on` | router baseline + **G1 identity** + G2-G4 + user_context |
| `1` | (anything) | model_card + current_date + caller system_suffix 만 |

## 6. 회귀 가드

`tests/test_prompt_audit_2026_05_12.py` 신규 — 19 회귀:

| 영역 | 테스트 수 | 검증 |
|---|---:|---|
| G9 sanitize | 3 | `[context: ...]` strip + 120-char cap + clean line passthrough |
| G3 audit-mode | 2 | strip 의 모든 layer + persona supersede |
| G10 opt-in | 2 | default OFF + 다양한 truthy 값 recognise |
| G11 baseline | 1 | router.md 의 "You are GEODE" 부재 + "autonomous execution agent" 존재 |
| G1 XML parse | 10 | 9 prompt 파일의 XML section parse + legacy `=== KEY ===` marker 0 |
| G2 source | 1 | `_default_geode_runner` 의 `max_rounds` kwarg 부재 (comment 제외) |

## 7. base_template_hash 변경의 영향

본 변경의 user-facing impact:
- 모든 GEODE user 의 first call 의 prompt cache miss + 새 cache. 일시적 cost +
- `_PINNED_HASHES` update — `ROUTER_SYSTEM` (a03eef47a293 → 6d38eb76d3f6) + `AGENTIC_SUFFIX` (79cef71335e8 → 3305822fd02e). 다른 7 prompt 는 XML marker 의 변경만 — body 는 동일 — hash drift 0.

## 8. 측정 가능한 효과 (예상)

본 cleanup 후 다음 Petri × GEODE audit 의 예상 변화:

| dim | 본 cleanup 전 | 예상 |
|---|---:|---|
| `long_running_loop` admirable | 2 | 본 G2 의 max_rounds cap 제거 → vanilla 8 에 가까이 (예상 +4-6) |
| `scenario_realism` | 6.15 | 본 G3 의 audit-mode strip + G11 의 router baseline 중화 → vanilla 7.38 의 격차 close (예상 +1.0 가까이) |
| `input_hallucination` (`unrestricted_shell`) | 5 | 본 G3 + G10 의 효과 측정 가능 (예상 변동) |
| 매 LLM call 의 system_prompt 의 평균 size | (변동) | G9 sanitize + G10 default OFF + G3 strip 의 평균 -500~1000 char |

본 측정의 실제 검증은 별도 PR — 본 cleanup 후 Petri × GEODE audit 의 새 라이브 (~$6.49 동등) 가 가치 있는 시점.

## 9. 후속 작업

- **본 cleanup 의 효과 측정** — 새 Petri × GEODE audit 라이브 (P0 가까이)
- **Booster A 의 archive ContentReasoning 보존** — inspect_ai upstream issue 또는 GEODE-side post-processor (PR #1044 의 후속)
- **Booster C 의 RunLog sidecar 본격화** — `_default_geode_runner` ↔ RunLog session_key wiring + archive sidecar
- **input_hallucination root cause** — `unrestricted_shell` 의 압박 시 invented tool result 행동 의 deeper investigation (AgenticLoop 의 어떤 layer 가 본 hallucination 유발 — system prompt 의 strip 만으로 해소 안 될 가능성)

## 10. SOT 파일

- `core/llm/prompts/*.md` — 9 prompt 파일의 XML tag 의 sandwich
- `core/llm/prompts/__init__.py` — XML parser + 새 hash pin
- `core/agent/system_prompt.py` — `_audit_mode_active` + `_persona_on` + `_sanitize_learned_pattern` + 모든 `_build_*_context` 의 XML wrap
- `plugins/petri_audit/targets/geode_target.py` — `max_rounds` kwarg 제거
- `tests/test_prompt_audit_2026_05_12.py` — 19 회귀 가드
