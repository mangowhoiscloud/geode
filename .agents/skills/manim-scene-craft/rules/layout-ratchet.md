# Layout ratchet — `verify_hero_layout.py`

The ratchet is the standing line of defence against the regressions the
filewalk and hero audits caught. Every PR with a layout / text change either
keeps text/container ratios within the recorded baseline or fails CI.

## The script

`scripts/visualizations/verify_hero_layout.py` does two jobs:

1. **Font presence gate** — `_ensure_fonts_installed()` runs `fc-list` and
   aborts if either `EN_FONT` (Helvetica Neue) or `KOR_FONT` (Pretendard)
   is missing. CI installs both before invoking the verifier.
2. **Layout ratchet** — measures every `Site` × `("en", "ko")` pair via
   `_make_text(...).width` / `.height`, divides by the container box's
   width/height, and compares against `layout_baseline.json`.

## SITES tuple

Each entry is a known text-inside-box pair. Adding a new box that didn't
exist in the baseline JSON is also tracked — see the static-check failure
message "MISSING from baseline".

```python
@dataclass(frozen=True)
class Site:
    site_id: str
    text_key: str               # T-dictionary key; empty string for inline literals
    font_size: int
    container_width: float
    container_height: float
    text_string_en: str | None = None   # inline literal override
    text_string_ko: str | None = None
```

Example entry:

```python
SITES: tuple[Site, ...] = (
    Site("agent_generator", "agent_generator", 14, 1.05, 0.5),
    Site("petri_box", "petri_box", 18, 3.0, 1.0),
    Site(
        "dim_means_dict", "", 10, 3.4, 0.45,
        text_string_en="dim_means: {broken_tool_use: 2.5, …}",
        text_string_ko="dim_means: {broken_tool_use: 2.5, …}",
    ),
    # ...
)
```

## Two modes

### Local — full measurement

```bash
uv run python scripts/visualizations/verify_hero_layout.py
uv run python scripts/visualizations/verify_hero_layout.py --update-baseline
```

The first form fails on **(a)** any ratio > 1.0 (overflow) or **(b)** any
ratio growing past the baseline + `RATCHET_TOLERANCE` (0.03). The second
form refreshes the baseline JSON so the new measurements become the
ratchet floor.

When measuring locally requires fonts + Manim, this is slow (Manim imports
take ~3 s, then each `_make_text` is another fraction of a second). Run
locally before pushing, not in CI.

### CI — static check, no Manim

```bash
uv run python scripts/visualizations/verify_hero_layout.py --static-check
```

Validates the committed `layout_baseline.json` against the `SITES` tuple
without importing Manim. Checks:

- Every `Site × lang` exists in the JSON (catches stale baseline after a
  new Site is added but `--update-baseline` was not run).
- Every recorded `ratio_w` and `ratio_h` is ≤ 1.0 (overflow guard).

Runs in <1 s on Linux CI. The full-measurement path is reserved for
local "did I make it worse?" checks.

## Adding a new box

1. Add the `Rectangle / Square` and its inner `Text` to the scene.
2. Append a `Site(...)` entry to `SITES` tuple in `verify_hero_layout.py`.
3. Run `uv run python scripts/visualizations/verify_hero_layout.py --update-baseline`
   locally. The JSON is updated with the measured ratios.
4. Commit both files (`<scene>.py` + `layout_baseline.json`) together.

## CI step

```yaml
- name: Hero viz layout ratchet
  if: needs.changes.outputs.code == 'true'
  run: uv run python scripts/visualizations/verify_hero_layout.py --static-check
```

The `if:` gate skips the step on docs-only PRs.

## What the ratchet does NOT catch

The ratchet measures **text-vs-container geometry only**. It cannot catch:

- Arrow head colour mismatches
- Label overlapping a dashed line (the dashed line isn't in `SITES`)
- Transition timing (empty / half-empty frames between bits)
- Glyph kerning drift inside the box (the box width metric is unchanged
  even when Pango inserts spurious gaps)

For those, the post-render audit workflow in [[viz-frame-audit]] is the
backstop. Future Step 2 ([uharfbuzz typography drift gate](../../viz-frame-audit/rules/typography-drift-gate.md))
and Step 3 ([pixelmatch frame ratchet](../../viz-frame-audit/rules/pixel-ratchet.md))
will add deterministic catches for the typography + transition cases.
