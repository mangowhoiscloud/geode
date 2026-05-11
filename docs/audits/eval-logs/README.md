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

## MANIFEST.jsonl — cross-session index

`MANIFEST.jsonl` is the single source of truth that maps **every**
archived eval to its committable summary + seed_ids + role token
totals. One JSON line per archive, append-only:

```json
{"archive":"<basename>.eval",
 "archive_sha":"<sha1>",
 "summary_yaml":"<YYYY-MM-DD>-<hash8>.summary.yaml",
 "status":"success", "task":"inspect_petri/audit",
 "samples":1, "seed_ids":["..."],
 "started_at":"<ISO8601>", "completed_at":"<ISO8601>",
 "models":{"auditor":"...","target":"...","judge":"..."},
 "role_usage_summary":{"<role>":{"in":N,"out":N,"cache_w":N,"cache_r":N}}}
```

**Why JSONL not YAML**: each `*.summary.yaml` is per-eval. MANIFEST is
cross-eval. JSONL appends without rewriting the whole file (concurrent
audits don't race), and one-line entries make `grep`/`jq` queries
trivial. The schema mirrors `core/audit/manifest.py:extract_manifest_entry`.

### Live runs — auto-append

`plugins/petri_audit/runner.py:_append_manifest_line` writes a line
after every `geode audit --live`. Best-effort + idempotent
(archive_sha dedup); a manifest failure is recorded as a note on the
`AuditReport`, never surfaced as an audit failure.

### Backfilling existing archives

`scripts/retrofit_manifest.py` walks `~/.geode/petri/logs/` and appends
any archive whose sha is not yet indexed. Safe to re-run:

```bash
uv run python scripts/retrofit_manifest.py
# Custom dirs:
uv run python scripts/retrofit_manifest.py \
    --archive-dir ~/.geode/petri/logs \
    --summary-dir docs/audits/eval-logs
```

### Querying — find evals by seed

```bash
# Every eval that ran the helpful_only_model_harmful_task seed:
jq -c 'select(.seed_ids[]? == "helpful_only_model_harmful_task")' \
    docs/audits/eval-logs/MANIFEST.jsonl

# Total auditor cache hits across all anthropic-stack runs:
jq -c 'select(.models.auditor | startswith("claude-")) | .role_usage_summary.auditor.cache_r' \
    docs/audits/eval-logs/MANIFEST.jsonl
```

## How to add a new entry (manual path)

```bash
# After `geode audit --live` finishes:
uv run geode petri-archive logs/<timestamp>_audit_<id>.eval
```

The command writes the raw archive (`~/.geode/petri/logs/`) + the YAML
summary here + (since 2026-05-11) appends a MANIFEST.jsonl line.
Idempotent — re-running over the same eval just overwrites the YAML
and skips the manifest line.
