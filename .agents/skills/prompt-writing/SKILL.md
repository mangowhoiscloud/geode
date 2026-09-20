---
name: prompt-writing
description: GEODE prompt-writing standards. Use when creating or editing runtime prompts, system prompts, tool/developer instructions, model-facing identity text, prompt templates, or scaffold rules that affect model behavior; especially when avoiding identity assertions such as "You are ...".
---

# Prompt Writing

Use this skill before editing model-facing prompt text in GEODE.

## Core Standard

Write prompts as metadata, behavior contracts, and task constraints. Avoid direct
identity assertions such as:

- `You are GEODE`
- `You are a helpful assistant`
- `Act as ...`
- `You are currently in ...`

Prefer declarative clauses:

- `Agent: GEODE.`
- `Runtime: self-hosting autonomous execution harness.`
- `Mode: task execution.`
- `Voice: direct, concise, operator-facing.`
- `Scope: the user's authorized task.`
- `Completion: report verified results and unresolved limits.`

This is GEODE's local style: describe the operating surface and desired
behavior without roleplay framing. It is not a vendor prohibition on role
prompts. Claude's [official guidance](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
uses clear instructions and descriptive XML boundaries, and also permits role
framing. Keep authored GEODE prompts in English; do not translate user content
or data to satisfy that convention.

## Workflow

1. Identify whether the text is model-facing.
2. If model-facing, scan for direct identity assertions and second-person role
   assignments.
3. Rewrite role text as metadata clauses or behavioral constraints.
4. Keep mode limitations after identity/metadata clauses so constraints override
   capability descriptions.
5. Preserve explicit opt-outs such as `GEODE_PERSONA=off` when present.
6. If editing `core/llm/prompts/`, update the pinned prompt hashes in the same
   commit.

## Assembly and model contracts

- Trace the authored text through assembly, context reduction, and the actual
  adapter request. A loader test alone does not prove the model receives it.
- Keep common conduct in the shared suffix and task procedures in the relevant
  skill. Avoid duplicate provider rankings, remembered model tables, or capability
  claims not supplied by the active runtime. Missing context is not permission
  to assume CLI access, a sandbox, or account entitlement.
- Separate instructions from observations with descriptive XML boundaries;
  escape interpolated data leaves, not trusted authored markup. XML is formatting,
  not an authorization or prompt-injection defense by itself. Preserve admitted
  skill guidance until the next request can consume it.
- Verify each changed mode (normal, persona-off, audit, override) and provider
  contract at its actual entry point. Check role placement, refusal semantics,
  structured-output admission, and replay fields when those boundaries change.
  Use the [model-onboarding skill](../model-onboarding/SKILL.md) for source-specific
  lifecycle and parameter support; do not silently substitute another billing route.
- State the desired result, evidence requirements, and stopping boundary concisely.
  Remove obsolete prohibitions before adding instructions. Use complete sentences;
  neither verbosity nor terse fragments demonstrate correctness.

Recheck the model-specific [Astra prompting guidance](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra#prompting-best-practices)
and [Fable prompting guidance](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5)
when compatibility is in scope. Apply supported contracts, not every example
prompt verbatim. Offline shape tests do not establish live model compliance.

## Good Pattern

```text
Agent: GEODE.
Runtime: self-hosting autonomous execution harness built around an AgenticLoop.
Voice: direct, concise, operator-facing.
Mode: task execution.
Scope: the user's authorized task.
Completion: report verified results and unresolved limits.
```

## Bad Pattern

```text
You are GEODE, a self-hosting autonomous execution agent.
You are currently in task execution mode.
Act as a direct operator assistant.
```

## Review Checklist

- No `You are ...` identity sentence in newly edited prompt text.
- No roleplay wrapper when a metadata clause works.
- No generic API-assistant fallback identity.
- Runtime capability claims are accurate for the mode.
- Constraints are concrete enough for the model to follow.
