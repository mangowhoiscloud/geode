# DESIGN.md — Portfolio (mangowhoiscloud.github.io/portfolio)

> Google Stitch DESIGN.md format — 9 sections. AI agents read this before writing UI for this codebase.
> Audience: developers, recruiters reviewing engineering work, technical reviewers.
> Surface: Next.js 16 + Tailwind 4 + React 19, static export at GH Pages.
> Aesthetic: GEODE Editorial — **warm dark mode**. Anthropic's editorial restraint, inverted to dark.
> Last verified against code: 2026-05-02.

---

## 1. Visual Theme & Atmosphere

**Mood**: Anthropic-inspired dark mode. Warm near-black substrate (not blue-black, not pure black), cream-on-warm-dark prose, amber accent. Reads like an editorial dossier on a leather desk at night — composed, dense, calm.

**Adjectives**: warm dark, editorial, restrained, ink-on-warm-dark, amber-accented, single-substrate.

**What it is not**: blue-night gradient, neon, mascot-heavy, multi-accent rainbow, motion-decorated. Pure-black surfaces (`#000`) and pure-white text (`#fff`) are forbidden — both are too cold for this aesthetic.

**Inspiration touchstones**: Anthropic docs (typographic restraint), Cursor (developer-first dark), Are.na (warm dark editorial), Tufte books inverted to dark, terminal `urxvt` with the `Tomorrow Night` palette.

## 2. Color Palette & Roles

| Role | Hex | Usage |
|---|---|---|
| `--paper` | `#181816` | App background. Warm dark stone surface. |
| `--paper-2` | `#23211F` | Card / elevated surface (sidebar, callout, hover). |
| `--paper-deep` | `#0E0E0C` | Code block (deepest). |
| `--ink` | `#EDE7DA` | Primary text. Warm cream, bumped for legibility. |
| `--ink-1` | `#DDD3BE` | Headings. |
| `--ink-2` | `#B5AC97` | Body — bright enough to keep prose from fading. |
| `--ink-3` | `#807665` | Captions, metadata. |
| `--rule` | `#3A342D` | Hairline borders. Slightly more visible than substrate. |
| `--rule-soft` | `#2A2520` | Softer divider, between sections. |
| `--acc-artifact` | `#4D9BFF` | **PETRI-BLUE** — primary accent. The self-improving hub's signature (`#0d6efd`, Bootstrap blue) lightened for AA on the dark substrate. OS / artifact / runtime / the live system. |
| `--acc-line` | `#D5B27A` | **CITRINE** — secondary. scaffold / line / process / CI. Warm complement to the petri-blue primary. |
| `--acc-soft` | `#7FB5FF` | Hover / elevated state for the petri-blue accent. |
| `--acc-si` | `#4D9BFF` | Self-Improving identity, now **unified with the primary** accent so the whole site (portfolio + docs + hub) reads as one petri-blue identity. |
| `--acc-si-soft` | `#7FB5FF` | Hover state for the self-improving accent. |
| `--code-bg` | `#0E0E0C` | Code block background. |
| `--code-text` | `#DDD3BE` | Code block text. Same as `--ink-1`. |
| `--code-string` | `#D5B27A` | Code strings (citrine, kindred to line accent). |

**Identity rationale.** The primary accent is **petri-blue** (`#4D9BFF`), the
self-improving hub's signature (`#0d6efd`) adapted for the dark substrate, so
the portfolio, the docs, and the hub all read as one system. PR-PALETTE-REGROUND
(2026-05-30) re-grounded it from amethyst to this hub identity. Citrine
(`#D5B27A`) is the secondary, kept for the scaffold / line / process axis as a
warm complement. The two-mode discipline holds: artifact / runtime / the live
system gets petri-blue, the scaffold that builds it gets citrine.

**Single substrate.** Every page is dark by design. There is no light mode. There is no dark-panel-on-light-page pattern. Mascot PNGs and SVG diagrams that were authored for dark mediums sit naturally on this substrate.

**Two accents, now one unified identity.** Petri-blue (artifact / OS / the live system, primary) and citrine (scaffold / line / process, secondary) are the two global accents. As of PR-PALETTE-REGROUND the petri-blue primary IS the hub signature, so `--acc-si` equals `--acc-artifact`: the Self-Improving Loop docs section no longer needs a distinct hue, and portfolio + docs + hub share one petri-blue. The `data-doc-section` + `--section-accent` mechanism remains in place (it resolves to `--acc-artifact` everywhere now), so re-introducing a scoped section hue later is a one-line change.

## 3. Typography Rules

| Variable | Family | Weights | Usage |
|---|---|---|---|
| `--font-inter` | Inter | 400, 500, 600, 700 | UI chrome, body sans |
| `--font-display` | Outfit | 600, 700, 800 | Page titles (h1), section labels |
| `--font-fira-code` | Fira Code | 400, 500 | Code blocks, file paths, version chips |

**Body is sans (Inter), not serif.** Editorial restraint comes from spacing, line-height, and color discipline — not from a serif body. Warm dark mode and serif body together would feel funereal; Inter on warm dark reads as a professional dossier.

**Korean (KO mode)**: same families. Korean glyph rendering falls back through `Apple SD Gothic Neo`, `Noto Sans KR`, `Malgun Gothic`. No additional Korean web font.

**Scale** (page prose):

| Element | Size | Line height |
|---|---|---|
| h1 (hero) | clamp(3rem, 8vw, 5rem) | 1.02 |
| h1 subhead | clamp(1.25rem, 2.5vw, 1.6rem) | 1.30 |
| h2 (section) | 1.6–2rem (~26–32px) | 1.20 |
| h3 (subsection) | 1.2–1.4rem | 1.25 |
| body | 16px | 1.65–1.75 |
| caption | 13px | 1.45 |
| code (inline) | 13px | 1.50 |
| code (block) | 12.5px | 1.65 |
| table cell | 13–14px | 1.50 |

**No text gradients. No clip-text effects.** Solid `--ink-1` for hero headlines.

## 4. Component Stylings

### Page-level wrapper

```tsx
<main className="min-h-screen bg-[var(--paper)] text-[var(--ink)]">
```

### Sticky header (when present)

`sticky top-0 z-30 border-b border-[var(--rule)] bg-[var(--paper)]/85 backdrop-blur`

### Sidebar

- Width 256px, sticky, own scroll.
- Section labels: `text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]`.
- Item: `text-[13px] text-[var(--ink-2)]`. Active: `bg-[var(--paper-2)] text-[var(--ink)]`.

### Cards

- `rounded-lg border border-[var(--rule)] bg-[var(--paper-2)] hover:border-[var(--ink-3)] p-5 transition-colors`
- No shadow. Hairline border only.

### Locale toggle

- Two-button group, hairline border, mono `text-[11px]`.
- Active state: `bg-[var(--paper-2)] text-[var(--ink)]`. Inactive: `text-[var(--ink-3)] hover:text-[var(--ink)]`.

### Hero

- Single-column 720px content max-width.
- h1 in display font, `--ink` color, no gradient.
- Subhead in display font, `--ink-1` color.
- Two narrative paragraphs, body sans, `--ink-2`.
- A single mono code block (or none).
- Nav links as small bordered chips, hairline border, hover swaps to amber.

### Tables

- `border-collapse: collapse; font-size: 13–14px`.
- `border: 1px solid var(--rule)` on every cell.
- Header row: `bg-[var(--paper-2)]; font-weight: 600; color: var(--ink-2)`.

### Code

- Inline: `bg-[var(--paper-2)]; padding: 0.1rem 0.4rem; border-radius: 3px; color: var(--code-string)`.
- Block: `bg-[var(--code-bg)]; border: 1px solid var(--rule); border-radius: 6px; padding: 1rem 1.25rem; color: var(--code-text)`. Horizontal scroll allowed; never wraps.

### Mascot

- Geodi PNG sits naturally on `--paper` (warm dark) — no inset wrapper needed; the PNG was authored for dark mediums and matches the substrate.
- 36×40px in hero, 32px in footer. Always static, never animated.

### Blockquotes

- `border-left: 3px solid var(--acc-artifact); padding-left: 1rem; color: var(--ink-2); font-style: italic`.

## 5. Layout Principles

- **Single column** for prose-led pages (landing, scaffold, docs body): 720px content max-width, centered. The geode landing composes this.
- **Three-column** for docs index: sidebar 256px · content 720px · gutter 32px. Outer max 80rem.
- **Vertical rhythm**: 96–128px between major sections. 48px between subsections. 1.4rem between paragraphs.
- **Sticky surfaces**: header, sidebar (own scroll). No sticky footers.
- **Whitespace policy**: prefer empty space to filler. Below H1 sits a single muted summary line, no decorative dividers above.

## 6. Depth & Elevation

- **Borders, not shadows.** Hairline `--rule` (warm dark, ~10% lighter than `--paper`) demarcates cards and sticky surfaces. The single substrate already does the contrast work.
- **Tone shifts.** Elevation comes from `--paper` → `--paper-2` (~6% lighter), not from luminance bumps. Code blocks go the other direction: `--paper-deep` (~8% darker) for inset code.
- The only blur is sticky-header `backdrop-blur` over the page background.
- No glow, no neon, no emboss.

## 7. Do's and Don'ts

**Do**:
- Default to `--paper` substrate everywhere. Single dark mode.
- Use `--acc-artifact` for OS / artifact / runtime / model content.
- Use `--acc-line` for scaffold / process / discipline / CI content.
- Use tables for structured comparison; bullet lists for narrative enumeration.
- Cite file paths and line numbers in mono `--code-string`.
- Use code blocks for any literal Python / TS snippet, even one-liners.
- Trust solid colors. Never compose colors via gradient.

**Don't**:
- Don't introduce a light mode. The substrate is fixed.
- Don't use pure black `#000` or pure white `#fff` — both are too cold.
- Don't introduce gradients (text or background).
- Don't add motion beyond `transition-colors`. No spring, no slide, no fade-in beyond the once-per-page-load 0.4s opacity fade.
- Don't add emojis to UI chrome (titles, headings, labels).
- Don't introduce new accent colors. Two accents. Petri-blue for artifact, citrine for line, and that is it.
- Don't use `dark-panel` or `mascot-inset` utilities — they were transitional and are removed in the dark-mode reset.
- Don't add larger corner radii than `rounded-lg` (8px).

## 8. Responsive Behavior

- **md (≥768px)**: full layout, sidebar visible (where applicable).
- **<md**: sidebar collapses, content fills with `px-6` margins.
- Tables overflow horizontally on small screens; never collapse to stacked card layout (the comparison value is lost).
- Code blocks scroll horizontally on overflow; never wrap.
- Touch targets: ≥32×32px effective hit area.

## 9. Agent Prompt Guide

When asked to build or modify UI in this portfolio repo:

1. **Read this DESIGN.md first.** Tokens are defined here; do not introduce new ones.
2. **Use `var(--*)` tokens, not hex literals.** New components reference `var(--paper)`, `var(--ink-1)`, etc. Hex literals are only acceptable in legacy components scheduled for migration.
3. **Single substrate.** Every page wraps in `bg-[var(--paper)] text-[var(--ink)]`. Section-level dark or light overrides are forbidden.
4. **Mascot images sit naturally on the substrate** — do not wrap in inset containers. Geodi was authored for warm dark mediums.
5. **Two-mode accents.** When emitting an artifact (OS, runtime, prompt, hash) reference, use `--acc-artifact`. When emitting a line (scaffold, ratchet, CI, kanban) reference, use `--acc-line`. Mixing them within a single section is acceptable only when comparing the two modes (recursion table).
6. **Korean default.** `<html lang="ko">` from `src/app/layout.tsx`. Bilingual content uses `<Bi ko={...} en={...} />` for the docs site or the `t(locale, ko, en)` helper for components.
7. **Verification**: after edits, run `node ./node_modules/typescript/bin/tsc --noEmit -p tsconfig.json` and `next build`. Both must exit 0.

**Forbidden additions** (without explicit user approval):
- New web fonts.
- New color tokens.
- shadcn/ui new components beyond Dialog / Slot / Tabs / Tooltip (already installed).
- Animation libs beyond Framer Motion (already installed, used minimally).
- A second design surface (light mode, marketing-style hero, etc.).
- The legacy `--sea-*`, `--glow-*` palette references in new code. Existing references will migrate over time.

**Reference DESIGN.md examples for similar aesthetic**: VoltAgent/awesome-design-md → Anthropic (dark variant inferred), Cursor, Linear (dark mode). Do not borrow gradient or neon patterns from any of them.

---

## 10. Portfolio Patterns (researched)

The hub at `/portfolio/` and the project pages adopt patterns proven on
high-attention developer portfolios and on top-starred Claude Code tool
READMEs. This section names the patterns and their sources, so future
edits stay anchored to the right reference instead of drifting into
generic SaaS-marketing layouts.

### Adopted patterns

| Pattern | Source / Precedent | Why we adopt it |
|---|---|---|
| **Single dated header** ("Portfolio · 2026-05-03") | leerob.io, paco.me | Shows the site is alive, makes the operator accountable to its currency. |
| **§ Now section** (current focus, dated entries) | nownownow.com convention, derek sivers | Recruiters read this first. Three lines that fit on one screen, freshest at top. |
| **§ Selected Work, not full CV** | brittanychiang.com, leerob.io | Two or three exhibits with concrete numbers beats a chronological resume. |
| **§ Recognition** (awards, talks, blog/yt counts) | senior-eng portfolios across industry | Outside validation in three lines max. No badges, no logos. |
| **§ Influences** (named people / projects + one-line note) | rauchg.com, paco.me's "things I like" | Signals intellectual lineage. Lifts the portfolio above task lists. |
| **Honest "currently looking for X" only when applicable** | (deliberately omitted today) | Adds friction when not actively job-seeking; remove if false. |
| **Code blocks in landing** | Cursor docs, Vercel docs landing | Shows the operator works in code, not slides. |
| **Mono `file:line` citations** | Anthropic docs, Linear changelog | Citations as content, not footnotes. |
| **Footer = nav, not legalese** | brittanychiang.com, leerob.io | One row of arrows to deeper pages. No copyright line. |

### Researched references — top-starred Claude Code tools

Their READMEs and landings consistently:

- Open with one-sentence purpose ("X for Y").
- Show install in three lines max.
- List concrete capabilities, not adjectives.
- Hide setup notes / troubleshooting in deeper sections.
- Use `code blocks` instead of marketing prose where possible.

Examples to study (publicly available repositories):

- `claude-code-action` — GitHub action; README is install + ready-to-paste YAML.
- `ccmanager` — CLI; README is install + commands + screenshots.
- `claude-flow` — orchestration; README is concept diagram + mode list.
- `awesome-claude-code` — curated list; sectioned by use case, no editorial fluff.

### Anti-patterns we avoid

- Generic "About me" paragraphs that read as cover-letter prose.
- Logos of past employers as visual proof.
- Skill bars / radar charts.
- Quote callouts from press / "What people say".
- Animated counters of GitHub stars / downloads.
- "Let's chat" CTA buttons. Contact lives in the footer as plain text.
- Theme switcher. We have one substrate.
- Light mode of any kind.

### Hub structure (canonical)

```
[Header]                  Name + role + bio paragraph (≤2 sentences)
[§ Now]                   3 dated entries, freshest at top
[§ Selected Work]         2–3 cards, each with concrete numbers
[§ Recognition]           ≤4 lines, label + detail
[§ Influences]            3–5 named references with one-line notes
[Footer]                  Plain mono arrows to deeper pages
```

Mobile collapses the three-column header to a single column; everything
else is already single-column.

### Voice guideline

Korean prose follows 합니다체 — the formal register that Korean tech
blogs (토스, 우아한형제들, 네이버 D2) use for engineering content.
Avoid 한다체 (literary), 해요체 (casual), 평어체 (academic). Numbers
stay Arabic in metric strips; in body prose they remain Arabic too
(64회, 5,523개) — this matches Korean tech-blog convention more than
prose convention (예순넷, 오천오백이십삼).

English prose stays declarative and concrete. Avoid em-dash chains
beyond two per paragraph. No "let's", "we'll", "exciting", "powerful",
"revolutionary". Past tense for shipped work, present tense for what
the system does today.

### Anti-LLM-smell checklist for new copy

Before merging copy changes, verify the prose does not exhibit any of:

- [ ] Slogan-as-equation ("X = Y. Y = Z.") — break into sentences.
- [ ] Em-dash heaped lists — convert to clauses.
- [ ] Unspecific verbs ("수행한다", "처리한다", "활용한다") — replace
      with concrete action verbs.
- [ ] "Frontier 어디에도 없다" or other unverifiable superlatives.
- [ ] Quotes around English terms purely for emphasis.
- [ ] Korean morphology of large numbers (예순네, 다섯, 아홉) outside
      narrative prose.
- [ ] Marketing-flavored adjectives (powerful, robust, seamless,
      elegant, beautiful).
- [ ] Sentences that translate cleanly back to "we built X to solve Y."

---

## 11. Petri-bundle bridge surfaces

The Petri bundle at `docs/petri-bundle/` is a *separate static surface* from the docs site. It is generated by `inspect_ai` tooling and uses Bootstrap. Visitors move between three URLs that should feel like one bundle:

| Bridge URL | What lives there | Owner |
|---|---|---|
| `/petri-bundle/` | inspect_ai eval-log viewer (`index.html`). Hash routes (`#/tasks/<eval>/samples/scoring`) are stable deep links. | inspect_ai (do not modify) |
| `/petri-bundle/landing.html` | GEODE-authored hub. Routes the user to viewer / seeds listing / docs. | this repo (`docs/petri-bundle/landing.html`) |
| `/petri-bundle/seeds/` | Self-improving-loop seed bundle. `listing.json` plus per-run JSON. | this repo (`docs/petri-bundle/seeds/`) |
| `/docs/petri/seeds/[run_id]/[candidate_id]/` | Markdown-rendered seed detail (frontmatter + body + critic / pilot / evolver sidebar). Static-export Next.js page. | this repo (`site/src/app/docs/petri/seeds/[run_id]/[candidate_id]/page.tsx`) |

### 11.1 Color policy on bridge surfaces

The viewer (`index.html`) uses Bootstrap's default dark palette. The GEODE-authored hub (`landing.html`) borrows that palette directly so the substrate is continuous when the visitor toggles between them:

| Role | Bridge hex | Docs-site equivalent |
|---|---|---|
| Substrate | `#212529` (Bootstrap `--bs-dark`) | `--paper` (`#181816`) |
| Elevated | `#2b3035` | `--paper-2` (`#23211F`) |
| Rule | `#3a3f44` | `--rule` (`#3A342D`) |
| Body ink | `#dee2e6` | `--ink` (`#EDE7DA`) |
| Muted | `#adb5bd` | `--ink-2` (`#B5AC97`) |
| Accent | `#0d6efd` (Bootstrap blue) | `--acc-artifact` (`#4D9BFF`), the site-wide petri-blue primary (the bundle blue lightened for AA on dark) |

This bridge palette (substrate / elevated / rule / ink) appears **only** in `docs/petri-bundle/landing.html` and any future static HTML co-located under `docs/petri-bundle/`. Next.js docs pages continue to use the §2 substrate/ink tokens, with no exception.

**Accent continuity is now automatic.** The self-improving hub's signature is the petri Bootstrap-blue `#0d6efd`, the identity color of the whole self-improving surface (hub + petri bundle). As of PR-PALETTE-REGROUND that color IS the site-wide primary `--acc-artifact` (`#4D9BFF`, lightened for AA on dark), so the bundle, the docs, and the portfolio share one petri-blue with no scoping needed. The `data-doc-section="04-self-improving"` + `--section-accent` mechanism in `docs-shell.tsx` remains (it resolves to `--acc-artifact` everywhere now), so re-introducing a distinct scoped hue later is a one-line change.

The hub's own token source of truth is `docs/design/self-improving-hub-system.md §3` (the light signature palette: white paper, `#0d6efd` accent, 3 surface buckets). The hub stays light (its native identity); docs stay dark — the shared thread is the signature accent, not the light/dark mode.

### 11.2 Anti-slop on bridge surfaces

The hub at `/petri-bundle/landing.html` and any sibling static page follow the same anti-slop rules as the docs site:

- No emoji in section anchors, button labels, table headers, or nav prefixes.
- No card grids when the content is data — dense `<table>` or `<dl>` only.
- No marketing prose (`fast`, `powerful`, `seamless`, `beautiful`, `revolutionary`).
- No "Click here" CTAs. Links carry the destination path (mono) and a terminal `→`.
- No gradient buttons, no glow, no hover scale. Hairline border + color shift only.
- Counters that read from JSON show `—` until the fetch resolves; no spinner, no skeleton shimmer.
- No web fonts — system stack (`system-ui`, `ui-monospace`).

### 11.3 Markdown rendering on the docs side

Seed candidate `.md` bodies render at build time inside the Next.js docs site:

| Tool | Role | Size impact |
|---|---|---|
| `gray-matter` | Frontmatter parse (`target_dims`, `tags`, `references`). | ~5KB gzip |
| `marked` | Markdown body → HTML. | ~25KB gzip |

`react-markdown` and the full `remark` toolchain were considered and rejected — they pull in 80KB+ for runtime rendering capability we do not need (build-time HTML is sufficient on a static-export site).

Rendered markdown sits inside the existing prose surface (§4 typography, §2 color tokens). Code blocks render to the `--code-bg` / `--code-text` token pair. Headings use `--ink-1`. No new CSS classes; the existing prose styles in `geode-docs` cover this.

### 11.4 Cross-link conventions

| From | To | Pattern |
|---|---|---|
| `/docs/petri/bundle/` | bundle hub | `/petri-bundle/landing.html` (absolute, since it leaves Next.js base path) |
| `/docs/petri/seeds/` survivor row | candidate detail | `/docs/petri/seeds/[run_id]/[candidate_id]/` (Next.js basePath-aware) |
| `/docs/petri/seeds/[run_id]/[candidate_id]/` raw link | raw `.md` | `/petri-bundle/seeds/<run_id>/candidates/<id>.md` |
| `/docs/petri/seeds/[run_id]/[candidate_id]/` eval link | inspect viewer deep link | `/petri-bundle/#/tasks/<eval_id>/samples/scoring` (only when an eval is matched to the candidate; otherwise omit) |
| `landing.html` viewer link | inspect viewer root | `./index.html` (relative — landing sits beside the viewer) |

The viewer hash routes (`#/tasks/...`) are not Next.js basePath-aware. Always use absolute paths starting with `/petri-bundle/` when constructing these.

### 11.5 Forbidden on bridge surfaces

- Inserting a Next.js page at `/petri-bundle/*` — that path is owned by the inspect viewer + static HTML.
- Modifying `docs/petri-bundle/index.html` directly — it is regenerated by inspect_ai tooling and will overwrite hand edits.
- Adding a build step that compiles `landing.html` from a template — it is plain HTML on purpose so anti-slop and link drift are reviewable in the diff.
- Re-exposing the Bootstrap palette via CSS custom properties in `globals.css`. The bridge hex values are scoped to the `landing.html` `<style>` block only.

---

**Maintained at**: `/Users/mango/workspace/portfolio/DESIGN.md`. Tokens authoritative source: `src/app/globals.css`. When tokens change in code, update this file in the same commit. Drift between code and DESIGN.md is a regression.
