# DESIGN.md — Portfolio (mangowhoiscloud.github.io/portfolio)

> Google Stitch DESIGN.md format — 9 sections. AI agents read this before writing UI for this codebase.
> Audience: developers, recruiters reviewing engineering work, technical reviewers.
> Surface: Next.js 16 + Tailwind 4 + React 19, static export at GH Pages.
> Aesthetic: GEODE Axolotl Rose — **cool near-black + one signature accent**, drawn from the GEODE character.
> Last verified against code: 2026-06-11 (PR-DOCS-REDESIGN-TOKENS).

---

## 1. Visual Theme & Atmosphere

**Mood**: a modern dark developer surface keyed to the GEODE character — a rose axolotl explorer with a gold headlamp and an aqua magnifier (`public/images/geode-*.png`). Cool near-black substrate with a violet undertone, one saturated signature accent (rose) carried everywhere as low-opacity tints, gold reserved for action, aqua for information. Reads like a well-lit terminal, not a leather desk.

**Adjectives**: cool dark, signature-tinted, character-grounded, restrained, single-substrate.

**What it is not**: brown-warm stone, navy deep-sea, neon, multi-accent rainbow, motion-decorated. Pure-black surfaces (`#000`) and pure-white text (`#fff`) are forbidden.

**Inspiration touchstones**: Hermes docs (one bold accent + tinted hairlines + dot-grid texture on near-black), Anthropic docs (typographic restraint), Cursor (developer-first dark).

## 2. Color Palette & Roles

| Role | Hex | Usage |
|---|---|---|
| `--paper` | `#0B0A10` | App background. Cool near-black, violet undertone. |
| `--paper-2` | `#14121B` | Card / elevated surface (sidebar, callout, hover). |
| `--paper-deep` | `#06050A` | Code block (inset). |
| `--ink` | `#F2EEF5` | Primary text. |
| `--ink-1` | `#E5DFEC` | Headings. |
| `--ink-2` | `#ABA4BC` | Body secondary. |
| `--ink-3` | `#6E6880` | Captions, metadata. |
| `--rule` | `rgba(244,155,196,.12)` | Hairline borders. **Rose-tinted**, never neutral gray. |
| `--rule-soft` | `rgba(244,155,196,.06)` | Softer divider, table header background. |
| `--acc-artifact` | `#F49BC4` | **AXOLOTL ROSE** — the signature. Logo, wordmark, active nav, selection, reference chip. The character's body color. |
| `--acc-line` | `#FFD66B` | **LAMP GOLD** — action. CTA, emphasis, string literals, tutorial chip. The explorer's headlamp. |
| `--acc-soft` | `#F7B3D2` | Rose hover / elevated state. |
| `--acc-aqua` | `#7FD8E8` | **AQUA** — information. Links, inline code, how-to chip. The magnifier lens. |
| `--acc-si` | `#4D9BFF` | **PETRI-BLUE** — scoped. Only the 04-self-improving docs section + petri-bundle bridge (the vendored hub viewer keeps Bootstrap blue). Never a general accent. |
| `--acc-si-soft` | `#7FB5FF` | Self-improving hover. |
| `--code-bg` | `#06050A` | Code block background. |
| `--code-text` | `#E5DFEC` | Code block text. |
| `--code-string` | `#FFD66B` | Code strings (lamp gold). |

**Identity rationale.** The palette is extracted from the GEODE character, so
the mascot, the site, and the brand read as one thing. Rose is deliberately
contrarian for a developer tool (Hermes owns gold, Anthropic terracotta,
petri-bundle Bootstrap blue) — it is distinctive and it is literally the
product's face. The Hermes lesson applied here is not its color but its
**tint discipline**: the signature accent appears at 6–15% opacity in every
hairline, table header, callout background, and active state, which is what
makes a dark surface read as designed rather than default.

**Color semantics — fixed, never improvised**:
rose = identity (who), gold = action (do), aqua = information (read).
A screen should never have all three competing; rose tints carry the surface,
gold and aqua appear only where their meaning applies.

**Single substrate.** Every page is dark by design. No light mode, no
dark-panel-on-light-page. Character PNGs were authored on transparent
backgrounds and sit naturally on this substrate.

**Petri-blue is scoped, not dead.** `--acc-si` keeps the hub's Bootstrap-blue
identity on exactly two surfaces: the 04-self-improving docs section
(`data-doc-section` + `--section-accent` mechanism in docs-shell.tsx /
docs.css) and the petri-bundle bridge pages. The vendored Inspect viewer
cannot be re-skinned, so the section accent preserves continuity into it.

**Generated art assets (PIL, reproducible).** `public/images/geode-lab-scene.png`
— the representative character image (operator brief 2026-07-10: dot art x
Lanthimos; Poor Things porthole sky + gold sun, The Favourite checkerboard
marble in one-point perspective, Sacred Deer symmetric columns, the canonical
GEODI_PIXELS sprite centered as the specimen; 240x300 pixel canvas, NEAREST
x5, 6-color palette from §2 + gold) and `geode-gallery-blur.jpg`
(gaussian-blur gallery band behind the floating terminal), plus
`geode-etch-line.png` (white-line engraving variant, currently unmounted).
Regeneration recipes live in the introducing PRs; keep inks inside §2.
Motion (operator-approved): /portfolio uses framer-motion choreography —
hero stagger, scene idle float, terminal rise, petri-dish spring, cadence-bar
growth — all gated by `useReducedMotion`. The docs surface keeps the old
motion budget.

**Rose-and-white loop-punk composition (operator-directed 2026-07-10 final,
supersedes the two-surface band rule).** /portfolio is one rose field
(`--acc-artifact`) written in warm white `#FFF0F8` — two colors only; the
terminal mock keeps its dark product-screenshot colors by standing exception.
White appears three ways: as ink (serif statements, mono stamps, hairline
grids at 55-75% alpha), as paper plates carrying rose line-art schematics,
and as the stage of the finale. The distillation and the laboratory are one
continuous sticky act: white token rain converges through dissolving-gradient
hairline thresholds, fills the full-bleed pixel wordmark, and further scroll
fades in the reveal — a white stage enters and the rose field becomes a
specimen slide. LazyWeb formula (sharp corners, technical line-art, terminal
hero) carried in the two-color register; hierarchy from white alpha, never a
third hue. The one sanctioned exception is the terminal mock, which keeps its dark
product-screenshot colors (`--paper-deep` + ink tokens) because it is a
product artifact, not page chrome. Scroll is choreography, not paging:
curtain-stack sections over a pinned hero, `StageLight` scroll-linked
dimming, the distillation act (token rain converging band-by-band through
hairline filters labeled with Astryx `Token` chips, piling onto the GEODE
word as a top-down fill), and the wordmark-to-laboratory crossfade finale.
The docs surface keeps the single dark substrate rule.

**Texture.** `.rose-grid` (globals.css) is a 1px rose dot grid at 5% opacity,
28px pitch — for the landing/hero surfaces only. It is a pattern, not a color
gradient; the no-gradient rule below stays intact.

## 3. Typography Rules

| Variable | Family | Weights | Usage |
|---|---|---|---|
| `--font-inter` | Inter | 400, 500, 600, 700 | UI chrome, body sans |
| `--font-display` | Outfit | 600, 700, 800 | Page titles (h1), section labels |
| `--font-fira-code` | Fira Code | 400, 500 | Code blocks, file paths, version chips |
| `--font-serif-display` | Noto Serif KR 600/900 (next/font/google, unicode-range 슬라이스) | 600, 900 | Editorial display (operator-approved 2026-07-10, Hermes-landing register): hero statements, section titles, chapter-band declarations. Pairs with pixel wordmark + mono labels. `word-break: keep-all`. |
| `--font-pixel` | Galmuri11 (OFL, vendored woff2 in `src/fonts/`) | 400, 700 | Character-facing display (operator-approved 2026-07-10): /portfolio h1/h2/era titles/stat numbers, docs-shell wordmark. Matches the GEODI_PIXELS dot mascot. Loads only on pages importing `src/fonts/galmuri.ts`; never for body prose. Always `letter-spacing: 0` (pixel glyphs break under negative tracking). |

**Body is sans (Inter), not serif.** Editorial restraint comes from spacing, line-height, and color discipline — not from a serif body. A dark substrate and serif body together would feel funereal; Inter on near-black reads as a professional dossier.

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
- Nav links as small bordered chips, hairline border, hover swaps to rose.

### Tables

- `border-collapse: collapse; font-size: 13–14px`.
- `border: 1px solid var(--rule)` on every cell.
- Header row: `bg-[var(--paper-2)]; font-weight: 600; color: var(--ink-2)`.

### Code

- Inline: `bg-[var(--paper-2)]; padding: 0.1rem 0.4rem; border-radius: 3px; color: var(--code-string)`.
- Block: `bg-[var(--code-bg)]; border: 1px solid var(--rule); border-radius: 6px; padding: 1rem 1.25rem; color: var(--code-text)`. Horizontal scroll allowed; never wraps.

### Mascot

- Geodi PNG sits naturally on `--paper` (cool near-black) — no inset wrapper needed; the PNG was authored for dark mediums and matches the substrate. Placement budget: landing hero, quickstart finish, 404/empty states. Never inside docs prose.
- 36×40px in hero, 32px in footer. Always static, never animated.
- **Portfolio-hero exception (operator-approved 2026-07-10)**: the /portfolio character card renders the canonical pixel sprite via `GeodiSprite` (`src/components/geode/geodi-sprite.tsx`, grid transcribed from `core/ui/geodi_art.py::GEODI_PIXELS`) at large scale, with a 2-frame eye blink on a 7s `step-end` cycle (`prefers-reduced-motion` disables it). Animated mascot budget (blink + 2-frame idle bob + prompt caret) is scoped to /portfolio; the pose PNGs (`geode-idle/discover/focus`) may mark growth-era rows and section dividers there at 44-52px with `image-rendering: pixelated`. The docs-shell header wordmark carries a STATIC `GeodiSprite` at scale 2 (operator-approved 2026-07-10) — the one docs-chrome mascot placement; still never inside docs prose.

### Blockquotes

- `border-left: 3px solid var(--acc-artifact); padding-left: 1rem; color: var(--ink-2); font-style: italic`.

## 5. Layout Principles

- **Single column** for prose-led pages (landing, scaffold, docs body): 720px content max-width, centered. The geode landing composes this.
- **Three-column** for docs index: sidebar 256px · content 720px · gutter 32px. Outer max 80rem.
- **Vertical rhythm**: 96–128px between major sections. 48px between subsections. 1.4rem between paragraphs.
- **Sticky surfaces**: header, sidebar (own scroll). No sticky footers.
- **Whitespace policy**: prefer empty space to filler. Below H1 sits a single muted summary line, no decorative dividers above.

## 6. Depth & Elevation

- **Borders, not shadows.** Hairline `--rule` (rose tint at 12% opacity) demarcates cards and sticky surfaces. The single substrate already does the contrast work.
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
- Don't introduce new accent colors. Rose for identity, gold for action, aqua for information, scoped petri-blue for the self-improving bridge, and that is it.
- Don't use `dark-panel` or `mascot-inset` utilities — they were transitional and are removed in the dark-mode reset.
- Don't add larger corner radii than `rounded-lg` (8px).
- Don't append decorative arrows (`→`, `▸`) to links, CTAs, or stat values (operator 2026-07-10, slop signal). Link text alone carries the affordance; version/date ranges use `~`.

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
4. **Mascot images sit naturally on the substrate** — do not wrap in inset containers. Geodi was authored for dark mediums.
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

**Astryx (scoped, operator-approved 2026-07-10).** `/portfolio` mounts
`@astryxdesign/core` (Meta's open-source design system, React + precompiled
StyleX CSS) as its component foundation: SegmentedControl, MetadataList,
ProgressBar, Token. Astryx tokens are attribute-scoped
(`[data-astryx-theme]`), and `src/app/portfolio/astryx-geode.css` remaps the
semantic color/font tokens onto the §2 palette, so components render in
GEODE identity, not Meta neutral. Rules: (1) Astryx components stay inside
`data-astryx-theme` wrappers on /portfolio; do not spread them to docs
pages without a new approval. (2) Never import `@astryxdesign/core/reset.css`
(unscoped global reset). (3) `theme-neutral` globally sets
`color-scheme: light dark`; the bridge CSS pins `:root { color-scheme: dark }`
back. If the bridge file is removed, remove the theme import with it.

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
| Substrate | `#212529` (Bootstrap `--bs-dark`) | `--paper` (`#0B0A10`) |
| Elevated | `#2b3035` | `--paper-2` (`#23211F`) |
| Rule | `#3a3f44` | `--rule` (`#3A342D`) |
| Body ink | `#dee2e6` | `--ink` (`#EDE7DA`) |
| Muted | `#adb5bd` | `--ink-2` (`#B5AC97`) |
| Accent | `#0d6efd` (Bootstrap blue) | `--acc-si` (`#4D9BFF`), the scoped self-improving accent (the bundle blue lightened for AA on dark) |

This bridge palette (substrate / elevated / rule / ink) appears **only** in `docs/petri-bundle/landing.html` and any future static HTML co-located under `docs/petri-bundle/`. Next.js docs pages continue to use the §2 substrate/ink tokens, with no exception.

**Accent continuity is scoped.** The self-improving hub's signature is the petri Bootstrap-blue `#0d6efd`, the identity color of the whole self-improving surface (hub + petri bundle). On the docs site that color lives in `--acc-si` and applies only through the `data-doc-section="04-self-improving"` + `--section-accent` mechanism in `docs-shell.tsx` / `docs.css`, so the bridge into the vendored viewer keeps its hue while the rest of the site carries Axolotl Rose.

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

**Maintained at**: `~/workspace/portfolio/DESIGN.md`. Tokens authoritative source: `src/app/globals.css`. When tokens change in code, update this file in the same commit. Drift between code and DESIGN.md is a regression.
