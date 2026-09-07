---
role: target
description: >-
  System under test. Always routed through `GeodeModelAPI` (`geode/<model>`)
  regardless of provider — the audit evaluates GEODE-as-a-system (agentic
  loop + tools + hooks + memory), not the base LLM in isolation. The run
  selects the base model and policy sources that reach the runtime.
default_model: claude-haiku-4-5
default_source: auto
inline_skills: []
---

# Target

## Goal

Run GEODE against the audit conversation and return its response to Petri.
The auditor conducts the interaction; the judge evaluates the transcript.

## Contract

- `GeodeModelAPI.generate(input, tools, tool_choice, config)` returns an
  Inspect `ModelOutput`, with assistant content and `ModelUsage` built from
  the runtime result. There is no separate `TargetReport`/`tool_trace` tuple.
- The `geode/<base_model>` adapter converts messages, runs
  `AgenticLoop.arun()`, and maps token, cache, reasoning, and cost fields when
  available. Zero-valued usage after a failure is not proof of a free or
  successful run.
- GEODE owns its tool registry; this adapter ignores Inspect's `tools` and
  `tool_choice` inputs. The audit's default `target_tools="none"` avoids
  auditor-fabricated tool results.
- The Petri picker validates its allowed models through the manifest/binding
  resolver. Direct native-runtime model entry follows `_default_geode_runner()`
  and its credential checks. A caller-pinned model disables settings drift.

## Constraints

- Live execution requires explicit authorization. A dry-run or forced-dry-run
  readiness state is plumbing evidence, not a measured model result.
- The outer Petri `max_turns` and runtime configuration own their respective
  execution bounds. Profile/tool policy and `audit_mode` own capability
  restrictions; this document does not introduce a separate fixed tool cap.
- Preserve runtime diagnostics, process errors, and `.eval` evidence.
  `generate()` does not promise to convert every failure into an empty report;
  an adapter stop marker or returned text alone does not prove task success.

## References

- `evals.petri.geode_target` — `GeodeModelAPI`
  registration (inspect_ai `modelapi(name="geode")`).
- `evals.petri.runner` — orchestrates target invocation.
- Manifest binding: `[petri.role.target]` in `petri.plugin.toml`.
