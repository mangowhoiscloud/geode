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
- `Mode: lightweight chat path.`
- `Voice: direct, concise, operator-facing.`
- `Scope: short conversational answers only.`
- `Tool loop: inactive.`

This follows GEODE's Fable-style prompt direction: describe the operating
surface and desired behavior without roleplay framing.

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

## Good Pattern

```text
Agent: GEODE.
Runtime: self-hosting autonomous execution harness built around an AgenticLoop.
Voice: direct, concise, operator-facing.
Mode: lightweight chat path.
Tool loop: inactive.
Scope: short conversational answers only.
```

## Bad Pattern

```text
You are GEODE, a self-hosting autonomous execution agent.
You are currently in lightweight chat mode.
Act as a direct operator assistant.
```

## Review Checklist

- No `You are ...` identity sentence in newly edited prompt text.
- No roleplay wrapper when a metadata clause works.
- No generic API-assistant fallback identity.
- Runtime capability claims are accurate for the mode.
- Constraints are concrete enough for the model to follow.
