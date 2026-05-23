# Adapter wrap port plan — petri_audit + autoresearch (Path B)

> 2026-05-23. Companion to PRs *I.* (petri_audit) and *J.* (autoresearch).
> Grounded against `~/workspace/paperclip` + `plugins/petri_audit/` +
> `autoresearch/train.py` before drafting.

## Why Path B (and not Path A)

`paperclip` 's `ServerAdapterModule` (TS interface in
`packages/adapter-utils/src/types.ts:349`) is a **subprocess-CLI
invocation contract** — it has no wire-shape translation layer because
the adapter binary owns the conversation translation internally.

`core.llm.adapters.LLMAdapter` (Python `Protocol` in
`core/llm/adapters/base.py`) is a richer contract — it speaks
adapter-neutral `Message`/`AdapterCallRequest` and each built-in (
`anthropic-payg/oauth/claude-cli`, `openai-payg/codex-oauth/codex-cli`,
`glm-payg/coding-plan`) translates to the provider wire shape.

`plugins/petri_audit/` already integrates with `inspect_ai`'s `ModelAPI`
abstraction. inspect_ai owns its own `ChatMessage` → provider-wire
translation (e.g. `openai_responses_inputs`, `openai_responses_chat_choices`).
Forcing `inspect_ai.ModelAPI.generate()` to delegate to
`LLMAdapter.acomplete(Message[])` would be **a lossy round-trip**: inspect's
`stop_reason`, `usage`, `tool_use_id`, `reasoning_summary` fields have no
1:1 mapping to `AdapterCallResult`.

So Path B: **collapse only the genuinely duplicated bits**, keep
`inspect_ai.ModelAPI` as the wire boundary for petri.

## Surfaces in scope

### Layer 1 — Codex OAuth header construction (4 duplicates)

```text
core/llm/providers/codex.py:119–124   # _get_codex_client (sync)
core/llm/providers/codex.py:147–152   # _get_async_codex_client
core/llm/adapters/_openai_common.py:60–63   # build_async_codex_client
plugins/petri_audit/codex_provider.py:198–201   # OpenAICodexAPI.__init__
```

All four build the same dict:

```python
account_id = _extract_account_id(token)
headers = {"originator": "codex_cli_rs"}
if account_id:
    headers["ChatGPT-Account-ID"] = account_id
```

**Collapse target**: `build_codex_oauth_headers(token: str) -> dict[str, str]`
in `core/llm/providers/codex.py`. Public function (no leading underscore).

### Layer 2 — Codex encrypted-reasoning replay

`core/llm/adapters/_openai_common.py:158`'s `build_codex_input(req)`
already implements the per-`Message.codex_reasoning_items` prepend pattern
that A2 introduced. petri's `OpenAICodexAPI.generate()` does its own
inspect_ai-flavoured `openai_responses_inputs(...)` call without that
prepend — so multi-turn petri Codex runs lose encrypted reasoning chains
across turns the same way the legacy `_legacy.py` path did pre-A2.

**Collapse target**: extract a standalone helper
`prepend_codex_reasoning(items: list[dict], reasoning_items: tuple[dict, ...])`
from `build_codex_input`. Petri's `generate()` can call this on the
inspect-converted input list before passing it to the OpenAI SDK. This is
**Step I.b** — a fast-follow PR after the header dedup lands and the
encrypted-reasoning regression test from A2 is verified to fire on the
petri path too.

### Layer 3 — credential / source resolution

`plugins/petri_audit/credential_source.py:23–148` resolves
`(provider, source)` through a manifest-driven 4-step chain (override →
settings → manifest.default → manifest.allowed). `core.llm.adapters.registry`
has its own `resolve_for(provider, source)` that does similar work for the
GEODE AgenticLoop.

**Collapse target**: petri's `credential_source.resolve_credential_source`
calls `core.llm.adapters.registry.adapter_health(provider, source)` to
augment its readiness probe — single SoT for "is this adapter available".
The manifest semantics (override → settings → default → allowed) stay in
petri because they encode petri-specific policy (rotation across allowed
sources mid-eval). This is **Step I.c** — fast-follow.

### Out of scope for step I

- inspect_ai ModelAPI subclasses (4 files, ~1200 LOC). Wire shape stays
  owned by inspect_ai. No `generate()` rewrites.
- `plugins/petri_audit/adapters/{http_anthropic,http_openai,http_zhipuai}.py`
  thin shims (90 LOC total). Their `register()` + `is_available()` contract
  is fine; they may delegate to `adapter_health` later but the structure
  stands.
- `plugins/petri_audit/manifest.py` TOML schema. petri's
  `[petri.adapter.<provider>.<source>]` entries serve picker UX (per-eval
  source rotation) that the LLMAdapter registry doesn't model.

## Step J — autoresearch (preview)

`autoresearch/train.py` (2365 LOC) hosts the self-improving outer-loop's
mutator runner. The LLM-call surface is narrower than petri:

```text
autoresearch/train.py:889   from core.llm.audit_lane import acquire_audit_lane
```

The audit lane already wraps an `LLMAdapter` (post-A1). What remains
duplicated:
- mutator runner subprocess invocation for `codex-cli` paths (bypasses
  the lane when CLI mode is selected)
- `_FALLBACK_SYSTEM_PROMPT` literal (PR-MINIMAL-2's drift invariant pin)

Step J ports the mutator runner subprocess branch onto
`core.llm.adapters.resolve_for(provider="openai", source="adapter")`
(== the `codex-cli` built-in) so the lane is the single LLM-call boundary
for autoresearch. The `_FALLBACK_SYSTEM_PROMPT` anchor invariant
(`tests/test_self_improving_minimal_2.py`) stays — it's prompt-layer,
not LLM-layer.

## Sequencing

| PR | Scope | LOC delta | Risk |
|----|-------|-----------|------|
| I.a | `build_codex_oauth_headers` helper, 4 call-site updates, unit test | +60 / -20 | low |
| I.b | `prepend_codex_reasoning` extract + petri `OpenAICodexAPI` wiring | +120 / -10 | medium (per-turn reasoning chain) |
| I.c | `credential_source` → `adapter_health` cross-check | +80 / -30 | low |
| J | autoresearch mutator runner → `resolve_for("openai","adapter")` | +200 / -150 | medium |

I.a lands first as a clean header dedup PR. I.b and I.c are fast-follow.
J is a separate sprint after step I lands on develop.

## Anti-deception checklist

For each PR:

- [ ] Every claim in CHANGELOG ("collapse", "single SoT", "per-turn replay")
      is grep-provable in the diff (CHANGELOG/PR-body parity rule)
- [ ] Codex MCP verify before push (`feedback_codex_mcp_verification`)
- [ ] No `# type: ignore` introduced
- [ ] Local gates mirror CI (`ruff format --check` + `lint-imports`)
- [ ] Tests added for each new helper
