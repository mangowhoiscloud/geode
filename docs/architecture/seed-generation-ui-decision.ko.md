# ADR -- Seed Generation UI/UX × 4-auth path

> [English](seed-generation-ui-decision.md) | **한국어**

> **Status**: Accepted (2026-05-18)
> **Scope**: seed-generation + Petri의 user-facing surface: credential picker, cost preview, ToS notice, pre-flight check, slash command.

## 컨텍스트

GEODE의 4 auth path:

- **A**: 로컬 `claude` CLI (macOS keychain 경유 Claude 구독) -- `claude_code_provider`
- **B**: 로컬 `codex` CLI (ChatGPT OAuth, device-code) -- `codex_provider`
- **C**: OpenAI PAYG (sk-…) -- `openai-payg`
- **D**: Anthropic PAYG (sk-ant-…) -- `anthropic-payg-geode`

Petri는 4-path를 모두 지원합니다 (P1-C 5-adapter split). seed-generation(ADR-001)도 동일한 coverage가 필요합니다. 추가로:

- 3-judge panel의 **provider diversity 강제** (최소 2 family). single-provider panel bias를 방지합니다.
- subscription path(A, B)의 **ToS 회색지대** 안내. 외부 배포에 부적합하다는 경고입니다.
- **cost preview**: PAYG 부담 + subscription quota %를 추정한 뒤 user confirm을 받습니다.
- **auth expiry pre-flight**: OAuth token TTL을 검사하고, 부족하면 abort하며 복구안을 제시합니다.

## 결정

**7-role × 4-path manifest + TUI picker + cost preview + ToS notice + pre-flight + slash command**.

### 1. Manifest 패턴 (Petri P1-A 4-layer 차용)

Petri의 `plugins/petri_audit/petri.plugin.toml` schema(`[petri]` / `[petri.role.*]` / `[petri.source.*]` / `[petri.adapter.*]`)를 그대로 차용합니다. seed-generation은 **source / adapter layer를 재정의하지 않고 Petri의 것을 참조합니다**: 같은 4-path를 같은 adapter로 호출합니다. role layer만 신규입니다.

`plugins/seed_generation/seed_generation.plugin.toml`:

```toml
# Schema layers:
#   1. [seed_generation] -- 활성화된 role 목록
#   2. [seed_generation.role.<name>] -- role별 default_model + allowed_models +
#      role_contract (Petri의 [petri.role.*] schema와 1:1)
#   3. source / adapter -- Petri의 [petri.source.*] + [petri.adapter.*] 재사용
#      (seed_generation.manifest.py의 loader가 petri.plugin.toml의 해당
#      섹션을 read-only로 import)

[seed_generation]
enabled_roles = [
    "generator", "critic", "proximity", "pilot",
    "ranker", "evolver", "meta_reviewer",
]
# 7 role = co-scientist 논문의 6 agent (generation/reflection/ranking/
# evolution/proximity/meta-review) + GEODE가 추가한 pilot (논문의
# scientist-in-the-loop 자리를 automated Petri audit으로 치환).

[seed_generation.role.generator]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-opus-4-7", "claude-sonnet-4-6", "gpt-5.5"]
role_contract = "roles/generator.md"

[seed_generation.role.critic]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-sonnet-4-6", "claude-haiku-4-5", "gpt-5.5"]
role_contract = "roles/critic.md"

[seed_generation.role.proximity]
# Embedding 기반, LLM-completion 아님. text_embed tool을 호출.
# default_model = embedding model (Petri의 family inference 우회 -- manifest
# loader가 이 role을 special-case로 표시하고, plan_registry 대신 OpenAI PAYG에
# 직접 binding).
default_model = "text-embedding-3-small"
allowed_models = ["text-embedding-3-small"]
role_contract = "roles/proximity.md"

[seed_generation.role.pilot]
default_model = "claude-haiku-4-5"
allowed_models = ["claude-haiku-4-5", "gpt-5.4-mini"]
role_contract = "roles/pilot.md"

[seed_generation.role.ranker]
# 3-judge panel orchestrator. 이 role의 default_model은 의미가 없음 --
# panel의 voter 3개가 [seed_generation.judge_panel]에서 별도로 binding됨.
default_model = "claude-sonnet-4-6"   # placeholder, 실제 호출은 panel이 수행
allowed_models = ["claude-opus-4-7", "claude-sonnet-4-6"]
role_contract = "roles/ranker.md"

[seed_generation.role.evolver]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-opus-4-7", "claude-sonnet-4-6"]
role_contract = "roles/evolver.md"

[seed_generation.role.meta_reviewer]
default_model = "claude-opus-4-7"
allowed_models = ["claude-opus-4-7", "claude-sonnet-4-6"]
role_contract = "roles/meta_reviewer.md"

# 3-judge panel -- Ranker role의 tournament 안에서 호출되는 voter 3개의
# binding. enabled_roles에 들어가지 않는 별도 sub-section.
# manifest loader가 이 section의 voter 3개가 최소 2개 family에 걸치는지 검사.
# 위반 시 reject.
[seed_generation.judge_panel]
voters = [
    { model = "claude-sonnet-4-6", family = "anthropic", source = "claude-cli" },
    { model = "gpt-5.5",           family = "openai",    source = "openai-codex" },
    { model = "claude-haiku-4-5",  family = "anthropic", source = "api_key" },
]
required_diversity_families = 2
```

source / adapter binding은 Petri의 `[petri.source.anthropic]` / `[petri.source.openai]` / `[petri.adapter.*]`를 그대로 재사용합니다. credential_source resolver도 `plugins.petri_audit.credential_source`를 직접 호출합니다. 즉 **provider diversity는 `[seed_generation.judge_panel].voters`의 `family` field 분포**로 표현됩니다.

manifest schema + loader는 `plugins/seed_generation/manifest.py`입니다 (Petri의 `plugins/petri_audit/manifest.py` 패턴 재사용; pydantic + drift validator + lazy yaml import + Petri manifest의 source/adapter import).

### 기본 3-judge panel 구성 (확정 결정)

`[seed_generation.judge_panel].voters`의 3-element 기본값 (위 TOML의 voters list와 동일):

| Voter | family | source | model | Plan ID (예) |
|---|---|---|---|---|
| voter[0] | anthropic | claude-cli | claude-sonnet-4-6 | claude-max-`<user>` |
| voter[1] | openai | openai-codex | gpt-5.5 | chatgpt-plus-`<user>` |
| voter[2] | anthropic | api_key | claude-haiku-4-5 | anthropic-payg-geode |

→ 2 family (anthropic + openai), 3 source, 3 model. diversity validator(`required_diversity_families = 2`)를 통과합니다.

Source 값은 Petri의 `[petri.source.<family>].allowed`와 1:1입니다 (anthropic은 `claude-cli` / `api_key` / `auto`, openai는 `openai-codex` / `api_key` / `auto`). Plan ID는 user 환경의 plan_registry에서 동적으로 lookup합니다.

### text_embed provider (확정 결정)

신규 tool `core/tools/text_embed.py`(S4)가 기본으로 사용할 provider:

- **OpenAI `text-embedding-3-small`** ($0.02 / 1M tok), 1536-dim.
- 다른 provider(Voyage, Cohere)는 후순위입니다. 본 ADR의 결정은 OpenAI 단일입니다.
- routing.toml의 `[embedding]` section으로 user override가 가능합니다 (별도 sub-PR의 enhancement).
- credential은 OpenAI PAYG(sk-…)만 사용합니다. ChatGPT OAuth는 embeddings API를 지원하지 않습니다.

### 2. 7-role × 4-path picker (TUI)

`plugins/seed_generation/picker.py`는 TerminalMenu 기반입니다. `/petri` 2-axis picker의 시각 패턴을 차용합니다.

```
╭─ Seed-pipeline 7-role + 3-judge panel binding ─────────────────────────────╮
│ Role / Voter    Family    Source         Plan ID              Status       │
│ ───────────────────────────────────────────────────────────────────────── │
│ Generator       anthropic claude-cli     claude-max-<user>    ✓            │
│ Critic          anthropic claude-cli     claude-max-<user>    ✓            │
│ Proximity       openai    api_key        openai-payg          ✓ (embed)    │
│ Pilot           anthropic claude-cli     claude-max-<user>    ✓            │
│ Ranker          anthropic claude-cli     claude-max-<user>    ✓            │
│   ├ Voter A     anthropic claude-cli     claude-max-<user>    ✓            │
│   ├ Voter B     openai    openai-codex   chatgpt-plus-<user>  ⚠ expired   │
│   └ Voter C     anthropic api_key        anthropic-payg-geode ✓ diversity! │
│ Evolver         anthropic claude-cli     claude-max-<user>    ✓            │
│ Meta-review     anthropic claude-cli     claude-max-<user>    ✓            │
│                                                                            │
│ Source values match plugins/petri_audit/petri.plugin.toml:                 │
│   anthropic.allowed = [claude-cli, api_key, auto]                          │
│   openai.allowed    = [openai-codex, api_key, auto]                        │
│                                                                            │
│ Cost preview:  $0.30 PAYG + ~12% Plus + ~8% Max                            │
│ Diversity:     Voter A/B/C = 2 family (anthropic + openai) ✓               │
│                                                                            │
│ [1-9] Edit  [a] Auto  [r] Refresh OAuth  [s] Save & exit  [q] Cancel       │
╰────────────────────────────────────────────────────────────────────────────╯
```

`required_diversity_families` 위반 시 picker가 save를 reject하고 재선택을 요구합니다.

### 3. ToS notice (subscription path 첫 활성화)

`claude_code_provider.py:38-56`의 policy notice 패턴을 재사용합니다. 본 ADR에서 picker의 inline notice로 통합하며, manifest의 source마다 first-activation hook을 둡니다:

```
첫 Claude subscription path 활성화 -- ToS 회색지대:

Anthropic Consumer ToS §3 (Acceptable Use)의 "automated access"
정의가 OAuth-routed subprocess 호출에 적용되는지 모호합니다. 문자
그대로의 위반은 아니지만, 정신적 위반 가능성이 있습니다 (좁은 해석).
외부 배포 / 공개 호스팅에 부적합합니다.

Petri / seed-generation 한정 사용을 권장합니다.
Production chat은 sk-ant-PAYG만 사용합니다.

활성화하시겠습니까? [y/N]:
```

ChatGPT subscription(B path)에도 동등한 notice를 표시합니다.

### 4. Cost preview (`geode audit-seeds quota`)

`plugins/seed_generation/cost_preview.py`는 `core/llm/pricing_loader.py`(P3-A)와 `core/cli/commands/login.py:_login_quota`의 quota 추정을 결합합니다.

```
$ geode audit-seeds quota --pipeline-config seed-generation.toml --candidates 15

추정 cost:

  Generation (15 × 8k in / 4k out, claude-cli):  ~180k tok    quota: ~4%
  Reflection (15 × 6k in / 2k out, claude-cli):  ~120k tok    quota: ~3%
  Proximity (1 batch, openai embed-3-small):     ~120k tok    PAYG: $0.0024
  Pilot (15 × 2 model × 1 paraphrase):           ~450k tok    quota: ~8% + $0.18 PAYG
  Tournament (60 match × 3 judge):               ~360k tok    quota: ~9% + $0.12 PAYG
  Evolution (top-5 × 1 round):                   ~80k tok     quota: ~2%
  Meta-review (1 batch):                         ~30k tok     quota: ~1%
  ─────────────────────────────────────────────  ──────────    ──────────────
  Total:                                         ~1.34M tok    ~$0.30 PAYG +
                                                              ~12% Plus + ~8% Max

예상 wall-time: ~25 min (Lane max=16)

Continue? [y/N]:
```

**Budget guard**: soft warning $0.30/gen, hard cap $1.00 (config 가능). 초과 시 pipeline을 abort합니다.

### 5. Pre-flight check (`geode audit-seeds generate` 진입 시)

```
Pre-flight check…
  Generator (claude-cli):    ✓ token expires in 14 days
  Critic (claude-cli):       ✓ token expires in 14 days
  Pilot judge (codex-cli):   ✗ token EXPIRED 24h ago

[ERROR] codex-cli token expired. Run `geode login openai` to refresh.
[option] Or override pilot judge to openai-payg via `geode audit-seeds picker`.

Aborting.
```

검사 항목: token expiry / quota 잔량 / 3-judge diversity / Lane 가용 capacity / budget guard.

### 6. CLI / Slash 진입점

**Typer** (`plugins/seed_generation/cli.py`):

| Sub-command | 책임 |
|---|---|
| `geode audit-seeds login` | 4-path status view |
| `geode audit-seeds picker` | role별 binding 편집 |
| `geode audit-seeds quota` | cost preview |
| `geode audit-seeds generate` | pipeline 시작 (pre-flight 포함) |
| `geode audit-seeds revoke <plan_id>` | 특정 plan disable |

**Slash** (`core/cli/routing.py`에 등록):

- `/audit-seeds <sub>`: REPL inside-loop 진입점. Typer sub-app과 같은 dispatch를 사용합니다.

`/petri`와 별도의 slash입니다. seed-generation이 pre-experiment phase로 개념적으로 분리되어 있고, `/petri seed-gen` 같은 nested form은 menu 깊이를 늘려 UX에 손해입니다. 결정: **별도 `/audit-seeds`**.

### 7. `/login` flow의 4-path 표면

기존 `_login_oauth(openai|anthropic)` + `_login_set_key`는 그대로 유지합니다. 단 status view 일관성을 위해:

- `_login_show_status`가 seed-generation manifest의 role binding도 함께 표시합니다 (선택, S11).
- `geode login claude-cli status`(keychain inspect) sub-action을 신설합니다. seed-generation picker가 이 status에 의존합니다.

## 결정 동인

- **Petri 패턴 재사용**: manifest + adapter + credential_source + picker. P1-A~G와 같은 PR 단위 구성입니다.
- **Co-evolution bias 회피**: 3-judge panel의 provider diversity 강제 (최소 2 family). single-provider 구성에서는 ranker가 한 model로 편향됩니다.
- **외부 배포 안전망**: subscription path 사용 시 ToS 회색지대를 명시합니다. user가 production 외부 배포 시 PAYG 단일화를 선택할 수 있게 합니다.
- **Cost 가시성**: pipeline 1회 ≈ $0.30 PAYG + quota. 무인 진화 시 누적 비용을 피하기 위한 confirmation step입니다.
- **Auth fragility 완화**: OAuth token expiry는 silent fail입니다. pre-flight가 이를 명시적 abort + 복구안 제시로 바꿉니다.

## 검토한 옵션

1. **Manifest + picker + cost + ToS + pre-flight + `/audit-seeds`** (✓ Accepted): 본 ADR.
2. Hardcoded all-claude-cli (Option γ, picker 없음): Rejected. diversity 손실, ToS 외 noise 0.
3. `/petri seed-gen` extension (nested): Rejected. menu depth.
4. `/login`에 picker 통합 (sub-pipeline별 별도 binding 표현 없음): Rejected. login의 책임 비대화.
5. Cost guard 없이 generate 즉시 실행: Rejected. 누적 비용 위험.

## 결과

### 긍정

- 4-path 모두 first-class. user가 claude-cli / codex-cli / PAYG를 자유롭게 조합합니다.
- 3-judge panel의 provider diversity를 자동으로 강제합니다. bias를 회피합니다.
- ToS 회색지대를 명시합니다. 외부 배포 시 user가 의식적으로 PAYG 단일화를 선택할 수 있습니다.
- Cost 가시성: pipeline 1회 비용 + quota 사용량을 사전에 확인합니다.
- Auth fragility 완화: token expiry가 silent fail하지 않습니다.

### 부정

- ~1,000 LOC UI/UX 추가 (이전 평가). 16 PR 중 S2.5 + S5.5 + S6.5 + S11 4개 PR.
- Picker UX의 시각 디자인 / TerminalMenu 한계: color / 멀티 column 정렬 등 platform 의존성.
- Cost preview의 token 추정이 사전 합산이라 실제 cost와 차이가 날 수 있습니다 (~20% 오차).
- ToS notice가 매 첫 활성화 시 user 인지 부담입니다. 1회 dismissal 후 나타나지 않도록 user-config 추가가 가능합니다 (별도 PR).

### 중립

- `_login_show_status`에 seed-generation binding 표시는 S11 선택 사항입니다. 본 ADR의 hard requirement가 아닙니다.

## 구현 포인터

- S2.5: `plugins/seed_generation/{manifest.py, seed_generation.plugin.toml}` (~220 LOC)
- S5.5: `plugins/seed_generation/{picker.py, pre_flight.py}` + ToS notice 통합 (~410 LOC)
- S6.5: `plugins/seed_generation/cost_preview.py` + budget guard (~250 LOC)
- S11: `plugins/seed_generation/cli.py` Typer sub-app + `core/cli/routing.py` slash 등록 (~280 LOC)

## 참고 자료

- ADR-001 -- seed-generation 아키텍처
- Petri P1-A~G manifest 패턴 -- `plugins/petri_audit/{petri.plugin.toml, manifest.py, cli.py:264,309}`
- 4-auth path 정의 -- `core/llm/routing/plans.py:PlanKind`
- ToS notice 패턴 -- `plugins/petri_audit/claude_code_provider.py:38-56`
- Quota 추정 base -- `core/cli/commands/login.py:_login_quota` (line 886)
- Pricing loader (P3-A) -- `core/llm/model_pricing.toml`
- `_login_oauth` flow -- `core/cli/commands/login.py:509-700`
