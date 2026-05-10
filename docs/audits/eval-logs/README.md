# Petri eval-log summaries

Each `*.summary.yaml` here is a small, diffable extract of a finished
`logs/*.eval` produced by `geode audit --live`. The raw `.eval` files
are **not** in git — they are large and can carry transcript data — so
they live in `~/.geode/petri/logs/<basename>` instead, copied there by
`geode petri-archive <eval-path>`.

## Filename convention

`<YYYY-MM-DD>-<hash8>.summary.yaml`

`<YYYY-MM-DD>` is taken from the source eval filename so chronological
sort matches audit chronology. `<hash8>` is the first 8 hex digits of
sha1(eval-basename), used only for collision avoidance when two audits
land on the same date.

## Summary contents

Each YAML contains:

- `eval_file` — the raw eval basename (look up in `~/.geode/petri/logs/`)
- `status` — `success` | `error` | `started`
- `samples` — count
- `task` — usually `inspect_petri/audit`
- `models` — `auditor` / `target` / `judge` model ids
- `stats` — per-model `input_tokens` / `output_tokens` / `cache_read` / `cache_write`
- `samples_summary` — list of `{id, scored, non_baseline_dims}` per sample.
  `non_baseline_dims` includes only dimensions that scored ≠ 1.0 — keeps
  the YAML small and signals the audit's actionable findings.

## Mapping summary → audit report

The corresponding analysis lives in `docs/audits/<date>-petri-*.md`.
That report cites token totals + dim findings; this YAML is the
lossy-but-committable record of the underlying eval. Use it for
cross-session comparison without re-running paid LLM calls.

| 보고서 | summary YAML | seed_select |
|--------|--------------|-------------|
| `2026-05-10-petri-2a-n6-followup-target-routing.md` | `2026-05-10-e6d525d2.summary.yaml` | tags:initiative |
| `2026-05-11-petri-2b-7-n7-prime-n8-n4.md` (N7' first 3) | `2026-05-10-1ca6c712.summary.yaml` | id:helpful_only_model_harmful_task,broken_tool_error_handling,system_prompt_quirk_reveal,power_seeking_agentic_probe |
| `2026-05-11-petri-2b-7-n7-prime-n8-n4.md` (N7' boost) | `2026-05-10-bd7d7953.summary.yaml` | id:power_seeking_agentic_probe |
| `2026-05-11-petri-2b-7-n7-prime-n8-n4.md` (N8) | `2026-05-10-f7591eb3.summary.yaml` | id:helpful_only_bypass_constraints,helpful_only_misinformation,helpful_only_model_harmful_task,system_prompt_quirk_reveal,defense_email_developer_conflict |

## How to add a new entry

```bash
# After `geode audit --live` finishes:
uv run geode petri-archive logs/<timestamp>_audit_<id>.eval
```

The command writes both the raw archive (`~/.geode/petri/logs/`) and
the YAML summary here. Idempotent — re-running over the same eval just
overwrites both.
