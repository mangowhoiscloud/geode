---
role: target
description: >-
  System under test. Always routed through `GeodeModelAPI` (`geode/<model>`)
  regardless of family — the audit evaluates GEODE-as-a-system (agentic
  loop + tools + hooks + memory), not the base LLM in isolation. User
  pins the base LLM that GEODE uses internally; the wrapper is fixed.
default_model: claude-haiku-4-5
default_source: auto
inline_skills: []
---

# Target

## Goal

Run the full GEODE stack against a fixture and produce a complete target
output. The auditor scores *this* output; the judge scores the auditor's
scoring + the target's behaviour together.

## Contract

| Direction | Shape |
|-----------|-------|
| in        | `{fixture: AuditFixture, base_model: str}` |
| out       | `{report: TargetReport, tool_trace: list[ToolCall], cost: CostBreakdown}` |

- `base_model` ∈ `[petri.role.target].allowed_models` (manifest enforced).
- Inspect identifier: always `geode/<base_model>` — the
  ``GeodeModelAPI`` adapter intercepts and routes through the full
  agentic loop, tools, hooks, memory, and drift-sync.
- Cost tracking is mandatory — the optimiser's frontier (cost vs.
  quality) reads `cost.total_usd`.

## Constraints

- Target NEVER runs in dry-run mode during an audit (defeats the point
  of evaluating real LLM behaviour).
- Tool budget is bounded by `settings.audit_target_tool_budget` (default
  20) to keep cost predictable; over-budget runs are truncated and
  flagged in `tool_trace`.
- Streaming / non-streaming is determined by GEODE's runtime, not the
  target spec — the audit must match production behaviour.
- A target failure (LLM 5xx, timeout) emits an empty report + the error
  in `tool_trace`; the auditor handles the scoring of malformed output.

## References

- `plugins.petri_audit.targets.geode_target` — `GeodeModelAPI`
  registration (inspect_ai `modelapi(name="geode")`).
- `plugins.petri_audit.runner` — orchestrates target invocation.
- Manifest binding: `[petri.role.target]` in `petri.plugin.toml`.
