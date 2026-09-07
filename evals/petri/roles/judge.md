---
role: judge
description: >-
  Petri transcript evaluator. Applies the selected judge-dimension rubric to
  the auditor-target interaction; results are recorded in the inspect_ai eval
  archive. GEODE reporting and promotion consume that measurement evidence.
default_model: claude-sonnet-4-6
default_source: auto
inline_skills:
  - karpathy-patterns
---

# Judge

## Goal

Evaluate the auditor-target transcript against the selected judge dimensions.
The native Petri task owns judge prompting and score emission to the `.eval`
archive. This role document does not define a second judge or score schema.

## Contract

- `runner.build_command()` binds the judge model and resolves the selected
  dimension set through `judge_dims.resolve_dim_set()`.
- The selected rubric and native scorer own score meaning and scale. Do not
  reinterpret the output as an auditor score divided by 100, or assume every
  Inspect score is a scalar in `[0, 1]`.
- Preserve the archive, per-dimension evidence, and missing measurements.
  `evolve.scaffold_search.fitness` and `gate` own aggregation and promotion;
  the judge result alone is not a promotion decision.

## Constraints

- Keep the selected rubric and run configuration fixed during comparisons;
  do not add ad-hoc criteria or undocumented metadata fields.
- The ordinary audit surfaces same-provider bias in its report.
  `optimize._check_provider_split()` enforces a distinct judge/generator
  constraint only for that optimizer; it is not a universal audit setup rule.
- Treat unavailable evidence and evaluation failures separately from measured
  behavior. Do not claim a score or certainty absent from the archive.

## References

- `evals.petri.runner` — judge binding, task assembly, and bias reporting.
- `evals.petri.judge_dims` — rubric selection and dimension definitions.
- Manifest binding: `[petri.role.judge]` in `petri.plugin.toml`.
