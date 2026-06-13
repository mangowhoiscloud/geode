---
title: Self-Improving Autoresearch · Visual Specification (Landing + 4 sub-pages)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
parent: self-improving-hub-system.md
applies_to_geode: ">=0.99.65"
sibling_pages:
  - self-improving-autoresearch.md
  - self-improving-autoresearch-baseline.md
  - self-improving-autoresearch-mutations.md
  - self-improving-autoresearch-results.md
  - self-improving-autoresearch-policies.md
  - self-improving-hub-system.md
  - self-improving-hub-visual-spec.md
  - self-improving-seed-generation-visual-spec.md
  - autoresearch-port-mapping.md
---

# Self-Improving Autoresearch · Visual Specification

> Concrete visual contract for the 5 autoresearch sub-pages:
>
> - `/geode/self-improving/autoresearch/` (landing)
> - `/geode/self-improving/autoresearch/baseline/`
> - `/geode/self-improving/autoresearch/mutations/`
> - `/geode/self-improving/autoresearch/results/`
> - `/geode/self-improving/autoresearch/policies/`
>
> Frontend agent renders HTML/CSS directly from this doc — no further design
> decisions required. This spec **does not invent** new colour tokens, fonts, or
> layouts. Heatmap-like rendering, sparklines, and delta colouring all compose
> from the existing `assets/hub.css` token table.
>
> Every citation of a field name, constant, or schema is grounded to a
> `file:line` in `core/self_improving/train.py`, `core/paths.py`, or
> `core/self_improving_loop/{runner,attribution}.py`. No general intuition.

---

## 1. Scope + Authority order

1. **Master DESIGN.md** ([`self-improving-hub-system.md`](./self-improving-hub-system.md)) — Authoritative for palette, sidebar contract, harness chips, anti-emoji + anti-card rule, versioning policy ([§15](./self-improving-hub-system.md#15-versioning-policy)).
2. **Per-page DESIGN.md** (`self-improving-autoresearch{,-baseline,-mutations,-results,-policies}.md`) — Authoritative for data sources, sections, columns, sidebar `.active`.
3. **Hub visual spec** ([`self-improving-hub-visual-spec.md`](./self-improving-hub-visual-spec.md)) — Authoritative for shared markup primitives (sidebar HTML, records table, chip CSS, build-info footer). All 5 autoresearch pages lift these primitives unchanged.
4. **Seed-gen visual spec** ([`self-improving-seed-generation-visual-spec.md`](./self-improving-seed-generation-visual-spec.md)) — Reference for the same-pattern second surface (heatmap-cell ramp, cost-grid, per-row `<details>` drilldown markup).
5. **Port mapping** ([`autoresearch-port-mapping.md`](./autoresearch-port-mapping.md)) — Authoritative for schema namespaces (§6), pinned constants (§7), and the no-publisher decision below (§3 here).
6. **Real data** — Sole input to the build script:
   - `state/self_improving/baseline.json` (live) or `state/self_improving/baseline.json.outdated-YYYYMMDD` (fallback)
   - `state/self_improving/baseline_archive.jsonl`
   - `state/self_improving/mutations.jsonl`
   - `state/self_improving/policies/*.json` (13 files + `few-shot-pool.jsonl` = 14)
   - `autoresearch/results.tsv` + `autoresearch/results.jsonl`

This spec governs 5 pages. Where it diverges from (1)/(2)/(3) the higher-rank doc wins — flag a fix-up PR.

All rem values resolved against `html { font-size: 16px }`. The pages reuse `docs/self-improving/assets/hub.css` *as-is* plus a single appended section `§ Autoresearch` (defined in §11 here). No `:root` token additions.

---

## 2. Shared shell (identical across all 5 pages)

All 5 pages reuse the **same sidebar HTML** as the hub, seed-gen index, and seed-gen run pages — only the `.active` highlight + `aria-current="page"` location differs. Frontend agent must NOT redesign the sidebar; lift it verbatim from `self-improving-hub-visual-spec.md` §3.1 and toggle:

| Page | Sidebar `.active` | nested |
|---|---|---|
| Landing | `Autoresearch > Overview` | — |
| Baseline | `Autoresearch > Baseline` | nested under Autoresearch |
| Mutations | `Autoresearch > Mutations` | nested under Autoresearch |
| Results | `Autoresearch > Results` | nested under Autoresearch |
| Policies | `Autoresearch > Policies` | nested under Autoresearch |

The Autoresearch nav group already exists in the shared sidebar template
(`self-improving-hub-system.md` §7); it expands to 4 sub-nav items
(Baseline / Mutations / Results / Policies) on autoresearch pages and
collapses to root link only on the landing page (mirrors how
`Seed Generation` expands on its own surface).

### 2.1 Page chrome (identical across all 5 pages)

```
┌─────────────────── 1440px viewport ──────────────────────────────────────────┐
│ ┌── aside.sidebar ──┬── main.content ─────────────────────────────────────┐ │
│ │ 260px fixed       │ flex 1, max-width 1100px, pad 32px 40px              │ │
│ │ identical markup  │                                                      │ │
│ │ .active toggled   │ ┌─ h1.page-title  "<page title>" ─────────────────┐ │ │
│ │ per table above   │ │   26px sans 600 --ink                            │ │ │
│ │                   │ └──────────────────────────────────────────────────┘ │ │
│ │                   │ ┌─ p.page-sub  (1-2 sentence orientation) ────────┐ │ │
│ │                   │ └──────────────────────────────────────────────────┘ │ │
│ │                   │                                                      │ │
│ │                   │ ── h2.section  (per-page sections, see below)        │ │
│ │                   │ <table.records> or <dl.status-grid> or <details>     │ │
│ │                   │                                                      │ │
│ │                   │ ─── .build-info footer (identical to hub)            │ │
│ └───────────────────┴──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Build-info footer + version stamp

Identical contract to seed-gen visual spec §13:

```html
<footer class="build-info">
  <p class="version-stamp">
    Rendered against GEODE <code>v0.99.65</code> · DESIGN.md schema 1 · built 2026-05-26.
    Baseline schema: v2 (PR-2). ApplyRecord schema: W4 (2026-05-25).
    Dim subset: 20 (5 critical + 12 auxiliary + 3 info) + stability synth.
    Fitness axes: 4 (dim 0.30 / ux 0.25 / admire 0.20 / bench 0.25).
  </p>
  <p class="muted">
    Source artifacts read directly from <code>state/self_improving/</code>
    (git-tracked policies + gitignored ledgers; see §3).
  </p>
</footer>
```

All values build-time substituted by `scripts/build_self_improving_hub.py` from `pyproject.toml` + the loaded state. No hand-written dates.

---

## 3. No-publisher decision

**Decision (2026-05-26)**: The hub builder reads `state/self_improving/*` directly. **No publisher mirror module.**

### 3.1 Why no publisher

The port-mapping document ([`autoresearch-port-mapping.md`](./autoresearch-port-mapping.md) §9) flags a "missing publisher" GAP. After re-checking:

| File | Tracked? | Source-of-truth location |
|---|---|---|
| `state/self_improving/policies/*.json` (13 files) | **git-tracked** (per [`core/paths.py:235-313`](../../core/paths.py)) | `state/self_improving/policies/` |
| `state/self_improving/policies/few-shot-pool.jsonl` | **git-tracked** ([`core/paths.py:318`](../../core/paths.py)) | `state/self_improving/policies/` |
| `state/self_improving/baseline.json` | gitignored (per `state/self_improving/*` rule) but stable absolute path | `state/self_improving/baseline.json` |
| `state/self_improving/baseline_archive.jsonl` | gitignored ([`core/paths.py:339`](../../core/paths.py)) but stable | `state/self_improving/baseline_archive.jsonl` |
| `state/self_improving/mutations.jsonl` | gitignored ([`core/paths.py:335`](../../core/paths.py)) but stable | `state/self_improving/mutations.jsonl` |
| `autoresearch/results.tsv` | gitignored | `autoresearch/results.tsv` |
| `autoresearch/results.jsonl` | gitignored | `autoresearch/results.jsonl` |

Both the 14 policy files (git-tracked) and the 5 ledger files (gitignored but stable absolute paths under `STATE_DIR`, [`core/self_improving/train.py:577`](../../core/self_improving/train.py)) are already accessible at build time from the repo root. A publisher would add:

1. Duplicate write path (`state/self_improving/X` → `docs/self-improving/autoresearch/X`)
2. New writer hook that must fire on every promote/iteration (per Wiring Verification CANNOT in CLAUDE.md — "Read-Write parity" risk)
3. A second SoT to keep drift-free (per `[[feedback-latest-vs-promoted-sot.md]]`)

GitHub Pages CI already reads from the repo at build time. The builder simply opens the live files. **No mirror, no publisher hook.**

### 3.2 Where the builder reads from

`scripts/build_self_improving_hub.py:load_autoresearch()` (current implementation at [line 255](../../scripts/build_self_improving_hub.py)) already reads `state/self_improving/` directly. It looks at the live `baseline.json` first and falls back to the most recent `baseline.json.outdated-*` per the same function ([lines 262-273](../../scripts/build_self_improving_hub.py)).

Phase 6 extends this loader. The Phase 5 stub returns a small struct
(`AutoresearchState` at [line 238](../../scripts/build_self_improving_hub.py)) used only on the hub landing; Phase 6 adds 4 fuller renderers + helpers (see §10 below).

### 3.3 Stale-snapshot handling

When `baseline.json` is absent and a `baseline.json.outdated-YYYYMMDD` exists, the builder:

1. Sets `state.baseline_path = <outdated path>`
2. Sets `state.baseline_stale = True`
3. Renders the page with the stale data but prepends a warning banner (see §4.2 below)

When ALL artifacts (baseline + archive + mutations + results + policies) are missing, the landing page renders an empty-state explanation (see §4.4) — it does not 500 the build.

---

## 4. Landing page (`/autoresearch/index.html`)

**File**: `docs/self-improving/autoresearch/index.html`
**Sidebar `.active`**: `Autoresearch > Overview`
**Page title**: `Autoresearch · Closed-Loop Self-Improvement`
**Page sub**: `Baseline + mutations + results + 14 policies. The self-improving loop reads state/self_improving/ directly — no mirror.`

### 4.1 Anatomy (top-down)

```
h1.page-title       "Autoresearch · Closed-Loop Self-Improvement"
p.page-sub          1-sentence orientation
                    
[CONDITIONAL] .warning-banner   if state.baseline_stale or state.baseline_path is None
                    
h2.section          "STATUS"
<dl class="status-grid">  9-row key/value grid (§4.3)
                    
h2.section          "GENERATION TIMELINE · {N} ROWS"
<table.records>     6-col table from baseline_archive.jsonl (§4.4)
                    
h2.section          "SUB-VIEWS · 4"
<table.records>     4-row records table linking to sub-pages (§4.5)
                    
.build-info         footer (§2.2)
```

### 4.2 Warning banner (conditional)

Two scenarios, both render the same `<div class="warning-banner">` shape:

| Condition | Banner body |
|---|---|
| `state.baseline_path is None` | `No live baseline. Run <code>uv run python core/self_improving/train.py --promote</code> to bootstrap.` |
| `state.baseline_stale is True` (i.e. reading from `baseline.json.outdated-YYYYMMDD`) | `Stale snapshot — reading <code>{filename}</code>. The live baseline.json is absent or has been rotated.` |

Markup:

```html
<div class="warning-banner" role="status">
  <span class="warning-banner__label">notice</span>
  <span class="warning-banner__body">{body}</span>
</div>
```

CSS in §11.

### 4.3 Status block (`<dl class="status-grid">`)

9 key/value rows. Reuses the existing `.status-grid` pattern (synonym of seed-gen visual spec §6 `.cost-grid`; both are flat 2-col `<dl>` grids).

| `<dt>` | `<dd>` content | Source |
|---|---|---|
| current baseline | `<code>{gen_tag}</code>` or `—` | `baseline.json.session_id` / `gen_tag` (in raw metadata; see `train.py:1810-1818` for the v2 layout) |
| fitness scalar | `<code>{value:.4f}</code>` or `—` | Computed via `compute_fitness(...)` ([`train.py:1100`](../../core/self_improving/train.py)) at audit time and stored in the v2 `fitness` namespace (PR-3 TBD; for now fall back to v1 inferred from `dim_means` via the same formula at build time, OR show `schema v1 (no fitness block)` if missing) |
| last promote | `<code>{ts_utc}</code>` (short form) | `baseline.json.promotion.timestamp` (v2 `promotion` namespace, PR-5 TBD); else `baseline.json.ts_utc` (top-level, v2); else `—` |
| auditor model | harness chip + `<code>` | `baseline.json.audit.auditor_model` (v2 `audit` namespace, PR-4 TBD); else `—` |
| target model | harness chip + `<code>` | `baseline.json.audit.target_model`; else `—` |
| judge model | harness chip + `<code>` | `baseline.json.audit.judge_model`; else `—` |
| mutations.jsonl | `{N} rows · last <code>{mtime}</code>` | `state.mutations_count` + `state.mutations_mtime` |
| results.tsv | `{N} rows · last <code>{mtime}</code>` | `state.results_count` + `state.results_mtime` |
| policies/ | `{N} files · last touched <code>{mtime}</code>` | `state.policies_count` + `state.policies_mtime` |

If any audit block field is missing, render `<span class="muted">schema v1 (no audit block)</span>` once (not 3 times). Spec name: **`schema-v1-degradation`**.

### 4.4 Generation timeline (`<table class="records">`)

Source: `state/self_improving/baseline_archive.jsonl` ([`core/paths.py:339`](../../core/paths.py) — `BASELINE_ARCHIVE_PATH`). Each row in that JSONL is one promoted baseline snapshot (append-only, see [`core/self_improving_loop/runner.py:1621-1645`](../../core/self_improving_loop/runner.py)).

6 columns:

| col | source field | format |
|---|---|---|
| gen_tag | `row.gen_tag` (or `row.session_id` if pre-P1a) | mono, `<code>` |
| ts | `row.ts_utc` | short ISO (`2026-05-26 15:30`) |
| fitness | `row.fitness.value` (v2) else recomputed from `row.dim_means` | num, 4 decimal |
| Δ fitness | computed against the next-older row in the archive | sparkline char + signed num (§7.4) |
| mut summary | `row.mutation.target_section` truncated to 32 chars | mono |
| audit models | 3 harness chips (auditor / target / judge) | inline chips per `_harness_chip()` helper |

Sort: newest first (reverse-chronological by `ts_utc`).

Current baseline row (the top row whose `gen_tag` matches `baseline.json.gen_tag`) gets `<tr class="gen-timeline-row active">` — bold weight + thicker bottom border, no new colour (see §11 CSS).

Empty state (0 rows): `<tr><td colspan="6" class="empty"><em>No promoted baselines yet.</em></td></tr>` per master `self-improving-hub-system.md` §10.

### 4.5 Sub-view records table (NOT card grid)

Per the anti-card-grid rule (`[[feedback-no-box-ui-no-emoji.md]]`), render as a 4-row `<table class="records">`:

| `<th>` | sub-page | rows | link |
|---|---|---|---|
| Baseline | `/geode/self-improving/autoresearch/baseline/` | `1` (current state) | full URL |
| Mutations | `/geode/self-improving/autoresearch/mutations/` | `{state.mutations_count}` | full URL |
| Results | `/geode/self-improving/autoresearch/results/` | `{state.results_count}` | full URL |
| Policies | `/geode/self-improving/autoresearch/policies/` | `14` | full URL |

Each row carries a `<span class="bucket autoresearch">autoresearch</span>` chip after the sub-page name, identical to how the hub landing page §5.3 renders the autoresearch row.

**No card-lift, no hover-zoom, no border-radius > 4px** (existing token `--rule` only). Mirror the markup of the hub-level autoresearch row at [`scripts/build_self_improving_hub.py:432-466`](../../scripts/build_self_improving_hub.py).

### 4.6 Empty states (all on landing)

| Scenario | Treatment |
|---|---|
| `baseline.json` + `baseline.json.outdated-*` BOTH absent | warning-banner (§4.2) + status block renders all `—` cells |
| `baseline_archive.jsonl` empty/absent | timeline section header shows `· 0 ROWS`; tbody renders single `<tr><td colspan=6 class="empty">No promoted baselines yet.</td></tr>` |
| `mutations.jsonl` absent | status row shows `0 rows · —` |
| `policies/` directory absent or contains only `.gitkeep` | status row shows `0 files · —`; sub-view "Policies" row shows `0` |

---

## 5. Baseline page (`/autoresearch/baseline/index.html`)

**File**: `docs/self-improving/autoresearch/baseline/index.html`
**Sidebar `.active`**: `Autoresearch > Baseline`
**Page title**: `Baseline · Current Promoted State`
**Page sub**: `Latest <code>state/self_improving/baseline.json</code> rendered by schema-v2 namespace (raw / axes / [normalized / fitness / audit / promotion]).`

### 5.1 Anatomy (top-down)

```
h1.page-title       "Baseline · Current Promoted State"
p.page-sub          1-sentence orientation
                    
[CONDITIONAL] .warning-banner   if state.baseline_stale  (see §4.2)
                    
h2.section          "METADATA"
<dl class="status-grid">   schema_version / session_id / gen_tag / commit / ts_utc (5 rows)
                    
h2.section          "RAW · 20-DIM AUDIT OUTPUT"
<table.records>     20-row dim table — dim / mean / stderr / sample / modality / tier
+ rubric_version    inline beneath the table (`<dl class="status-grid">`)
+ eval_archive      link if present, else muted "—"
                    
h2.section          "NORMALIZED · DIM SCORES" [render only if normalized block present]
<table.records>     20-row table — dim / score (computed via _dim_score) / tier
                    
h2.section          "AXES · 4-AXIS FITNESS COMPONENTS"
<table.records>     3-row table — ux_means / admire_means / bench_means
                    each row expandable to per-field <details> (§5.5)
                    
h2.section          "FITNESS · WEIGHTED AGGREGATE" [render only if fitness block present]
<dl class="status-grid">   value / formula_version / weights / components
                    
h2.section          "AUDIT · MODEL ROLES" [render only if audit block present]
<dl class="status-grid">   3 harness-chipped models + seed_limit / dim_set / usd_spent
                    
h2.section          "PROMOTION · DECISION TRAIL" [render only if promotion block present]
<dl class="status-grid">   rule fired / margin / N / previous baseline ref
                    
.build-info         footer (§2.2)
```

### 5.2 Schema-v2 vs schema-v1 detection

Per the port mapping ([§6](./autoresearch-port-mapping.md#6-schema-v2-baseline-namespaces)) the v2 layout is:

```json
{
  "schema_version": 2,
  "session_id": "...",
  "commit": "...",
  "ts_utc": "...",
  "raw": {...},
  "axes": {...}
}
```

Detection rule:

```python
schema = int(baseline.get("schema_version") or 1)
is_v2 = schema >= 2
```

When `is_v2 is False` (the live `baseline.json.outdated-20260522` snapshot, for instance — it has only `dim_means` + `dim_stderr` at top level):

- The **Metadata** section shows `schema_version = 1 (legacy)`.
- The **Raw** section renders `baseline["dim_means"]` + `baseline["dim_stderr"]` directly (same 20-row table). Modality column shows `<span class="muted">unknown</span>` for every row. sample column shows `—`.
- The **Normalized / Fitness / Audit / Promotion** sections each render as:
  ```html
  <h2 class="section"><span>{Name} · {note}</span></h2>
  <p class="muted">schema v1 — no {name} block in this baseline.</p>
  ```
  No table at all. Cleanest graceful path; mirrors how missing seed-gen sections render (`render_seedgen_run` skips empty blocks).
- The **Axes** section is similarly skipped (v1 has no axes).

The page must NOT 500 on v1 baseline data. The Phase 6 E2E test
(`test_autoresearch_baseline_schema_v1_renders_gracefully`, see §13) freezes this.

### 5.3 Per-section table treatment

The 20-row dim tables (Raw + Normalized) share the same column layout. **22-row** label was a stale early-draft figure; the operational dim count is **20 + 1 stability synth = 21** rows in the per-dim view; here we render only the 20 dims and surface stability separately if `normalized.stability_score` is present.

Order: **CRITICAL_DIMS first (5), then AUXILIARY_DIMS (12), then INFO_DIMS (3)**.
Sourced from [`core/self_improving/train.py:426-428`](../../core/self_improving/train.py):

```python
CRITICAL_DIMS  = tuple(d for d, t in AXIS_TIERS.items() if t == "critical")    # 5
AUXILIARY_DIMS = tuple(d for d, t in AXIS_TIERS.items() if t == "auxiliary")   # 12
INFO_DIMS      = tuple(d for d, t in AXIS_TIERS.items() if t == "info")        # 3
```

Columns:

| col | source field | format |
|---|---|---|
| dim | dim name | mono |
| tier | `critical` / `auxiliary` / `info` | `<span class="tier-badge tier-{tier}">` (§11) |
| mean | `raw.dim_means[dim]` or `baseline.dim_means[dim]` (v1) | num, 2 decimal, right-aligned |
| stderr | `raw.dim_stderr[dim]` | num, 2 decimal |
| sample | `raw.sample_count[dim]` | int |
| modality | `raw.measurement_modality[dim]` | mono small label |

**Petri convention** (per seed-gen visual spec §8.1): **high score = problematic**. Mean cell colour rule (palette tokens only, no new tokens; identical to seed-gen heatmap §8.2):

| Range | class | source token |
|---|---|---|
| `1.0 ≤ x < 2.0` | `.dim-safe` | `var(--rule-soft)` bg, `var(--ink-soft)` fg |
| `2.0 ≤ x < 4.0` | `.dim-cool` | `rgba(125, 134, 148, 0.18)` (derived from `--ink-faint`) |
| `4.0 ≤ x < 6.0` | `.dim-mid` | `rgba(125, 134, 148, 0.38)` |
| `6.0 ≤ x < 8.0` | `.dim-warn` | `rgba(180, 83, 9, 0.20)` (derived from `--bucket-autoresearch`) |
| `8.0 ≤ x ≤ 10.0` | `.dim-hot` | `var(--bucket-autoresearch)` solid, `#fff` fg |

This is **not a heatmap** in the canvas sense — it's per-cell background-colour driven by a Python helper `_score_to_bucket(score: float) -> str`, just as the seed-gen pilot heatmap (`assets/hub.css §Pilot Scores`) already does. **No new colour tokens.**

### 5.4 dim_means / dim_scores rendering — table not visualisation

Per the per-page DESIGN.md ([`self-improving-autoresearch-baseline.md`](./self-improving-autoresearch-baseline.md) §5): each dim dict is a single-row data shape (dim → float). We render it as a **20-row table** (dim name + value cell with 5-bucket background colour), NOT a visualisation chart. Reason:

1. No JS framework allowed (master §13).
2. Single-row data does not benefit from canvas / SVG — pure HTML table is more accessible, copy-pasteable, and grep-able.
3. Pilot heatmap (seed-gen) renders cells across N candidates × 20 dims; here we have 1 baseline × 20 dims, so the heatmap collapses to a single column — better expressed as a column-per-attribute table.

### 5.5 Axes section (3-row table with `<details>` drilldown)

Each row = one axis. Markup:

```html
<table class="records">
  <thead>
    <tr><th>axis</th><th>aggregate</th><th>fields</th><th>weight</th></tr>
  </thead>
  <tbody>
    <tr>
      <td>
        <span class="bucket autoresearch">ux</span>
        <code>ux_means</code>
      </td>
      <td class="num">0.66</td>
      <td>
        <details>
          <summary>4 fields</summary>
          <dl class="axis-fields">
            <dt>success_rate</dt><dd class="num">0.66</dd>
            <dt>token_cost_norm</dt><dd class="num">0.99</dd>
            <dt>revert_ratio_norm</dt><dd class="num">0.80</dd>
            <dt>latency_norm</dt><dd class="num">0.75</dd>
          </dl>
        </details>
      </td>
      <td class="num">0.25</td>
    </tr>
    <!-- admire (2 fields), bench (7 fields) -->
  </tbody>
</table>
```

Per-axis details:

| axis | weight constant | source (file:line) | fields |
|---|---|---|---|
| dim | `FITNESS_DIM_4AX = 0.30` | [`train.py:418`](../../core/self_improving/train.py) | 20 dims + stability; aggregated by `compute_fitness()` ([`train.py:1100`](../../core/self_improving/train.py)) |
| ux | `FITNESS_UX_4AX = 0.25` | [`train.py:419`](../../core/self_improving/train.py) | 4 fields — `autoresearch/ux_means.py:71-78` |
| admire | `FITNESS_ADMIRE_4AX = 0.20` | [`train.py:420`](../../core/self_improving/train.py) | 2 fields — `autoresearch/admire_means.py:55-58` |
| bench | `FITNESS_BENCH_4AX = 0.25` | [`train.py:421`](../../core/self_improving/train.py) | 7 fields — `autoresearch/bench_means.py:188-196` |

If an `axes.X` value is `null`: row renders `<td><span class="muted">null (axis not configured)</span></td>` for the aggregate + collapsed `<details>` with `<em>No data</em>` inside.

### 5.6 Audit row: 3 harness-chipped models

Per master DESIGN.md §3, each of `auditor_model` / `target_model` / `judge_model` from the `audit` namespace gets a chip via `harness_chip(model_str)` ([`scripts/build_self_improving_hub.py:142`](../../scripts/build_self_improving_hub.py)):

```html
<dl class="status-grid">
  <dt>auditor</dt>
  <dd><span class="chip codex">Codex</span> <code>codex/gpt-5-codex-high</code></dd>
  <dt>target</dt>
  <dd><span class="chip claude">Claude Code</span> <code>claude-cli/claude-opus-4-7</code></dd>
  <dt>judge</dt>
  <dd><span class="chip claude">Claude Code</span> <code>claude-cli/claude-sonnet-4-5</code></dd>
  <dt>seed_limit</dt><dd><code>10</code></dd>
  <dt>dim_set</dt><dd><code>geode_judge_subset_v3-22dim-PR0</code></dd>
  <dt>usd_spent</dt><dd class="num">$2.18</dd>
</dl>
```

Pinned rubric version constant: `PETRI_RUBRIC_VERSION = "v3-22dim-PR0"` ([`train.py:1754`](../../core/self_improving/train.py)) — render the value live, not hard-coded in HTML.

### 5.7 Outgoing links

- "Previous baselines (archive)" — anchor to landing-page §4.4 timeline (i.e. `/geode/self-improving/autoresearch/#generation-timeline`). The archive page itself (separate `/baseline/archive/` URL) is an OPTIONAL follow-up — defer to a later sprint; the timeline on the landing serves as the archive view for now.
- "Mutation that produced this baseline" — `/geode/self-improving/autoresearch/mutations/#mut-{mutation_id}` (cross-link via `promotion.previous_baseline_ref` if PR-5 promotion namespace lands; else skip).

### 5.8 Empty state

If `baseline.json` is absent and no `.outdated-*` exists either:

```html
<div class="warning-banner" role="status">
  <span class="warning-banner__label">no baseline</span>
  <span class="warning-banner__body">
    Run <code>uv run python core/self_improving/train.py --promote</code> to bootstrap.
  </span>
</div>
```

…and skip the rest of the page (no empty sections — cleanest minimal output).

---

## 6. Mutations page (`/autoresearch/mutations/index.html`)

**File**: `docs/self-improving/autoresearch/mutations/index.html`
**Sidebar `.active`**: `Autoresearch > Mutations`
**Page title**: `Mutations · Apply Ledger + Attribution`
**Page sub**: `Append-only JSONL ledger of every applied mutation + post-audit attribution row. Schema: W4 ApplyRecord + AttributionRecord (2026-05-25).`

### 6.1 Anatomy (top-down)

```
h1.page-title       "Mutations · Apply Ledger + Attribution"
p.page-sub          1-sentence orientation
                    
h2.section          "FILTER · GEN_TAG / TARGET_SECTION / VERDICT"
.filter-strip       inline summary list — design call below (§6.2)
                    
h2.section          "MUTATIONS · {N} ROWS (NEWEST FIRST)"
<table.records>     9-col table from mutations.jsonl (§6.3)
+ per-row <details> drilldown rendered inside the last cell or as
                    a sibling row collapse (markup §6.4)
                    
.build-info         footer (§2.2)
```

### 6.2 Filter strip — designer's call

Per the per-page DESIGN.md §4 ("Filter strip — by gen_tag / target_section / verdict ([…] or render multiple pre-filtered tables OR just sort by ts desc; designer's call"):

**Decision: server-side single sorted table, NO JS filters.**

The filter strip is a **read-only summary** of the unique values present in the data, so operators eyeballing the page can scan the distribution. Markup:

```html
<dl class="filter-strip">
  <dt>gen_tag</dt>
  <dd><code>gen0</code> · <code>gen1</code> · <code>gen2</code></dd>
  <dt>target_kind</dt>
  <dd><code>prompt</code> · <code>tool_policy</code> · <code>decomposition</code> · <code>reflection</code></dd>
  <dt>verdict</dt>
  <dd><span class="verdict-applied">applied</span> · <span class="verdict-attribution">attribution</span></dd>
</dl>
```

Values are computed at build time by scanning the JSONL. This avoids:

1. Client-side JS filters (forbidden, master §13)
2. Render-N-pre-filtered-tables explosion
3. URL-param-based static partition pages (high maintenance, low value)

The single table is sorted **newest first by `ts`** (the float timestamp field on both ApplyRecord — [`runner.py:91`](../../core/self_improving_loop/runner.py) — and AttributionRecord — [`attribution.py:61`](../../core/self_improving_loop/attribution.py)).

### 6.3 Mutations table columns (9 cols)

Each line in `mutations.jsonl` is either an `ApplyRecord` (`kind = "applied"`) or an `AttributionRecord` (`kind = "attribution"`). The table renders both kinds in one stream, distinguished by row-class.

| col | source field (ApplyRecord) | source field (AttributionRecord) | format |
|---|---|---|---|
| ts | `row.ts` (float UNIX ts) | `row.ts` | short ISO via `_dt.datetime.fromtimestamp(row.ts, tz=UTC)` |
| kind | `applied` | `attribution` | `<span class="verdict-{kind}">` |
| mut_id | `row.mutation_id` | `row.mutation_id` | mono, anchor `id="mut-{mut_id}"` on first occurrence |
| target_section | `row.target_section` (e.g. `wrapper-sections.json::sycophancy_guardrail`) | (paired via mut_id; show same as the ApplyRecord) | mono, truncate to 40 chars |
| target_kind | `row.target_kind` (`prompt` / `tool_policy` / …) | (paired) | mono |
| mutator model | `harness_chip(row.cost_model)` | — (n/a for attribution) | chip + `<code>` |
| Δfitness | — | `row.fitness_delta` | num, 4 decimal, **with sparkline char + colour** (§6.5) |
| audit_ref | `row.audit_run_id` (if present) | `row.audit_run_id` | mono `<code>` |
| cost | `${row.cost_input_tokens + row.cost_output_tokens} tok · {row.cost_elapsed_seconds:.1f}s` | — | mono |

Empty state: `<tr><td colspan="9" class="empty"><em>No mutations recorded yet.</em></td></tr>`.

### 6.4 Per-row `<details>` drilldown — read JSONL per row, not pre-aggregate

**Decision**: render per-row drill-down inline at build time from the same JSONL pass. The builder reads `mutations.jsonl` once into a list-of-dicts, sorts, and emits one `<tr>` per row + one inline `<tr class="mut-detail">` containing a `<details><pre>` block.

Why per-row at build time (not lazy at view time):

1. No client-side JS allowed.
2. JSONL is small (~10s-100s of rows for the foreseeable future; the runner emits 1-2 rows per audit).
3. Embedding the full payload as inline `<pre>` lets `Ctrl+F` work across all rows.

Markup (one logical mutation = 2 `<tr>` siblings):

```html
<tr id="mut-{mutation_id}" class="mut-summary">
  <td class="num">{short_ts}</td>
  <td><span class="verdict-applied">applied</span></td>
  <td><code>{mutation_id}</code></td>
  <td><code>{target_section}</code></td>
  <td><code>{target_kind}</code></td>
  <td>{harness_chip(cost_model)}</td>
  <td class="num delta-positive">▆ +0.0214</td>
  <td><code>{audit_run_id}</code></td>
  <td class="num">{cost}</td>
</tr>
<tr class="mut-detail">
  <td colspan="9">
    <details>
      <summary>payload + attribution</summary>
      <pre class="mut-json">{JSON pretty-printed, json.dumps(row, indent=2)}</pre>
      <dl class="status-grid mut-attribution">
        <dt>observed_dim</dt>
        <dd>{20-dim mini-table — same 5-bucket palette}</dd>
        <dt>ci95</dt>
        <dd>{20-dim mini-table}</dd>
        <dt>fitness_before → after</dt>
        <dd class="num">{fitness_before:.4f} → {fitness_after:.4f} (Δ {fitness_delta:+.4f})</dd>
        <dt>cost</dt>
        <dd>{cost_input_tokens} in · {cost_output_tokens} out · {cost_elapsed_seconds:.1f}s · {cost_model}</dd>
      </dl>
    </details>
  </td>
</tr>
```

The attribution-row counterpart shows the SAME mut_id anchor but `kind="attribution"` and renders only the attribution payload (observed_dim, ci95, fitness_before/after) — the apply row has the cost; the attribution row has the deltas.

### 6.5 Δfitness colour rule + sparkline char

**Δfitness colour** uses **existing palette tokens only**:

| Range | class | source token |
|---|---|---|
| `delta > +0.005` | `.delta-positive` | `var(--bucket-seedgen)` (`#198754`) for fg, `rgba(25, 135, 84, 0.10)` for bg |
| `delta < -0.005` | `.delta-negative` | `var(--bucket-autoresearch)` (`#b45309`) for fg, `rgba(180, 83, 9, 0.10)` for bg |
| `|delta| ≤ 0.005` | `.delta-noise` | `var(--ink-faint)` fg, no bg |

`--bucket-seedgen` is the "positive pressure" green from master DESIGN.md §3; `--bucket-autoresearch` is the warm tone already permitted by §3 rule 2. **No new tokens.**

The **sparkline character** for the Δfitness cell is the magnitude-bucket from this 8-step Unicode block ramp:

```python
_SPARK_BLOCKS = ("▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")
# ▁ ▂ ▃ ▄ ▅ ▆ ▇ █
```

Pick the block char by `|delta|` magnitude bucket; positive deltas use the char as-is, negative use the same char (the colour communicates the sign):

| `|delta|` | char |
|---|---|
| `< 0.005` | `·` (middle dot, neutral) |
| `< 0.020` | `▁` |
| `< 0.050` | `▂` |
| `< 0.100` | `▃` |
| `< 0.200` | `▅` |
| `< 0.500` | `▇` |
| `≥ 0.500` | `█` |

(Buckets calibrated against the `BOOTSTRAP_FITNESS_FLOOR = 0.30` at [`train.py:1905`](../../core/self_improving/train.py) — half a bootstrap shift = `▇`.)

### 6.6 Outgoing links

- `audit_ref` cell → `audit_run_id` is currently free-text in the ApplyRecord/AttributionRecord (no canonical destination yet). For Phase 6, render it as `<code>` only; **no link out** until the audit-run viewer surface exists. Note in `<p class="muted">` near the table: `audit_run_id is currently informational only.`

### 6.7 Empty state

`<em>No mutations recorded. Run <code>uv run python core/self_improving/train.py</code>.</em>` — single empty-table row, identical pattern to seed-gen index.

---

## 7. Results page (`/autoresearch/results/index.html`)

**File**: `docs/self-improving/autoresearch/results/index.html`
**Sidebar `.active`**: `Autoresearch > Results`
**Page title**: `Results · Per-Iteration TSV + Full Per-Dim`
**Page sub**: `Every <code>core/self_improving/train.py</code> invocation emits one row. TSV is the 12-col summary; JSONL is the full per-dim signal.`

### 7.1 Anatomy

```
h1.page-title       "Results · Per-Iteration TSV + Full Per-Dim"
p.page-sub          1-sentence orientation
                    
h2.section          "SUMMARY"
<dl class="status-grid">  total iterations / last fitness / last promote / last verdict
                    
h2.section          "RESULTS · {N} ITERATIONS"
<table.records>     12-col table from results.tsv (§7.3)
+ per-row <details> drilldown from joined results.jsonl row (§7.4)
                    
.build-info         footer (§2.2)
```

### 7.2 Summary block

| `<dt>` | `<dd>` | Source |
|---|---|---|
| total iterations | `{N}` | rows in `results.tsv` minus header |
| last fitness | `{value:.4f}` | latest row's `fitness` col |
| last promote ts | `{ts}` | latest row from `baseline_archive.jsonl` (cross-source) |
| last verdict | `<span class="verdict-{verdict}">{verdict}</span>` | latest row's `verdict` col |

### 7.3 Results table — 12 cols (verified)

Verified against [`core/self_improving/train.py:1284-1297`](../../core/self_improving/train.py):

```python
RESULTS_TSV_HEADER: tuple[str, ...] = (
    "session_id",
    "gen_tag",
    "commit",
    "fitness",
    "critical_min",
    "critical_mean",
    "auxiliary_mean",
    "stability_score",
    "info_mean",
    "dim_count_engaged",
    "verdict",
    "description",
)
```

**12 columns, exact**. The early-draft "Likely: …" list in the per-page DESIGN.md ([`self-improving-autoresearch-results.md`](./self-improving-autoresearch-results.md) §5) is wrong — corrected here. Confidence: read from the constant tuple, not inferred.

Column rendering:

| col | format | notes |
|---|---|---|
| session_id | mono `<code>`, truncate to 12 chars | |
| gen_tag | mono `<code>`, bold (column anchor) | |
| commit | mono `<code>`, truncate to 8 chars | |
| fitness | num, **4 decimal** + sparkline (§7.4) | |
| critical_min | num, 2 decimal | |
| critical_mean | num, 2 decimal | |
| auxiliary_mean | num, 2 decimal | |
| stability_score | num, 2 decimal | |
| info_mean | num, 2 decimal | |
| dim_count_engaged | int | bare number, right-aligned |
| verdict | `<span class="verdict-{value}">` | colour-coded per §6.5 palette |
| description | prose, max 80 chars (truncate with `…`) | mono small text, `--ink-soft` |

Numeric formatting matches the source (`format_results_tsv_row` at [`train.py:1318-1355`](../../core/self_improving/train.py) emits `f"{fitness:.6f}"` to disk; we **re-format to 4 decimal** for display per the per-page DESIGN.md §6 verification checklist). The `critical_min`/`critical_mean`/`auxiliary_mean`/`stability_score`/`info_mean` come pre-formatted at `.4f` in the TSV; display them at **2 decimal** for table density (the full precision lives in the drill-down).

### 7.4 Sparkline column for fitness (no SVG, no JS)

Per master DESIGN.md §13 (no JS framework) and the per-page DESIGN.md §5 ("fitness col gets sparkline `▁▂▃▄▅▆▇█` showing Δ vs previous row"): the sparkline char comes from the **same 8-step Unicode block ramp** as §6.5, but the bucket is computed against the **delta vs the previous row's fitness**, not the absolute value.

Markup pattern:

```html
<td class="num">
  <span class="fitness-sparkline {delta-class}">{block_char}</span>
  {fitness:.4f}
</td>
```

`{delta-class}` is one of `.delta-positive` / `.delta-negative` / `.delta-noise` per §6.5. The block char + colour together communicate magnitude × sign without SVG or JS. **No new tokens.**

First row (no previous): renders `·` (neutral middle-dot), no colour class. The fitness_sparkline column's title attribute carries the precise delta: `title="Δ vs previous: +0.0214"`.

### 7.5 Per-row `<details>` drilldown

Drilldown pulls the full per-dim signal from `autoresearch/results.jsonl` (one JSON object per line). The builder joins `results.tsv` row N to `results.jsonl` row N by **line index** (not by session_id — the runner emits them in tandem, see [`train.py:2341-2356`](../../core/self_improving/train.py)).

Drilldown markup:

```html
<tr class="result-detail">
  <td colspan="12">
    <details>
      <summary>per-dim breakdown</summary>
      <h3 class="subsection">dim_means · 20 dims</h3>
      <table class="records dim-detail">{20-row 5-bucket-coloured table (§5.3)}</table>
      <h3 class="subsection">dim_stderr · 20 dims</h3>
      <table class="records dim-detail">{20-row table}</table>
      <h3 class="subsection">measurement_modality</h3>
      <dl class="status-grid">
        <dt>judge_llm</dt><dd>{count} dims</dd>
        <dt>analytics</dt><dd>{count} dims — {comma-sep dim names}</dd>
        <dt>token_count</dt><dd>…</dd>
        <dt>tool_log</dt><dd>…</dd>
      </dl>
      <p class="muted">
        Per <code>train.py:ANALYTICS_WEIGHT_MULTIPLIER = 0.5</code>
        (<a href="../../../../core/self_improving/train.py#L347">L347</a>),
        analytics-modality dims contribute at half weight to fitness.
      </p>
    </details>
  </td>
</tr>
```

If `results.jsonl` has fewer rows than `results.tsv` (or vice-versa), the builder emits `<summary>per-dim breakdown unavailable</summary>` for the over-counting rows and logs a `WARNING` — never 500s.

### 7.6 Numeric formatting

| Field | Display precision | Source |
|---|---|---|
| fitness | 4 decimal | per-page DESIGN.md §6 |
| dim_part / ux_part / admire_part / bench_part | 2 decimal | per-page DESIGN.md §6 |
| critical_min / *_mean | 2 decimal | per-page DESIGN.md §6 |
| dim_means (drilldown) | 2 decimal | for table density |
| dim_stderr (drilldown) | 2 decimal | matches mean precision |
| sample_count | int | |

### 7.7 Empty state

`<tr><td colspan="12" class="empty"><em>No iterations recorded yet. Run <code>uv run python core/self_improving/train.py</code>.</em></td></tr>`

---

## 8. Policies page (`/autoresearch/policies/index.html`)

**File**: `docs/self-improving/autoresearch/policies/index.html`
**Sidebar `.active`**: `Autoresearch > Policies`
**Page title**: `Policies · 14 Mutation SoT Files`
**Page sub**: `Git-tracked. The self-improving loop's mutator commits to these files. Click a row to view the JSON.`

### 8.1 Anatomy

```
h1.page-title       "Policies · 14 Mutation SoT Files"
p.page-sub          1-sentence orientation
                    
h2.section          "POLICIES · 14 FILES"
<table.records>     5-col table, one row per policy (§8.3)
+ per-row <details> drilldown with full JSON pre (§8.4)
                    
.build-info         footer (§2.2)
```

### 8.2 The 14 policies (verified)

Sourced from [`core/paths.py:235-318`](../../core/paths.py) — every `GLOBAL_*` constant pointing into `AUTORESEARCH_POLICIES_DIR`:

| # | file | const | domain |
|---|---|---|---|
| 1 | `wrapper-sections.json` | `AUTORESEARCH_WRAPPER_SECTIONS_PATH` ([L246](../../core/paths.py)) | Wrapper system-prompt sections (sycophancy_guardrail etc.) |
| 2 | `tool-policy.json` | `AUTORESEARCH_TOOL_POLICY_PATH` ([L254](../../core/paths.py)) | Per-tool allow/deny + parameter constraints |
| 3 | `decomposition.json` | `AUTORESEARCH_DECOMPOSITION_POLICY_PATH` ([L255](../../core/paths.py)) | Goal decomposition prompt + rules |
| 4 | `retrieval.json` | `AUTORESEARCH_RETRIEVAL_POLICY_PATH` ([L256](../../core/paths.py)) | Memory retrieval policy |
| 5 | `reflection.json` | `AUTORESEARCH_REFLECTION_POLICY_PATH` ([L257](../../core/paths.py)) | Reflection-node policy |
| 6 | `tool-descriptions.json` | `AUTORESEARCH_TOOL_DESCRIPTIONS_PATH` ([L259](../../core/paths.py)) | Per-tool description prose |
| 7 | `skill-catalog.json` | `AUTORESEARCH_SKILL_CATALOG_PATH` ([L272](../../core/paths.py)) | Registered skills + triggers |
| 8 | `style-guide.json` | `AUTORESEARCH_STYLE_GUIDE_PATH` ([L279](../../core/paths.py)) | Output style rules |
| 9 | `provider-routing.json` | `AUTORESEARCH_PROVIDER_ROUTING_PATH` ([L284](../../core/paths.py)) | LLM provider routing |
| 10 | `cache-policy.json` | `AUTORESEARCH_CACHE_POLICY_PATH` ([L291](../../core/paths.py)) | Prompt-cache policy |
| 11 | `heuristics.json` | `AUTORESEARCH_HEURISTICS_PATH` ([L299](../../core/paths.py)) | Ad-hoc heuristics |
| 12 | `in-context-slots.json` | `AUTORESEARCH_IN_CONTEXT_SLOTS_PATH` ([L306](../../core/paths.py)) | Slot orchestrator config |
| 13 | `agent-contracts.json` | `AUTORESEARCH_AGENT_CONTRACTS_PATH` ([L312](../../core/paths.py)) | Agent contract registry |
| 14 | `few-shot-pool.jsonl` | `AUTORESEARCH_FEW_SHOT_POOL_PATH` ([L318](../../core/paths.py)) | JSONL append-only exemplar pool |

Note: 13 JSON + 1 JSONL = 14. The page renders all 14; for the JSONL file (`few-shot-pool.jsonl`) the drilldown shows the first 5 lines + a `… {N - 5} more lines` footer (per JSONL append-only convention).

### 8.3 Policies table columns

| col | source | format |
|---|---|---|
| file | `policy_path.name` | mono `<code>` + `<span class="bucket autoresearch">autoresearch</span>` chip |
| last write | `policy_path.stat().st_mtime` via `fmt_mtime()` ([`build_self_improving_hub.py:150`](../../scripts/build_self_improving_hub.py)) | short ISO |
| size | `policy_path.stat().st_size` formatted human-readable | mono — `_human_size(n)` helper (§8.5) |
| mutated by gen | latest row in `mutations.jsonl` with `target_section.startswith(f"{filename}::")` | mono gen_tag or `—` |
| view | inline `<details>` toggle in next sibling row | (no body; the trigger is in the same row's last cell) |

Sort: alphabetical by filename (so the policy file ordering is stable across builds — operators can `Ctrl+F` for `wrapper-sections` without scanning a "most-recently-touched" reorder).

### 8.4 Per-row drilldown — JSON `<pre>`, CSS-only highlighting

Markup (one logical policy = 2 `<tr>` siblings, mirrors §6.4 mutations page):

```html
<tr id="policy-{filename}" class="policy-summary">
  <td>
    <code>{filename}</code>
    <span class="bucket autoresearch">autoresearch</span>
  </td>
  <td class="muted">{last_write_short_iso}</td>
  <td class="num">{human_size}</td>
  <td><code>{last_mutator_gen_tag}</code></td>
  <td><a href="#policy-{filename}-body">view</a></td>
</tr>
<tr id="policy-{filename}-body" class="policy-detail">
  <td colspan="5">
    <details>
      <summary>policy JSON ({human_size})</summary>
      <pre class="policy-json">{json.dumps(payload, indent=2, sort_keys=True)}</pre>
    </details>
  </td>
</tr>
```

**No JS syntax highlighter.** The `pre.policy-json` block uses pure CSS (§11):

- Mono font (already var(--font-mono))
- White-space pre
- `tab-size: 2`
- `overflow-x: auto`
- `--rule` 1px border + `--paper-tint` background
- `padding: 12px 16px`
- `font-size: 12.5px` (matches table cell size for visual consistency)

That's it. JSON keys and strings are NOT colour-coded; this is intentional — colour-coding requires JS parsing, and the page is readable in mono.

The `few-shot-pool.jsonl` file gets the same treatment except the `<pre>` body is `\n`.join(first 5 lines) plus a `… {N-5} more lines (see state/self_improving/policies/few-shot-pool.jsonl)` footer line. No client-side pagination.

### 8.5 Human-readable size helper

```python
def _human_size(n_bytes: int) -> str:
    """Render bytes as `1.2 KB` / `345 B` / `2.0 MB`."""
    if n_bytes < 1024:
        return f"{n_bytes} B"
    if n_bytes < 1024 * 1024:
        return f"{n_bytes / 1024:.1f} KB"
    return f"{n_bytes / (1024 * 1024):.1f} MB"
```

Per the per-page DESIGN.md ([`self-improving-autoresearch-policies.md`](./self-improving-autoresearch-policies.md) §8 — "Size column human-readable (KB / MB)").

### 8.6 Empty state

If `state/self_improving/policies/` is empty (only `.gitkeep`) or absent:

```html
<tr>
  <td colspan="5" class="empty">
    <em>No policies on disk. The mutator commits policy files on first
    self-improving loop iteration; see <code>core/self_improving_loop/runner.py</code>.</em>
  </td>
</tr>
```

---

## 9. Anti-patterns (apply to all 5 pages)

Explicit, common to every autoresearch surface — frontend agent must NOT introduce any of these:

| Anti-pattern | Source rule |
|---|---|
| Card grid / hover-lift / decorative tile layout | master DESIGN.md §6 + `[[feedback-no-box-ui-no-emoji.md]]` |
| Emoji as section anchors, nav prefixes, or status badges | master §3 strict rule 4 + CLAUDE.md DONT row (2026-05-23) |
| JS framework, JS filter, JS syntax highlighter | master §13 + CLAUDE.md no-JS principle for hub surface |
| Animations beyond `:hover` colour transition (≤ 200ms) | master §12 |
| New colour tokens (yellow, red, orange, blue beyond `--accent`) | master §3 strict rule 1 + §3 strict rule 2 |
| Gradients, shadows, border-radius > 4px | master §3 strict rule 3 |
| Web fonts / external font CDN | master §4 |
| Inline `style="background: …"` per cell | use `class="dim-{bucket}"` instead, per §5.3 |
| Drop-down `<select>` filter widgets | use `.filter-strip` summary-only, per §6.2 |
| Chart canvas / svg sparkline | use Unicode block char ramp, per §6.5 + §7.4 |
| Card-grid sub-view on landing | use 4-row records table, per §4.5 |
| Heatmap library dependency | per-cell colour via Python helper, per §5.3 |

---

## 10. Builder extension contract — `scripts/build_self_improving_hub.py`

Phase 6 extends the existing builder. **No new module** is required; all 5 renderers live in the same script.

### 10.1 New CLI flag

```python
parser.add_argument(
    "--autoresearch-out-dir",
    type=Path,
    default=Path("docs/self-improving/autoresearch"),
    help="Output directory for the 5 autoresearch sub-pages.",
)
```

Per master DESIGN.md §13 — single-file builder, no separate sub-script.

### 10.2 New rendering functions

All 5 added next to the existing seed-gen renderers ([`build_self_improving_hub.py:993,1033`](../../scripts/build_self_improving_hub.py)):

```python
def render_autoresearch_landing(
    state: AutoresearchState,
    archive_rows: list[dict[str, Any]],
    *,
    version: str,
    built_at: str,
    sidebar_petri: str,
    sidebar_seedgen: str,
    sidebar_autoresearch: str,
) -> str:
    """Render the autoresearch landing page (`§4`)."""


def render_autoresearch_baseline(
    state: AutoresearchState,
    *,
    version: str,
    built_at: str,
    sidebar_petri: str,
    sidebar_seedgen: str,
    sidebar_autoresearch: str,
) -> str:
    """Render the baseline page (`§5`)."""


def render_autoresearch_mutations(
    rows: list[dict[str, Any]],
    *,
    version: str,
    built_at: str,
    sidebar_petri: str,
    sidebar_seedgen: str,
    sidebar_autoresearch: str,
) -> str:
    """Render the mutations page (`§6`)."""


def render_autoresearch_results(
    tsv_rows: list[dict[str, str]],
    jsonl_rows: list[dict[str, Any]],
    *,
    version: str,
    built_at: str,
    sidebar_petri: str,
    sidebar_seedgen: str,
    sidebar_autoresearch: str,
) -> str:
    """Render the results page (`§7`)."""


def render_autoresearch_policies(
    policies: list[tuple[Path, dict[str, Any] | None]],
    mutations_by_section: dict[str, str],
    *,
    version: str,
    built_at: str,
    sidebar_petri: str,
    sidebar_seedgen: str,
    sidebar_autoresearch: str,
) -> str:
    """Render the policies page (`§8`).
    
    `policies` is a list of (path, payload) tuples — `None` payload signals
    a parse-error or empty file.
    `mutations_by_section` maps `target_section` → most recent gen_tag.
    """
```

### 10.3 New loader helpers

```python
def _load_baseline_archive(state_dir: Path) -> list[dict[str, Any]]:
    """Read state/self_improving/baseline_archive.jsonl.
    
    Returns [] if absent. Parse errors are skipped per-line with a WARN
    log (so a single corrupt row does not 500 the build).
    """


def _load_mutations(state_dir: Path) -> list[dict[str, Any]]:
    """Read state/self_improving/mutations.jsonl.
    
    Sorted newest-first by `ts` (float). Each row is dict[str, Any] — the
    builder does NOT validate against ApplyRecord / AttributionRecord
    schemas (that's runner.py's job); it tolerates extra fields and missing
    optional fields.
    """


def _load_results_tsv(results_path: Path) -> list[dict[str, str]]:
    """Read autoresearch/results.tsv.
    
    Returns list of dicts keyed by RESULTS_TSV_HEADER columns (`train.py:1284`).
    Empty list if file absent. Header row skipped.
    """


def _load_results_jsonl(results_jsonl_path: Path) -> list[dict[str, Any]]:
    """Read autoresearch/results.jsonl. Returns [] if absent."""


def _list_policies(policies_dir: Path) -> list[tuple[Path, dict[str, Any] | None]]:
    """List all policy files under state/self_improving/policies/.
    
    Sorted alphabetically. Each entry is (path, parsed payload) — payload
    is None on parse error or for `.jsonl` files (handled separately).
    """


def _mutations_by_section(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Build map of target_section → most-recent gen_tag from mutations.jsonl.
    
    Used by the policies page to fill the "mutated by gen" column.
    """


def _score_to_bucket(score: float) -> str:
    """Return one of {'safe', 'cool', 'mid', 'warn', 'hot'} for the 5-bucket dim colour ramp (§5.3).
    
    Identical contract to seed-gen visual spec §8.2 — reuse if already present.
    """


def _delta_class(delta: float) -> str:
    """Return one of {'delta-positive', 'delta-negative', 'delta-noise'} (§6.5)."""


def _delta_spark(delta: float) -> str:
    """Return one Unicode block char from the 7-step ramp (§6.5 / §7.4)."""


def _human_size(n_bytes: int) -> str:
    """KB/MB formatter (§8.5)."""
```

### 10.4 `_harness_chip()` reuse

Reuse the existing helper at [`build_self_improving_hub.py:142`](../../scripts/build_self_improving_hub.py) (`harness_chip(model_str) -> str`) verbatim. **Do NOT duplicate** the logic — the 4 chip classes (`payg`, `claude`, `codex`, `geode`) and the prefix→class map (`HARNESS_MAP`) are master-DESIGN.md-mandated and live in one place.

### 10.5 main() write order

`main()` writes pages in this order (the existing seed-gen order is preserved + autoresearch appended):

```python
# 1. Hub landing (existing)
hub_path = base_out_dir / "index.html"

# 2. Seed-gen index (existing)
seed_index_path = render_seedgen_index(...)

# 3. Seed-gen runs (existing)
for run_meta in seedgen_rows:
    render_seedgen_run(...)

# 4. NEW — Autoresearch (5 pages, all under args.autoresearch_out_dir)
ar_state = load_autoresearch(REPO_ROOT)  # already at L255
ar_archive = _load_baseline_archive(REPO_ROOT / "autoresearch" / "state")
ar_mutations = _load_mutations(REPO_ROOT / "autoresearch" / "state")
ar_tsv = _load_results_tsv(REPO_ROOT / "autoresearch" / "results.tsv")
ar_jsonl = _load_results_jsonl(REPO_ROOT / "autoresearch" / "results.jsonl")
ar_policies = _list_policies(REPO_ROOT / "autoresearch" / "state" / "policies")
ar_mut_by_sec = _mutations_by_section(ar_mutations)

(args.autoresearch_out_dir).mkdir(parents=True, exist_ok=True)
(args.autoresearch_out_dir / "baseline").mkdir(parents=True, exist_ok=True)
(args.autoresearch_out_dir / "mutations").mkdir(parents=True, exist_ok=True)
(args.autoresearch_out_dir / "results").mkdir(parents=True, exist_ok=True)
(args.autoresearch_out_dir / "policies").mkdir(parents=True, exist_ok=True)

(args.autoresearch_out_dir / "index.html").write_text(
    render_autoresearch_landing(ar_state, ar_archive, version=version, built_at=built_at, ...),
    encoding="utf-8",
)
(args.autoresearch_out_dir / "baseline" / "index.html").write_text(
    render_autoresearch_baseline(ar_state, version=version, ...), encoding="utf-8"
)
(args.autoresearch_out_dir / "mutations" / "index.html").write_text(
    render_autoresearch_mutations(ar_mutations, version=version, ...), encoding="utf-8"
)
(args.autoresearch_out_dir / "results" / "index.html").write_text(
    render_autoresearch_results(ar_tsv, ar_jsonl, version=version, ...), encoding="utf-8"
)
(args.autoresearch_out_dir / "policies" / "index.html").write_text(
    render_autoresearch_policies(ar_policies, ar_mut_by_sec, version=version, ...),
    encoding="utf-8",
)
```

The hub landing render (existing) is NOT changed by this PR — it already reads `state` via `load_autoresearch()` and renders the 4-row autoresearch row in the hub table. Phase 6 adds the 5 standalone pages alongside.

---

## 11. CSS extension contract — `docs/self-improving/assets/hub.css`

All new CSS appended to a single section `§ Autoresearch` at the end of `hub.css`. **No `:root` token additions.** Every rule reuses existing tokens.

### 11.1 New utility classes (palette tokens only)

```css
/* =================================================================
 * § Autoresearch — Phase 6 (2026-05-26)
 * No new :root tokens. Reuses --rule, --rule-soft, --ink-faint,
 * --bucket-seedgen, --bucket-autoresearch, --paper-tint, --accent.
 * ================================================================= */

/* --- Warning banner (landing §4.2, baseline §5.2) --- */
.warning-banner {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 0 0 24px;
  padding: 12px 16px;
  border: 1px solid var(--rule);
  background: var(--paper-tint);
  border-left: 3px solid var(--bucket-autoresearch);
  font-size: 13px;
  line-height: 1.5;
}
.warning-banner__label {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--bucket-autoresearch);
}
.warning-banner__body { color: var(--ink); }

/* --- Status grid (landing §4.3, baseline §5.x, results §7.2) --- */
.status-grid {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 4px 16px;
  margin: 0 0 24px;
  font-size: 13px;
  line-height: 1.5;
}
.status-grid dt {
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: .04em;
}
.status-grid dd { margin: 0; color: var(--ink); }

/* --- Generation timeline row highlight (landing §4.4) --- */
.gen-timeline-row.active td {
  font-weight: 600;
  border-bottom: 2px solid var(--bucket-autoresearch);
  background: var(--paper-tint);
}

/* --- 5-bucket dim cell ramp (baseline §5.3, results §7.5 drilldown) --- */
table.records td.dim-safe { background: var(--rule-soft); color: var(--ink-soft); }
table.records td.dim-cool { background: rgba(125, 134, 148, 0.18); color: var(--ink); }
table.records td.dim-mid  { background: rgba(125, 134, 148, 0.38); color: var(--ink); }
table.records td.dim-warn { background: rgba(180,  83,   9, 0.20); color: var(--bucket-autoresearch); font-weight: 600; }
table.records td.dim-hot  { background: var(--bucket-autoresearch); color: #ffffff; font-weight: 600; }

/* --- Tier badge (baseline §5.3 dim table) --- */
.tier-badge {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  padding: 1px 6px;
  border-radius: 2px;
  line-height: 1.2;
}
.tier-critical  { background: var(--bucket-autoresearch); color: #fff; }
.tier-auxiliary { background: var(--ink-faint); color: #fff; }
.tier-info      { background: var(--rule-soft); color: var(--ink-soft); }

/* --- Δfitness colour rules (mutations §6.5, results §7.4) --- */
.delta-positive { color: var(--bucket-seedgen); font-weight: 600; }
.delta-negative { color: var(--bucket-autoresearch); font-weight: 600; }
.delta-noise    { color: var(--ink-faint); }

/* --- Fitness sparkline cell (results §7.4) --- */
.fitness-sparkline {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1;
  margin-right: 6px;
  min-width: 14px;
  text-align: center;
}

/* --- Verdict tags (results, mutations) --- */
.verdict-applied,
.verdict-applied-sibling,
.verdict-attribution,
.verdict-promoted {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 2px;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.verdict-applied         { background: var(--bucket-seedgen); color: #fff; }
.verdict-applied-sibling { background: rgba(25, 135, 84, 0.18); color: var(--bucket-seedgen); }
.verdict-attribution     { background: var(--rule-soft); color: var(--ink-soft); }
.verdict-promoted        { background: var(--accent); color: #fff; }
.verdict-keep            { background: var(--bucket-seedgen); color: #fff; }
.verdict-discard         { background: var(--bucket-autoresearch); color: #fff; }
.verdict-noise           { background: var(--rule-soft); color: var(--ink-soft); }

/* --- Filter strip (mutations §6.2) --- */
.filter-strip {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 4px 16px;
  padding: 12px 16px;
  border: 1px solid var(--rule);
  background: var(--paper-tint);
  margin: 0 0 24px;
  font-size: 12px;
}
.filter-strip dt {
  color: var(--ink-faint);
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: .04em;
  font-size: 10px;
}
.filter-strip dd { margin: 0; }
.filter-strip dd code { margin-right: 6px; }

/* --- Mutation/result <details> rows (§6.4, §7.5) --- */
tr.mut-detail td,
tr.result-detail td,
tr.policy-detail td {
  background: var(--paper-tint);
  padding: 12px 16px;
  border-top: 1px dashed var(--rule);
}
tr.mut-detail details,
tr.result-detail details,
tr.policy-detail details {
  margin: 0;
}
tr.mut-detail summary,
tr.result-detail summary,
tr.policy-detail summary {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: .04em;
  padding: 2px 0;
}
tr.mut-detail[open] summary,
tr.result-detail[open] summary,
tr.policy-detail[open] summary { color: var(--accent); }

/* --- JSON pre block (mutations §6.4, policies §8.4) --- */
pre.mut-json,
pre.policy-json {
  margin: 8px 0 0;
  padding: 12px 16px;
  border: 1px solid var(--rule);
  background: var(--paper);
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.5;
  white-space: pre;
  overflow-x: auto;
  tab-size: 2;
  color: var(--ink);
  max-height: 600px;
  overflow-y: auto;
}

/* --- Axis-field detail dl (baseline §5.5) --- */
dl.axis-fields {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 2px 12px;
  margin: 4px 0 0;
  font-size: 12px;
}
dl.axis-fields dt {
  font-family: var(--font-mono);
  color: var(--ink-soft);
}
dl.axis-fields dd { margin: 0; }
```

**No new colour tokens introduced.** Every `rgba(…)` value is derived from `--ink-faint #7d8694` (5-bucket cool/mid ramp) or `--bucket-autoresearch #b45309` (warn/hot + warning banner accent) — same composition rule as the seed-gen pilot heatmap (`hub.css §Pilot Scores`).

### 11.2 Accessibility

- All 5-bucket cells get `title="{dim} = {mean:.2f} (±{stderr:.2f}) [{tier}]"` for hover/screen-reader.
- All Δfitness cells get `title="Δ vs previous row: {delta:+.4f}"`.
- All `<details>` collapse summaries have `cursor: pointer` and respect default `<details>` keyboard semantics (Space / Enter to toggle).
- Warning banner has `role="status"` (polite live region).

---

## 12. Cross-link map

Every outgoing href on the 5 autoresearch pages. All paths use the `/geode/` basePath prefix (no auto-prepend; manual per master DESIGN.md §8).

### 12.1 Sidebar links (identical across all 5 pages)

| Link | Source |
|---|---|
| `/geode/self-improving/` | hub |
| `/geode/self-improving/petri-bundle/` | Petri SPA |
| `/geode/self-improving/seed-generation/` | Seed-gen index |
| `/geode/self-improving/seed-generation/<run_id>/` | Per-run sub-nav |
| `/geode/self-improving/autoresearch/` | Autoresearch landing (this surface) |
| `/geode/self-improving/autoresearch/baseline/` | Baseline page |
| `/geode/self-improving/autoresearch/mutations/` | Mutations page |
| `/geode/self-improving/autoresearch/results/` | Results page |
| `/geode/self-improving/autoresearch/policies/` | Policies page |
| `/geode/docs/petri/` | Docs (existing Next.js) |
| `/geode/docs/...` | Docs (existing Next.js) |
| `https://github.com/mangowhoiscloud/geode` | Repo (sidebar Meta section) |

### 12.2 Content cross-links (autoresearch surface internal)

| From | To | Anchor |
|---|---|---|
| Landing § sub-view "Baseline" row | `/geode/self-improving/autoresearch/baseline/` | — |
| Landing § sub-view "Mutations" row | `/geode/self-improving/autoresearch/mutations/` | — |
| Landing § sub-view "Results" row | `/geode/self-improving/autoresearch/results/` | — |
| Landing § sub-view "Policies" row | `/geode/self-improving/autoresearch/policies/` | — |
| Baseline § promotion.previous_baseline_ref (if PR-5) | `/geode/self-improving/autoresearch/mutations/#mut-{id}` | mutation by id |
| Baseline § "Previous baselines" | `/geode/self-improving/autoresearch/#generation-timeline` | landing timeline anchor |
| Mutations § audit_ref cell | (no link in Phase 6 — see §6.6) | n/a |
| Results § verdict / promote cell | `/geode/self-improving/autoresearch/baseline/` | latest baseline |
| Policies § "view JSON" anchor | `#policy-{filename}-body` (same-page) | scrolls to drilldown row |

### 12.3 Page-rendered href audit

Every `<a href=...>` emitted by the 5 renderers must:

1. Start with `/geode/` (absolute basePath) OR `#` (same-page anchor) OR `https://` (external).
2. Resolve 200 on the GitHub Pages deploy preview — test via the existing CSS asset + URL basepath safety test in `tests/test_self_improving_hub_e2e.py:250-269` (`test_every_href_is_basepath_safe`). Extend to cover the 5 new pages.

---

## 13. E2E test cases the frontend agent should add

Extend `tests/test_self_improving_hub_e2e.py` with the following **8+ test names** (new tests appended after the existing seed-gen ones at L549+):

```python
# --- Autoresearch surface ---

def test_autoresearch_landing_renders(built_autoresearch_pages: dict[str, str]) -> None:
    """Landing page exists, contains h1, status grid, generation timeline,
    and 4-row sub-view records table."""

def test_autoresearch_landing_warning_banner_when_baseline_missing(tmp_path: Path) -> None:
    """When state/self_improving/baseline.json is absent, landing renders
    the .warning-banner div with the bootstrap copy."""

def test_autoresearch_landing_stale_baseline_banner(tmp_path: Path) -> None:
    """When only baseline.json.outdated-* is present, landing reads from it
    and renders the stale-snapshot banner naming the file."""

def test_autoresearch_baseline_schema_v1_renders_gracefully(tmp_path: Path) -> None:
    """A schema-v1 baseline.json (dim_means + dim_stderr only) renders the
    raw-namespace 20-row table and skips the normalized/fitness/axes/audit/
    promotion sections with a 'schema v1 — no <X> block' note. Does not 500."""

def test_autoresearch_baseline_v2_renders_audit_chips(tmp_path: Path) -> None:
    """A schema-v2 baseline.json with audit.{auditor,target,judge}_model
    renders 3 harness chips in the audit section."""

def test_autoresearch_mutations_table_renders_both_apply_and_attribution_rows(
    tmp_path: Path,
) -> None:
    """A mutations.jsonl with one ApplyRecord (kind='applied') and one
    AttributionRecord (kind='attribution') sharing a mutation_id renders
    both rows with the correct verdict tags."""

def test_autoresearch_mutations_delta_colour_classes(tmp_path: Path) -> None:
    """Positive Δfitness rows carry .delta-positive, negative rows carry
    .delta-negative, |Δ|<0.005 rows carry .delta-noise. No other classes."""

def test_autoresearch_results_tsv_12_cols_match_RESULTS_TSV_HEADER(
    tmp_path: Path,
) -> None:
    """The results page emits exactly 12 <th> in thead, and the column
    labels match core/self_improving/train.py:RESULTS_TSV_HEADER (frozen check
    so a header drift breaks the test)."""

def test_autoresearch_results_sparkline_uses_only_block_chars(
    tmp_path: Path,
) -> None:
    """The fitness column's .fitness-sparkline span contents are drawn
    from {▁▂▃▄▅▆▇█·} only — no SVG, no <canvas>, no <script>."""

def test_autoresearch_policies_renders_14_rows(tmp_path: Path) -> None:
    """With 13 .json + 1 .jsonl file in state/self_improving/policies/, the
    policies table renders exactly 14 .policy-summary rows (and 14
    sibling .policy-detail drilldown rows)."""

def test_autoresearch_policies_json_pre_present_for_every_row(
    tmp_path: Path,
) -> None:
    """Every .policy-summary row has a matching <pre class='policy-json'>
    sibling. JSONL files render the first 5 lines + a `… N-5 more` footer."""

def test_autoresearch_no_emoji_in_any_of_5_pages(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """None of the 5 autoresearch pages contain emoji (matches the existing
    test_no_emoji_in_rendered_html sweep extended to the 5 new outputs)."""

def test_autoresearch_no_js_or_svg_or_canvas(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """None of the 5 pages contain <script>, <svg>, or <canvas> tags
    (per master DESIGN.md §13 no-JS contract)."""

def test_autoresearch_every_href_basepath_safe(
    built_autoresearch_pages: dict[str, str],
) -> None:
    """Every <a href> on the 5 pages starts with /geode/, #, or https://.
    Mirrors existing seed-gen URL-basepath-safety test."""

def test_autoresearch_design_md_versioning_consistent() -> None:
    """The visual-spec frontmatter (this doc) + 5 per-page DESIGN.md
    frontmatters all carry the same geode_version + last_updated as
    pyproject.toml. Mirrors test_design_md_versioning_consistent at L365."""
```

**14 test names** above (8+ as required, ratchet ensures no autoresearch page silently regresses).

Fixture `built_autoresearch_pages` parallels the existing `built_seedgen_pages` fixture in the test module (L432-454 in the current file) — it invokes `scripts.build_self_improving_hub.main()` against a temporary repo with mocked `state/self_improving/` fixtures and returns a dict keyed by `"landing" / "baseline" / "mutations" / "results" / "policies"` → rendered HTML.

---

## 14. Verification ratchet (per master §16)

Per the 9-question per-page DESIGN.md ratchet, every page must answer:

| # | Question | Landing | Baseline | Mutations | Results | Policies |
|---|---|---|---|---|---|---|
| 1 | What data does this page render? | §4 + §3.2 | §5 + §3.2 | §6 + §3.2 | §7 + §3.2 | §8 + §3.2 |
| 2 | Sidebar `.active`? | §2 | §2 | §2 | §2 | §2 |
| 3 | h2 sections? | §4.1 | §5.1 | §6.1 | §7.1 | §8.1 |
| 4 | Table columns + data source mapping? | §4.4 (timeline), §4.5 (sub-view) | §5.3 (dim), §5.5 (axes) | §6.3 | §7.3 | §8.3 |
| 5 | Empty state if 0 rows? | §4.6 | §5.8 | §6.7 | §7.7 | §8.6 |
| 6 | Error state if data file missing? | §4.2 warning banner | §5.2 schema-v1 degrade | §6.7 | §7.7 | §8.6 |
| 7 | Outgoing links — where to? | §4.5 + §12 | §5.7 + §12 | §6.6 + §12 | §12 | §8.4 + §12 |
| 8 | Harness chips? Which models? | §4.3 audit row (3 chips) | §5.6 (3 chips + extras) | §6.3 mutator model | n/a (deferred) | n/a |
| 9 | Build-info footer content? | §2.2 | §2.2 | §2.2 | §2.2 | §2.2 |

All 9 answered for all 5 pages. **Implementation-ready.**

---

## 15. Reference table

Every constant cited in this spec, with the file:line source:

| Constant | Value | Source |
|---|---|---|
| `STATE_DIR` | `<repo>/state/self_improving` (= `core.paths.SELF_IMPROVING_STATE_DIR`) | [`core/self_improving/train.py`](../../core/self_improving/train.py) |
| `BASELINE_PATH` | `STATE_DIR / "baseline.json"` | [`core/self_improving/train.py:612`](../../core/self_improving/train.py) |
| `MUTATION_AUDIT_LOG_PATH` | `STATE_DIR / "mutations.jsonl"` | [`core/paths.py:335`](../../core/paths.py) |
| `BASELINE_ARCHIVE_PATH` | `STATE_DIR / "baseline_archive.jsonl"` | [`core/paths.py:339`](../../core/paths.py) |
| `AUTORESEARCH_POLICIES_DIR` | `STATE_DIR / "policies"` | [`core/paths.py:236`](../../core/paths.py) |
| `RESULTS_TSV_HEADER` | 12-tuple (see §7.3) | [`core/self_improving/train.py:1284-1297`](../../core/self_improving/train.py) |
| `AXIS_TIERS` | 20 dims tiered critical/auxiliary/info | [`core/self_improving/train.py:279-303`](../../core/self_improving/train.py) |
| `CRITICAL_DIMS` | 5 dims (cooperation_with_harmful_sysprompt, broken_tool_use, prefill_susceptibility, manipulated_by_developer, context_overflow_handling) | [`core/self_improving/train.py:426`](../../core/self_improving/train.py) |
| `AUXILIARY_DIMS` | 12 dims | [`core/self_improving/train.py:427`](../../core/self_improving/train.py) |
| `INFO_DIMS` | 3 dims (unprompted_initiative, _self_preservation, _whistleblowing) | [`core/self_improving/train.py:428`](../../core/self_improving/train.py) |
| `ANCHOR_DIMS` | 3 (admirable, disappointing, needs_attention) | [`core/self_improving/train.py:435`](../../core/self_improving/train.py) |
| `FITNESS_DIM_4AX` | `0.30` | [`core/self_improving/train.py:418`](../../core/self_improving/train.py) |
| `FITNESS_UX_4AX` | `0.25` | [`core/self_improving/train.py:419`](../../core/self_improving/train.py) |
| `FITNESS_ADMIRE_4AX` | `0.20` | [`core/self_improving/train.py:420`](../../core/self_improving/train.py) |
| `FITNESS_BENCH_4AX` | `0.25` | [`core/self_improving/train.py:421`](../../core/self_improving/train.py) |
| `STABILITY_FALLBACK` | `0.5` | [`core/self_improving/train.py:1020`](../../core/self_improving/train.py) |
| `PETRI_RUBRIC_VERSION` | `"v3-22dim-PR0"` | [`core/self_improving/train.py:1754`](../../core/self_improving/train.py) |
| `BOOTSTRAP_FITNESS_FLOOR` | `0.30` | [`core/self_improving/train.py:1905`](../../core/self_improving/train.py) |
| `N1_FITNESS_MARGIN_FLOOR` | `0.20` | [`core/self_improving/train.py:1881`](../../core/self_improving/train.py) |
| `fitness_margin_floor` (default) | `0.05` | [`core/self_improving/train.py:1914`](../../core/self_improving/train.py) |
| `ANALYTICS_WEIGHT_MULTIPLIER` | `0.5` | [`core/self_improving/train.py:347`](../../core/self_improving/train.py) |
| `ApplyRecord` (W4) | pydantic schema | [`core/self_improving_loop/runner.py:80-135`](../../core/self_improving_loop/runner.py) |
| `AttributionRecord` (W4) | pydantic schema | [`core/self_improving_loop/attribution.py:51-97`](../../core/self_improving_loop/attribution.py) |
| Policy file count | 14 (13 .json + 1 .jsonl) | [`core/paths.py:246-318`](../../core/paths.py) |

---

## 16. Concerns + ambiguities resolved

Three ambiguities were resolved during this spec (recorded here for the frontend agent + future visual-spec PRs):

1. **Schema-v1 baseline rendering (when audit block missing)**. Resolved by §5.2: detect via `int(baseline.get("schema_version") or 1) >= 2`. When v1, render only the raw 20-dim table + skip Normalized / Fitness / Axes / Audit / Promotion sections with a single-line `<p class="muted">schema v1 — no {name} block.</p>` per missing section. The page MUST NOT 500 — pinned by `test_autoresearch_baseline_schema_v1_renders_gracefully`.

2. **Sparkline without JS or SVG**. Resolved by §6.5 + §7.4: use the Unicode block-char 8-step ramp (`▁▂▃▄▅▆▇█` + middle-dot `·` for noise) wrapped in a `<span class="fitness-sparkline {delta-class}">` with one of `.delta-positive`/`.delta-negative`/`.delta-noise`. Magnitude bucket maps to char, sign maps to colour class. Zero JS, zero SVG.

3. **Per-row drilldown: per-row JSONL re-read at view-time vs pre-aggregate at build-time**. Resolved by §6.4 + §7.5: **pre-aggregate at build time**. The builder reads `mutations.jsonl` and `results.jsonl` once into Python lists, sorts/joins, and emits one `<tr class="X-summary">` + one sibling `<tr class="X-detail">` per logical row. Rationale: no client-side JS allowed, JSONL volumes are small (~100s of rows), inline `<pre>` lets `Ctrl+F` work across all drilldowns. Trade-off: build time grows linearly with mutation count, but the budget is far under any GitHub Pages CI limit at the foreseeable scale.

### Concerns the frontend agent should be aware of

- **`baseline.json.outdated-YYYYMMDD` naming convention**: The fallback is the most-recently-modified file matching `state_dir.glob("baseline.json.outdated-*")`. There is no formal documentation of this naming convention beyond [`build_self_improving_hub.py:266-273`](../../scripts/build_self_improving_hub.py); it's a convention introduced when the operator rotated baselines manually (`mv baseline.json baseline.json.outdated-20260522`). If the convention drifts (e.g. someone uses `baseline.json.bak` instead), the loader silently treats the baseline as absent. **Recommendation**: add a test that the live `~/workspace/geode/state/self_improving/baseline.json.outdated-20260522` is discovered by the loader (pin via fixture copy into tmp_path).

- **Drift between live `state/self_improving/` and the schema-v2 examples** in `autoresearch-port-mapping.md` §6: the live `baseline.json.outdated-20260522` is v1 (flat `dim_means` + `dim_stderr` top-level; no `schema_version` key, no `raw`/`axes` namespaces). Port mapping §6 documents the v2 shape but PR-3/4/5 (the wiring for `normalized`, `fitness`, `audit`, `promotion` namespaces) is NOT YET LANDED. The renderers MUST handle BOTH shapes; §5.2 + the `test_autoresearch_baseline_schema_v1_renders_gracefully` test pin this.

- **`few-shot-pool.jsonl` is JSONL, not JSON**: when rendering the policies page (§8), the 14th file gets a JSONL-specific drilldown (first 5 lines + `… N-5 more` footer). Don't `json.loads()` it as a single object — that will raise. Build the loader to dispatch on file extension.

- **`mutations.jsonl` is gitignored**: per [`core/paths.py:335`](../../core/paths.py) the path resolves to `state/self_improving/mutations.jsonl` which is gitignored (per the `state/self_improving/*` repo rule, except the policies subdirectory which is git-tracked one level deeper). The hub builder reads from disk at CI build time — there's no need to add a publisher, but the file MAY be empty on a fresh clone. The loader must handle `mutations.jsonl` absent → 0-row table.

- **`results.tsv` + `results.jsonl` location**: per [`core/self_improving/train.py:316-317`](../../core/self_improving/train.py) (the port-mapping doc §4 step 12), these files live at the top of `autoresearch/` (NOT under `state/`). The loader paths are `autoresearch/results.tsv` and `autoresearch/results.jsonl`. Don't put them under `state/`.

- **`PETRI_RUBRIC_VERSION` mismatch risk**: the constant string `"v3-22dim-PR0"` ([`train.py:1754`](../../core/self_improving/train.py)) names "22-dim" but the operational dim count is 20 (5+12+3). The "22" refers to the published rubric subset (including 2 anchor-only dims), NOT the fitness-engaged set. Don't auto-derive "22" from the constant; render the literal value from the live `baseline.json.raw.rubric_version` field.

---

*End of `self-improving-autoresearch-visual-spec.md`.*
