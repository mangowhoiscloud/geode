---
title: GEODE Self-Improving Hub Design System
geode_version: 0.99.65
schema_version: 3
last_updated: 2026-10-20
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

**Mood (schema 3, 2026-10-19)**: a room of the mangowhois research collection
(`tech.mangowhois.ai`) — the experiment archive of a near-future museum. Night
substrate, paper ink, condensed display titles, a mono ledger for every number,
and one signal vermilion spent only on the current place, hover and focus.
It still reads like an instrument log: calm, dense, no marketing tone.

**Adjectives**: night, archival, ledger-dense, square, hairline, restrained.

**What it is not**: card grid with hover-lifts, emoji navigation, gradient hero,
marketing CTA, colored left-border accent bars, box-card sub-view navigation.

**Atmosphere devices (all CSS, no markup change)**: square station nodes on the
section rules, a placard line (mono capitals) for the breadcrumb above each
title, two fixed corner registration marks framing the viewport, and one
registration settle on the page title at load (off under reduced motion).

**Inspiration touchstones**: the mangowhois design system (`src/styles/tokens.css`,
`src/lib/palette.js` in the site repository) supplies palette, families, scale
and the square/hairline shape rule; inspect_ai's bundled SPA remains the data
reading model.

## 3. Color Palette & Roles

| Token | Value | Role |
|---|---|---|
| `--paper` | `#0d100f` | Night substrate (palette.js `STAGE.night`) |
| `--paper-tint` | `#171b19` | Sidebar and raised panels (`STAGE.night2`) |
| `--ink` | `#f3f0e6` | Primary text (paper) |
| `--ink-soft` | `#c9c7bd` | Secondary text |
| `--ink-faint` | `#969589` | Captions, metadata, section labels, the row-filter input frame (6.3:1 on `--paper`, 5.7:1 on `--paper-tint`) |
| `--rule` / `--rule-soft` / `--rule-strong` | paper at 16% / 7% / 32% | Hairlines, row dividers, header frames (decorative; never the only cue to a control) |
| `--accent` | `#e8542f` | Signal vermilion: current place, hover line, focus outline — never a fill for content |
| `--accent-faint` | vermilion at 12% | Current nav item ground |

### Harness Chips (4 only — palette explosion forbidden)

Chips are a 1px outline in their own tone on the night field (no fill).

| Chip | Tone | Use |
|---|---|---|
| `.chip.payg` | `#c9c7bd` | `anthropic/` or `openai/` prefix — PAYG API billing |
| `.chip.claude` | `#efaa70` | historical `claude-cli/` artifact prefix — read-only legacy receipt |
| `.chip.codex` | `#9fd9bb` | `codex/` or `openai-codex/` prefix — ChatGPT OAuth |
| `.chip.geode` | `#9fb0ff` | `geode/` prefix — self-target wrapper |

### Surface Buckets (3 only)

| Bucket | Tone | Role |
|---|---|---|
| `.bucket.petri` | `#9fb0ff` (check blue) | Petri audit artifact |
| `.bucket.seedgen` | `#9fd9bb` | Seed-generation artifact |
| `.bucket.autoresearch` | `#efaa70` (decision orange) | Autoresearch artifact |

**Strict rules**:
1. **No additional hues.** Status semantics reuse the bucket tones, else `--ink-faint`. Heatmap warmth steps are decision orange (`#e8781e`) at 16/32/58/100%.
2. **Vermilion is not a status colour.** It marks only where the reader is and what has focus.
3. **No gradients, no box shadows, no rounded corners.** Hairline borders only. The title's registration settle is a transient text offset that ends at none.
4. **No emoji.** Role labels are uppercase letterforms with `.role-label` class.

## 4. Typography

| Variable | Family (fallbacks) | Use |
|---|---|---|
| `--font-display` | Mangowhois Display → Archivo → system | `h1.page-title` (condensed 75%, 800), brand mark (112%) |
| `--font-sans` | Mangowhois Sans → Pretendard → system (Hangul faces included) | Prose, navigation, controls |
| `--font-mono` | Mangowhois Mono → JetBrains Mono → system mono | IDs, hashes, paths, numbers, section labels, placard line |

**Font loading.** `hub.css` declares no `@font-face`. The research host injects
its own font stylesheet (`/fonts/mangowhois.css`); the GitHub Pages copy renders
the same layout in the system stack with zero extra requests.

### Scale

Sizes are `rem` steps (`--fs-11` … `--fs-16`); the floor is 12px (the
mangowhois minimum), so `--fs-11` and `--fs-12` are both .75rem.

| Element | Size | Line height | Family |
|---|---|---|---|
| `h1.page-title` | clamp(1.75rem, 1.1rem + 2.4vw, 3rem) | 1.05 | display, condensed 75%, 800; wraps long run ids |
| `.crumbs` (placard) | .75rem | 1.3 | mono capitals, tracking .08em |
| `.page-sub` | 1rem | 1.6 | sans, `--ink-soft`; `p.page-sub` capped at `--measure` (46rem) |
| `h2.section` | .75rem | 1.30 | mono 600 capitals, square vermilion node + hairline |
| `h3.subsection` | .875rem | 1.35 | mono, 600 |
| `body` | .9375rem (15px) | 1.6 | sans, tabular figures |
| `table.records` cell / header | .8125rem / .75rem | 1.5 | mono; header capitals |
| `.chip`, `.bucket`, `.role-label` | .75rem | 1.3 | mono, 600 |
| Row-filter input | 1rem | — | inherits sans; 16px stops iOS focus zoom |

## 5. Responsive shell (schema 2)

Mobile first. One breakpoint, `64rem` (1024 CSS px), switches between two
arrangements of the same DOM; the reading order is always brand, Contents,
breadcrumb, page.

```
narrow (< 64rem)                       wide (>= 64rem)
┌──────────────────────────────┐       ┌──────────┬───────────────────────────┐
│ GEODE/self-improving Contents│       │ GEODE    │ Hub / Section / Page      │
├──────────────────────────────┤       │ (nav,    │ h1.page-title             │
│ (nav list when opened)       │       │  sticky, │ .page-sub                 │
│ Hub / Section / Page         │       │  own     │ On this page: ...         │
│ h1.page-title                │       │  scroll) │ h2.section ─────────────  │
│ .page-sub                    │       │ 16rem    │ ┌ table-scroll ─────────┐ │
│ h2.section ────────────────  │       │          │ │ table.records         │ │
│ ┌ table-scroll ───────────┐  │       │          │ └───────────────────────┘ │
│ │ table.records  ──scroll▶│  │       │          │ .build-info               │
│ └─────────────────────────┘  │       │          │                           │
└──────────────────────────────┘       └──────────┴───────────────────────────┘
```

- **Navigation disclosure.** `aside.sidebar` holds the brand link and one
  native `<details class="hub-nav" data-hub-nav>` whose `<summary>` reads
  "Contents". It is closed in the HTML, so a phone shows the page content
  directly under a 3rem bar. The list opens in flow below the bar: no
  overlay, no modal, no focus trap. `assets/hub.js` opens it at the wide
  breakpoint, where the summary hides and the aside becomes a 16rem sticky
  column with its own vertical scroll (`100vh`/`100dvh`). Without JS the
  summary stays visible on every width and opens the same list.
- **Content.** `main.content#main` has `min-width: 0`, max-width 76rem and a
  fluid gutter (`clamp(1rem, .5rem + 2.5vw, 2rem)`). Reflow holds at 320,
  375, 390 and 768 CSS px and at 200% zoom; the page itself never scrolls
  sideways.
- **2-D data.** Tables may be wider than the viewport; they scroll inside
  their own `.table-scroll` region (WCAG 1.4.10 exception for data tables).
  Tables with 4+ columns keep `min-width: 40rem`, 7+ columns `56rem`, the
  pilot heatmap `64rem` with a sticky id column, so columns stay legible
  instead of collapsing to one character. No column is hidden at any width.
- **Prose and values.** Body text breaks long tokens (`overflow-wrap:
  break-word`); key/value grids (`.status-grid`, `.cost-grid`,
  `.run-detail-header dl`, `.phases-legend`) use `fit-content(45%)
  minmax(0, 1fr)` and stack below 30rem; code, JSON and payload blocks wrap
  (`pre.msg`, `pre.diff`, `.policy-json`) or scroll in place (`pre`,
  `.fitness-sparkline`).
- **Sticky surfaces.** Only the wide sidebar and, on the wide layout, the run
  page's `.run-map`. Nothing sticks on narrow screens.

## 6. Components (canonical names)

| Component | Selector | Used on |
|---|---|---|
| Skip link | `a.skip-link` → `#main` | All pages |
| Sidebar shell | `aside.sidebar` (`a.brand`, `details.hub-nav`) | All pages |
| Sidebar nav section header | `.nav-section` | All pages |
| Sidebar item with count | `.nav-section .count` | All pages |
| Collapsible long list | `details.nav-group > ul.sub-nav` | Recent audits, Runs by campaign |
| Breadcrumb | `nav.crumbs` (last item `aria-current="page"`) | Every page below the hub root |
| On-this-page map | `nav.page-map` (build-time) / `nav.run-map` (run page) | Pages with 3+ sections |
| Surface orientation list | `.hub-orient .orient-list` | Hub landing |
| Page title | `h1.page-title` | All pages |
| Page subtitle | `.page-sub` | All pages |
| Section header | `h2.section` (with flex `::after` rule) | All pages |
| Table scroll region | `div.table-scroll[role=region][aria-label]` | Every table (build-time) |
| Records table | `table.records` (thead + tbody) | All data pages |
| Row filter | `.table-filter` (hub.js) | Tables with 8+ row groups |
| Harness chip | `.chip.{payg,claude,codex,geode}` | All rows referencing models |
| Surface bucket chip | `.bucket.{petri,seedgen,autoresearch}` | hub, activity feed |
| Role label inline | `.role-label` | Any model cell with N roles |
| Build info footer | `.build-info` | All pages |

**Forbidden** components: rounded card boxes, hover-lift, decorative grid icons, hero gradients, modal dialogs, toast notifications.

The landing's orientation list is a flat `<ol>` with hairline separators, one
row per surface (name linking to its section, the count label the builder
already computes, one sentence, one destination link). It reflows from one to
two columns; it is not a card grid and adds no status beyond those labels.

**Row filter.** `hub.js` inserts a labelled `type="search"` input above any
records table with 8 or more row groups (a mutation's payload row travels with
its row). Rows are hidden with the `hidden` attribute, never removed; headers,
navigation and other tables are untouched. A `role="status"` line announces
"Showing N of M rows." after typing pauses, and a zero match reads
"No rows match "q". Clear the filter to show all M rows." Escape clears.

## 7. Navigation Contract

One renderer, `render_hub_nav` in `scripts/build_self_improving_hub.py`,
emits the nav for every page (all templates via `{{ hub_nav }}` and every
seedgen sub-page via `_render_seedgen_subpage`), so the structure cannot
drift per page:

1. **Brand** — `GEODE` / `/self-improving`, a link to the hub root
2. **Hub** — Overview
3. **Petri Audit** — count, SPA log viewer, Recent audits (collapsible)
4. **Seed Generation** — count, All runs, Runs by campaign (collapsible,
   grouped by `gen_tag`), Phase log viewer, Seed runs (docs)
5. **Autoresearch** — baseline status (`snapshot` / `stale` / `absent`),
   Overview / Baseline / Mutations / Results / Evidence / Runs / Policies
6. **Crucible** — count label, Kernel architecture (source), Bounded search (docs)

**Corrections (2026-10-08).** The status label read `live`, which implied
current runtime activity on a static archive; a found, non-outdated baseline
now reads `snapshot` (recorded at build time), and `stale` / `absent` keep
their meaning. The inherited Crucible link `/geode/docs/architecture/crucible-kernel`
has no docs route (404). "Kernel architecture (source)" now opens
`docs/architecture/crucible-kernel.md` pinned at
`80b130c3113ddaca9d4712d81a277005143c28aa`, and "Bounded search (docs)"
opens `/geode/docs/capabilities/outer-loop/`. `--refresh-presentation` applies
both: it normalizes a published `live` label and carries the single
`_HREF_CORRECTIONS` entry (old → pinned source), which its evidence guard
counts as kept. No other destination, record or build stamp changes.
7. **Docs** — links to `/geode/docs/petri/*` (existing Next.js pages)
8. **Meta** — GitHub repo link `https://github.com/mangowhoiscloud/geode`

Current page: the link whose `href` equals the page URL gets
`aria-current="page"` (hairline frame + 600 weight, not colour alone). A page
without its own entry (run sub-pages, run reports, Active runs) marks its
closest ancestor link with `data-ancestor` instead of a false
`aria-current`; its breadcrumb carries `aria-current="page"`. A collapsible
group opens when it contains either mark. Trailing ↗ marks are
`aria-hidden` so link names stay clean.

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

- Color contrast ≥ 4.5:1 for body text (`--ink #1a1f29` on `--paper #fff` is 16.3:1 ✓) and for `--ink-faint` labels (4.8:1 on paper, 4.6:1 on paper-tint).
- Chip colors ≥ 3:1 (verified above palette).
- Landmarks: `aside` › `nav[aria-label="Hub navigation"]`, `main#main`, `nav.crumbs[aria-label="Breadcrumb"]`, `nav.page-map`. The first focusable element is the "Skip to content" link to `#main`.
- Current page: `aria-current="page"` on the matching nav link and on the last breadcrumb item (see §7).
- Disclosures are native `<details>/<summary>`: keyboard operable with Enter/Space and exposing expanded/collapsed (the `aria-expanded` state) through the browser, so no ARIA is duplicated on them. On narrow screens Escape inside the open nav closes it and returns focus to Contents. Focus moves in document order; nothing traps it.
- Targets: nav rows, breadcrumb, page-map, sub-view links, summaries and the filter input are at least 44 CSS px tall (`--tap`), except nav rows on a fine pointer at the wide layout (36px, above the 24px WCAG 2.5.8 minimum).
- Focus: a 2px `--accent` outline at 2px offset on every focusable element, including scroll regions.
- Control boundaries (WCAG 1.4.11): the empty row-filter input is identified only by its frame, so the frame is `--ink-faint` (6.3:1 on `--paper`), never a translucent `--rule*` hairline (`--rule-strong` composites to 2.7:1).
- Scroll regions: each `.table-scroll` is `role="region"` with an `aria-label` from the nearest preceding heading and `tabindex="0"` so keyboard users can scroll it; `hub.js` drops the tab stop while a region does not overflow. Native wheel and touch scrolling only: no `preventDefault`, no `overscroll-behavior` overrides.
- Motion: none beyond the Active runs pulse, which runs only under `prefers-reduced-motion: no-preference`. No hover transitions.

## 13. Implementation stack

- **Static HTML + CSS + one deferred script.** No framework, CDN, or dependency. Pages are generated by `scripts/build_self_improving_hub.py` (also reached through `geode hub build`) from `docs/self-improving/**/*.html.template` plus the in-code seedgen sub-page shell; never hand-edit a generated `.html`.
- Shared CSS at `docs/self-improving/assets/hub.css`, shared script at `docs/self-improving/assets/hub.js`, both referenced from every page: `<link rel="stylesheet" href="/geode/self-improving/assets/hub.css">` and `<script src="/geode/self-improving/assets/hub.js" defer></script>`.
- Every page is written through `write_hub_page`, whose build-time pass (`finalize_hub_page`) wraps each table in its labelled scroll region and adds stable `sec-*` ids plus the "On this page" map. Overflow handling therefore never depends on JS.
- `hub.js` is enhancement only: the wide-breakpoint nav state (moving focus to Contents if a resize hides the focused link), scroll-region tab stops, tables in client-rendered Markdown (each `.markdown-body[data-md-target]` watches only its own children), and the row filter, which shows its row count from first render. With JS off every page, link and row stays reachable.
- **Presentation-only refresh of published pages.** Some published values (runtime baselines, local Crucible ledgers, runs whose inputs are gone) have no tracked source, so a rebuild would replace public evidence with empty states. `--refresh-presentation DIR` re-skins a copy of the published `docs/self-improving` tree in place through the same chrome (`refresh_page_presentation` → `render_hub_nav` + `finalize_hub_page`) and reads nothing else. It touches only hub-owned `index.html` files (`<main class="content"` + `hub.css`), never `petri-bundle/**` or `seed-generation/bundle/**`; re-renders each sidebar from that page's own published counts and lists; adds the script, skip link, `main#main` and breadcrumb; unwraps the legacy `.heatmap-scroll` wrapper; and copies the current `hub.css`/`hub.js` into `assets/`. `<main>` content, table cells, code blocks, destinations and historical build stamps are not rewritten. A page that would lose a destination, cell or `<pre>` is left untouched and the run exits 1. It is idempotent. Normal builds still go through the canonical renderers.
- Deployed via existing `.github/workflows/pages.yml` after path filter widens to `docs/self-improving/**`.
- Regression: `test_every_generated_page_shares_the_responsive_shell` in `tests/evolve/scaffold_search/test_self_improving_hub_e2e.py` builds the fixture and checks the shell on every generated page.

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
- ✅ "the 22 judge dimensions ([`evals/petri/judge_dims/geode_judge_subset.yaml`](../../evals/petri/judge_dims/geode_judge_subset.yaml), as of v0.99.65)"

- ❌ "8 pipeline phases"
- ✅ "8 pipeline phases ([`evals/seed_generation/orchestrator.py:_PHASE_ORDER`](../../evals/seed_generation/orchestrator.py), as of v0.99.65)"

- ❌ "schema v2 baseline.json"
- ✅ "schema v2 baseline.json (PR-2 of petri-schema-v2 cascade, v0.99.37+)"

- ❌ "ApplyRecord mutation row"
- ✅ "ApplyRecord mutation row (W4 schema, 2026-05-25, v0.99.54+)"

### Pinned constants (cite source + version)

| Constant | Value as of v0.99.65 | Source |
|---|---|---|
| Judge dimension count (subset) | 22 | `evals/petri/judge_dims/geode_judge_subset.yaml` |
| Judge dimension count (full) | 38 | inspect-petri default |
| Pipeline phase count | 8 | `evals/seed_generation/orchestrator.py:_PHASE_ORDER` |
| Baseline schema version | v2 | PR-2 of petri-schema-v2 cascade |
| Mutation row schema | W4 | `evolve/scaffold_search/loop/runner.py:81` ApplyRecord |
| Fitness axes count | 4 (dim / ux / admire / bench) | ADR-012 §Decision.2 amendment |
| Hub surface count | 3 (petri / seedgen / autoresearch) | This DESIGN.md |
| Harness chip count | 4 (PAYG / Legacy Claude CLI / ChatGPT / GEODE) | This DESIGN.md §3 |

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
