---
name: manim-scene-craft
description: |
  Trigger when: (1) the user mentions "manim", "scene", "video", "EN/KO render",
  "GEODE_HERO_LANG", "1080p60", or (2) editing files under
  `scripts/visualizations/` ending in `.py`, or (3) the user asks to render,
  re-render, or extend any of the four validated scenes (`geode_hero.py`,
  `autoresearch_filewalk.py`, `autoresearch_compare.py`, `critical_floor.py`).

  GEODE Manim Scene authoring standard. Locks the patterns the four validated
  scenes already share — Anthropic-style palette, Helvetica Neue + Pretendard
  font pairing with weight=NORMAL, EN/KO multilingual lang via
  `GEODE_HERO_LANG` env, `_dashed_arrow_with_head` stage-coupled tinting,
  `verify_hero_layout.py` ratchet — so the next scene does not re-discover
  the kerning / padding / transition regressions catalogued in
  [[viz-frame-audit]].
when_to_use: |
  Use BEFORE writing a new Manim scene from scratch, or before editing render
  / font / arrow / layout constants in an existing scene. Skip when only
  changing CHANGELOG, docs, or non-visualisation code.
user-invocable: false
---

# Manim Scene Craft

## Core invariants

The five rules below are non-negotiable. Detailed rationale + code lives in
`rules/`.

1. **Single text entry point.** All `Text(...)` calls go through `_make_text`
   so the EN/KO font + `weight=NORMAL` lock can't slip. Raw `Text(` is a
   regression. See [rules/scene-skeleton.md](rules/scene-skeleton.md).
2. **Padding safe zones.** Box + header + outline lines arrange as a single
   `VGroup(...).arrange(DOWN, buff=...).next_to(body.get_top(), DOWN, buff=...)`
   — never as separate `move_to` calls. See [rules/safe-zones.md](rules/safe-zones.md).
3. **Section transitions in one play.** `_set_section_title` bundles
   FadeOut(prior title) + FadeOut(prior content) + FadeIn(new title) into a
   single `self.play(...)` so transitions don't show a 0.5–0.8 s empty frame.
   See [rules/scene-skeleton.md](rules/scene-skeleton.md).
4. **Arrow labels perpendicular.** Arrow labels offset ≥ 0.5 perpendicular to
   the arrow direction. `UP * 0.25` from center is forbidden — near-vertical
   dashed lines slice through the glyphs. See [rules/safe-zones.md](rules/safe-zones.md).
5. **Layout ratchet on every box.** Every new container + text pair gets a
   `Site(...)` entry in `verify_hero_layout.py`. Run `--update-baseline`
   locally, commit `layout_baseline.json`. See [rules/layout-ratchet.md](rules/layout-ratchet.md).

## File map

| File | Purpose |
|------|---------|
| [rules/scene-skeleton.md](rules/scene-skeleton.md) | Imports, palette, `_t`, `_make_text`, `_set_section_title`, Bit construction order |
| [rules/safe-zones.md](rules/safe-zones.md) | Padding rules, arrow geometry, canvas edge limits, `_dashed_arrow_with_head` |
| [rules/multilingual-render.md](rules/multilingual-render.md) | EN/KO lang switch, render commands, output paths, `~/Downloads/` copy |
| [rules/layout-ratchet.md](rules/layout-ratchet.md) | `verify_hero_layout.py` SITES + baseline JSON + CI step |
| [references/data-sot.md](references/data-sot.md) | Which markdown SoT each scene reads from + parity rules |
| [references/pre-pr-checklist.md](references/pre-pr-checklist.md) | 5-item grep checklist before pushing |
| [references/external-oss.md](references/external-oss.md) | adithya-s-k/manim_skill (mobject API reference) + other OSS, with stars / last-push verified 2026-05-21 |

## Pre-flight

```bash
uv add manim --dev && uv sync
brew install pkg-config cmake                  # macOS, for pycairo
brew install --cask font-pretendard            # KO font

uv run python scripts/visualizations/verify_hero_layout.py --static-check
```

`--static-check` validates the committed `layout_baseline.json` without
importing Manim — fast CI gate.

## Standard render

```bash
uv run manim -qh -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>
GEODE_HERO_LANG=ko uv run manim -qh -o <Name>-KO scripts/visualizations/<file>.py <SceneClass>
cp media/videos/<file>/1080p60/<Name>-{EN,KO}.mp4 ~/Downloads/
```

After render, run the post-mortem audit workflow in [[viz-frame-audit]].

## Workflow differentiator

`adithya-s-k/manim_skill` (874★) is the recommended external reference for
the general ManimCE API. This skill layers GEODE-specific patterns on top
that the external skill does not cover: EN/KO lang switch, Helvetica Neue +
Pretendard pairing with `weight=NORMAL` lock, Anthropic-style 6-color palette,
`verify_hero_layout.py` ratchet, `_dashed_arrow_with_head` stage-coupled head
tinting, and the 12+ defect catalogue from four validated scenes.

The defect catalogue (filewalk × 5, hero × 7) lives in
[[viz-frame-audit]]'s `references/defect-catalogue.md`.
