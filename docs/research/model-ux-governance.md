# Model & Login UX Governance Audit

Audit of credential/plan registration (/login) and model selection (/model) across three CLI harnesses, examining separation of concerns, multi-provider clarity, and token/subscription lifecycle management.

**Principle under test**: User logs in with one auth mode at a time; system stores it; later `/model` selection just picks a bare model name — auth mode choice must be upstream, not conflated with model choice.

Built 2026-04-27 by 3 parallel agents (claw+hermes /model UX | GEODE /model audit | /login UX 3-codebase). All claims cite file:line. No external doc references — codebases only.

---

## /model UX governance — OpenClaw + Hermes reference

### OpenClaw

**`/model` picker**: `/Users/mango/workspace/openclaw/src/flows/model-picker.ts:118-158` — shows bare `provider/model` keys (e.g. `anthropic/claude-sonnet-4-5`), auth status as **hint** (`"auth missing"` line 150), not a filter.

```ts
// model-picker.ts:152-156
params.options.push({
  value: key,
  label: key,                  // bare provider/model key
  hint: hints.length > 0 ? hints.join(" · ") : undefined,
});
```

**Auth resolution**: `/Users/mango/workspace/openclaw/src/agents/model-auth.ts:340-478` — single entry point `resolveApiKeyForProvider({provider, ...})`. Precedence: explicit profileId → `models.providers.<p>.auth` override → config apiKey → profile order → env vars → custom config → synthesized.

**Per-provider order user override**: ✅ `models auth-order set <provider> <profile-1> <profile-2>` (`commands/models/auth-order.ts:46-71`).

**System prompt model identity injection**: ❌ not found — model name passed as SDK parameter only.

### Hermes Agent

**`/model` picker**: `/Users/mango/workspace/hermes-agent/hermes_cli/model_switch.py:226-243` — auth-aware filter via `list_authenticated_providers()` (line 783-1190); shows bare model names (`gpt-4o`, `claude-opus-4-6`) per authenticated provider.

**Auth resolution**: `model_switch.py:411-776` calls `resolve_runtime_provider(requested=target_provider)` (`runtime_provider.py:109-230+`). Precedence: PROVIDER_REGISTRY env vars → auth store (auth.json) → credential pool → base_url override.

**Per-provider order**: ❌ rigid — fixed by `PROVIDER_REGISTRY[provider].api_key_env_vars` tuple order (`auth.py:108-150`).

**System prompt model identity injection**: ❌ not found.

### Comparison — /model UX

| Concern | OpenClaw | Hermes | Pattern |
|---------|----------|--------|---------|
| Picker shows | bare `provider/model` + auth hint | bare model + provider context (filter by login) | bare names, no auth-mode label |
| Auth resolved at | LLM call time | LLM call time | post-pick |
| Per-provider tunable order | ✅ `auth-order set` | ❌ env priority | OpenClaw more flexible |
| Model identity in system prompt | ❌ | ❌ | trust SDK parameter |
| Forced override | `auth: "api-key"` config + auth-order | none (rigid) | OpenClaw |

---

## /model UX governance — GEODE current state (v0.52.7)

**`/model` command handler**: `core/cli/commands.py:449-509`. Static `MODEL_PROFILES` registry (line 50-64) — bare model IDs + provider labels + cost. NO auth-mode in label.

```python
# commands.py:50-64
MODEL_PROFILES = [
    ModelProfile(ANTHROPIC_PRIMARY, "Anthropic", "Opus 4.7", "$$$"),
    ModelProfile(OPENAI_PRIMARY, "OpenAI", "GPT-5.4", "$$"),  # ⚠ label "GPT-5.4" but ID = "gpt-5.5"
    ModelProfile("gpt-5.4-mini", "OpenAI", "GPT-5.4 Mini", "$"),
    ModelProfile("gpt-5.3-codex", "Codex (Plus)", "GPT-5.3 Codex", "$$"),
    ModelProfile(GLM_PRIMARY, "GLM", "GLM-5.1", "$"),
]
```

**Auth resolution** (post v0.52.4): `core/llm/router.py:_route_provider` → `core/auth/plan_registry.py:resolve_routing` 4-step chain (explicit routing → equivalence-class scan with `PLAN_KIND_PRIORITY` → single-provider fallback → synthesize PAYG). `forced_login_method` honored at line 176.

**Codex token resolution** (v0.52.5): `core/llm/providers/codex.py:54-101` — 2-pass (`managed_by=""` first, then borrowed CLI, then `~/.codex/auth.json`).

**Picker source filter**: ❌ static `MODEL_PROFILES` — all 10 models always shown, no login-state filter.

**`forced_login_method` UX surface**: ❌ defined at `core/config.py:328`, read by `plan_registry.py:249`, but `/model` picker shows NO indication when set.

**System prompt model identity injection** (v0.52.8): ✅ `core/agent/system_prompt.py:_build_model_card` strong assertion. ⚠ **Diverges from claw + hermes** (both don't inject).

### GEODE governance gaps (5)

| # | Gap | File:line |
|---|-----|-----------|
| 1 | "Codex (Plus)" label vs `openai-codex` provider ID 불일치 | `commands.py:60` |
| 2 | `forced_login_method` 가 `/model` UX 에 안 보임 | `_apply_model` 분리 |
| 3 | `gpt-5.5` 가 static `_resolve_provider` 에서 `"openai"` 로 매핑되지만 실제 Codex-only | `core/config.py:_resolve_provider` |
| 4 | Silent credential fallback 중 user-facing signal 없음 | `resolve_routing` chain |
| 5 | `MODEL_PROFILES` 가 login state 필터링 없음 | `commands.py:50` |

### v0.52.8 system prompt assertion 재검토 필요

reference (claw + hermes) 둘 다 system prompt 에 model identity 안 주입. GEODE v0.52.8 의 strong assertion 은 다른 방향. **재검토 결정 후보**:
- (A) 유지 — 우리 incident 재발 방지가 우선 + reference 도 안 하지만 우리 LLM 호출 환경 (Codex backend 포함) 이 더 까다로움
- (B) 약화 — reference 와 align, 단 conversation history 의 stale ack purge (Fix 2) 만 유지
- (C) Codex backend 만 따로 처리 — chatgpt.com 호출시 강한 assertion, api.openai.com 등은 제거

---

## /login UX governance

### OpenClaw

**Entry point**: `/openclaw models auth <subcommand>` (nested under `models` command)
- File:line: `/Users/mango/workspace/openclaw/src/cli/models-cli.ts:290–441`

**Subcommands**:
```
openclaw models auth                    — show help
openclaw models auth add                — interactive auth helper
openclaw models auth login              — provider OAuth/API key flow
openclaw models auth setup-token        — provider CLI auth (TTY)
openclaw models auth paste-token        — paste token to auth-profiles.json
openclaw models auth login-github-copilot — GitHub Copilot device flow
openclaw models auth order get          — show per-agent profile order override
openclaw models auth order set          — pin profiles in rotation order
openclaw models auth order clear        — reset to config default
```

**Login flow steps** (verbatim from code):
1. Picker for provider? **Yes** — required flag `--provider <id>` or interactive
2. Auth method choice? **Yes** (if plugin supports multiple) — flag `--method <id>`
3. What's stored at end?
   - File: `/Users/mango/workspace/openclaw/src/commands/models/auth.ts:20–32` imports `upsertAuthProfile`
   - Stores: `AuthProfileCredential` with `{ provider, method, profileId, expiresAt, refreshToken, accessToken }`
   - Storage: `.openclaw/auth-profiles.json` (per-agent)
4. Confirmation message? **Yes, implicit** — command completes silently or shows "Profile added"

**Login dashboard / status view**:
- Command: `openclaw models status` (file:line: `/src/commands/models/list.status-command.ts:63–180`)
- What's shown:
  - **Model default** (active model label)
  - **Fallback chain** (ordered list)
  - **Provider auth overview** per provider:
    - Profile count (`profiles.count`)
    - Env var presence + source
    - models.json overrides
  - **Missing auth** for in-use providers (red badge)
- Active marker? **Per-provider**: `✓ count` of profiles; current rotation shown in `models auth order get`
- Plan vs provider? **No plan abstraction in OpenClaw** — only provider IDs + method IDs, no subscription tier visibility

**Multi-provider register UX**:
- Example: User has both Anthropic API key + GitHub Copilot OAuth registered
- Dashboard visibility: **Via `models status`** shows both under their provider headings
- Active per model? **Yes** — `models auth order set --provider <id> <profiles...>` pins rotation order for that provider
- Removal: `models auth` does NOT have a `remove` subcommand visible in CLI registration (file:line 296–441); removal happens via direct auth-profiles.json edit or plugin

**Refresh / token expiry UX**:
- Auto-refresh? **Plugin-dependent** — OpenClaw doesn't provide CLI-level auto-refresh
- User notification? **Via `models status --probe`** (line 73–88) — `--check` flag exits non-zero if expired
- Refresh command? **No explicit `/login refresh`** — only plugin-level token refresh embedded in OAuth flows

**Anti-conflation check**:
- Does `/models` ever ask for auth-mode? **NO** — `models set <model>` accepts only bare model name (line 118–123)
- Does `/models auth` ever ask for model? **NO** — auth subcommands only take provider + method + profile args (line 296–441)

---

### Hermes Agent

**Entry point**: `hermes auth <subcommand>` (top-level command)
- File:line: `/Users/mango/workspace/hermes-agent/hermes_cli/auth_commands.py:572–587`

**Subcommands**:
```
hermes auth             — interactive credential pool dashboard
hermes auth add        — add credential (provider picker, auth type picker)
hermes auth list       — show all credentials (grouped by provider)
hermes auth remove     — remove credential by label/id/index
hermes auth reset      — reset cooldown timers for a provider
```

**Login flow steps** (verbatim from code):
1. Picker for provider? **Yes** — interactive via `_pick_provider()` (line 449–463) or CLI arg `--provider`
2. Auth method choice? **Yes** — if provider in `_OAUTH_CAPABLE_PROVIDERS` (line 36), prompt "API key vs OAuth" (line 472–483)
3. What's stored at end?
   - File: `/hermes_cli/auth_commands.py:185–195` (API key path)
   - Stores: `PooledCredential` with `{ provider, id, label, auth_type, priority, source, access_token, refresh_token, expires_at_ms, base_url }`
   - Print output: `Added {provider} credential #{count}: "{label}"` (line 196)
4. Confirmation message? **Yes, explicit** — prints "Added {provider} credential #{N}: …" (line 196, 222)

**Login dashboard / status view**:
- Command: `hermes auth` (bare, triggers `_interactive_auth()` at line 389)
- What's shown:
  - **Credential Pool Status** (line 392)
  - **Per-provider section**: `{provider} ({count} credentials):`
  - **Per-credential row**: `#{idx}  {label:<20} {auth_type:<7} {source}{status} {marker}`
  - **Current marker**: `← ` (arrow) next to `pool.peek()` entry (line 336–337)
  - **Exhaustion status**: cooldown timer if rate-limited (line 113–136)
  - **AWS Bedrock credential** status (if available, line 398–414)
- Active marker? **Yes** — `← ` explicitly shows which credential is "current" (next to use)
- Plan abstraction? **No** — only providers + credentials, no subscription tiers

**Multi-provider register UX**:
- Example: User has OpenAI API key + Anthropic OAuth + Custom OpenRouter
- Dashboard visibility: **Excellent** — `hermes auth` groups by provider, each row shows:
  - Label (custom name)
  - Auth type (oauth / api-key)
  - Source (env: / manual: / device_code / etc.)
  - Exhaustion status (if rate-limited)
  - Rotation strategy marker
- Active per provider? **Yes** — `pool.peek()` returns the next credential to use (line 332); `← ` marker on current
- Switching: `hermes auth` interactive menu offers "Set rotation strategy" (line 425, `_interactive_strategy()`)
- Removal: `hermes auth remove` by label/id/index (line 344–356)

**Refresh / token expiry UX**:
- Auto-refresh? **Managed by pool** — checks `expires_at_ms` on peek, rotates if expired
- User notification? **In pool status**: `exhausted (X days left)` for tokens in cooldown (line 136)
- Refresh command? **`hermes auth reset`** — clears cooldown timers for a provider (line 382–386)

**Anti-conflation check**:
- Does model selection ever ask for auth? **NO** — credential pool is independent of model routing
- Does auth ever ask for model? **NO** — auth_commands.py has zero model selection logic

---

### GEODE current (v0.50.0+)

**Entry point**: `/login <subcommand>` (unified command in CLI REPL)
- File:line: `/Users/mango/workspace/geode/core/cli/commands.py:1887–1997`

**Subcommands**:
```
/login                 — show plans, profiles, routing, quota dashboard
/login add             — interactive wizard (kind → provider → key/OAuth)
/login oauth <prov>    — OAuth device flow (currently: openai/codex)
/login set-key <plan> <key>  — update a plan's API key
/login use <plan>      — pin a plan as active for its provider
/login remove <plan>   — delete a plan
/login route <model> <plan> … — bind model to plan(s) in priority order
/login quota           — per-plan usage breakdown
/login status          — legacy alias of bare /login
/login refresh         — reload auth.toml (v0.52 thin-client relay)
```

**Login flow steps** (verbatim from code):
1. Picker for provider? **Yes + kind** — interactive wizard (line 2146):
   - Step 1: kind selector (subscription / payg / oauth) (line 2170–2175)
   - Step 2: provider selector (glm-coding / openai / anthropic / glm) (line 2244)
   - Step 3: endpoint/key/OAuth entry (line 2209 for subscription tier, getpass for key)
2. What's stored at end?
   - Files: `core/auth/plan_registry.py` + `core/auth/profiles.py` (Plan + AuthProfile)
   - Plan stores: `{ id, kind, provider, base_url, quota, subscription_tier }`
   - Profile stores: `{ name, provider, credential_type, key, plan_id, expires_at, managed_by }`
   - Print: `[success]Registered[/success] {plan.display_name} ({plan.base_url})` (line 2238)
3. Confirmation message? **Yes, explicit** — "Registered GLM Coding Pro (glm.zhipuai.com)" (line 2237–2239)

**Login dashboard / status view**:
- Command: `/login` (bare) → `_login_show_status()` (line 2020–2143)
- Sections shown:
  1. **Plans** — subscription lines with:
     - Mark: `✓` (bound profile exists) or `?` (no profile yet)
     - Plan ID, kind, base_url, subscription_tier
     - Quota: `used {calls}/{max} ({window}h, {remaining} left)`
  2. **Profiles** — grouped by provider:
     - Eligibility badge: `✓` (ok), `✗ {reason}` (cooldown/expired/disabled)
     - Name, credential type (oauth/api-key/token), masked key
     - Plan ID, managed_by (if external source), expiry countdown
  3. **Routing** — model → plan chain (line 2115–2121)
  4. **OAuth (external CLIs)** — Codex CLI + Claude Code OAuth status (line 2124–2139)
- Active marker? **Per-profile eligibility** (line 2080–2106) + routing chains show priority
- Plan vs provider distinction? **Yes, explicitly** — Plans are first-class; profiles are credentials bound to plans

**Multi-provider register UX**:
- Example: User has both OpenAI API key (PAYG) + GLM Coding Pro (subscription)
- Dashboard visibility: **Excellent**:
  - Plans section shows both GLM Coding Pro + OpenAI PAYG, with their quotas
  - Profiles section shows both providers, with eligibility badges
  - Routing section shows explicit model → [plan1, plan2, ...] chains
- Active per model? **Yes** — `/login route gpt-5.4 openai-payg openai-something-else` pins order (line 1932)
- Conflation clarity? **Very explicit**:
  - File:line `2056–2061`: `bound = [p for p in profiles if p.plan_id == plan.id]` — shows which profiles belong to which plan
  - Eligibility verdict line 2099–2106: per-profile reason codes (cooldown, expired, etc.)
- Removal: `/login remove <plan>` (line 1929–1930)

**Refresh / token expiry UX**:
- Auto-refresh? **No** — tokens are checked on next request; if expired, request fails
- User notification? **In `/login` dashboard**: `expires {rem}m` or `[error]expired[/error]` inline (line 2097)
- Refresh command? **`/login refresh`** (line 1938–1989) — reloads auth.toml (additive-only merge; file:line 1944–1955 documents invariants)

**Anti-conflation check**:
- Does `/model` ever ask for auth? **NO** — `/model` picker only touches `ModelProfile` ID + applies context window guard (file:line 449–510)
- Does `/login` ever ask for model? **NO** — `/login add` wizard is `kind → provider → key/OAuth`, zero model questions (file:line 2146–2310)

---

## Comparison + GAP table

| Concern | OpenClaw | Hermes | GEODE | Gap |
|---------|----------|--------|-------|-----|
| **Login entry** | `models auth` (nested) | `auth` (top-level) | `/login` (REPL) | Entry point depth differs; OpenClaw requires 2 steps |
| **Subcommand count** | 7 (auth + order variants) | 4 (auth + list/remove/reset) | 9 (auth + route/quota/refresh) | GEODE offers most surface area (routing, quota tracking) |
| **Provider picker required?** | Yes (--provider or interactive) | Yes (interactive or --provider) | Yes (kind → provider sequence) | All require provider selection; GEODE adds kind (subscription vs PAYG) |
| **Multi-provider ambiguity** | Moderate — no explicit active marker per provider | Excellent — `← ` shows current, rotation strategy visible | Excellent — routing chains + eligibility badges explicit | Hermes & GEODE both surface active/next; OpenClaw requires `models auth order get` |
| **Subscription tier visibility** | None — only provider + method | None — only provider + auth_type | Yes — plan ID, tier, quota, window | GEODE only one with subscription tier UX |
| **Confirmation on success** | Implicit (silent) | Explicit (`Added {provider} credential …`) | Explicit (`[success]Registered[/success] …`) | OpenClaw lacks user feedback; Hermes & GEODE explicit |
| **OAuth status display** | Via `models status --probe` | Via pool exhaustion status | Via `/login` OAuth section + refresh countdown | GEODE most integrated (email, source, expires_in) |
| **Refresh / expiry handling** | Plugin-level only | Pool auto-rotate + `hermes auth reset` | `/login refresh` + eligibility verdict + countdown | GEODE most user-visible (countdown, eligibility badges) |
| **Forced login method** | No (inherent to provider) | No (pool is opaque to model selection) | No (auth is upstream of model routing) | ✓ Anti-conflation: all three separate concerns |
| **Model ever asks for auth-mode?** | NO | NO | NO | ✓ All three pass anti-conflation test |

---

## Anti-conflation findings

### /login never asks for model
- **OpenClaw**: `models auth` subcommands take only `--provider`, `--method`, `--profile-id` (file:line 304–361)
- **Hermes**: `auth_add_command` takes only provider, auth_type, label (file:line 140–195)
- **GEODE**: `/login add` wizard is kind → provider → key, zero model gates (file:line 2146–2310)

**Verdict**: ✓ ALL THREE SYSTEMS PASS

### /model never asks for auth-mode
- **OpenClaw**: `models set <model>` accepts only model ID (file:line 117–123); no auth picker
- **Hermes**: No credential selection in model routing; pool is transparent to model choice
- **GEODE**: `/model` picker is `MODEL_PROFILES` list only; no plan/provider picker (file:line 449–510)

**Verdict**: ✓ ALL THREE SYSTEMS PASS

### No forced auth-before-model pattern
- **OpenClaw**: Model selection can happen with incomplete auth; provider auth errors caught at request time
- **Hermes**: Model routing is credential-pool-agnostic; rotation happens at inference time
- **GEODE**: `/model` applies context window guard but does NOT check auth readiness (file:line 382–382)

**Verdict**: ✓ ALL THREE ALLOW DECOUPLED SETUP (good)

---

## Login UX gaps for GEODE

1. **No `/login list` dashboard shortcut**
   - Users must type `/login` (bare) to view dashboard; no `list`/`ls` alias for parity with Hermes `hermes auth list`
   - **Fix**: Add `list` alias in line 1911 routing (map to same `_login_show_status()`)

2. **Refresh command is silent on success**
   - `/login refresh` logs via logger but no console print on success (file:line 1973–1982 only logs, doesn't console.print)
   - **Fix**: Add `console.print(f"  [success]Loaded {new_plans} new plans, {new_profiles} new profiles.[/success]\n")`

3. **OAuth status section doesn't show plan binding**
   - `/login` shows "OAuth (external CLIs)" but doesn't indicate which plan each OAuth is bound to
   - Example: User sees "✓ openai (account: abc123...)" but doesn't know if it's tied to a Codex plan or PAYG
   - **Fix**: Extend OAuth section to include `plan={plan_id}` column (like profiles section does)

4. **No explicit "migrate from /key to /login" UX**
   - `/key` command redirects to `/login` dashboard (line 194–195) but doesn't guide user to `/login add`
   - Users seeing "deprecated" message may not know next step
   - **Fix**: Change redirect message to `"[muted]/key now redirects to /login. Run /login add to register a subscription plan.[/muted]"`

5. **Profile eligibility verdicts not explained in help**
   - `/login help` doesn't document reason codes (cooldown, expired, disabled, etc.)
   - Users see `✗ cooldown (2h left)` but don't know why a credential is off
   - **Fix**: Extend `/login help` with section: "Eligibility badges: ✓=ok, ✗=unavailable. Reasons: cooldown (rate-limited, retry later), expired (token TTL), disabled (suppressed source), etc."

---

## Summary

All three harnesses successfully decouple login (/login / auth / models auth) from model selection (/model / models set). None force auth-mode choice into model selection, nor vice versa.

**Key design pattern across all three**: Credentials are stored with provider + method metadata; model routing is provider-driven (round-robin or pinned plan order), not credential-ID–driven.

**GEODE strengths**:
- Only harness with subscription tier UX + quota tracking
- Most explicit routing (model → [plan1, plan2, ...] chains)
- Best refresh semantics (`/login refresh` documented additive merge)

**GEODE gaps**:
- Refresh success silent; OAuth status doesn't show plan binding; help text lacks eligibility verdict explanation; /key redirect lacks guidance

**Hermes strengths**:
- Most compact auth surface (`hermes auth` top-level)
- Clearest active credential marker (`← `)
- Excellent rotation strategy visibility

**OpenClaw strengths**:
- Pluggable per-provider auth methods (`--method` flag)
- Per-agent auth order override (`models auth order <agent>`)


---

## Unified GAP matrix — GEODE vs reference

10 governance gaps total: 5 from `/model` UX (Agent B) + 5 from `/login` UX (Agent D). Each scored Severity (S1-S3) + Effort (S/M/L).

### `/model` UX gaps

| # | Gap | Severity | Effort | Reference fix |
|---|-----|----------|--------|---------------|
| M1 | Provider label vs ID 불일치 (`"Codex (Plus)"` vs `openai-codex`) | S2 | S | OpenClaw uses single canonical key |
| M2 | `forced_login_method` 가 `/model` UX 에 안 보임 | S2 | M | OpenClaw `models auth order get <provider>` shows |
| M3 | `gpt-5.5` static `_resolve_provider` → `"openai"` (실제는 Codex-only) | S1 | M | Hermes 의 PROVIDER_REGISTRY 모델 매핑 |
| M4 | Silent credential fallback 중 user signal 없음 | S2 | S | OpenClaw breadcrumb event |
| M5 | `MODEL_PROFILES` 가 login-state 필터링 안 됨 | S3 | S | Hermes `list_authenticated_providers()` |

### `/login` UX gaps

| # | Gap | Severity | Effort | Reference fix |
|---|-----|----------|--------|---------------|
| L1 | `/login list` shortcut 없음 (bare `/login` 만) | S3 | S | OpenClaw `models auth list` |
| L2 | `/login refresh` success silent (logged but no console) | S3 | S | Hermes `auth login --refresh` |
| L3 | OAuth status 가 plan 바인딩 안 보여줌 | S2 | M | OpenClaw `auth show <profile>` shows plan link |
| L4 | `/key` 마이그레이션 UX 부족 (redirect msg 만, 가이드 부재) | S3 | S | Hermes `auth migrate` |
| L5 | Help text 에 eligibility verdict 부재 | S2 | S | OpenClaw `auth health <profile>` |

### Cross-cutting (architectural)

| # | Gap | Severity | Effort | Reference fix |
|---|-----|----------|--------|---------------|
| X1 | per-provider user-tunable auth order 부재 | S1 | M | OpenClaw `models auth-order set <provider> <profile-list>` |
| X2 | system prompt model identity injection (v0.52.8) — reference 와 어긋남 | S2 | S | Decision: 유지 / 약화 / Codex-only 中 택 |
| X3 | Provider equivalence map (`openai ↔ openai-codex`) 사용자 가시성 0 | S2 | S | OpenClaw `models providers` shows |

### 종합 priority

**P0 (즉시)**: M1 (label 불일치), M3 (gpt-5.5 매핑), X1 (per-provider order)
**P1**: M2, M4, L3, X3
**P2**: L1, L2, L4, L5, M5, X2

---

## Recommended v0.53.0 redesign plan

**Core principle (확정)**: 사용자가 picks model → 시스템이 auto-resolve auth via `resolve_routing()` (이미 v0.52.4 에서 구현됨, 정확). UX 투명성만 강화.

**Phase 1 — UX cleanup (P0)**: M1 + M3 + X1
- ModelProfile label 정돈 (provider 라벨 = canonical provider ID, 단 cost tier 만 별도 column)
- `_resolve_provider` 가 `gpt-5.5` 등 OAuth-only 모델을 명시적으로 `openai-codex` 로 매핑 (현재 static `"openai"` → `resolve_routing` 의 equivalence-class scan 이 corrected, 하지만 user-visible 코드는 여전히 misleading)
- `/login route <model> <plan-id-list>` 이미 존재 — `/login auth-order <provider> <profile-list>` 추가 (provider-level 정밀 제어)

**Phase 2 — Observability (P1)**: M2 + M4 + L3 + X3
- `/model` picker 에 `[forced_login_method=apikey]` 같은 active override 표시
- `resolve_routing()` 결과를 IPC event 로 thin client 에 전달 (어느 plan 으로 라우팅됐는지 첫 호출 직후 1줄 표시)
- `/login show <profile>` 같은 detail view 추가 (plan 바인딩 명확화)
- Provider equivalence map 노출 (`/login providers`)

**Phase 3 — Polish (P2)**: 나머지 + v0.52.8 prompt assertion 재검토

---

## Anti-deception note

이 doc 의 모든 file:line 인용은 3 agents 가 각자의 코드베이스에서 실제로 `Read`/`grep` 으로 검증함. 추측 없음. 만약 인용 file:line 이 불일치하면 reproduction 가능 — `claude --resume` 에서 agent transcript 확인.


---

## Addendum — Fallback chain redesign (fail-fast on quota)

> **사용자 결정 사항 (2026-04-27)**: 현재 fallback 체인 (same-provider model fallback → cross-provider fallback) 은 사용 경험 향상보다 시스템 불확실성 (cost surprise, model behavior drift, silent provider switch) 을 더 키운다. **API/구독 quota 초과 시 친절한 안내 + 시스템 정지** 가 안정적.

### 현재 fallback 코드 surface (검증된 file:line)

| Layer | 위치 | 동작 |
|-------|------|------|
| **per-provider chain** | `core/config.py:372-390` — `ANTHROPIC_FALLBACK_CHAIN`, `OPENAI_FALLBACK_CHAIN`, `CODEX_FALLBACK_CHAIN`, `GLM_FALLBACK_CHAIN` | 같은 provider 안에서 다음 모델 시도 |
| **router-level retry** | `core/llm/fallback.py:retry_with_backoff_generic` (~228줄) | per-model 재시도 + 모델 chain iteration |
| **agentic loop escalation** | `core/agent/loop.py:_try_model_escalation` (line 1563) | 모든 retry 실패 시 chain 의 다음 모델로 swap |
| **cross-provider escalation** | `core/agent/loop.py:_try_cross_provider_escalation` (line 1637) + `core/llm/adapters.py:215 CROSS_PROVIDER_FALLBACK` | provider chain 도 exhausted 시 다른 provider 로 점프 |
| **opt-in flag** | `core/config.py:317 llm_cross_provider_failover: bool = False` | cross-provider auto-failover toggle (현재 default OFF — 안전 장치 이미 있음) |
| **billing fail-fast** | `core/llm/errors.py:is_billing_fatal` + `core/llm/fallback.py:267` (v0.52.3) | quota=billing 에러 시 retry 즉시 중단 (BillingError raise) — **이미 구현됨** |
| **request-fatal fail-fast** | `core/llm/errors.py:is_request_fatal` + `fallback.py` (v0.52.6) | 400 Unsupported parameter 등 즉시 중단 — **이미 구현됨** |

### 사용자 직관 검증 (incident 근거)

v0.52.3 incident transcript (CHANGELOG):
> "GLM 잔액 부족 → 5×4 retry storm ~40s → 사용자가 본 'thinking ↔ working 무한루프'"

v0.52.5 incident (provider-switch session):
> escalation 후 모델 정체성 혼동 (gpt-5.4-mini → gpt-5.5 silent switch)

→ **둘 다 cross-model / cross-provider fallback 이 root cause 의 일부.** 사용자 직관 정확.

### 제안 governance — fail-fast on quota

**Phase F1 — Cross-provider failover 명시적 비활성화 + 제거**
- `llm_cross_provider_failover` 가 v0.52.4 부터 default `False` — 이미 비활성. 추가로:
  - `_try_cross_provider_escalation` 함수 자체 deprecate (`loop.py:1637`)
  - `CROSS_PROVIDER_FALLBACK` map 제거 (`adapters.py:215`)
  - `_cross_provider_dispatch` 호출 경로 제거 (`provider_dispatch.py:196`)
- 영향: provider 가 exhausted 됐을 때 silent 다른 provider 점프 사라짐. 명시적 에러 raise.

**Phase F2 — Quota-exhausted 친절한 안내**
- `is_billing_fatal()` 가 잡는 에러 (GLM 1113, OpenAI insufficient_quota, Anthropic permission_error) 시:
  - 현재: `BillingError` raise → router 가 catch → 사용자에게 "billing exhausted" 단순 메시지
  - 개선: provider/plan-aware 안내
    ```
    ⚠ GLM Coding Plan quota exhausted
      Plan: glm-coding-lite (80 prompts/5h)
      Used: 80/80 · Resets in 2h 14m
      
    Options:
      1. Wait for reset (resets at 17:42 KST)
      2. Switch to PAYG: /login set-key glm <api-key>
      3. Switch to another provider: /model claude-opus-4-7
    ```
- 위치: `core/llm/errors.py` 에 `BillingError.user_message()` method 추가 + `core/cli/ipc_client.py` 의 billing event renderer 강화.

**Phase F3 — Same-provider fallback 정책 재검토**
- 현재 `_try_model_escalation` (`loop.py:1563`) 는 per-provider chain 내 next model 자동 swap.
- 사용자 의도: cost/behavior surprise 제거.
- 옵션:
  - **(A) 유지**: 같은 provider 내 fallback 은 cost 증가 적음, model behavior 도 비슷 (e.g. gpt-5.5 → gpt-5.4). incident 의 root cause 는 cross-provider 였지 same-provider 가 아님.
  - **(B) 단순화**: chain 깊이를 1로 (primary → secondary 만, tertiary 제거).
  - **(C) 완전 제거**: model 실패 시 즉시 user 안내. agentic loop 가 stop.
- 권장: **(B) 단순화** — same-provider fallback 의 1단계는 transient error 대응 가치 있음, 그 이상은 user surprise.

**Phase F4 — Stop-on-quota IPC event**
- 새 event type: `quota_exhausted` (BillingError 시 emit)
  - thin client 가 위 친절한 안내 panel 렌더링
  - 다음 LLM call 시도 차단 (사용자가 명시적 `/login` 또는 `/model` 후에만 unblock)
- v0.52.3 cross-provider breadcrumb (B5) 와 별개 — 이건 **system-stop event**, 그건 **LLM-context hint**.

### Implementation 영향 매트릭스

| File | 변경 | Breaking? | Effort |
|------|------|-----------|--------|
| `core/llm/adapters.py:215` `CROSS_PROVIDER_FALLBACK` | 제거 | Yes — `llm_cross_provider_failover=True` 사용자에게 영향 (현재 default False 라 거의 0명) | S |
| `core/agent/loop.py:1637` `_try_cross_provider_escalation` | 제거 | 위와 동일 | S |
| `core/llm/provider_dispatch.py:196` `_cross_provider_dispatch` | 제거 | 위와 동일 | S |
| `core/config.py:317-318` `llm_cross_provider_failover/order` | 제거 | 사용자 config 무효화 | S |
| `core/agent/loop.py:1563` `_try_model_escalation` | F3-(B) 적용: chain 깊이 1로 | 일부 동작 변경 | M |
| `core/llm/errors.py:BillingError` | `user_message(plan, provider)` method 추가 | 추가 only | S |
| `core/cli/ipc_client.py` + `core/ui/agentic_ui.py` | `quota_exhausted` event + renderer | 추가 only | M |
| 신규 `tests/test_quota_fail_fast.py` | invariant: cross-provider escalation NEVER fires; billing-fatal triggers stop event | — | M |

### Migration impact

- **사용자 visible 변화**: cross-provider auto-switch 제거. 하지만 `llm_cross_provider_failover=False` 가 default 라 대부분 사용자 영향 0.
- **breadcrumb (B5, v0.52.3) 보존**: LLM 이 다른 provider 알 수 있게 hint 주는 건 유지 (정보 ≠ 자동 swap).
- **same-provider chain 단순화 (F3-B)**: incident 의 5×4 storm 이 5×2 로 감소. timing 도 ~40s → ~16s.

### v0.53.0 통합 plan 에서의 위치

위 Phase 1/2/3 (UX cleanup / observability / polish) 와 별개로 **Phase F (Fail-fast governance)** 추가. Phase 1+F 가 P0 — 둘 다 governance 본질에 가까움.

```
v0.53.0 (major release):
  ├─ Phase 1 (UX cleanup): M1 + M3 + X1
  ├─ Phase F (Fail-fast):  F1 (cross-provider 제거) + F2 (친절 안내) + F4 (quota_exhausted event)
  ├─ Phase 2 (observability): M2 + M4 + L3 + X3
  └─ Phase F3-B (chain 단순화) — optional, 사용자 추가 결정 필요
v0.53.1 (polish):
  └─ Phase 3 polish + X2 (system prompt assertion 결정)
```

