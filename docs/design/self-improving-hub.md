---
title: DESIGN.md · `/geode/self-improving/` (Hub)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/` (Hub)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first. This doc is the **page contract**.

## 1. Page purpose

The landing page for the entire Self-Improving Hub. Visitor lands here from `https://mangowhoiscloud.github.io/geode/self-improving/`. Must orient in <10 seconds: what surfaces exist, what shipped recently, where to drill in. Option 1 (surface-first) layout per operator selection 2026-05-26.

## 2. Data sources (build-time read)

| Source | Used for |
|---|---|
| `docs/self-improving/petri-bundle/logs/listing.json` | Petri audit table — filter `task=inspect_petri/audit` |
| `docs/self-improving/petri-bundle/seeds/listing.json` | Seed-gen runs section (count + run list) |
| `~/.geode/self-improving/baseline.json` | Autoresearch baseline status (live or stale flag) |
| `core/self_improving/state/baseline_archive.jsonl` | Generation index, last promote, fitness deltas |
| `core/self_improving/state/mutations.jsonl` | Recent mutation rows |
| `autoresearch/results.tsv` (if present) | Row count |
| `~/.geode/diagnostics/<YYYY-MM>.log` | Optional last activity timestamp (skip if absent) |

Build-time render — static HTML produced by `scripts/build_self_improving_hub.py` (new, Phase 4). No client-side fetch.

## 3. Sidebar `.active`

`Hub > Overview`

## 4. Sections (h2.section, top to bottom)

1. **Petri Audit** — table of recent audits (5-10 rows max, "view all ↗" link)
2. **Seed Generation** — table of seed-gen runs (all of them; small N for now)
3. **Autoresearch** — table of baseline / mutations / results / policies artifacts (4 rows static)
4. **Documentation** — table of `/geode/docs/petri/*` pages (5 rows static)

## 5. Per-section columns

### 5.1 Petri Audit

| Column | Source field |
|---|---|
| id | `task_id` (short form) |
| seeds | `task_args_passed.limit` if present, else `dataset.samples` |
| auditor | `model_roles.auditor.model` → harness chip + monospace |
| target | `model_roles.target.model` → harness chip + monospace |
| judge | `model_roles.judge.model` → harness chip + monospace |
| started | `started_at` (ISO short) |

Sort: `started_at` descending. Limit: 10 rows. Footer link "→ /geode/self-improving/petri-bundle/" to SPA viewer.

### 5.2 Seed Generation

| Column | Source field |
|---|---|
| run_id | `runs[].run_id` (anchor → seed-gen run detail) |
| gen_tag | `runs[].gen_tag` |
| target_dim | `runs[].target_dim` |
| mutator | always `claude-cli/claude-opus-4-7` for now (single mutator) — harness chip + mono |
| draft → surv | `runs[].candidates_drafted` → `runs[].survivors_count` |
| evolved | `runs[].evolved_count` |
| cost USD | `runs[].usd_spent` ($X.XX) |

Sort: most recent first. No limit (currently 1 row).

### 5.3 Autoresearch

| Column | Source field |
|---|---|
| artifact | static label (baseline.json / mutations.jsonl / results.tsv / policies/) |
| last write | `os.path.getmtime` formatted |
| generation | from `baseline.json.metadata.gen_tag` for baseline; row count for mutations; row count for results; file count for policies |
| auditor / target / judge | from `baseline.json.audit.{auditor_model, target_model, judge_model}` |
| fitness | from `baseline.json.fitness.value` (N/A for non-baseline rows) |

4 rows. Static labels, dynamic data.

### 5.4 Documentation

Static 5-row table:

| page | summary |
|---|---|
| Petri Overview | Petri framework + GEODE wrapper, 3 model roles |
| Petri Scenarios | 22 GEODE-specific seeds across critical / auxiliary / info |
| Run an Audit | `geode audit` primary path + `inspect eval` raw |
| Judge Dimensions | 22 dim subset + 38 dim full set |
| Seed Dashboard | per-run survivors + cost + meta-review (Next.js page) |

## 6. Sidebar contract

Per master DESIGN.md §7:

```
GEODE
/self-improving

──── Hub
  Overview                    [active]

──── Petri Audit            [11]
  SPA log viewer ↗
  Recent audits
    audit_Hz4Qrv4Z
    audit_k4QhmKXs
    audit_m8BRHKDA          (top 3 by started_at)

──── Seed Generation        [1 run]
  All runs
    gen1-redundant_tool_invocation
  Run dashboard ↗            (link to /geode/docs/petri/seeds)

──── Autoresearch          [stale or live]
  Baseline
  Mutations
  Results
  Policies

──── Docs
  Petri overview
  Run an audit
  Judge dimensions

──── Meta
  GitHub ↗                  (https://github.com/mangowhoiscloud/geode)
```

## 7. Empty states

- Petri table 0 rows → `<tr><td colspan="6"><em>No audits published yet. Run <code>geode audit --live</code>.</em></td></tr>`
- Seed-gen 0 rows → `<tr><td colspan="7"><em>No seed-generation runs published yet.</em></td></tr>`
- Autoresearch `baseline.json` absent → row reads "no baseline written yet — run <code>uv run python core/self_improving/train.py --promote</code>"

## 8. Error states

- listing.json malformed → build script fails CI. No rendered fallback.
- baseline.json malformed → render row with `status=parse-error` in `--ink-faint`.

## 9. Build-info footer

```
Source: docs/self-improving/ (mirrors docs/petri-bundle/ post-relocation).
Built by .github/workflows/pages.yml on every main push.
Harness chip legend: PAYG · Claude Code · Codex · GEODE.
Repo: github.com/mangowhoiscloud/geode
```

## 10. Outgoing links

| Link | Target |
|---|---|
| Sidebar `Hub > Overview` (self) | `/geode/self-improving/` |
| Petri audit row id | `/geode/self-improving/petri-bundle/#/tasks/<task_id>` (SPA deep link) |
| Petri section footer | `/geode/self-improving/petri-bundle/` |
| Seed-gen run row id | `/geode/self-improving/seed-generation/<run_id>/` |
| Seed-gen footer | `/geode/docs/petri/seeds` (Next.js dashboard) |
| Autoresearch artifact row | `/geode/self-improving/autoresearch/<artifact>/` |
| Docs links | `/geode/docs/petri/<slug>` |
| GitHub | `https://github.com/mangowhoiscloud/geode` |

## 11. Verification checklist

- [ ] All sidebar links return 200 (post-merge `docs-link-audit`)
- [ ] All `<a href>` start with `/geode/` (no missing basePath)
- [ ] Build script reads real listing.json (no hardcoded data)
- [ ] Harness chips reflect actual `model_roles` from data
- [ ] Empty state visible when no data (test: rename listing.json to listing.json.bak)
- [ ] Page < 50KB gzipped (no JS, system fonts, no images other than favicon)
- [ ] Color contrast ≥ 4.5:1 for body, ≥ 3:1 for chips
- [ ] No emoji, no card-lifts, no gradients
- [ ] GitHub repo link visible in sidebar Meta section
- [ ] Build-info footer cites actual deploy timestamp from CI
