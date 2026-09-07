# Layout ratchet — `verify_hero_layout.py`

The ratchet checks the registered hero layout sites. Local measurement
compares current geometry and glyph sequences with the baseline; CI checks
the committed baseline only, not whether the current render matches it.

## The script

[`verify_hero_layout.py`](../../../../scripts/visualizations/verify_hero_layout.py)
has three checks:

1. **Font presence gate** — `_ensure_fonts_installed()` runs `fc-list` and
   aborts if either `EN_FONT` (Helvetica Neue) or `KOR_FONT` (Pretendard)
   is missing from its output. If `fc-list` itself is unavailable, this
   check warns and skips. The CI static mode does not run font checks.
2. **Layout ratchet** — measures every `Site` × `("en", "ko")` pair via
   `_make_text(...).width` / `.height`, divides by the container box's
   width/height, and compares against `layout_baseline.json`.
3. **Typography drift** — local measurement compares recorded HarfBuzz
   glyph sequences; see the [typography gate](../../viz-frame-audit/rules/typography-drift-gate.md)
   for the distinction between measurement and static validation.

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
    font_family: str | None = None      # explicit family override, e.g. Menlo
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

The first form fails on overflow (ratio > 1.0), growth past the baseline +
`RATCHET_TOLERANCE` (0.03), glyph drift, or measurement/shaping errors.
The second form writes the measured baseline and returns 0 even when the
measurement loop collected failures. Use it only for an intentional,
reviewed baseline change, inspect the diff, then run the first form and
`--static-check`; an update exit code alone is not verification.

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
- Every site with declared text has a non-empty `glyph_clusters` list.
  This does not recompute glyphs or validate each pair's integer shape;
  the latter is covered by the [baseline tests](../../../../tests/visualizations/test_verify_hero_layout.py).

Runs in <1 s on Linux CI. The full-measurement path is reserved for
local "did I make it worse?" checks.

## Adding a new box

1. Add the `Rectangle / Square` and its inner `Text` to the scene.
2. Append a `Site(...)` entry to `SITES` tuple in `verify_hero_layout.py`.
3. Review the intended layout, update the baseline locally as above, then
   run measurement and static checks without updating it.
4. Include the scene, verifier `SITES` change, and baseline together when
   integration is authorized.

## CI step

```yaml
- name: Hero viz layout ratchet
  if: needs.changes.outputs.code == 'true'
  run: uv run python scripts/visualizations/verify_hero_layout.py --static-check
```

The `if:` gate skips the step on docs-only PRs.

## What the ratchet does NOT catch

The geometry portion measures **text-vs-container extents only**. It cannot catch:

- Arrow head colour mismatches
- Label overlapping a dashed line (the dashed line isn't in `SITES`)
- Transition timing (empty / half-empty frames between bits)
- Glyph kerning drift inside the box (the box width metric is unchanged
  even when Pango inserts spurious gaps)

For those, use the [post-render audit workflow](../../viz-frame-audit/rules/audit-workflow.md).
The implemented [typography drift gate](../../viz-frame-audit/rules/typography-drift-gate.md)
and [pixel frame ratchet](../../viz-frame-audit/rules/pixel-ratchet.md)
provide additional checks within their recorded sites/frames and available
dependencies. They do not prove every rendered glyph or transition is correct.
