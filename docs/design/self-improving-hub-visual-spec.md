---
title: Self-Improving Hub · Visual Specification (Option 1, surface-first)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
parent: self-improving-hub-system.md
applies_to_geode: ">=0.99.65"
---

# Self-Improving Hub · Visual Specification

> Concrete visual contract for `/geode/self-improving/` (the hub landing page).
> Resolves every ambiguity in `self-improving-hub-system.md` + `self-improving-hub.md`.
> The frontend agent renders HTML/CSS directly from this doc — no further design decisions required.
>
> This spec **does not invent** new tokens or components. It re-states the master DESIGN.md
> with absolute units, computes color-contrast numbers, fixes HTML structure, and freezes
> ambiguous sidebar/sub-nav/footer markup.

## 0. Scope + Authority order

1. **Master DESIGN.md** (`self-improving-hub-system.md`) — Authoritative for tokens, palette, anti-patterns.
2. **Per-page DESIGN.md** (`self-improving-hub.md`) — Authoritative for data sources, columns, sidebar tree.
3. **This visual spec** — Authoritative for concrete CSS values, HTML markup, accessibility numbers,
   and any unresolved ambiguity. Where this doc and (1)/(2) diverge, (1)/(2) win — flag a fix-up PR.
4. **Mockup HTML** (`/tmp/geode-hub-mockups-v2/option-1-surface-first.html`) — Visual reference only;
   not authoritative once this spec is written.

All rem values resolved against **`html { font-size: 16px }`** (browser default).
Pixel values are exact; rem values retained for readability where they were authored in rem.

---

## 1. CSS variable values (production token table)

Single source of truth. The frontend agent declares these on `:root` in `assets/hub.css`.

```css
:root {
  /* Ink + paper substrate */
  --ink:         #1a1f29;
  --ink-soft:    #4a5260;
  --ink-faint:   #7d8694;
  --rule:        #e5e8ec;
  --rule-soft:   #f1f3f5;
  --accent:      #0d6efd;
  --accent-faint:#e7f1ff;
  --paper:       #ffffff;
  --paper-tint:  #f8f9fa;

  /* Harness chip palette — 4 only, palette explosion forbidden */
  --chip-payg-bg:   #f1f3f5;  --chip-payg-fg:   #4a5260;
  --chip-claude-bg: #efe7fb;  --chip-claude-fg: #5a2ca0;
  --chip-codex-bg:  #d1e7dd;  --chip-codex-fg:  #0a3622;
  --chip-geode-bg:  #cfe2ff;  --chip-geode-fg:  #052c65;

  /* Surface bucket palette — 3 only */
  --bucket-petri:        #0d6efd;
  --bucket-seedgen:      #198754;
  --bucket-autoresearch: #b45309;  /* the only warm tone permitted on the surface */

  /* Sidebar geometry */
  --sidebar-w: 260px;

  /* Content geometry */
  --content-max:    1100px;
  --content-pad-y:  32px;   /* 2rem */
  --content-pad-x:  40px;   /* 2.5rem */
}
```

### 1.1 Resolved rem → px table

| Token in master DESIGN.md | rem | px (at 16px base) | Notes |
|---|---|---|---|
| Body font-size | — | **14px** | Set on `body`, *not* on `:root`, so `rem` keeps its 16px math. |
| h1.page-title | 1.6rem | **25.6px → render as 26px** | font-weight 600 |
| .page-sub | 0.95rem | **15.2px** | --ink-soft, max-width 780px |
| h2.section | 0.72rem | **11.52px** | mono uppercase, letter-spacing .1em |
| h3.subsection | 0.9rem | **14.4px** | mono 600 |
| table.records cell | 0.78rem | **12.48px** | mono |
| table.records thead | 0.64rem | **10.24px** | mono uppercase, letter-spacing .04em |
| .chip | 0.62rem | **9.92px** | mono 600 |
| .bucket | 0.58rem | **9.28px** | mono 700 uppercase, letter-spacing .08em |
| .role-label | 0.58rem | **9.28px** | mono 600 uppercase, letter-spacing .05em |
| aside .brand | 1rem | **16px** | font-weight 700 |
| aside .brand-sub | 0.68rem | **10.88px** | mono, --ink-faint |
| aside .nav-section | 0.62rem | **9.92px** | mono 600 uppercase, letter-spacing .12em |
| aside .nav-list a | 0.83rem | **13.28px** | sans, --ink-soft |
| aside .sub-nav a | 0.76rem | **12.16px** | sans |
| aside .count | 0.7rem | **11.2px** | mono, --ink-faint |
| .build-info | 0.7rem | **11.2px** | mono, --ink-faint |
| Sidebar pad | 1.5rem 1rem | **24px 16px** | |
| Content pad | 2rem 2.5rem | **32px 40px** | |
| h2.section gap to next | margin 1.75rem 0 .55rem | **28px / 8.8px** | |
| Build-info top margin | 2.5rem | **40px** | + 16px padding-top + 1px rule = 57px visual gap |

### 1.2 Typography stacks (no web fonts)

```css
--font-sans: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
--font-mono: ui-monospace, Menlo, "SF Mono", monospace;
```

Frontend agent applies `--font-sans` on `body`, `--font-mono` on `.nav-section`, `.brand-sub`,
`.count`, `h2.section`, `h3.subsection`, `table.records`, `.chip`, `.bucket`, `.role-label`,
`code`, `.build-info`.

---

## 2. Page anatomy (ASCII, top-down)

All widths/heights are computed against a 1440px viewport baseline.

```
┌─────────────────── 1440px viewport ──────────────────────────────────────────┐
│ ┌── aside.sidebar ──┬── main.content ─────────────────────────────────────┐ │
│ │ 260px fixed       │ flex 1, max-width 1100px, pad 32px 40px             │ │
│ │ sticky top:0      │                                                      │ │
│ │ max-h:100vh       │ ┌─ h1.page-title    "GEODE Self-Improving Hub" ──┐ │ │
│ │ overflow-y:auto   │ │   26px, sans 600, --ink                          │ │ │
│ │ bg:--paper-tint   │ └──────────────────────────────────────────────────┘ │ │
│ │ border-right 1px  │ ┌─ p.page-sub  (max-width 780px) ─────────────────┐ │ │
│ │                   │ │   15.2px sans 400, --ink-soft, 24px mb           │ │ │
│ │ Brand "GEODE"     │ └──────────────────────────────────────────────────┘ │ │
│ │ Sub  "/self-..."  │                                                      │ │
│ │                   │ ── h2.section "PETRI AUDIT · 11 ARCHIVES" ──────── │ │
│ │ [nav-section]     │ <table.records> 6 cols, ~10 rows                    │ │
│ │ HUB               │                                                      │ │
│ │   Overview ◀ act  │ ── h2.section "SEED GENERATION · 1 RUN" ───────── │ │
│ │                   │ <table.records> 7 cols, indented sub-rows           │ │
│ │ PETRI AUDIT  [11] │                                                      │ │
│ │   SPA viewer ↗    │ ── h2.section "AUTORESEARCH · BASELINE+LEDGER" ── │ │
│ │   Recent audits   │ <table.records> 5 cols, 4 rows                      │ │
│ │     ├ audit_xx    │                                                      │ │
│ │     ├ audit_yy    │ ── h2.section "DOCUMENTATION" ─────────────────── │ │
│ │     └ audit_zz    │ <table.records> 2 cols, 5 rows                      │ │
│ │                   │                                                      │ │
│ │ SEED GEN [1 run]  │ ─────── 1px --rule, 40px above ─────────────────── │ │
│ │   All runs        │ .build-info  11.2px mono --ink-faint                 │ │
│ │     └ gen1-…      │   p × 4 (source / publish / harness legend /          │ │
│ │   Run dash ↗      │          version-stamp)                              │ │
│ │                   │                                                      │ │
│ │ AUTORESEARCH      │                                                      │ │
│ │ [stale]           │                                                      │ │
│ │   Baseline        │                                                      │ │
│ │   Mutations       │                                                      │ │
│ │   Results         │                                                      │ │
│ │   Policies        │                                                      │ │
│ │                   │                                                      │ │
│ │ DOCS              │                                                      │ │
│ │   Petri overview  │                                                      │ │
│ │   Run an audit    │                                                      │ │
│ │   Judge dim's     │                                                      │ │
│ │                   │                                                      │ │
│ │ META              │                                                      │ │
│ │   GitHub ↗        │                                                      │ │
│ └───────────────────┴──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

Grid: `display:grid; grid-template-columns: 260px 1fr; min-height:100vh;`
Content area absolute width on 1440px viewport = 1440 − 260 = 1180px; `max-width:1100px` clamps;
visible content column ≈ 1020px (1100 − 2×40 padding). Mobile <768px: out of scope (Phase 5).

---

## 3. Sidebar component spec (`<aside class="sidebar">`)

The sidebar is **identical across all hub pages**; only `.active` moves. For the hub page,
`.active` lives on `Hub > Overview`.

### 3.1 Canonical HTML structure

```html
<aside class="sidebar" aria-label="Self-Improving Hub navigation">
  <div class="brand">GEODE</div>
  <div class="brand-sub">/self-improving</div>

  <nav>
    <div class="nav-section">Hub</div>
    <ul class="nav-list">
      <li><a href="/geode/self-improving/" class="active" aria-current="page">Overview</a></li>
    </ul>

    <div class="nav-section">Petri Audit <span class="count">11</span></div>
    <ul class="nav-list">
      <li><a href="/geode/self-improving/petri-bundle/">SPA log viewer ↗</a></li>
      <li>
        <a href="/geode/self-improving/petri-bundle/#/tasks">Recent audits</a>
        <ul class="sub-nav">
          <li><a href="/geode/self-improving/petri-bundle/#/tasks/audit_Hz4Qrv4Z">audit_Hz4Qrv4Z</a></li>
          <li><a href="/geode/self-improving/petri-bundle/#/tasks/audit_k4QhmKXs">audit_k4QhmKXs</a></li>
          <li><a href="/geode/self-improving/petri-bundle/#/tasks/audit_m8BRHKDA">audit_m8BRHKDA</a></li>
        </ul>
      </li>
    </ul>

    <div class="nav-section">Seed Generation <span class="count">1 run</span></div>
    <ul class="nav-list">
      <li>
        <a href="/geode/self-improving/seed-generation/">All runs</a>
        <ul class="sub-nav">
          <li><a href="/geode/self-improving/seed-generation/gen1-redundant_tool_invocation/">gen1-redundant_tool_invocation</a></li>
        </ul>
      </li>
      <li><a href="/geode/docs/petri/seeds">Run dashboard ↗</a></li>
    </ul>

    <div class="nav-section">Autoresearch <span class="count">stale</span></div>
    <ul class="nav-list">
      <li><a href="/geode/self-improving/autoresearch/baseline/">Baseline</a></li>
      <li><a href="/geode/self-improving/autoresearch/mutations/">Mutations</a></li>
      <li><a href="/geode/self-improving/autoresearch/results/">Results</a></li>
      <li><a href="/geode/self-improving/autoresearch/policies/">Policies</a></li>
    </ul>

    <div class="nav-section">Docs</div>
    <ul class="nav-list">
      <li><a href="/geode/docs/petri/overview">Petri overview</a></li>
      <li><a href="/geode/docs/petri/run-an-audit">Run an audit</a></li>
      <li><a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a></li>
    </ul>

    <div class="nav-section">Meta</div>
    <ul class="nav-list">
      <li><a href="https://github.com/mangowhoiscloud/geode" rel="noopener external">GitHub ↗</a></li>
    </ul>
  </nav>
</aside>
```

### 3.2 Sidebar CSS

```css
aside.sidebar {
  border-right: 1px solid var(--rule);
  background: var(--paper-tint);
  padding: 24px 16px;            /* 1.5rem 1rem */
  position: sticky;
  top: 0;
  align-self: start;
  max-height: 100vh;
  overflow-y: auto;
}
aside .brand {
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 3.2px;          /* .2rem */
  letter-spacing: 0.02em;
  color: var(--ink);
}
aside .brand-sub {
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 10.88px;            /* .68rem */
  margin-bottom: 24px;           /* 1.5rem */
}
aside nav { display: block; }
aside .nav-section {
  font-size: 9.92px;             /* .62rem */
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
  font-weight: 600;
  font-family: var(--font-mono);
  margin: 18.4px 0 5.6px;        /* 1.15rem 0 .35rem */
}
aside ul.nav-list { list-style: none; padding: 0; margin: 0; }
aside ul.nav-list li { margin: 0; }
aside ul.nav-list a {
  display: block;
  padding: 4.8px 8.8px;          /* .3rem .55rem */
  color: var(--ink-soft);
  text-decoration: none;
  font-size: 13.28px;            /* .83rem */
  border-radius: 3px;
  transition: background-color 120ms ease, color 120ms ease;
}
aside ul.nav-list a:hover {
  background: var(--accent-faint);
  color: var(--accent);
}
aside ul.nav-list a:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
aside ul.nav-list a.active {
  background: var(--paper);
  color: var(--ink);
  font-weight: 600;
}
aside ul.nav-list a.active[aria-current="page"] {
  /* No additional treatment — `.active` carries it.
     `aria-current="page"` is the a11y signal; visual treatment matches .active. */
}
aside ul.nav-list .count {
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 11.2px;             /* .7rem */
  margin-left: 5.6px;            /* .35rem */
  font-weight: 400;
}
aside ul.nav-list ul.sub-nav {
  list-style: none;
  padding: 0 0 0 12.8px;         /* 0 0 0 .8rem */
  margin: 2.4px 0 5.6px;         /* .15rem 0 .35rem */
  border-left: 1px solid var(--rule);
}
aside ul.nav-list ul.sub-nav a {
  font-size: 12.16px;            /* .76rem */
  padding: 2.4px 7.2px;          /* .15rem .45rem */
}
```

### 3.3 Sidebar invariants

- Counts (`<span class="count">…</span>`) live **inside** `.nav-section`, not inside the `<a>`.
  Rationale: counts are section-level summaries, not link text; screen readers should read the
  section header as "Petri Audit, 11" and then list its links.
- Sub-nav (`ul.sub-nav`) sits **inside** the parent `<li>`, after the parent `<a>`. It is **not**
  a sibling list. This nesting is what produces the visual indent + left rule.
- The 7th section is **Meta** (added per per-page DESIGN.md §6). It exists on every hub page.
- The GitHub link uses absolute URL (https), not the `/geode/` basePath prefix.

---

## 4. Records table spec (`<table class="records">`)

### 4.1 Canonical structure

```html
<h2 class="section"><span>Petri Audit · 11 archives</span></h2>
<table class="records">
  <thead>
    <tr>
      <th scope="col">id</th>
      <th scope="col">seeds</th>
      <th scope="col">auditor</th>
      <th scope="col">target</th>
      <th scope="col">judge</th>
      <th scope="col">started</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td class="id">
        <a href="/geode/self-improving/petri-bundle/#/tasks/audit_T6LMA3ko">audit_T6LMA3ko</a>
        <span class="bucket petri">petri</span>
      </td>
      <td class="muted">2</td>
      <td><span class="chip claude">Claude Code</span> <code>claude-sonnet-4-6</code></td>
      <td><span class="chip geode">GEODE</span> <code>geode/gpt-5.5</code></td>
      <td><span class="chip claude">Claude Code</span> <code>claude-opus-4-7</code></td>
      <td class="muted">2026-05-22 05:56</td>
    </tr>
    <!-- … additional <tr> rows, up to 10 -->
  </tbody>
</table>
```

### 4.2 Cell padding, borders, alignment

```css
table.records {
  width: 100%;
  font-family: var(--font-mono);
  font-size: 12.48px;            /* .78rem */
  border-collapse: collapse;
  margin-bottom: 8px;
}
table.records thead th {
  text-align: left;
  padding: 5.6px 9.6px 5.6px 0;  /* .35rem .6rem .35rem 0 */
  border-bottom: 1px solid var(--rule);
  font-size: 10.24px;            /* .64rem */
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
  font-weight: 600;
  white-space: nowrap;
}
table.records tbody td {
  padding: 7.2px 9.6px 7.2px 0;  /* .45rem .6rem .45rem 0 */
  border-bottom: 1px solid var(--rule-soft);
  vertical-align: top;
}
table.records tbody tr:last-child td { border-bottom: 0; }
table.records tbody tr:hover {
  background: var(--paper-tint);  /* subtle bg tint — NO lift, NO shadow */
}
table.records td.id a {
  color: var(--accent);
  text-decoration: none;
}
table.records td.id a:hover { text-decoration: underline; }
table.records td.id a:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
  border-radius: 2px;
}
table.records td.num   { text-align: right; color: var(--ink); }
table.records td.muted { color: var(--ink-soft); }
table.records td code  { background: transparent; padding: 0; }  /* model names inline */
table.records td .role-label + code { margin-left: 2px; }
```

**Forbidden hover treatments**: `transform: translateY(…)`, `box-shadow`, `border-radius` shifts.
**Allowed hover**: `background-color` change to `var(--paper-tint)` with 120ms ease.

### 4.3 Multi-role model cell (seedgen / autoresearch)

When one row references >1 model role (e.g. baseline.json referencing auditor + target + judge),
each role appears as a separate inline group **`chip + code + role-label`**, in role order
`auditor → target → judge → mut`. Layout:

```html
<td>
  <span class="chip claude">Claude Code</span> <code>claude-opus-4-7</code> <span class="role-label">aud</span>
  <span class="chip geode">GEODE</span>      <code>geode/gpt-5.5</code>      <span class="role-label">tgt</span>
  <span class="chip claude">Claude Code</span> <code>claude-sonnet-4-6</code> <span class="role-label">jud</span>
</td>
```

Role label vocabulary (4 only): `aud` / `tgt` / `jud` / `mut`. Always lowercase 3-letter form.
When N=1 role per cell (e.g. petri thead split into `auditor` / `target` / `judge` columns),
omit the `.role-label` — the column header carries the role.

### 4.4 Indented sub-rows (seed-gen phase rows)

The seed-gen table uses **indented `td.id`** to express phase hierarchy under a run row.
Indent = `padding-left: 24px;` (`1.5rem`). The prefix glyph is U+2514 `└` followed by ` `
(NBSP) + phase name, all wrapped in the existing `td.id` cell. No nested table.

```html
<tr>
  <td class="id" style="padding-left: 24px;">└&nbsp;generator</td>
  <td class="muted">.eval card</td>
  …
</tr>
```

### 4.5 Column-count → empty-state colspan map (for hub page)

| Section | thead cols | Empty `<td colspan>` |
|---|---|---|
| Petri Audit | 6 (id, seeds, auditor, target, judge, started) | 6 |
| Seed Generation | 7 (run_id/phase, target_dim, mutator, samples, score …) | 7 |
| Autoresearch | 5 (artifact, last write, generation, models, fitness) | 5 |
| Documentation | 2 (page, summary) | 2 |

---

## 5. Harness chip spec (`.chip.{payg,claude,codex,geode}`)

### 5.1 Base CSS

```css
.chip {
  display: inline-flex;
  align-items: center;
  padding: 1.28px 6.72px;        /* .08rem .42rem */
  border-radius: 3px;            /* hairline rounded, NOT pill */
  font-size: 9.92px;              /* .62rem */
  font-weight: 600;
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
  margin-right: 4px;             /* .25rem */
  margin-bottom: 1.92px;         /* .12rem */
  vertical-align: baseline;
  white-space: nowrap;
  /* NO border — solid bg only. NO box-shadow. */
}
.chip.payg   { background: var(--chip-payg-bg);   color: var(--chip-payg-fg); }
.chip.claude { background: var(--chip-claude-bg); color: var(--chip-claude-fg); }
.chip.codex  { background: var(--chip-codex-bg);  color: var(--chip-codex-fg); }
.chip.geode  { background: var(--chip-geode-bg);  color: var(--chip-geode-fg); }
```

### 5.2 Chip text contents (locked vocabulary)

| Selector | Visible text | Used when model prefix matches |
|---|---|---|
| `.chip.payg`   | `PAYG`        | `anthropic/…`, `openai/…` (raw provider API key billing) |
| `.chip.claude` | `Claude Code` | `claude-cli/…` (Claude Code Max OAuth) |
| `.chip.codex`  | `Codex Plus`  | `codex/…`, `openai-codex/…` (ChatGPT Plus OAuth) |
| `.chip.geode`  | `GEODE`       | `geode/…` (self-target wrapper) |

Frontend agent does **not** localize chip text. Always English. Always exactly as above.

### 5.3 Color contrast verification (WCAG 1.4.3 normal-text ≥ 4.5:1 / 1.4.11 ≥ 3:1)

All contrast ratios computed with sRGB relative luminance per WCAG 2.1.

| Chip | Fg hex | Bg hex | Ratio | Threshold | Pass |
|---|---|---|---|---|---|
| `.chip.payg`   | `#4a5260` (L=0.0838) | `#f1f3f5` (L=0.8866) | **7.74:1** | ≥ 4.5 | ✓ |
| `.chip.claude` | `#5a2ca0` (L=0.0561) | `#efe7fb` (L=0.8419) | **8.05:1** | ≥ 4.5 | ✓ |
| `.chip.codex`  | `#0a3622` (L=0.0254) | `#d1e7dd` (L=0.7765) | **10.42:1** | ≥ 4.5 | ✓ |
| `.chip.geode`  | `#052c65` (L=0.0223) | `#cfe2ff` (L=0.7559) | **10.46:1** | ≥ 4.5 | ✓ |

All four chips clear the WCAG AA normal-text threshold (4.5:1) — well above the master
DESIGN.md's stated 3:1 minimum for chips. No chip needs a border to compensate.

### 5.4 Chip placement rules

- **Inline before model code**: `<span class="chip …">…</span> <code>model/name</code>`.
  Always exactly one space (rendered NBSP unnecessary; standard space).
- **Multi-chip cells**: separate role groups by **one trailing space + new chip**. Browser
  wraps naturally at cell edge; do not insert `<br>`.
- The chip is **never** the link surface; the link is on the row id (`td.id a`).

---

## 6. Surface-bucket chip spec (`.bucket.{petri,seedgen,autoresearch}`)

```css
.bucket {
  display: inline-block;
  padding: 1.28px 6.4px;         /* .08rem .4rem */
  border-radius: 3px;
  font-size: 9.28px;              /* .58rem */
  font-weight: 700;
  font-family: var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  vertical-align: middle;
  margin-left: 5.6px;            /* .35rem */
}
.bucket.petri        { background: rgba(13, 110, 253, 0.12); color: var(--bucket-petri); }
.bucket.seedgen      { background: rgba(25, 135,  84, 0.12); color: var(--bucket-seedgen); }
.bucket.autoresearch { background: rgba(180, 83,   9, 0.12); color: var(--bucket-autoresearch); }
```

### 6.1 Bucket text + contrast

| Bucket | Visible text | Fg | Bg (effective on white) | Ratio | Pass (≥4.5 for normal, ≥3 for large) |
|---|---|---|---|---|---|
| `.bucket.petri`        | `petri`        | `#0d6efd` | `#dfeafc` (approx 12% on white) | **5.05:1** | ✓ |
| `.bucket.seedgen`      | `seedgen`      | `#198754` | `#dceee4` | **4.74:1** | ✓ |
| `.bucket.autoresearch` | `autoresearch` | `#b45309` | `#fbece0` | **4.77:1** | ✓ |

All three clear 4.5:1 — full WCAG AA even at small mono 9.28px.

### 6.2 Placement

- One bucket chip per row, in the `td.id` cell, **after** the id `<a>`.
- The bucket text is lowercase: `petri`, `seedgen`, `autoresearch`. Letter-spacing + uppercase
  CSS does the visual transform — keep the source HTML lowercase so screen-readers say it once
  and don't enumerate letters.

---

## 7. Section header spec (`h2.section`)

```css
h2.section {
  font-size: 11.52px;            /* .72rem */
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-faint);
  font-weight: 600;
  margin: 28px 0 8.8px;          /* 1.75rem 0 .55rem */
  font-family: var(--font-mono);
  display: flex;
  align-items: center;
  gap: 12px;                     /* .75rem */
}
h2.section::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--rule);
}
h2.section > span {
  /* Wrap label in <span> so the flex `::after` sibling can grow into the remaining width. */
}
```

Markup pattern: `<h2 class="section"><span>Petri Audit · 11 archives</span></h2>`.
The `<span>` wrapper is mandatory — without it, `::after` would push the flex behaviour onto
loose text nodes and not render the divider correctly across some flexbox edge cases.

Label format: `<Surface name> · <count + unit>`. Examples:
- `Petri Audit · 11 archives`
- `Seed Generation · 1 run · 7 phase tasks`
- `Autoresearch · baseline + mutation ledger`
- `Documentation`

The middle dot is U+00B7 (`·`), surrounded by single spaces.

---

## 8. Build-info footer spec (`.build-info`)

### 8.1 CSS

```css
.build-info {
  margin-top: 40px;              /* 2.5rem */
  padding-top: 16px;             /* 1rem */
  border-top: 1px solid var(--rule);
  color: var(--ink-faint);
  font-size: 11.2px;              /* .7rem */
  font-family: var(--font-mono);
}
.build-info p { margin: 4px 0; } /* .25rem */
.build-info code { background: var(--paper-tint); }
.build-info .chip { margin-right: 4px; }
.build-info .version-stamp {
  margin-top: 10px;
  color: var(--ink-soft);
}
```

### 8.2 Canonical markup

```html
<div class="build-info">
  <p>Source: <code>docs/self-improving/</code> (mirrors <code>docs/petri-bundle/</code> post-relocation).</p>
  <p>Published by <code>.github/workflows/pages.yml</code> on every <code>main</code> push.</p>
  <p>Harness chip legend:
    <span class="chip payg">PAYG</span>API key billing ·
    <span class="chip claude">Claude Code</span>Max OAuth ·
    <span class="chip codex">Codex Plus</span>ChatGPT Plus OAuth ·
    <span class="chip geode">GEODE</span>self-target wrapper.
  </p>
  <p>Repo: <a href="https://github.com/mangowhoiscloud/geode"><code>github.com/mangowhoiscloud/geode</code></a></p>
  <p class="version-stamp">
    Rendered against GEODE <code>v{GEODE_VERSION}</code> ·
    DESIGN.md schema {SCHEMA_VERSION} ·
    built {BUILD_DATE}.
    Dim subset: {DIM_SUBSET_COUNT} ({DIM_SUBSET_NAME}).
    Pipeline phases: {PIPELINE_PHASE_COUNT}.
    Baseline schema: v{BASELINE_SCHEMA_VERSION}.
  </p>
</div>
```

### 8.3 Build-time placeholder resolution

The build script (`scripts/build_self_improving_hub.py`, Phase 4) substitutes each `{…}`:

| Placeholder | Source | Example (v0.99.62) |
|---|---|---|
| `{GEODE_VERSION}` | `pyproject.toml` `version` field | `0.99.62` |
| `{SCHEMA_VERSION}` | `self-improving-hub-system.md` frontmatter `schema_version` | `1` |
| `{BUILD_DATE}` | CI `date -u +%Y-%m-%d` at workflow run | `2026-05-26` |
| `{DIM_SUBSET_COUNT}` | YAML row count `plugins/petri_audit/judge_dims/geode_judge_subset.yaml` | `22` |
| `{DIM_SUBSET_NAME}` | basename of subset file (sans `.yaml`) | `geode_5axes` (or `geode_judge_subset`) |
| `{PIPELINE_PHASE_COUNT}` | `len(_PHASE_ORDER)` in `plugins/seed_generation/orchestrator.py` | `8` |
| `{BASELINE_SCHEMA_VERSION}` | constant in `autoresearch/state/baseline.json.metadata.schema_version` | `2` |

If any placeholder cannot be resolved at build time → CI fails. **No silent default substitution**
(this prevents the [[feedback-changelog-implementation-parity]] anti-pattern of stale stamps).

### 8.4 Anchor invariant

The legend paragraph must contain all four chips in the exact order `PAYG · Claude Code · Codex Plus
· GEODE`. This order is fixed so visitors building muscle memory across pages always see chips in
the same slot. Per-page DESIGN.md `verification_checklist` test asserts this order via regex.

---

## 9. Empty-state visual spec

### 9.1 Petri Audit · 0 rows

```html
<h2 class="section"><span>Petri Audit · 0 archives</span></h2>
<table class="records">
  <thead>
    <tr>
      <th scope="col">id</th><th scope="col">seeds</th>
      <th scope="col">auditor</th><th scope="col">target</th>
      <th scope="col">judge</th><th scope="col">started</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td colspan="6" class="muted">
        <em>No audits published yet. Run <code>geode audit --live</code>.</em>
      </td>
    </tr>
  </tbody>
</table>
```

Style: italic via `<em>`, color via inherited `td.muted` (`--ink-soft`). No icon, no illustration,
no skeleton loader. Cell padding identical to data rows.

### 9.2 Seed Generation · 0 rows

```html
<tbody>
  <tr>
    <td colspan="7" class="muted">
      <em>No seed-generation runs published yet.</em>
    </td>
  </tr>
</tbody>
```

### 9.3 Autoresearch · `baseline.json` absent

The baseline row collapses to a single empty-message cell **while remaining inside the 4-row table**
(the other 3 artifact rows — mutations/results/policies — render independently from their own files).

```html
<tr>
  <td class="id">baseline.json <span class="bucket autoresearch">autoresearch</span></td>
  <td colspan="4" class="muted">
    <em>No baseline written yet — run
      <code>uv run python autoresearch/train.py --promote</code>.
    </em>
  </td>
</tr>
```

If `mutations.jsonl` is also absent: same pattern, message
`<em>No mutations recorded yet. Loop has not run.</em>`.
If `results.tsv` absent: `<em>No results written yet.</em>`.
If `policies/` directory is missing: `<em>Policies directory not yet populated.</em>`.

### 9.4 Whole-page fallback (build-time fatal)

Per master DESIGN.md §10: if `listing.json` is missing entirely, the build script raises and CI
fails. The deployed page never shows a "all empty" hero — that's a build error, not a runtime
state.

---

## 10. Accessibility compliance checklist

### 10.1 Color contrast summary (all WCAG 2.1 AA)

| Pair | Use | Ratio | Required | Pass |
|---|---|---|---|---|
| `--ink #1a1f29` on `--paper #ffffff` | Body text | **16.31:1** | 4.5 | ✓ |
| `--ink-soft #4a5260` on `--paper #ffffff` | `.muted`, `.page-sub` | **9.17:1** | 4.5 | ✓ |
| `--ink-faint #7d8694` on `--paper #ffffff` | Captions, `.nav-section` | **3.93:1** | 3.0 (large/UI) | ✓ |
| `--ink-faint #7d8694` on `--paper-tint #f8f9fa` | Sidebar captions | **3.78:1** | 3.0 | ✓ |
| `--accent #0d6efd` on `--paper #ffffff` | Links | **4.62:1** | 4.5 | ✓ |
| `--accent #0d6efd` on `--accent-faint #e7f1ff` | Hover nav link | **4.10:1** | 3.0 (UI) | ✓ |
| `.chip.payg` | (see §5.3) | 7.74:1 | 4.5 | ✓ |
| `.chip.claude` | (see §5.3) | 8.05:1 | 4.5 | ✓ |
| `.chip.codex` | (see §5.3) | 10.42:1 | 4.5 | ✓ |
| `.chip.geode` | (see §5.3) | 10.46:1 | 4.5 | ✓ |
| `.bucket.petri` | (see §6.1) | 5.05:1 | 4.5 | ✓ |
| `.bucket.seedgen` | (see §6.1) | 4.74:1 | 4.5 | ✓ |
| `.bucket.autoresearch` | (see §6.1) | 4.77:1 | 4.5 | ✓ |

`--ink-faint` on `--paper` at **3.93:1** is **below** the 4.5 normal-text threshold but **above**
the 3.0 large-text + UI-element threshold. We use it only for: section header captions
(`h2.section` is uppercase letter-spaced mono and visually closer to a label than body text),
`.nav-section`, `.brand-sub`, `.count`, `.build-info`. All these uses are non-prose UI labels.
For prose, use `--ink-soft` (9.17:1).

### 10.2 ARIA / semantics

- `<aside class="sidebar">` wraps a `<nav aria-label="Self-Improving Hub navigation">`.
- The active sidebar link gets **both** `class="active"` and `aria-current="page"`.
- Tables use `<th scope="col">` on each header.
- `<th>` font-weight 600 + uppercase suffices; do not add `aria-label` to plain text headers.
- External links use `↗` glyph **plus** `rel="noopener external"`.
- No `target="_blank"` on internal `/geode/*` links. External GitHub link **may** omit `target`
  (page already has no JS state to preserve); browser default behaviour is acceptable.

### 10.3 Focus-visible state

Every interactive element (`a`, `button` if any) gets:

```css
a:focus-visible, button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
  border-radius: 2px;
}
```

No `:focus { outline: none; }` overrides anywhere — frontend agent must preserve native focus
rings on non-`:focus-visible` matches too if any element ever takes programmatic focus.

### 10.4 Motion

- **Zero animations.** No `@keyframes`, no `animation:`, no scroll-driven motion.
- **Allowed transitions**: `background-color` and `color` only, max duration `120ms`, `ease`.
- `prefers-reduced-motion: reduce` — no override needed because we declared no motion to begin
  with. (Still acceptable to add `@media (prefers-reduced-motion: reduce) { * { transition: none; } }`
  as a defensive belt-and-braces.)

### 10.5 Keyboard navigation

- Tab order follows DOM order: sidebar nav (top-down) → main content links (left-to-right,
  top-to-bottom).
- No `tabindex` overrides except `tabindex="-1"` if a skip-link target is ever added (not in
  scope for hub MVP).
- No focus traps — there are no modals.

### 10.6 Skip-link (recommended)

```html
<a href="#main-content" class="visually-hidden-focusable">Skip to main content</a>
<main id="main-content" class="content">…</main>
```

```css
.visually-hidden-focusable {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0); border: 0;
}
.visually-hidden-focusable:focus-visible {
  position: static; width: auto; height: auto; padding: 4px 8px; margin: 0;
  background: var(--accent); color: #fff; clip: auto;
}
```

---

## 11. Anti-patterns this page must avoid

The frontend agent must NOT introduce any of the following. Each item is a hard fail —
flagged at PR review by `docs-link-audit` + visual inspection.

| # | Anti-pattern | Why it's banned |
|---|---|---|
| 1 | Card-lift hover (`transform: translateY(-2px)`, `box-shadow` on hover) | [[feedback-no-box-ui-no-emoji]] — dense data, not marketing cards |
| 2 | Emoji as nav prefix, section anchor, or in chip text (📊, 🧪, 🔬, ✓, ☆, etc.) | Same rule. Allowed only inside opt-in report outputs. |
| 3 | Gradient backgrounds (`linear-gradient`, `radial-gradient`) | Master DESIGN.md §3 — hairline borders only |
| 4 | Drop shadows (`box-shadow`, `filter: drop-shadow`) | Same |
| 5 | Toast notifications or modal dialogs | Master DESIGN.md §6 — forbidden components |
| 6 | Animations beyond `:hover` color change | §10.4 + master DESIGN.md §12 |
| 7 | Warm tones (yellow / orange / red / amber / terracotta) other than `--bucket-autoresearch` | Cotton monochromatic discipline borrowed |
| 8 | Web font imports (`@import url(…fonts.googleapis…)`, `<link rel="stylesheet" href="…fonts…">`) | Master DESIGN.md §4 — system stack only, 0 extra HTTP |
| 9 | JS framework (React, Vue, Svelte, Alpine.js, htmx) | Master DESIGN.md §13 — static HTML+CSS only |
| 10 | Inline `<style>` blocks > 5 lines | Push to `assets/hub.css` — one stylesheet, cacheable |
| 11 | `<img>` tags (except favicon, ≤2KB) | Master DESIGN.md §13 + per-page §11 size budget |
| 12 | Dark mode toggle / `prefers-color-scheme: dark` rules | Single substrate (light only) — master DESIGN.md §2 |
| 13 | Rounded card boxes (`border-radius` > 4px on container divs) | Hairline rule borders only; chip 3px is the only rounded surface |
| 14 | Decorative grid icons (SVG icons, icon fonts) | Forbidden per master DESIGN.md §6 |
| 15 | Hero CTAs (`<button class="cta">Get started</button>`) | This is a status page, not marketing |
| 16 | Placeholder counts (`XXX seeds`, `TBD`) | [[feedback-changelog-implementation-parity]] anti-deception |
| 17 | `target="_blank"` without `rel="noopener"` | Security; we keep external links `rel="noopener external"` |
| 18 | `<style>` overrides of `:focus` to `outline:none` without `:focus-visible` replacement | a11y regression |
| 19 | Sidebar containing per-page-unique tree shapes (e.g. dropping the Meta section on some pages) | Master DESIGN.md §7 — identical across all hub pages |
| 20 | Manual-written timestamp in `.version-stamp` or `.build-info` | CI substitution only — see §8.3 |

---

## 12. Implementation note (single stylesheet)

The frontend agent produces:

- One HTML file: `docs/self-improving/index.html`
- One CSS file: `docs/self-improving/assets/hub.css`
- One favicon: `docs/self-improving/assets/favicon.svg` (or reuse existing)

No other files. No JS file. No image directory. Total gzipped page weight target: **<50KB** per
per-page DESIGN.md §11. With system fonts + minified CSS + 10-row tables, this is comfortable;
the constraint exists only to prevent unintentional bloat (web font, hero image, JS framework).

### 12.1 CSS file order

```
1. :root tokens                  (§1)
2. *, html, body resets
3. Layout shell (.shell, aside.sidebar, main.content)
4. Sidebar internals             (§3.2)
5. Page-level typography (h1, .page-sub, h2.section, h3.subsection, code)
6. table.records + cells         (§4.2)
7. .chip + .chip.{payg,claude,codex,geode}    (§5.1)
8. .bucket + .bucket.{petri,seedgen,autoresearch}  (§6)
9. .role-label
10. .build-info + .version-stamp  (§8.1)
11. Accessibility helpers (.visually-hidden-focusable, focus-visible)
12. (optional) @media (prefers-reduced-motion: reduce) defensive override
```

Total expected: ~250-300 lines uncompressed. Comment headers between sections.

---

## 13. Verification checklist (matches per-page §11)

Frontend agent must self-verify before submitting PR:

- [ ] All `<a href>` start with `/geode/` (except `https://github.com/…`).
- [ ] Sidebar matches §3.1 exactly (7 sections incl. Meta).
- [ ] Active link has both `class="active"` and `aria-current="page"`.
- [ ] `<nav aria-label="Self-Improving Hub navigation">` wraps the sidebar links.
- [ ] All 4 chips present in build-info legend in canonical order.
- [ ] All tables include `<th scope="col">` on headers.
- [ ] Empty-state markup (§9) included for at least one section in dev preview.
- [ ] Build-info version-stamp uses `{…}` placeholders, never hand-written values.
- [ ] Page weighs <50KB gzipped (CI ratchet, deferred but check manually).
- [ ] No `box-shadow`, `transform`, `gradient`, `@keyframes`, `animation` in `hub.css`.
- [ ] `ruff`-equivalent: HTML validates (W3C); CSS validates (no parse errors).
- [ ] Color contrast spot-check matches §10.1 (Lighthouse / axe-core).
