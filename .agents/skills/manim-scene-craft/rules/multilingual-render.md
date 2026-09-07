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

Render only the requested languages. For an EN/KO pair, use an isolated output
directory so concurrent work and before/after evidence are not overwritten:

```bash
(
    set -e
    render_dir=$(mktemp -d "${TMPDIR:-/tmp}/geode-render.XXXXXX")
    printf 'Render output: %s\n' "$render_dir"
    uv run manim -qh --media_dir "$render_dir" --disable_caching \
        -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>
    GEODE_HERO_LANG=ko uv run manim -qh --media_dir "$render_dir" --disable_caching \
        -o <Name>-KO scripts/visualizations/<file>.py <SceneClass>
)
```

These are documented [Manim CLI options](https://docs.manim.community/en/stable/guides/configuration.html).
Confirm support in the installed version's help if the environment differs.
`--disable_caching` avoids cache reuse but still writes cache files inside the
isolated output directory; it is not a cleanup command.

`-qh` is **1080p60 high quality**. Other useful flags:

| Flag | Output | Use case |
|------|--------|----------|
| `-ql` | 480p15 | Draft / fast iteration |
| `-qm` | 720p30 | Mid quality |
| `-qh` | 1080p60 | Default for finished scenes |
| `-qk` | 4K60 | Only for hero / release |

Default layout under the printed output directory:
`videos/<file>/1080p60/<Name>-{EN,KO}.mp4`. Inspect the actual render output and
record its path; a project config can customize directories.

## Sync to Downloads

Copy verified artifacts to `~/Downloads/` only when requested. Resolve exact
source and destination files first and do not overwrite an unrelated existing
artifact. Keep paired filenames in `<SceneName>-{EN,KO}.mp4` shape and report
which render revision each contains.

## Parallel KO render gotcha

When iterating on EN first (typical), remember KO is one render behind
unless explicitly re-rendered. A layout or text change affecting both languages
requires both outputs to be verified from that revision. Use the isolated,
cache-disabled procedure above; never delete the shared `media/videos/<file>/`
tree. Unchanged source, fonts, renderer configuration, and environment may reuse
the recorded passing evidence.

## KO-specific layout drift

Korean text width differs from English (typically narrower per character but
wider overall for the same semantic content). Boxes sized to EN may overflow
under KO — verify both languages in the audit workflow.

`verify_hero_layout.py` measures both EN and KO at every `Site` (the
`SITES` tuple is language-agnostic; the verifier walks `("en", "ko")`).
