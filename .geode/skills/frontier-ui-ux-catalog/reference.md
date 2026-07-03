# Claude Code & Codex CLI — Dynamic Terminal UI/UX Catalog

> Source-grounded survey of the live, animated terminal UI in the **latest installed builds**:
> **Claude Code 2.1.170** (Bun-compiled native binary, `claude.exe`) and **Codex CLI 0.142.4**.
> Strings extracted directly from the Claude Code binary; Codex facts from OpenAI's `developers.openai.com/codex/cli/features` + GitHub issues. Captured 2026-06-30.

The motivating example — one composite "live status line" that updates several times a second:

```
✢ Hyperspacing… (7m 29s · ↓ 27.7k tokens · thought for 7s)
```

Every token in that line is a separate animated element. The rest of this doc decomposes it, then catalogs every other dynamic surface, then explains the rendering machinery ("how is this made").

---

## 0. Anatomy of the live status line

| Segment | What it is | Update cadence | Source |
|---------|-----------|----------------|--------|
| `✢` | **Spinner glyph** — cycles an asterisk family (`✻ ✶ ✳ ✢ ·`) plus brightness dimming | frame timer, ~10–12 fps | frame index `% frames.length` |
| `Hyperspacing…` | **Random gerund** status word, held a few frames then re-rolled | every few seconds | picked from a ~250-word table (Appendix A) |
| `(7m 29s)` | **Live elapsed timer** since the turn started | every 1 s | `now - turnStart`, formatted `Xm Ys` |
| `↓ 27.7k tokens` | **Streamed token counter** (received), humanized `k`/`M` | on each stream chunk | running accumulator from SSE usage deltas |
| `thought for 7s` | **Thinking duration** — shown while/after extended thinking | on thinking-block close | timestamp delta of the thinking block |
| `esc to interrupt` | **Interrupt hint** (alternates into the parenthetical) | static within a turn | confirmed string `"type": "interrupt"` |

The whole line is repainted in place using a carriage return (`\r`) + clear-to-EOL, never appended — that's why it animates without scrolling.

---

## 1. Claude Code 2.1.170 — dynamic surfaces

Built with **Ink** (React renderer for terminals, Yoga/flexbox layout) on top of the Bun-compiled binary. Renders in the **normal scrollback buffer** (not alt-screen) so completed output stays in history.

### 1.1 Status / spinner line
The composite above. Color shifts by phase (idle vs working vs error). The gerund table is whimsical by design — a brand-signature UX. Confirmed words in the binary include `Hyperspacing, Schlepping, Percolating, Noodling, Channelling, Cogitating, Marinating, Vibing, Simmering` (full curated list → Appendix A).

### 1.2 Streaming markdown render
Assistant text appears token-by-token and is **formatted live** as markdown — bold, inline code, lists, headings, fenced code with syntax highlighting — re-laid-out on every chunk as the buffer grows.

### 1.3 Interleaved thinking blocks
Extended thinking renders as a dim, collapsible `✻ Thinking…` region; on completion it collapses to `thought for Ns`. Binary confirms `thinking` / `thinking_delta` streaming and `[Thinking...]` rendering.

### 1.4 Tool-use cards
Each tool call renders as a bullet block:
```
⏺ Read(file_path: "…")
  ⎿  Read 120 lines
```
`⏺` = call header, `⎿` = indented result/continuation. Long output is truncated with an expand affordance.

### 1.5 Diff rendering
`Edit`/`Write` show a colored unified diff (`+`/`-`) with syntax highlighting, framed inside the tool card.

### 1.6 Live to-do widget
The todo list re-renders in place as state changes — checkbox state (`[ ]` → `[~]` in-progress → `[x]` done), with completed items styled differently. Updates mid-turn without redrawing history.

### 1.7 Permission / approval prompts
Interactive select menus (`1. Yes  2. Yes, and don't ask again  3. No`), arrow-key navigable, that pause the turn.

### 1.8 Autocomplete dropdowns
- `/` → **slash-command** fuzzy menu (live-filtered as you type)
- `@` → **file-mention** picker (fuzzy path search)
- These overlay the composer and update on each keystroke.

### 1.9 Context / usage visualizations
- `/context` → a visual grid of the context window broken down by category (system, tools, messages, free).
- **Auto-compact**: a warning bar near the limit, then an animated "compacting…" pass. Binary confirms `compact-2026-01-12` / `compaction summary` machinery.

### 1.10 Mode + shortcut chrome
- Bottom hint `Press h + Enter to show shortcuts` (exact string in binary).
- Mode cycling via `shift+tab` (normal → auto-accept-edits → plan), with the active mode shown in the bottom bar.
- `esc` interrupts; `esc esc` rewinds to a prior message.

### 1.11 Queued input
Typing while a turn runs **queues** the message; queued items render below the composer and flush on the next turn.

### 1.12 Startup banner
Boxed welcome with version, cwd, and tips on launch.

---

## 2. Codex CLI 0.142.4 — dynamic surfaces

Built with **ratatui** (immediate-mode Rust TUI) over a **crossterm** backend, typically in the **alt-screen** with a full render loop and widget tree (paragraphs, gauges).

### 2.1 Configurable status line
Configured via `[tui] status_line` (ordered item list) in `~/.codex/config.toml`. Available items:

| Item | Shows |
|------|-------|
| `model-with-reasoning` | active model + reasoning effort |
| `current-dir` | working directory |
| `context-usage` | % of context window used (often a gauge/bar) |
| `used-tokens` | tokens consumed this session |
| `five-hour-limit` | rolling 5-hour rate-limit bar |
| `weekly-limit` | weekly rate-limit bar |

(Feature refs: openai/codex #21324 persistent footer w/ progress bars, #17827 customizable status line.)

### 2.2 Working / reasoning indicator
A spinner while the model works; Codex "explains its plan before making a change," and renders a **reasoning summary** stream.

### 2.3 Syntax-highlighted markdown + diffs
Markdown code blocks and review diffs are syntax-highlighted in the TUI.

### 2.4 Theme picker — live preview
`/theme` opens a picker that **previews themes live** before saving; supports custom `.tmTheme` files.

### 2.5 Approval workflow
Inline approve/reject of each step before it executes; diffs shown with highlighting during review.

### 2.6 Input / history affordances
- **Tab** queues follow-up text / slash / shell commands while a turn runs.
- **Ctrl+R** searches prompt history from the composer.
- **@** opens workspace-root fuzzy file search.
- **Ctrl+G** launches `$VISUAL`/`$EDITOR`.
- **Up/Down** restores prior draft text + image placeholders.
- **Ctrl+O** copies latest completed output.

### 2.7 Session controls
`/status` (session info), `/clear` (wipe chat), **Ctrl+L** (clear screen, keep conversation), **Ctrl+C** / `/exit`.

---

### 1.13 Tool-activity density — collapse, don't stretch
Claude Code groups each tool call into a **collapsed card** and hides the bulk behind progressive disclosure:
```
• Ran git worktree list --porcelain
  └ worktree ~/workspace/geode
    HEAD 1351742ec5c447d8e71507d26bfd67bd764195d1
    … +8 lines (ctrl + t to view transcript)
```
The `… +N lines (ctrl + t to view transcript)` affordance keeps the timeline scannable no matter how chatty the tool is — the column height stays bounded.

This is the **opposite** of Codex's planner activity stream, which prints **one line per micro-step** and grows a tall single column:
```
✓ glob_files → ok (0.0s)
✓ glob_files → ok (0.0s)
✓ read_document → ok (0.0s)
✓ grep_files → ok (0.2s)
…  (×20+)
```
Both are "live", but the UX cost differs: collapse-with-disclosure (Claude Code) bounds vertical space and reads as one action; the per-call stretch (Codex) is honest-but-noisy and pushes context off-screen. **Design rule: collapse tool chatter into a summarized card with an expand affordance; never render one row per internal call.**

## 3. Claude Code vs Codex — side-by-side

| Dimension | Claude Code 2.1.170 | Codex CLI 0.142.4 |
|-----------|---------------------|-------------------|
| UI framework | Ink (React/JS, Yoga flexbox) | ratatui (Rust, immediate-mode) + crossterm |
| Screen model | normal scrollback (history persists) | alt-screen render loop |
| Spinner identity | whimsical rotating gerund + asterisk glyph | plain working/reasoning spinner |
| Status line | fixed composite (timer · tokens · thought · interrupt) | **user-configurable** item list (`config.toml`) |
| Token/context | `/context` grid + auto-compact bar | inline gauge items (context %, used tokens, limits) |
| Theming | fixed | `/theme` live picker + custom `.tmTheme` |
| Queue while running | type → queued | **Tab** → queued |
| Diff/markdown | live syntax-highlighted | syntax-highlighted |
| Approvals | select-menu prompts | inline approve/reject |

---

## 4. How it's built (the implementation pattern)

The animation is not magic — it's a small set of terminal primitives both tools share:

1. **A frame timer.** A `setInterval`/render-loop (~10–15 fps) increments a frame counter. `glyph = frames[frame % frames.length]` gives the spinning character. Same counter drives any pulsing/dimming.
2. **In-place repaint.** The live line is rewritten with `\r` (carriage return) + ANSI *erase-to-end-of-line* (`\x1b[K`), so it overwrites itself instead of scrolling. Multi-line widgets save/restore the cursor and clear N lines.
3. **State → re-render.** Claude Code: Ink diffs a React tree and patches only changed cells (like a virtual DOM for the terminal). Codex: ratatui redraws the whole widget tree each loop iteration but diffs against the previous buffer before emitting bytes.
4. **ANSI SGR for color/style.** `\x1b[2m` dim, `\x1b[36m` cyan, `\x1b[39;2m` reset-fg-keep-dim, etc. (these exact codes appear in the Claude Code binary's shortcut hint).
5. **Streaming accumulators.** SSE/stream chunks update counters (tokens) and append text; each update triggers a repaint. Elapsed time is derived from a start timestamp, not stored per frame.
6. **Unicode glyph sets.** Asterisk family (`✻ ✶ ✳ ✢`) or Braille spinners (`⠋ ⠙ ⠹ ⠸ ⠼ ⠴`); box-drawing for cards (`⏺ ⎿`); bars/gauges (`█ ▓ ░`) for progress.
7. **Terminal-width awareness.** Width is queried (and watched for resize) to truncate/wrap so the line never wraps mid-animation.

**Minimal reproduction** (the core loop, ~15 lines of any language):

```js
const frames = ["✻","✶","✳","✢","·"];
const words  = ["Hyperspacing","Schlepping","Percolating","Noodling"];
const start  = Date.now();
let f = 0, tokens = 0;
setInterval(() => {
  f++;
  if (f % 20 === 0) word = words[(Math.random()*words.length)|0]; // re-roll word
  const s = Math.floor((Date.now()-start)/1000);
  const t = `${Math.floor(s/60)}m ${s%60}s`;
  process.stdout.write(
    `\r\x1b[K\x1b[35m${frames[f%frames.length]}\x1b[0m ${word}… ` +
    `\x1b[2m(${t} · ↓ ${(tokens/1000).toFixed(1)}k tokens · esc to interrupt)\x1b[0m`
  );
}, 80);
```

For real apps don't hand-roll: use **Ink** + a spinner component (JS/TS), or **ratatui** + `throbber-widgets` (Rust). Both give you the frame loop, layout, and diffed repaint for free — the ladder is: native terminal escape → existing spinner lib → custom only if neither fits.

---

## Appendix A — Claude Code spinner gerund table (curated)

~250+ single-word gerunds live in the binary and are selected at random per status update. The whimsical signature set (extracted, noise-filtered):

```
Accomplishing Actualizing Architecting Befuddling Bloviating Boondoggling Booping
Bootstrapping Brewing Calculating Canoodling Caramelizing Cascading Catapulting
Cerebrating Channelling Choreographing Clauding Cogitating Combobulating Computing
Concocting Conjuring Contemplating Cooking Crafting Crystallizing Cultivating
Deciphering Deliberating Discombobulating Dithering Doodling Elucidating Enchanting
Envisioning Fermenting Finagling Flibbertigibbeting Frolicking Gallivanting Garnishing
Germinating Gesticulating Honking Hullaballooing Hyperspacing Ideating Imagining
Improvising Incubating Infusing Interleaving Ionizing Jitterbugging Marinating
Noodling Orchestrating Osmosing Perambulating Percolating Philosophising
Photosynthesizing Pollinating Pondering Pontificating Prestidigitating Puttering
Puzzling Quantumizing Razzmatazzing Recombobulating Reticulating Ruminating
Scampering Schlepping Shenaniganing Shimmying Simmering Skedaddling Smooshing
Spelunking Sublimating Symbioting Synthesizing Tempering Tomfoolering Transfiguring
Transmuting Undulating Unfurling Vibing Waddling Whatchamacalliting Whirlpooling
Wibbling Wrangling Zigzagging
```

> The list mixes whimsical (`Flibbertigibbeting`, `Hullaballooing`, `Razzmatazzing`, `Clauding`) with mundane (`Computing`, `Crafting`, `Synthesizing`); random selection per repaint is what makes the spinner feel alive.

## Appendix B — Sources

- Claude Code 2.1.170 binary string extraction (`/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`)
- [Codex CLI — Features](https://developers.openai.com/codex/cli/features)
- [openai/codex #21324 — TUI usage status line items](https://github.com/openai/codex/issues/21324)
- [openai/codex #17827 — Customizable status line](https://github.com/openai/codex/issues/17827)
- Ink (vadimdemedes/ink) · ratatui (ratatui-org/ratatui) — rendering frameworks
