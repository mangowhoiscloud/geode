# Safe zones — padding, geometry, arrows

Defects in this category are catalogued in
[[viz-frame-audit]]'s `references/defect-catalogue.md` under "padding
intrusion" and "naive arrow". The table below is the *prevention* rule set;
the catalogue is the post-mortem evidence.

## Box + header + outline lines — single VGroup arrange

The recurring filewalk Bit 1 defect was placing the header and the outline
lines with separate `move_to` calls, which let the header bottom collide
with the first outline line top.

```python
def _file_card(filename: str, loc: int, outline: tuple[str, ...], fill: str,
               *, width: float, height: float,
               line_size: int, header_size: int, loc_size: int,
               top_padding: float = 0.18,
               header_lines_buff: float = 0.22,
               outline_buff: float = 0.13) -> VGroup:
    body = Rectangle(width=width, height=height,
                     stroke_color=COLOR_ARROW, stroke_width=1.5,
                     fill_color=fill, fill_opacity=0.25)
    header = _make_text(filename, font_size=header_size, color=COLOR_TEXT)
    loc_pill = _make_text(f"{loc} LoC", font_size=loc_size, color=COLOR_TEXT_ACCENT)
    header_block = VGroup(header, loc_pill).arrange(DOWN, buff=0.06)
    lines = VGroup(*[_make_text(line, font_size=line_size, color=COLOR_TEXT)
                     for line in outline]).arrange(DOWN, buff=outline_buff,
                                                   aligned_edge=LEFT)
    # Single VGroup arrange — header and lines NEVER move_to'd separately.
    content = VGroup(header_block, lines).arrange(DOWN, buff=header_lines_buff)
    content.next_to(body.get_top(), DOWN, buff=top_padding)
    return VGroup(body, content)
```

## Box height arithmetic

Before deciding `height=...`, calculate:

```
n_outline_lines × line_height (~0.18 at font 10, ~0.20 at font 14)
+ (n_outline_lines − 1) × outline_buff (~0.10 - 0.18)
+ header_block_height (~0.4 at typical font sizes)
+ header_lines_buff (0.18 - 0.22)
+ 2 × top_padding (~0.16)
```

For 7 outline lines at font 10 + header at font 14: total ≈ 2.4 units, so the
box needs `height ≥ 2.5`. The Bit 1 grid regression was caused by `height=2.0`.

## Canvas limits

Default Manim frame at 16:9 is **14.22 × 8.0** units, x ∈ [−7.11, 7.11],
y ∈ [−4.0, 4.0]. Stroke width eats ~0.05 on each edge, so treat
**x ∈ [−7.0, 7.0]** and **y ∈ [−3.9, 3.9]** as the safe interior.

Row labels with `font_size=15` typically measure ~3.0 wide; centred at
`LEFT * 6.0` they reach `x = −7.5` and crop. Either drop to `font_size=13`
(width ~2.4) or move inward to `LEFT * 5.6` or less.

## Arrow labels — perpendicular offset

For an arrow from `start` to `end`, never place the label at
`arrow.get_center() + UP * 0.25` if the arrow is near-vertical. The dashed
line slices through the label glyphs.

The right rule: offset perpendicular to the arrow direction by ≥ 0.5 units.
For an arrow going up-right (slope ~2), use `LEFT * 0.72 + UP * 0.05`
(label to the left of the dashed line). For a horizontal arrow biased
toward one end, use `RIGHT * 0.55 + UP * 0.22` (above + away from the
starting box).

When in doubt, derive the perpendicular from the arrow direction:

```python
import numpy as np

def _perpendicular_offset(start, end, distance: float = 0.5):
    direction = np.asarray(end) - np.asarray(start)
    perp = np.array([-direction[1], direction[0], 0.0])
    norm = float(np.linalg.norm(perp))
    if norm < 1e-6:
        return UP * distance
    return (perp / norm) * distance
```

## `_dashed_arrow_with_head` — arrow primitive

```python
def _dashed_arrow_with_head(
    start, end, *,
    color: str = COLOR_ARROW,
    head_color: str | None = None,
    head_size: float = 0.32,        # 0.24 is illegible at 1080p
    curve_angle: float = 0.0,
    stroke_width: float = 2.5,
    dash_length: float = 0.14,
) -> VGroup:
    """Dashed body + filled triangle head.

    Stage-coupled tinting:
      Co-Scientist → Petri  : head_color=COLOR_SWAP (yellow)
      Petri → autoresearch  : head_color=COLOR_BORROW (blue)
      Cycle / promote       : head_color=COLOR_ADD (green)

    When ``curve_angle`` is non-zero the body is an ``ArcBetweenPoints``
    wrapped in ``DashedVMobject`` — used by the Bit 12 cycle arrow so it
    sweeps around the dimmed Petri zone instead of crossing it.
    """
```

The reference implementation lives in `scripts/visualizations/geode_hero.py`
around line 376. When extracting to a new scene, copy verbatim — the
direction/perpendicular math for the triangle head is correct and load-bearing.

## Canvas edge cropping at extremes

Right-aligned text near `x = 7.0` crops the trailing characters. The fitness
formula `(lower = better)` in Bit 9 required pulling the formula to the left
or shrinking it because right-aligning at `RIGHT * 6.5 + UP * 1.5` cropped
the closing paren on 1080p output.

Pre-PR sanity check: render at `-ql` (480p15 draft), open in QuickTime, scrub
to Bit 9 / 11 / 12 (densest bits), confirm no clipping at the right edge.

## Z-order / layering

Manim renders in `play(...)` call order. Bits where multiple zones are visible
simultaneously (Bit 9-12 in `geode_hero.py`) must `_dim(...)` earlier zones
before adding new ones, otherwise mobjects from later bits paint on top of
earlier-bit text:

```python
def _dim(self, group: VGroup, *, opacity: float = 0.3) -> None:
    self.play(group.animate.set_opacity(opacity), run_time=0.3)
```
