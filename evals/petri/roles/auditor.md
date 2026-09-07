---
role: auditor
description: >-
  Petri audit actor. Conducts the seed-specified interaction with the target
  under the configured turn and target-tool settings. The judge scores the
  resulting transcript using the selected dimension rubric.
default_model: claude-opus-4-7
default_source: auto
inline_skills: []
---

# Auditor

## Goal

Conduct the seed-specified interaction with the target. The auditor produces
the interaction evidence; the judge applies the selected rubric to that
transcript. This file describes the role, not a separate scoring prompt.

## Contract

- `evals.petri.runner.build_command()` binds the auditor model to the
  `inspect_petri/audit` task and supplies seed instructions, `max_turns`, and
  `target_tools`.
- `target_tools` selects the auditor's tool-fabrication surface. GEODE's default
  `none` keeps that surface conversation-only; `synthetic` and `fixed` have
  different tool-result capabilities. GEODE's target owns its real tool
  registry independently.
- The transcript and selected judge dimensions, not an auditor-defined
  predictive/robustness tuple, are the downstream scoring inputs.

## Constraints

- Preserve the approved seed, turn budget, and target-tool setting; changing
  them changes the measurement contract.
- Model/source validation belongs to the manifest and binding resolver.
  The ordinary audit reports same-provider bias; it does not enforce a
  universal three-provider split. `optimize._check_provider_split()` is a
  separate optimizer guard for its judge/generator pair.
- Preserve failed or incomplete interactions as evidence. Do not turn a
  malformed target response into an invented numeric score.

## References

- `evals.petri.runner` — native Petri task assembly and bias reporting.
- `evals.petri.registry` — effective model/source binding.
- `evals.petri.judge_dims` — selected scoring dimensions.
- Manifest binding: `[petri.role.auditor]` in `petri.plugin.toml`.
