# Petri × GEODE Observability — Layered Architecture

> Status: SOT for the post-2026-05-11 architecture (PR #1024 + #1026 + #1027).
> Companion ground-truth report: `docs/audits/2026-05-11-petri-observability-audit.md`.

`geode audit --live` is a 3-model dance: an inspect_petri **auditor** (red-team
prompts), a GEODE-wrapped **target** (`geode/<model>` via
`GeodeModelAPI`), and a **judge** (16-dim rubric scoring). Every turn the
three models combine cache-heavy prompts + thinking + multi-call subloops, so
"how much did this audit cost" and "what did the target actually do" can only
be answered if observability is wired end-to-end across three layered systems
— each with its own contract.

This doc is the single map of which layer captures what, why each one exists,
and where the boundaries (cross-layer extraction points) live.

## TL;DR — three layers, three responsibilities

| Layer | Path | Scope | Lifetime | Producer | Consumer |
|------:|------|-------|----------|----------|----------|
| **1. Raw archive** | `~/.geode/petri/logs/*.eval` | Single eval, full transcript | Forever (out-of-git, PII risk) | inspect_ai's `EvalRecorder` | `inspect view`, debugging, `extract_summary` |
| **2. Token ledger** | `~/.geode/usage/<YYYY-MM>.jsonl` | All LLM calls across sessions | Forever | `TokenTracker._persist_usage` (per-call) + `core.audit.eval_to_jsonl` (per-eval rollup) | `geode history`, cost monitoring |
| **3. Archive manifest** | `docs/audits/eval-logs/MANIFEST.jsonl` | Per-eval metadata + seed_ids + role tokens | Forever (git-tracked) | `core.audit.manifest.append_manifest` | seed lookup, cross-archive jq queries |

Layer 1 is **inspect_ai-native** (binary `.eval` ZIP). Layers 2 and 3 are
**GEODE additions** because inspect_ai has no concept of cross-session
aggregation or git-tracked index.

## Why three layers

inspect_ai already does a lot — 26 typed events, `EvalStats.role_usage` /
`model_usage` aggregation, `LoggerEvent` capture of Python `logging`,
crash-safe `SampleBufferFilestore` recovery. Re-implementing any of that in
GEODE would be redundant and would drift. So GEODE only adds what
inspect_ai's scope (single-eval) leaves out:

1. **Cross-session token aggregation** — `geode history` rollup answers
   "what did petri cost me this month?". inspect_ai's `.eval` carries the
   per-eval totals; rolling them up over many evals requires a single
   GEODE-side ledger.

2. **Cross-archive index** — "which evals ran the
   `helpful_only_model_harmful_task` seed?" requires a flat searchable file.
   The raw `.eval` archives are out-of-git (large + PII), and per-eval
   `*.summary.yaml` are scoped to that one eval. MANIFEST.jsonl is the join
   table.

3. **Cache + thinking token preservation** — Defect A's F-A2 leak was that
   GEODE's TokenTracker dropped cache/thinking tokens at the `_persist_usage`
   seam even though `_calculate_cost` priced them correctly. The schema
   extension in PR #1026 closed the leak.

Everything else inspect_ai already covers — see [§Out of scope](#out-of-scope).

## Layer 1 — Raw archive (inspect_ai native)

```
~/.geode/petri/logs/<YYYY-MM-DDThh-mm-ss>-<id>_audit_<task-id>.eval
```

A ZIP container (inspect_ai v2 log format) that holds the entire eval:

- `header.json` — final `EvalLog`: status, stats, results
- `samples/<id>_epoch_<n>.json` — per-sample EvalSample with all events
- `summaries.json` — thinned `EvalSampleSummary[]` (truncated strings, <1k
  fields)
- `_journal/start.json` + `_journal/summaries/` — recovery snapshots
- `results.json` + `reductions.json` — scorer outputs

Out-of-git on purpose:
- Size — 40KB–700KB per archive, multiplied by every live run
- PII risk — auditor messages can include personal data depending on seed

Reads use `inspect_ai.log.read_eval_log(path)` (or `header_only=True` for
just the stats). `inspect view <path>` opens a local TUI.

## Layer 2 — Token ledger (`~/.geode/usage/<YYYY-MM>.jsonl`)

```
{"ts":<unix>,"model":"<name>","in":N,"out":N,
 "cache_w":N,"cache_r":N,"think":N,
 "session":"<id>","role":"<target|judge|auditor>",
 "source":"<""|petri_eval>","eval_id":"<basename>.eval","cost":<usd>}
```

Two producers append to the same monthly file:

### Producer 2a — per-call (default GEODE path)

`core.llm.token_tracker.TokenTracker._persist_usage` writes one row per LLM
call from inside `AgenticLoop`. Triggered by `_response.track_usage` after
every provider response. `source=""` (default), `role=""`. This is how
`geode "<prompt>"` and every non-petri agentic call lands in the ledger.

### Producer 2b — per-eval rollup (petri path)

inspect_ai's native `AnthropicAPI` / `OpenAIAPI` (used for the judge and
auditor models) **bypass GEODE's TokenTracker** — they call the provider
SDK directly. The 5/11 ground truth check confirmed this: archive
`role_usage` recorded judge `in=21 out=846 cache_w=6740` and auditor `in=7
out=1007 cache_r=34006`, while the matching wall-clock minute in
`~/.geode/usage/2026-05.jsonl` had zero rows.

`core.audit.eval_to_jsonl.extract_to_usage_store(eval_path)` closes this
hole. After a petri archive lands (`_maybe_auto_archive`), this function
walks `EvalStats.model_usage`, maps each model to its role via
`eval.model_roles`, and appends one `source="petri_eval"` row per `(model,
role)` pair. `ts` is stamped from `eval.created` (not now()), so cross-tier
ts joins still work.

Idempotent: `UsageStore.has_eval_id(eval_id)` skips a second extraction of
the same archive.

### Why one file, two sources

A separate `usage-petri.jsonl` would force `geode history` to scan two
places. The `source` field is the only column an aggregation cares about,
and the JSONL reader's `.get(...)` fallback keeps pre-extension rows
(`{ts,model,in,out,cost}`) compatible — see `tests/test_usage_store.py:
TestUsageRecordExtensionFields::test_from_json_legacy_record_compat`.

## Layer 3 — Archive manifest (`docs/audits/eval-logs/MANIFEST.jsonl`)

```
{"archive":"<basename>.eval","archive_sha":"<sha1>",
 "summary_yaml":"<YYYY-MM-DD>-<hash8>.summary.yaml",
 "status":"success", "task":"inspect_petri/audit",
 "samples":N, "seed_ids":["..."],
 "started_at":"<ISO>", "completed_at":"<ISO>",
 "models":{"auditor":"...","target":"...","judge":"..."},
 "role_usage_summary":{"<role>":{"in":N,"out":N,"cache_w":N,"cache_r":N}}}
```

Append-only, git-tracked, one line per archive. Producer:
`core.audit.manifest.append_manifest`, called by
`plugins.petri_audit.runner._append_manifest_line` after every
`_maybe_auto_archive` succeeds. Idempotent via `archive_sha`
(file sha1).

Schema choices:

- **JSONL not YAML** — append-only without rewriting the whole file means
  concurrent audits don't race; one-line entries make `grep` / `jq` queries
  trivial.
- **`archive_sha` is the dedup key**, not the basename. If an audit is
  re-archived (e.g. someone copies an older `.eval` back in), the manifest
  still records a single canonical entry.
- **`models` is basename-only** — provider prefix (`anthropic/`,
  `openai/`) stripped so a query like "every run that used opus-4-7" hits
  regardless of which provider routed it.
- **Sample count from `eval.dataset.samples`** — `header_only=True` empties
  `log.samples` but the dataset path is populated because it describes the
  input plan.

Existing archives are backfilled via `scripts/retrofit_manifest.py`. Safe
to re-run.

### Example queries (jq)

```bash
# Every eval that ran a specific seed
jq -c 'select(.seed_ids[]? == "helpful_only_model_harmful_task")' MANIFEST.jsonl

# Total auditor cache reads across anthropic-stack runs
jq -c 'select(.models.auditor | startswith("claude-"))
       | .role_usage_summary.auditor.cache_r' MANIFEST.jsonl

# Cross-archive cost summary by judge model
jq -s 'group_by(.models.judge)
       | map({judge: .[0].models.judge,
              total_judge_in: ([.[].role_usage_summary.judge.in] | add)})' \
   MANIFEST.jsonl
```

## Cross-layer flow (one audit, end-to-end)

```
geode audit --live
  │
  ├─ inspect eval (subprocess) ──► writes logs/<...>.eval (Layer 1, worktree-local)
  │
  ├─ Layer 2a (live): every TARGET call inside the GEODE AgenticLoop hits
  │   TokenTracker.record → _persist_usage → ~/.geode/usage/<YYYY-MM>.jsonl
  │   (judge and auditor calls inside inspect_ai do NOT pass through here)
  │
  └─ _maybe_auto_archive (after subprocess returns)
      ├─ archive_eval(eval_path)
      │   ├─ copy logs/<...>.eval → ~/.geode/petri/logs/<...>.eval   (Layer 1, permanent)
      │   └─ extract_summary → docs/audits/eval-logs/<...>.summary.yaml (per-eval YAML)
      │
      ├─ Layer 2b: _import_usage(raw_path)
      │   └─ extract_to_usage_store reads .eval header, walks
      │      stats.model_usage, appends 3 rows
      │      (auditor + judge + target) tagged source="petri_eval"
      │      to ~/.geode/usage/<YYYY-MM>.jsonl
      │
      └─ Layer 3: _append_manifest_line(raw_path, summary_path)
          └─ append_manifest reads .eval header, writes one JSON line
             to docs/audits/eval-logs/MANIFEST.jsonl
```

Both Layer 2b and Layer 3 are best-effort: failures land as notes on the
`AuditReport` but never propagate. The raw archive itself is the
self-contained truth — every bookkeeping step is reproducible by replaying
the extractors against the `.eval`.

## Out of scope (already covered by inspect_ai)

The following are intentionally **not** rebuilt in GEODE because
inspect_ai's native implementation covers them:

| Concern | inspect_ai location | Why not duplicated |
|---------|---------------------|--------------------|
| Cost calculation | `ModelUsage.total_cost` via internal `compute_model_cost` | GEODE's `calculate_cost` is the fallback when `.total_cost` is None |
| Stdout/stderr capture | `SandboxEvent` (truncated 100 lines) | GEODE has no sandbox abstraction in this path |
| Crash recovery | `SampleBufferFilestore` + `_journal/` | inspect_ai handles eval-set resume; GEODE side has no orchestration loop |
| Retry / error capture | `ModelEvent.retries` + `ErrorEvent` | Visible in `.eval` directly |
| 26 event types | `event/_event.py` Event union | Replay via `read_eval_log` is the canonical path |
| Score persistence | `ScoreEvent` + `EvalSampleSummary` | Mirrored into per-eval `*.summary.yaml` for git-friendliness |
| Log dir control | `INSPECT_LOG_DIR` env + `--log-dir` | GEODE reads from inspect_ai's default location |
| Python logging capture | `LoggerEvent` (Python `logging.getLogger`) | F-A3 logs land in `.eval` automatically |

## Where the seams are (when to change what)

| Change shape | Touch this layer | Examples |
|--------------|------------------|----------|
| New cost dimension on existing models | Layer 2 (UsageRecord) | Adding `reasoning_cache_read_tokens` |
| New audit metadata (e.g. dim_set used) | Layer 3 (manifest entry) | Adding `dim_set: "5axes"` to the manifest line |
| New per-call observability (latency, retries) | Layer 2 (UsageRecord) **and** TokenTracker | Latency requires the AgenticLoop to time the call |
| New raw-archive content | inspect_ai upstream — not GEODE | Wait for inspect_ai release |
| New search index (e.g. by score) | Layer 3 only | Add `judge_scores` to the manifest entry |

The general rule: extract from Layer 1 (`.eval`), persist into Layer 2 or 3.
Never the other direction. Layer 1 is inspect_ai's domain and must not be
mutated by GEODE.

## See also

- `core/audit/eval_to_jsonl.py` — Layer 1 → Layer 2 extractor
- `core/audit/manifest.py` — Layer 1 → Layer 3 extractor
- `core/llm/token_tracker.py` — Layer 2 producer (per-call)
- `core/llm/usage_store.py` — Layer 2 storage
- `plugins/petri_audit/runner.py:_maybe_auto_archive` — orchestration seam
- `plugins/petri_audit/eval_archive.py:archive_eval` — Layer 1 copy + YAML
- `docs/audits/2026-05-11-petri-observability-audit.md` — ground-truth report
- `docs/architecture/observability-report.md` — older system-wide inventory
- inspect_ai source: `.venv/lib/python3.12/site-packages/inspect_ai/`
