# Multilingual render — EN/KO

## Lang switch

The `GEODE_HERO_LANG` env var picks the translation row. Default is `en`.

```python
LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

T = {"en": {...}, "ko": {...}}

def _t(key: str) -> str:
    return T.get(LANG, T["en"]).get(key, T["en"].get(key, key))
```

The translation table is module-level so the same scene renders both
languages by setting the env var differently between `manim` invocations.

## Font pairing

| Lang | Font | Source | Why |
|------|------|--------|-----|
| EN | Helvetica Neue | macOS-bundled `HelveticaNeue.ttc` | Closest match to Anthropic's Styrene/Inter visual identity that Manim's Pango backend renders without spacing / kerning artifacts |
| KO | Pretendard | OFL, `brew install --cask font-pretendard` | Modern Korean sans pairing cleanly with Helvetica Neue. Apple SD Gothic Neo has the "초반 멈춤" glyph artifact |

Inter is **forbidden** as the EN font. Pango misreads its ligature table on
macOS and inserts spurious whitespace between consonants — verified
regression cases: "GE ODE", "cr itic", "Petr i aud it", "g eneration",
"fit ness".

If Pango still inserts gaps with Helvetica Neue at a small font size, raise
the font: at `font_size ≥ 20` the per-pair kerning quirks become
imperceptible (the outro x-axis label drift was fixed this way).

## Render commands

```bash
# EN
uv run manim -qh -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>

# KO
GEODE_HERO_LANG=ko uv run manim -qh -o <Name>-KO scripts/visualizations/<file>.py <SceneClass>
```

`-qh` is **1080p60 high quality**. Other useful flags:

| Flag | Output | Use case |
|------|--------|----------|
| `-ql` | 480p15 | Draft / fast iteration |
| `-qm` | 720p30 | Mid quality |
| `-qh` | 1080p60 | Default for finished scenes |
| `-qk` | 4K60 | Only for hero / release |

Output path: `media/videos/<file>/1080p60/<Name>-{EN,KO}.mp4`.

## Sync to Downloads

```bash
cp media/videos/<file>/1080p60/<Name>-{EN,KO}.mp4 ~/Downloads/
```

The user opens `~/Downloads/` in Finder to review. Keep filenames in
`<SceneName>-{EN,KO}.mp4` shape — the audit workflow (extract frames + diff)
relies on consistent naming.

## Parallel KO render gotcha

When iterating on EN first (typical), remember KO is one render behind
unless explicitly re-rendered. After every code change that affects layout
or text:

```bash
rm -rf media/videos/<file>/
uv run manim -qh -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>
GEODE_HERO_LANG=ko uv run manim -qh -o <Name>-KO scripts/visualizations/<file>.py <SceneClass>
```

The full re-render is necessary because Manim's per-bit partial movie cache
sometimes keeps stale fragments when constants like `font_size` change.

## KO-specific layout drift

Korean text width differs from English (typically narrower per character but
wider overall for the same semantic content). Boxes sized to EN may overflow
under KO — verify both languages in the audit workflow.

`verify_hero_layout.py` measures both EN and KO at every `Site` (the
`SITES` tuple is language-agnostic; the verifier walks `("en", "ko")`).
