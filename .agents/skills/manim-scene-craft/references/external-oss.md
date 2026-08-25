# External OSS — references

Star counts and last-push timestamps are **verified 2026-05-21 via direct
GitHub API**. The frontier-research agent's initial numbers contained
errors (e.g. confused `awesome-skills/manim-skill` 5★ with
`adithya-s-k/manim_skill` 874★); always re-verify with `gh api repos/<owner>/<name>`
before trusting an external reference.

## Primary external reference

### [adithya-s-k/manim_skill](https://github.com/adithya-s-k/manim_skill)
- **Stars**: 874
- **Last push**: 2026-01-23
- **License**: present (check repo for current)
- **Structure**: 3 sub-skills — `skills/manimce-best-practices/` (matches our
  ManimCE), `skills/manim-composer/` (scene composition), `skills/manimgl-best-practices/`
- **What to use it for**: General ManimCE API study. Consult `rules/animations.md`,
  `rules/transform-animations.md`, `rules/text.md`, `rules/positioning.md`,
  `rules/timing.md`, `rules/cli.md` for mobject / animation / LaTeX / 3D /
  camera / styling patterns this skill does NOT cover.

### [ManimCommunity docs](https://docs.manim.community/en/stable/)
- API spec final SoT. Use when `adithya-s-k/manim_skill` lacks a specific
  class or when checking method signatures changed between versions.

## Supplementary

### [awesome-skills/manim-skill](https://github.com/awesome-skills/manim-skill)
- **Stars**: 5
- **Last push**: 2026-03-01
- Single-SKILL.md format from the Anthropic skills marketplace style.
- Use only as a structure example for SKILL.md frontmatter; the rules
  themselves are subsumed by `adithya-s-k/manim_skill`.

### [Yusuke710/manim-skill](https://github.com/Yusuke710/manim-skill)
- **Stars**: 55
- **Last push**: 2026-01-26
- 4-phase loop: Plan → Code → Render → Iterate (with browser preview).
- The iteration pattern informs [[viz-frame-audit]]'s audit workflow; the
  scene-authoring pieces are subsumed by `adithya-s-k/manim_skill`.

## Tooling

### [harfbuzz/uharfbuzz](https://github.com/harfbuzz/uharfbuzz) 0.54.1
- **Stars**: 99
- **Last push**: 2026-05-19 (active)
- **License**: Apache-2.0
- Step 2 typography drift gate. Used to record `glyph_clusters` baseline in
  `verify_hero_layout.py`'s JSON so the Helvetica Neue + Pango "GE ODE" /
  "g eneration" / "fit ness" drift can be caught at compile time, not at
  post-render audit.

### [fonttools/fonttools](https://github.com/fonttools/fonttools)
- Active.
- Font metadata sanity check (PostScript-name match for the Helvetica Neue
  TTC + Pretendard OTF). Use as a single snippet, not a dependency on the
  full toolkit.

## MCP servers (on hold)

### [abhiemj/manim-mcp-server](https://github.com/abhiemj/manim-mcp-server)
- **Stars**: 593
- **Last push**: 2025-05-19 (≈1 year stale)
- MCP wrapper around Manim render. Would let agents call
  `mcp__manim__execute(...)` instead of `Bash(uv run manim ...)`.
- **Currently on hold** because of the 1-year stale push. Mount only after
  fork or community handover.

### [eequaled/frames-mcp](https://lobehub.com/mcp/eequaled-frames-mcp)
- **License**: GPL-3.0 (needs separate-process isolation if GEODE core is MIT-ish)
- 4 tools — `extract_frame`, `extract_multiple_frames`, `get_video_info`,
  `extract_clip`. Tesseract OCR built in.
- Would replace the `Bash(ffmpeg ...)` step in the audit workflow with a
  direct MCP call. See [[viz-frame-audit]] for audit-side integration plans.

## Voiceover / TTS extension

### [ManimCommunity/manim-voiceover](https://github.com/ManimCommunity/manim-voiceover)
- Active, official ManimCommunity package.
- When the workflow extends to voice-over (Whisper / Kokoro / ElevenLabs /
  Azure TTS), this is the integration point.
- Not used today; the four validated scenes are silent.

## What this skill differentiates from external OSS

`adithya-s-k/manim_skill` (the main external reference) does **not** cover:

- EN/KO multilingual lang via `GEODE_HERO_LANG` env
- Helvetica Neue + Pretendard pairing with explicit `weight=NORMAL` lock
- Anthropic-style 6-color palette (`COLOR_KARPATHY` / `COLOR_GEODE` /
  `COLOR_SWAP` / `COLOR_ADD` / `COLOR_BORROW` / `COLOR_REMOVE`)
- `verify_hero_layout.py` ratchet (text width/height ↔ container ratio gate
  with per-language baseline JSON)
- `_dashed_arrow_with_head` stage-coupled head tinting (Petri yellow /
  autoresearch blue / promote green)
- The 12+ defect catalogue from four validated scenes — documented in
  [[viz-frame-audit]]'s `references/defect-catalogue.md`

These six items are why this skill exists as a layer on top, not as a
replacement for the external reference.
