# ADR — Seed Generation UI/UX × 4-auth path

> **Status**: Accepted (2026-05-18)
> **Scope**: seed-generation + Petri 의 user-facing surface — credential picker, cost preview, ToS notice, pre-flight check, slash command.

## Context

GEODE 의 4 auth path:

- **A**: local `claude` CLI (Claude subscription via macOS keychain) — `claude_code_provider`
- **B**: local `codex` CLI (ChatGPT Plus OAuth, device-code) — `codex_provider`
- **C**: OpenAI PAYG (sk-…) — `openai-payg`
- **D**: Anthropic PAYG (sk-ant-…) — `anthropic-payg-geode`

Petri 는 4-path 모두 받침 (P1-C 5-adapter split). seed-generation (ADR-001) 도 동일 coverage 필요. 추가로:

- 3-judge panel 의 **provider diversity 강제** (최소 2 family) — single-provider panel bias 방지.
- subscription path (A, B) 의 **ToS 회색지대** 안내 — 외부 배포 부적합 경고.
- **cost preview** — PAYG 부담 + subscription quota % 추정 후 user confirm.
- **auth expiry pre-flight** — OAuth token TTL 검사 + 부족 시 abort + 보수안.

## Decision

**7-role × 4-path manifest + TUI picker + cost preview + ToS notice + pre-flight + slash command**.

### 1. Manifest pattern (Petri P1-A 4-layer 차용)

Petri 의 `plugins/petri_audit/petri.plugin.toml` 의 schema (`[petri]` / `[petri.role.*]` / `[petri.source.*]` / `[petri.adapter.*]`) 를 그대로 차용. seed-generation 은 **source / adapter layer 를 재정의하지 않고 Petri 의 것을 참조** — 같은 4-path 를 같은 adapter 로 호출. role layer 만 신규.

`plugins/seed_generation/seed_generation.plugin.toml`:

```toml
# Schema layers:
#   1. [seed_generation] — enabled roles
#   2. [seed_generation.role.<name>] — per-role default_model + allowed_models +
#      role_contract (Petri's [petri.role.*] schema 와 1:1)
#   3. source / adapter — reuse Petri's [petri.source.*] + [petri.adapter.*]
#      (seed_generation.manifest.py 의 loader 가 petri.plugin.toml 의 해당
#      섹션을 read-only 로 import)

[seed_generation]
enabled_roles = [
    "generator", "critic", "proximity", "pilot",
    "ranker", "evolver", "meta_reviewer",
]
# 7 role = co-scientist paper 6 agent (generation/reflection/ranking/evolution/
# proximity/meta-review) + GEODE 추가 pilot (paper 의 scientist-in-the-loop
# 자리를 automated Petri audit 으로 치환).

[seed_generation.role.generator]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-opus-4-7", "claude-sonnet-4-6", "gpt-5.5"]
role_contract = "roles/generator.md"

[seed_generation.role.critic]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-sonnet-4-6", "claude-haiku-4-5", "gpt-5.5"]
role_contract = "roles/critic.md"

[seed_generation.role.proximity]
# Embedding-based, not LLM-completion. text_embed tool 호출.
# default_model = embedding model (Petri 의 family inference 우회 — manifest
# loader 가 본 role 을 special-case 로 표시, plan_registry 대신 OpenAI PAYG
# 직 binding).
default_model = "text-embedding-3-small"
allowed_models = ["text-embedding-3-small"]
role_contract = "roles/proximity.md"

[seed_generation.role.pilot]
default_model = "claude-haiku-4-5"
allowed_models = ["claude-haiku-4-5", "gpt-5.4-mini"]
role_contract = "roles/pilot.md"

[seed_generation.role.ranker]
# 3-judge panel orchestrator. 본 role 의 default_model 은 의미 없음 —
# panel 의 3 voter 가 [seed_generation.judge_panel] 에서 별도 binding.
default_model = "claude-sonnet-4-6"   # placeholder, panel 이 실제 호출
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

# 3-judge panel — Ranker role 의 tournament 안에서 호출되는 3 voter 의
# binding. enabled_roles 에 들어가지 않는 별도 sub-section.
# manifest loader 가 본 section 의 voter 3 의 family 가 최소 2 인지 검사.
# 위반 시 reject.
[seed_generation.judge_panel]
voters = [
    { model = "claude-sonnet-4-6", family = "anthropic", source = "claude-cli" },
    { model = "gpt-5.5",           family = "openai",    source = "openai-codex" },
    { model = "claude-haiku-4-5",  family = "anthropic", source = "api_key" },
]
required_diversity_families = 2
```

source / adapter binding — Petri 의 `[petri.source.anthropic]` / `[petri.source.openai]` / `[petri.adapter.*]` 를 그대로 재사용. credential_source resolver 도 `plugins.petri_audit.credential_source` 를 직 호출. 즉 **provider diversity = `[seed_generation.judge_panel].voters` 의 `family` field 분포** 로 표현.

manifest schema + loader — `plugins/seed_generation/manifest.py` (Petri 의 `plugins/petri_audit/manifest.py` 패턴 재사용, pydantic + drift validator + lazy yaml import + Petri manifest 의 source/adapter import).

### Default 3-judge panel composition (settled decision)

`[seed_generation.judge_panel].voters` 의 3-element default (위 TOML 의 voters list 와 동일):

| Voter | family | source | model | Plan ID (예) |
|---|---|---|---|---|
| voter[0] | anthropic | claude-cli | claude-sonnet-4-6 | claude-max-`<user>` |
| voter[1] | openai | openai-codex | gpt-5.5 | chatgpt-plus-`<user>` |
| voter[2] | anthropic | api_key | claude-haiku-4-5 | anthropic-payg-geode |

→ 2 family (anthropic + openai), 3 source, 3 model. diversity validator (`required_diversity_families = 2`) 통과.

Source value 는 Petri 의 `[petri.source.<family>].allowed` 와 1:1 (anthropic 의 `claude-cli` / `api_key` / `auto`, openai 의 `openai-codex` / `api_key` / `auto`). Plan ID 는 user 환경 의 plan_registry 에서 동적 lookup.

### text_embed provider (settled decision)

신규 tool `core/tools/text_embed.py` (S4) 가 기본 사용할 provider:

- **OpenAI `text-embedding-3-small`** ($0.02 / 1M tok), 1536-dim.
- 다른 provider (Voyage, Cohere) 후순위 — 본 ADR 의 결정은 OpenAI 단일.
- routing.toml 의 `[embedding]` section 으로 user override 가능 (별도 sub-PR 의 enhancement).
- credential — OpenAI PAYG (sk-…) 만 사용. ChatGPT Plus OAuth 는 embeddings API 미지원.

### 2. 7-role × 4-path picker (TUI)

`plugins/seed_generation/picker.py` — TerminalMenu 기반. `/petri` 2-axis picker 의 시각 패턴 차용.

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

`required_diversity_families` 위반 시 picker 가 save reject + 재선택 요구.

### 3. ToS notice (subscription path 첫 활성화)

`claude_code_provider.py:38-56` 의 policy notice 패턴 재사용. 본 ADR 에서 picker 의 inline notice 로 통합 — manifest 의 source 마다 first-activation hook:

```
첫 Claude subscription path 활성화 — ToS 회색지대:

Anthropic Consumer ToS §3 (Acceptable Use) 의 "automated access"
정의가 OAuth-routed subprocess 호출에 적용되는지 모호. 문자 그대로
위반 X, 정신적 위반 가능 (좁은 해석). 외부 배포 / 공개 호스팅 부적합.

Petri / seed-generation 한정 사용 권장.
Production chat 은 sk-ant-PAYG 만 사용.

활성화하시겠습니까? [y/N]:
```

ChatGPT Plus subscription (B path) 도 동등 notice.

### 4. Cost preview (`geode audit-seeds quota`)

`plugins/seed_generation/cost_preview.py` — `core/llm/pricing_loader.py` (P3-A) + `core/cli/commands/login.py:_login_quota` 의 quota 추정 결합.

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

**Budget guard**: soft warning at $0.30/gen, hard cap at $1.00 (config 가능). 초과 시 pipeline abort.

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
| `geode audit-seeds picker` | per-role binding 편집 |
| `geode audit-seeds quota` | cost preview |
| `geode audit-seeds generate` | pipeline 시작 (pre-flight 포함) |
| `geode audit-seeds revoke <plan_id>` | 특정 plan disable |

**Slash** (`core/cli/routing.py` 등록):

- `/audit-seeds <sub>` — REPL inside-loop 진입점, Typer sub-app 와 같은 dispatch.

`/petri` 와 별도 slash. seed-generation 이 pre-experiment phase 로 conceptually 분리되어 있고, `/petri seed-gen` 같은 nested form 은 menu 깊이 ↑ — UX 손해. 결정: **별도 `/audit-seeds`**.

### 7. `/login` flow 의 4-path 표면

기존 `_login_oauth(openai|anthropic)` + `_login_set_key` 그대로 유지. 단 status view 일관성 위해:

- `_login_show_status` 가 seed-generation manifest 의 role binding 도 함께 표시 (선택, S11).
- `geode login claude-cli status` (keychain inspect) 신규 sub-action — seed-generation picker 가 status 의존.

## Decision Drivers

- **Petri 패턴 재사용**: manifest + adapter + credential_source + picker — 같은 PR 단위 (P1-A~G) 동일.
- **Co-evolution bias 회피**: 3-judge panel 의 provider diversity 강제 (최소 2 family) — single-provider 매니징 시 ranker 가 한 model 편향.
- **외부 배포 안전망**: subscription path 사용 시 ToS 회색지대 명시. user 가 production 외부 배포 시 PAYG 단일화 선택 가능하도록.
- **Cost 가시성**: pipeline 1 회 ≈ $0.30 PAYG + quota — 무인 진화 시 누적 비용 회피 위한 confirmation step.
- **Auth fragility 완화**: OAuth token expiry 가 silent fail → pre-flight 가 명시적 abort + 복구안 제시.

## Considered Options

1. **Manifest + picker + cost + ToS + pre-flight + `/audit-seeds`** (✓ Accepted): 본 ADR.
2. Hardcoded all-claude-cli (Option γ, picker 없음): Rejected — diversity 손실, ToS 외 noise 0.
3. `/petri seed-gen` extension (nested): Rejected — menu depth.
4. `/login` 에 picker 통합 (sub-pipeline 별 별도 binding 표현 없음): Rejected — login 의 책임 비대화.
5. Cost guard 없이 generate 즉시 실행: Rejected — 누적 비용 위험.

## Consequences

### 긍정

- 4-path 모두 first-class. user 가 claude-cli / codex-cli / PAYG 자유롭게 조합.
- 3-judge panel 의 provider diversity 자동 강제 — bias 회피.
- ToS 회색지대 명시 — 외부 배포 시 user 가 의식적으로 PAYG 단일화 선택 가능.
- Cost 가시성 — pipeline 1회 비용 + quota 사용량 사전 확인.
- Auth fragility 완화 — token expiry 가 silent fail 안 함.

### 부정

- ~1,000 LOC UI/UX 추가 (이전 평가). 16 PR 중 S2.5 + S5.5 + S6.5 + S11 4 개 PR.
- Picker UX 의 시각 디자인 / TerminalMenu 한계 — color / 멀티 column 정렬 등 platform 의존성.
- Cost preview 의 token 추정이 사전 합산 — 실제 cost 와 차이 가능 (~20% 오차).
- ToS notice 가 매 첫 활성화 시 user 인지 부담 — 1회 dismissal 후 안 나타나도록 user-config 추가 가능 (별도 PR).

### 중립

- `_login_show_status` 에 seed-generation binding 표시는 S11 선택 사항. 본 ADR 의 hard requirement 아님.

## Implementation pointers

- S2.5: `plugins/seed_generation/{manifest.py, seed_generation.plugin.toml}` (~220 LOC)
- S5.5: `plugins/seed_generation/{picker.py, pre_flight.py}` + ToS notice 통합 (~410 LOC)
- S6.5: `plugins/seed_generation/cost_preview.py` + budget guard (~250 LOC)
- S11: `plugins/seed_generation/cli.py` Typer sub-app + `core/cli/routing.py` slash 등록 (~280 LOC)

## References

- ADR-001 — seed-generation architecture
- Petri P1-A~G manifest pattern — `plugins/petri_audit/{petri.plugin.toml, manifest.py, cli.py:264,309}`
- 4-auth path 정의 — `core/llm/routing/plans.py:PlanKind`
- ToS notice pattern — `plugins/petri_audit/claude_code_provider.py:38-56`
- Quota 추정 base — `core/cli/commands/login.py:_login_quota` (line 886)
- Pricing loader (P3-A) — `core/llm/model_pricing.toml`
- `_login_oauth` flow — `core/cli/commands/login.py:509-700`
