# External OSS — references

Star counts and last-push timestamps **verified 2026-05-21 via direct
GitHub API**. Re-verify with `gh api repos/<owner>/<name>` before relying
on an external claim — frontier-research summaries occasionally swap
similarly-named projects.

## Iteration / authoring patterns

### [Yusuke710/manim-skill](https://github.com/Yusuke710/manim-skill)
- **Stars**: 55
- **Last push**: 2026-01-26
- 4-phase loop: Plan → Code → Render → Iterate (with browser preview).
- The iteration shape (auto-loop until user signs off) informs the
  workflow in `rules/audit-workflow.md`. This skill goes one step
  further with **automated multi-frame LLM audit** via Claude Code's
  Read tool, not browser-driven manual feedback.

## Comparator / ratchet primitives

### [whtsky/pixelmatch-py](https://github.com/whtsky/pixelmatch-py) v0.4.0
- **Stars**: 137
- **Last push**: 2026-05-12 (active)
- **License**: ISC
- Python port of Mapbox's `pixelmatch` JS. Anti-aliasing-aware perceptual
  diff. `pixelmatch()` + `contrib.PIL.pixelmatch()` 1-line API.
- Step 3 integration plan: `rules/pixel-ratchet.md`.

### [matplotlib/pytest-mpl](https://github.com/matplotlib/pytest-mpl) v0.19.0
- **Last push**: 2026-03-30 (active)
- **Use as reference only** — matplotlib-specific. Borrow the
  `@pytest.mark.mpl_image_compare` + `--mpl-generate-path` baseline
  regeneration UX shape for our Step 3 pytest integration. The
  comparator itself is `pixelmatch-py`, not pytest-mpl.

### [harfbuzz/uharfbuzz](https://github.com/harfbuzz/uharfbuzz) 0.54.1
- **Stars**: 99
- **Last push**: 2026-05-19 (active)
- **License**: Apache-2.0
- Step 2 typography drift gate — `rules/typography-drift-gate.md`.
  Extends `verify_hero_layout.py` with HarfBuzz glyph cluster comparison
  for category 3 (kerning drift) compile-time catch.

## MCP servers (on hold)

### [eequaled/frames-mcp](https://lobehub.com/mcp/eequaled-frames-mcp)
- **License**: GPL-3.0 (needs separate-process isolation if GEODE core
  is MIT-ish; MCP itself is a separate process so this is fine).
- 4 tools — `extract_frame`, `extract_multiple_frames`, `get_video_info`,
  `extract_clip`. Tesseract.js OCR built in.
- Would replace `Bash(ffmpeg ...)` in `rules/audit-workflow.md` with a
  direct MCP call. OCR side effect could also auto-extract on-screen text
  for category 3 cross-checks.
- **Mount evaluation deferred** — npm-only distribution (no GitHub stars
  to verify), needs cautious validation before adding to the GEODE MCP
  registry.

### [abhiemj/manim-mcp-server](https://github.com/abhiemj/manim-mcp-server)
- **Stars**: 593
- **Last push**: 2025-05-19 (≈1 year stale)
- Documented in [[manim-scene-craft]]'s `references/external-oss.md`.
  This skill doesn't render, only audits, so the manim-mcp-server is
  not directly relevant here.

## What this skill does that external OSS doesn't

- Defines a **fixed four-category defect taxonomy** (naive arrow / padding
  intrusion / glyph kerning drift / frame-order error) with a verified
  12+ incident catalogue tied to real GEODE scenes.
- Embeds the audit into a Claude Code Read-tool flow, not browser-driven
  user review — the model directly inspects frames and classifies.
- Integrates with `verify_hero_layout.py` geometry ratchet as one
  cooperating layer of three (geometry / typography / pixel), each
  catching a different category at the cheapest layer.

These integrations are not provided by `Yusuke710/manim-skill` or any of
the listed comparators in isolation.
