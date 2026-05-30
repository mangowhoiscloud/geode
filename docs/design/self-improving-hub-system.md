---
title: GEODE Self-Improving Hub Design System
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
sibling_pages:
  - self-improving-hub.md
  - self-improving-petri-bundle.md
  - self-improving-seed-generation-index.md
  - self-improving-seed-generation-run.md
  - self-improving-autoresearch.md
  - self-improving-autoresearch-baseline.md
  - self-improving-autoresearch-mutations.md
  - self-improving-autoresearch-results.md
  - self-improving-autoresearch-evidence.md
  - self-improving-autoresearch-policies.md
---

# GEODE Self-Improving Hub · Design System

> Master DESIGN.md for the 9-page hub surface under `/geode/self-improving/`.
> Sibling per-page docs in `docs/design/self-improving-*.md` (one per page).
> Frontend agents must read this **before** touching any HTML/CSS.

## 1. Mission

`/geode/self-improving/` is the discovery surface for GEODE's autonomous self-improvement loop. Three telemetry streams converge here:

- **Petri** — inspect_ai audit transcripts (`.eval` archives)
- **Seed Generation** — per-run candidates, survivors, evolved variants, meta-review
- **Autoresearch** — baseline + mutations + results + 14 policy SoT files

Visitors range from operators (daily status check) to external readers (PR demo). The hub must orient both in under 10 seconds.

## 2. Visual Theme & Atmosphere

**Mood**: inspect_ai SPA-adjacent. Bootstrap-light primary `#0d6efd` blue, system sans, monospace for IDs. Reads like a server-status page — calm, dense, no marketing tone.

**Adjectives**: neutral, dense, monochromatic-with-data-bursts, terminal-adjacent, no chrome.

**What it is not**: card grid with hover-lifts, emoji navigation, gradient hero, marketing CTA, dark mode (single light substrate).

**Inspiration touchstones**:
- inspect_ai's bundled SPA (`docs/petri-bundle/index.html` v0.3.220)
- cotton's editorial restraint discipline (`~/workspace/cotton/wiki/design/10-frontend-design.md` — single substrate, no warm tones, monospace for data, prose for human content)
- Bootstrap 5.3 token vocabulary (only color/spacing primitives reused)

## 3. Color Palette & Roles

| Token | Hex | Role |
|---|---|---|
| `--ink` | `#1a1f29` | Primary text |
| `--ink-soft` | `#4a5260` | Secondary text |
| `--ink-faint` | `#7d8694` | Captions, metadata, section labels |
| `--rule` | `#e5e8ec` | Hairline borders |
| `--rule-soft` | `#f1f3f5` | Softer dividers between rows |
| `--accent` | `#0d6efd` | Links, primary action — matches `--bs-blue` |
| `--accent-faint` | `#e7f1ff` | Hover bg for nav items |
| `--paper` | `#ffffff` | Surface background |
| `--paper-tint` | `#f8f9fa` | Sidebar background, raised surfaces |

### Harness Chips (4 only — palette explosion forbidden)

| Chip | Bg / Fg | Use |
|---|---|---|
| `.chip.payg` | `#f1f3f5` / `#4a5260` | `anthropic/` or `openai/` prefix — PAYG API billing |
| `.chip.claude` | `#efe7fb` / `#5a2ca0` | `claude-cli/` prefix — Claude Code Max OAuth |
| `.chip.codex` | `#d1e7dd` / `#0a3622` | `codex/` or `openai-codex/` prefix — ChatGPT OAuth |
| `.chip.geode` | `#cfe2ff` / `#052c65` | `geode/` prefix — self-target wrapper |

### Surface Buckets (3 only)

| Bucket | Color | Role |
|---|---|---|
| `.bucket.petri` | `#0d6efd` | Petri audit artifact |
| `.bucket.seedgen` | `#198754` | Seed-generation artifact |
| `.bucket.autoresearch` | `#b45309` | Autoresearch artifact |

**Strict rules**:
1. **No additional colors.** Status semantics (success / partial / fail) reuse the surface bucket palette where possible, else `--ink-faint` for muted.
2. **No warm yellow / red / orange** except `--bucket-autoresearch` (deliberate signal for the closed-loop surface). Cotton's monochromatic discipline absorbed.
3. **No gradients, no shadows.** Hairline borders only (`var(--rule)`).
4. **No emoji.** Per `[[feedback-no-box-ui-no-emoji]]`. Role labels are uppercase letterforms with `.role-label` class.

**Signature accent propagation.** `--accent` (`#0d6efd`, the petri Bootstrap-blue) is the signature of the whole self-improving surface. The docs site (dark) propagates it as its `04-self-improving` section identity — token `--acc-si` (`#5B9BFF`, the same hue lightened for AA on the dark substrate). The hub stays light (this palette); the docs stay dark; the shared thread is the accent, not the mode. Docs-side policy: `site/DESIGN.md §11.1`.

## 4. Typography

| Variable | Family | Weights | Use |
|---|---|---|---|
| Body sans | `-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif` | 400, 600, 700 | Prose, headlines, buttons |
| Monospace | `ui-monospace, Menlo, "SF Mono", monospace` | 400, 600 | IDs (run_id, eval_id), hashes, paths, numeric data, code |

**No web fonts.** GitHub Pages cold-start budget = 0 extra HTTP. System stack only.

### Scale

| Element | Size | Line height | Family |
|---|---|---|---|
| `h1.page-title` | 1.6rem (≈26px) | 1.30 | sans, 600 |
| `.page-sub` | .95rem (≈15px) | 1.55 | sans, 400, `--ink-soft` |
| `h2.section` | .72rem (≈11.5px) | 1.20 | mono, 600 uppercase, `--ink-faint`, letter-spacing 0.1em, with `::after` flex divider |
| `h3.subsection` | .9rem (≈14px) | 1.35 | mono, 600 |
| `body` | 14px | 1.5 | sans |
| `table.records` cell | .78rem (≈12.5px) | 1.5 | mono |
| `.chip` | .62rem (≈10px) | 1.0 | mono, 600 |
| `.role-label` | .58rem (≈9px) | 1.0 | mono, 600, uppercase, letter-spacing 0.05em |

## 5. Layout Grid

Two-column shell, sticky sidebar:

```
┌──────────┬────────────────────────────────────────┐
│          │ h1.page-title                          │
│ aside    │ .page-sub                              │
│ .sidebar │                                        │
│ (260px)  │ h2.section · · · · · · · · · · · · · ·│
│ sticky   │ table.records or content block          │
│ top 0    │                                        │
│ max      │ h2.section · · · · · · · · · · · · · ·│
│ 100vh    │ table.records or content block          │
│ overflow │                                        │
│ scroll   │ .build-info (footer-equivalent)        │
└──────────┴────────────────────────────────────────┘
```

- `main.content` max-width 1100px, padding 2rem 2.5rem.
- Mobile: sidebar collapses to top horizontal bar at <768px (defer to Phase 5 — initial hub is desktop-first).

## 6. Components (canonical names)

| Component | Selector | Used on |
|---|---|---|
| Sidebar shell | `aside.sidebar` | All pages |
| Sidebar nav section header | `.nav-section` | All pages |
| Sidebar item with count | `aside ul.nav-list li a .count` | All pages |
| Sidebar nested item | `aside ul.nav-list ul.sub-nav` | hub, seed-gen index |
| Page title | `h1.page-title` | All pages |
| Page subtitle | `.page-sub` | All pages |
| Section header | `h2.section` (with flex `::after` rule) | All pages |
| Records table | `table.records` (thead + tbody) | All data pages |
| Harness chip | `.chip.{payg,claude,codex,geode}` | All rows referencing models |
| Surface bucket chip | `.bucket.{petri,seedgen,autoresearch}` | hub, activity feed |
| Role label inline | `.role-label` | Any model cell with N roles |
| Build info footer | `.build-info` | All pages |

**Forbidden** components: rounded card boxes, hover-lift, decorative grid icons, hero gradients, modal dialogs, toast notifications.

## 7. Navigation Contract

Every page has the same sidebar structure:

1. **Brand** — `GEODE` / `/self-improving`
2. **Hub section** — link to `/self-improving/` (highlight if current)
3. **Petri Audit section** — count + sub-nav of N recent items
4. **Seed Generation section** — count + sub-nav of N runs
5. **Autoresearch section** — count + sub-nav: Baseline / Mutations / Results / Policies
6. **Docs section** — links to `/geode/docs/petri/*` (existing Next.js pages)
7. **Meta section** — GitHub repo link `https://github.com/mangowhoiscloud/geode`

Sidebar is **identical across all hub pages** so visitors never lose their place. The only diff is the `.active` highlight.

## 8. URL Contract

All links use absolute paths prefixed with `/geode/` (basePath). Plain `<a>` tags do NOT auto-prepend, so manual `/geode/` is mandatory.

```
/geode/self-improving/                  ← hub
/geode/self-improving/petri-bundle/     ← moved SPA viewer
/geode/self-improving/seed-generation/  ← runs index
/geode/self-improving/seed-generation/<run_id>/
/geode/self-improving/autoresearch/     ← landing
/geode/self-improving/autoresearch/baseline/
/geode/self-improving/autoresearch/mutations/
/geode/self-improving/autoresearch/results/
/geode/self-improving/autoresearch/policies/
/geode/docs/petri/*                     ← existing Next.js pages (no move)
https://github.com/mangowhoiscloud/geode ← repo
```

Old `/geode/petri-bundle/` URL gets a static redirect HTML with `<meta http-equiv="refresh" content="0; url=/geode/self-improving/petri-bundle/">` for grace period.

## 9. Per-row Metadata Schema

Every record row across all 3 surfaces carries the same metadata cells where applicable:

| Cell | Source |
|---|---|
| **id** | `run_id` / `eval_id` / `mutation_id`. Anchor link target. mono. |
| **timestamp** | ISO 8601 short form (`2026-05-25 05:05`). `--ink-soft`. |
| **bucket** | `.bucket.{petri,seedgen,autoresearch}` chip next to id. |
| **model + harness chips** | For each role (auditor / target / judge / mut), one chip + monospace model name. `.role-label` if N>1. |
| **status** | `success` / `partial` / `fail` — derived per surface. mono, color-coded with subdued bucket palette. |
| **link out** | `↗` glyph (Unicode 0x2197) if external. |

## 10. Empty States + Errors

| Scenario | Treatment |
|---|---|
| listing.json missing | `.build-info` block reads "no published runs yet — check <code>docs/petri-bundle/seeds/listing.json</code>" |
| Surface has 0 rows | Empty table with `<tr><td colspan="N"><em>No artifacts yet</em></td></tr>`. No skeleton loaders. |
| JSON fetch fails (client-side rendered pages) | inline `.err-msg` block, no toast |
| Auto-redirect URL | `<meta refresh>` + visible `<p>` "Page moved. <a>Click if not auto-redirected</a>." |

## 11. Anti-deception clauses (cross-page)

Borrowed from CLAUDE.md DONT table:

- Every data row's source path must be `git check-ignore`-clean (the data files we render).
- Every link in the sidebar must 200 on the deploy preview (the docs-link-audit skill applies).
- No placeholder counts ("XXX seeds") — query the actual listing.json at build time.
- Footer's "Last validated" timestamp must come from CI output, not a hand-written date.

## 12. Accessibility minimum

- Color contrast ≥ 4.5:1 for body text (`--ink #1a1f29` on `--paper #fff` is 16.3:1 ✓).
- Chip colors ≥ 3:1 (verified above palette).
- Sidebar nav uses `<nav>` with `aria-label`. Active link gets `aria-current="page"`.
- No keyboard trap: every interactive is `<a>` or `<button>`, focusable.
- No motion: zero animations, transitions only on `:hover` color (under 200ms).

## 13. Implementation stack

- **Static HTML + CSS only.** No JS framework. No build step. Each page is a single `.html` file under `docs/self-improving/` checked into git.
- Shared CSS at `docs/self-improving/assets/hub.css`. `<link rel="stylesheet" href="/geode/self-improving/assets/hub.css">` on every page.
- Optional progressive enhancement: small inline `<script>` for filter toggles or fetch-then-render of listing.json. No external dependencies.
- Deployed via existing `.github/workflows/pages.yml` after path filter widens to `docs/self-improving/**`.

## 14. Page Inventory

Per-page DESIGN.md docs in `docs/design/`:

| Page | DESIGN.md | Sidebar `.active` |
|---|---|---|
| Hub | `self-improving-hub.md` | Hub > Overview |
| Petri bundle (moved) | `self-improving-petri-bundle.md` | Petri > SPA viewer |
| Seed-gen index | `self-improving-seed-generation-index.md` | Seed Gen > All runs |
| Seed-gen run detail | `self-improving-seed-generation-run.md` | Seed Gen > `<run_id>` |
| Autoresearch landing | `self-improving-autoresearch.md` | Autoresearch (no sub) |
| Autoresearch baseline | `self-improving-autoresearch-baseline.md` | Autoresearch > Baseline |
| Autoresearch mutations | `self-improving-autoresearch-mutations.md` | Autoresearch > Mutations |
| Autoresearch results | `self-improving-autoresearch-results.md` | Autoresearch > Results |
| Autoresearch policies | `self-improving-autoresearch-policies.md` | Autoresearch > Policies |

Each per-page doc is the **contract** the frontend agent reads to produce HTML. If it's not in the per-page doc, it doesn't go on the page.

## 15. Versioning policy

**All DESIGN.md docs + every rendered hub page carry the GEODE version that authored them.** Reasoning: dim sets, axis weights, schema versions, harness chip palette, and pipeline phase counts evolve. A row in a rendered page that shows "22 dim subset" is only meaningful if the reader can ground that to which GEODE version pinned 22 dims.

### Frontmatter contract (every DESIGN.md)

```yaml
---
title: <human title>
geode_version: 0.99.65        # exact pyproject.toml version when this doc was authored
schema_version: 1             # bumped on breaking change to THIS doc's contract
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65" # version range this doc remains valid for
---
```

When a downstream change invalidates a doc (e.g., dim subset grows from 22 → 24), the doc author:

1. Bumps `last_updated`
2. Updates `geode_version` to the new version
3. Bumps `applies_to_geode` lower bound if a hard break
4. Bumps `schema_version` only if the contract itself changes (new columns, new sections)

### Page-rendered version stamp

Every page's `.build-info` footer carries an explicit version block:

```html
<p class="version-stamp">
  Rendered against GEODE <code>v0.99.62</code> · DESIGN.md schema 1 · built 2026-05-26.
  Dim subset: 22 (geode_5axes). Pipeline phases: 8. Baseline schema: v2 (PR-2).
</p>
```

The version values are **build-time substituted** from `pyproject.toml` + CHANGELOG, not hand-written.

### Versioned references inside DESIGN.md prose

When citing data that may change, anchor to source with version:

- ❌ "the 22 judge dimensions"
- ✅ "the 22 judge dimensions ([`plugins/petri_audit/judge_dims/geode_judge_subset.yaml`](../../plugins/petri_audit/judge_dims/geode_judge_subset.yaml), as of v0.99.65)"

- ❌ "8 pipeline phases"
- ✅ "8 pipeline phases ([`plugins/seed_generation/orchestrator.py:_PHASE_ORDER`](../../plugins/seed_generation/orchestrator.py), as of v0.99.65)"

- ❌ "schema v2 baseline.json"
- ✅ "schema v2 baseline.json (PR-2 of petri-schema-v2 cascade, v0.99.37+)"

- ❌ "ApplyRecord mutation row"
- ✅ "ApplyRecord mutation row (W4 schema, 2026-05-25, v0.99.54+)"

### Pinned constants (cite source + version)

| Constant | Value as of v0.99.65 | Source |
|---|---|---|
| Judge dimension count (subset) | 22 | `plugins/petri_audit/judge_dims/geode_judge_subset.yaml` |
| Judge dimension count (full) | 38 | inspect-petri default |
| Pipeline phase count | 8 | `plugins/seed_generation/orchestrator.py:_PHASE_ORDER` |
| Baseline schema version | v2 | PR-2 of petri-schema-v2 cascade |
| Mutation row schema | W4 | `core/self_improving_loop/runner.py:81` ApplyRecord |
| Fitness axes count | 4 (dim / ux / admire / bench) | ADR-012 §Decision.2 amendment |
| Hub surface count | 3 (petri / seedgen / autoresearch) | This DESIGN.md |
| Harness chip count | 4 (PAYG / Claude Code / Codex / GEODE) | This DESIGN.md §3 |

If any of these change, the master DESIGN.md schema_version bumps + every sibling per-page doc that cites it must re-stamp `last_updated`.

### Version drift detection (CI ratchet, deferred)

A future test (`tests/test_design_versioning.py`) could verify that:

1. Every DESIGN.md frontmatter `geode_version` matches `pyproject.toml`
2. Every page-rendered `<p class="version-stamp">` has a non-placeholder value
3. The pinned constants table values still match the cited source files

For now, manual ratchet — the operator reviews on every DESIGN.md edit.

## 16. Verification ratchet

Per-page DESIGN.md must answer:

1. What data does this page render? (file paths + JSON keys)
2. What's the sidebar `.active` highlight?
3. What sections (h2) does the page have?
4. For each section: table columns + data source field mapping?
5. Empty state if section has 0 rows?
6. Error state if data file missing?
7. Outgoing links — where do row IDs link to?
8. Any harness chips? Which models?
9. Build-info footer content — what does it say?

If any of these 9 questions is unanswered the page is not implementation-ready.
