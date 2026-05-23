# Scene skeleton

Every validated scene shares this skeleton. Copy-paste, then customise the
`T` dictionary + `construct()` bit list.

## Imports + module-level constants

```python
"""<Scene description — title, bit breakdown, data sources>.

Render
======
::

    uv run manim -qh -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>
    GEODE_HERO_LANG=ko uv run manim -qh -o <Name>-KO scripts/visualizations/<file>.py <SceneClass>
"""

from __future__ import annotations

import os

from manim import (
    DOWN, LEFT, NORMAL, ORIGIN, RIGHT, UP,
    AnimationGroup, Circle, Create, DashedLine, FadeIn, FadeOut,
    LaggedStart, Line, Rectangle, Scene, Square, Text, VGroup, config,
)

config.background_color = "#FFFFFF"
config.frame_rate = 60

LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

# Anthropic-style palette — shared across every scene
COLOR_BORROW = "#A4C2F4"      # blue — verbatim / Co-Scientist seed
COLOR_SWAP = "#FFE599"        # yellow — Petri / domain swap
COLOR_ADD = "#93C47D"         # green — autoresearch / GEODE-only addition
COLOR_REMOVE = "#E06666"      # red — critical regression
COLOR_KARPATHY = "#F4CCCC"    # light pink — Karpathy panel fill
COLOR_GEODE = "#D5E8D4"       # very light green — GEODE panel fill
COLOR_ARROW = "#666666"
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"

EN_FONT = "Helvetica Neue"
KOR_FONT = "Pretendard"

TITLE_Y = 3.45
SECTION_TITLE_Y = 2.85
CONTENT_TOP = 2.5
CONTENT_BOTTOM = -2.0
FOOTER_Y = -3.3
```

## Translation dictionary

```python
T = {
    "en": {
        "title": "Scene title",
        "bit_1_title": "Section 1 — ...",
        # ...
    },
    "ko": {
        "title": "씬 제목",
        "bit_1_title": "Section 1 — ...",
        # ...
    },
}

def _t(key: str) -> str:
    return T.get(LANG, T["en"]).get(key, T["en"].get(key, key))
```

## `_make_text` — the only Text constructor

Direct `Text(...)` calls are forbidden. The `_make_text` helper locks the
font (EN_FONT vs KOR_FONT based on `LANG`) and `weight=NORMAL` so Pango's
weight metric drift cannot slip in.

```python
def _make_text(text: str, **kw) -> Text:
    font = kw.pop("font", None)
    if font is None:
        font = KOR_FONT if LANG == "ko" else EN_FONT
    kw.setdefault("color", COLOR_TEXT)
    kw.setdefault("weight", NORMAL)
    return Text(text, font=font, **kw)
```

Pre-PR grep: `grep -n "Text(" scripts/visualizations/<file>.py` must show
only `_make_text(` matches.

## Bit / section construction

```python
class MyScene(Scene):
    def construct(self) -> None:
        self._section_title = None
        self._section_content = VGroup()
        self._show_title()
        self._bit_1_xxx()
        self._bit_2_yyy()
        # ... up to N bits
        self._outro()

    def _show_title(self) -> None:
        title = _make_text(_t("title"), font_size=26, color=COLOR_TEXT).move_to(
            UP * TITLE_Y
        )
        self.title = title
        self.play(FadeIn(title), run_time=0.6)

    def _set_section_title(self, key: str) -> None:
        """Swap title in ONE play call.

        Bundling (FadeOut prior title + FadeOut prior content + FadeIn new
        title) into a single `self.play(...)` eliminates the empty / half-
        empty transition frames previous versions had between bits.
        """
        new_title = _make_text(
            _t(key), font_size=18, color=COLOR_TEXT_ACCENT
        ).move_to(UP * SECTION_TITLE_Y)
        fade_outs = []
        if self._section_title is not None:
            fade_outs.append(FadeOut(self._section_title))
        if len(self._section_content) > 0:
            fade_outs.append(FadeOut(self._section_content))
        if fade_outs:
            self.play(*fade_outs, FadeIn(new_title), run_time=0.4)
        else:
            self.play(FadeIn(new_title), run_time=0.3)
        self._section_title = new_title
        self._section_content = VGroup()
```

## Bit body convention

Each bit body must end with `self._section_content = VGroup(...)` registering
the new content so the next bit's `_set_section_title` can fade it out:

```python
def _bit_1_xxx(self) -> None:
    self._set_section_title("bit_1_title")
    # ... build mobjects ...
    group = VGroup(card_a, card_b, label)
    self.play(FadeIn(group), run_time=0.6)
    self._section_content = group
    self.wait(2.4)
```

## Outro

```python
def _outro(self) -> None:
    fade_outs = []
    if len(self._section_content) > 0:
        fade_outs.append(FadeOut(self._section_content))
    if self._section_title is not None:
        fade_outs.append(FadeOut(self._section_title))
    fade_outs.append(FadeOut(self.title))
    self.play(*fade_outs, run_time=0.4)
    # ... outro mobjects ...
```
