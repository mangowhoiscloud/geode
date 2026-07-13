# ADR -- Seed Generation UI/UX × 4-auth path

> **English** | [한국어](seed-generation-ui-decision.ko.md)

> **Status**: Accepted (2026-05-18)
> **Scope**: user-facing surface of seed-generation + Petri: credential picker, cost preview, ToS notice, pre-flight check, slash command.

## Context

GEODE's 4 auth paths:

- **A**: local `claude` CLI (Claude subscription via macOS keychain) -- `claude_code_provider`
- **B**: local `codex` CLI (ChatGPT OAuth, device-code) -- `codex_provider`
- **C**: OpenAI PAYG (sk-…) -- `openai-payg`
- **D**: Anthropic PAYG (sk-ant-…) -- `anthropic-payg-geode`

Petri supports all 4 paths (P1-C 5-adapter split). seed-generation (ADR-001) needs the same coverage. In addition:

- **Enforced provider diversity** for the 3-judge panel (minimum 2 families), preventing single-provider panel bias.
- **ToS gray-area** notice for the subscription paths (A, B), warning that they are unsuitable for external distribution.
- **cost preview**: estimate the PAYG cost + subscription quota %, then require user confirmation.
- **auth expiry pre-flight**: check the OAuth token TTL; abort with a recovery suggestion when insufficient.

## Decision

**7-role × 4-path manifest + TUI picker + cost preview + ToS notice + pre-flight + slash command**.

### 1. Manifest pattern (borrowed from the Petri P1-A 4-layer)

Borrows the schema of Petri's `plugins/petri_audit/petri.plugin.toml` (`[petri]` / `[petri.role.*]` / `[petri.source.*]` / `[petri.adapter.*]`) as-is. seed-generation **does not redefine the source / adapter layers and references Petri's instead**: the same 4 paths are called through the same adapters. Only the role layer is new.

`plugins/seed_generation/seed_generation.plugin.toml`:

```toml
# Schema layers:
#   1. [seed_generation] -- enabled roles
#   2. [seed_generation.role.<name>] -- per-role default_model + allowed_models +
#      role_contract (1:1 with Petri's [petri.role.*] schema)
#   3. source / adapter -- reuse Petri's [petri.source.*] + [petri.adapter.*]
#      (the loader in seed_generation.manifest.py imports the corresponding
#      sections of petri.plugin.toml read-only)

[seed_generation]
enabled_roles = [
    "generator", "critic", "proximity", "pilot",
    "ranker", "evolver", "meta_reviewer",
]
# 7 roles = the co-scientist paper's 6 agents (generation/reflection/ranking/
# evolution/proximity/meta-review) + a GEODE-added pilot (replaces the paper's
# scientist-in-the-loop slot with an automated Petri audit).

[seed_generation.role.generator]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-opus-4-7", "claude-sonnet-4-6", "gpt-5.5"]
role_contract = "roles/generator.md"

[seed_generation.role.critic]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-sonnet-4-6", "claude-haiku-4-5", "gpt-5.5"]
role_contract = "roles/critic.md"

[seed_generation.role.proximity]
# Embedding-based, not LLM-completion. Calls the text_embed tool.
# default_model = embedding model (bypasses Petri's family inference -- the
# manifest loader marks this role as a special case and binds it directly to
# OpenAI PAYG instead of the plan_registry).
default_model = "text-embedding-3-small"
allowed_models = ["text-embedding-3-small"]
role_contract = "roles/proximity.md"

[seed_generation.role.pilot]
default_model = "claude-haiku-4-5"
allowed_models = ["claude-haiku-4-5", "gpt-5.4-mini"]
role_contract = "roles/pilot.md"

[seed_generation.role.ranker]
# 3-judge panel orchestrator. This role's default_model is meaningless --
# the panel's 3 voters are bound separately in [seed_generation.judge_panel].
default_model = "claude-sonnet-4-6"   # placeholder, the panel makes the actual calls
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

# 3-judge panel -- binding for the 3 voters called inside the Ranker role's
# tournament. A separate sub-section that is not part of enabled_roles.
# The manifest loader checks that the 3 voters in this section span at least
# 2 families. Violations are rejected.
[seed_generation.judge_panel]
voters = [
    { model = "claude-sonnet-4-6", family = "anthropic", source = "claude-cli" },
    { model = "gpt-5.5",           family = "openai",    source = "openai-codex" },
    { model = "claude-haiku-4-5",  family = "anthropic", source = "api_key" },
]
required_diversity_families = 2
```

source / adapter binding: reuses Petri's `[petri.source.anthropic]` / `[petri.source.openai]` / `[petri.adapter.*]` as-is. The credential_source resolver also calls `plugins.petri_audit.credential_source` directly. In other words, **provider diversity is expressed as the distribution of the `family` field across `[seed_generation.judge_panel].voters`**.

manifest schema + loader: `plugins/seed_generation/manifest.py` (reuses the pattern of Petri's `plugins/petri_audit/manifest.py`; pydantic + drift validator + lazy yaml import + import of the Petri manifest's source/adapter).

### Default 3-judge panel composition (settled decision)

The 3-element default of `[seed_generation.judge_panel].voters` (identical to the voters list in the TOML above):

| Voter | family | source | model | Plan ID (example) |
|---|---|---|---|---|
| voter[0] | anthropic | claude-cli | claude-sonnet-4-6 | claude-max-`<user>` |
| voter[1] | openai | openai-codex | gpt-5.5 | chatgpt-plus-`<user>` |
| voter[2] | anthropic | api_key | claude-haiku-4-5 | anthropic-payg-geode |

→ 2 families (anthropic + openai), 3 sources, 3 models. Passes the diversity validator (`required_diversity_families = 2`).

Source values map 1:1 to Petri's `[petri.source.<family>].allowed` (`claude-cli` / `api_key` / `auto` for anthropic, `openai-codex` / `api_key` / `auto` for openai). Plan IDs are looked up dynamically from the plan_registry in the user's environment.

### text_embed provider (settled decision)

The provider the new tool `core/tools/text_embed.py` (S4) uses by default:

- **OpenAI `text-embedding-3-small`** ($0.02 / 1M tok), 1536-dim.
- Other providers (Voyage, Cohere) are deprioritized; this ADR's decision is OpenAI only.
- User override is possible via the `[embedding]` section of routing.toml (an enhancement in a separate sub-PR).
- credential: OpenAI PAYG (sk-…) only. ChatGPT OAuth does not support the embeddings API.

### 2. 7-role × 4-path picker (TUI)

`plugins/seed_generation/picker.py`: TerminalMenu-based. Borrows the visual pattern of the `/petri` 2-axis picker.

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

On a `required_diversity_families` violation the picker rejects the save and requires reselection.

### 3. ToS notice (first activation of a subscription path)

Reuses the policy notice pattern of `claude_code_provider.py:38-56`. This ADR consolidates it into an inline notice in the picker, with a first-activation hook per manifest source:

```
First activation of the Claude subscription path -- ToS gray area:

Whether the "automated access" definition in Anthropic Consumer ToS §3
(Acceptable Use) applies to OAuth-routed subprocess calls is ambiguous.
Not a literal violation; possibly a violation in spirit (narrow
interpretation). Unsuitable for external distribution / public hosting.

Recommended for Petri / seed-generation use only.
Production chat uses sk-ant-PAYG only.

Activate? [y/N]:
```

The ChatGPT subscription (path B) gets an equivalent notice.

### 4. Cost preview (`geode audit-seeds quota`)

`plugins/seed_generation/cost_preview.py`: combines `core/llm/pricing_loader.py` (P3-A) with the quota estimation of `core/cli/commands/login.py:_login_quota`.

```
$ geode audit-seeds quota --pipeline-config seed-generation.toml --candidates 15

Estimated cost:

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

Expected wall-time: ~25 min (Lane max=16)

Continue? [y/N]:
```

**Budget guard**: soft warning at $0.30/gen, hard cap at $1.00 (configurable). The pipeline aborts on overrun.

### 5. Pre-flight check (on entering `geode audit-seeds generate`)

```
Pre-flight check…
  Generator (claude-cli):    ✓ token expires in 14 days
  Critic (claude-cli):       ✓ token expires in 14 days
  Pilot judge (codex-cli):   ✗ token EXPIRED 24h ago

[ERROR] codex-cli token expired. Run `geode login openai` to refresh.
[option] Or override pilot judge to openai-payg via `geode audit-seeds picker`.

Aborting.
```

Checked items: token expiry / remaining quota / 3-judge diversity / available Lane capacity / budget guard.

### 6. CLI / Slash entry points

**Typer** (`plugins/seed_generation/cli.py`):

| Sub-command | Responsibility |
|---|---|
| `geode audit-seeds login` | 4-path status view |
| `geode audit-seeds picker` | edit per-role bindings |
| `geode audit-seeds quota` | cost preview |
| `geode audit-seeds generate` | start the pipeline (includes pre-flight) |
| `geode audit-seeds revoke <plan_id>` | disable a specific plan |

**Slash** (registered in `core/cli/routing.py`):

- `/audit-seeds <sub>`: REPL inside-loop entry point, same dispatch as the Typer sub-app.

A slash command separate from `/petri`. seed-generation is conceptually separated as a pre-experiment phase, and a nested form like `/petri seed-gen` increases menu depth, which hurts UX. Decision: **a separate `/audit-seeds`**.

### 7. 4-path surface of the `/login` flow

The existing `_login_oauth(openai|anthropic)` + `_login_set_key` are kept as-is. For status-view consistency, however:

- `_login_show_status` also displays the role bindings of the seed-generation manifest (optional, S11).
- New sub-action `geode login claude-cli status` (keychain inspect); the seed-generation picker depends on this status.

## Decision Drivers

- **Petri pattern reuse**: manifest + adapter + credential_source + picker, the same PR-unit breakdown as P1-A~G.
- **Co-evolution bias avoidance**: enforced provider diversity for the 3-judge panel (minimum 2 families); with single-provider management the ranker skews toward one model.
- **External-distribution safety net**: the ToS gray area is stated explicitly when a subscription path is used, so the user can choose to consolidate on PAYG for production external distribution.
- **Cost visibility**: one pipeline run ≈ $0.30 PAYG + quota; a confirmation step to avoid cost accumulation during unattended evolution.
- **Auth fragility mitigation**: OAuth token expiry is a silent fail; pre-flight turns it into an explicit abort plus a recovery suggestion.

## Considered Options

1. **Manifest + picker + cost + ToS + pre-flight + `/audit-seeds`** (✓ Accepted): this ADR.
2. Hardcoded all-claude-cli (Option γ, no picker): Rejected. Diversity loss; zero noise apart from ToS.
3. `/petri seed-gen` extension (nested): Rejected. Menu depth.
4. Integrating the picker into `/login` (no way to express separate bindings per sub-pipeline): Rejected. Bloats login's responsibility.
5. Running generate immediately without a cost guard: Rejected. Cost-accumulation risk.

## Consequences

### Positive

- All 4 paths are first-class. The user freely combines claude-cli / codex-cli / PAYG.
- Provider diversity for the 3-judge panel is enforced automatically, avoiding bias.
- The ToS gray area is stated explicitly; for external distribution the user can consciously consolidate on PAYG.
- Cost visibility: per-run pipeline cost + quota usage confirmed up front.
- Auth fragility mitigated: token expiry does not fail silently.

### Negative

- Adds ~1,000 LOC of UI/UX (prior estimate). 4 PRs out of 16: S2.5 + S5.5 + S6.5 + S11.
- Visual design of the picker UX / TerminalMenu limitations: platform dependencies such as color and multi-column alignment.
- The cost preview's token estimate is a pre-run aggregate; it can differ from actual cost (~20% error).
- The ToS notice adds a user-awareness burden on every first activation; a user-config to suppress it after one dismissal can be added (separate PR).

### Neutral

- Displaying seed-generation bindings in `_login_show_status` is an S11 option, not a hard requirement of this ADR.

## Implementation pointers

- S2.5: `plugins/seed_generation/{manifest.py, seed_generation.plugin.toml}` (~220 LOC)
- S5.5: `plugins/seed_generation/{picker.py, pre_flight.py}` + ToS notice integration (~410 LOC)
- S6.5: `plugins/seed_generation/cost_preview.py` + budget guard (~250 LOC)
- S11: `plugins/seed_generation/cli.py` Typer sub-app + `core/cli/routing.py` slash registration (~280 LOC)

## References

- ADR-001 -- seed-generation architecture
- Petri P1-A~G manifest pattern -- `plugins/petri_audit/{petri.plugin.toml, manifest.py, cli.py:264,309}`
- 4-auth path definition -- `core/llm/routing/plans.py:PlanKind`
- ToS notice pattern -- `plugins/petri_audit/claude_code_provider.py:38-56`
- Quota estimation base -- `core/cli/commands/login.py:_login_quota` (line 886)
- Pricing loader (P3-A) -- `core/llm/model_pricing.toml`
- `_login_oauth` flow -- `core/cli/commands/login.py:509-700`
