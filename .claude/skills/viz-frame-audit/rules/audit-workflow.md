# Audit workflow

## 1. Pick timestamps

The bit transitions in our scenes use a 0.4 s bundled FadeOut/FadeIn (see
[[manim-scene-craft]]'s `_set_section_title`). Frames captured during that
window show empty or half-empty content and are useless for defect
classification.

Target the middle of each bit's *wait* phase:

```
bit_N: _set_section_title (0.4 s) → main play (0.6 - 1.6 s) → self.wait(2.4 s)
       ─────────────── 3.4 - 4.4 s total ────────────────
```

→ Capture 1.0 - 3.0 s after each bit starts.

For a 12-bit + outro scene running ~51 s, 7-10 timestamps is enough:

```python
# 32 s filewalk: 7 timestamps × 4.5 s spacing
TIMESTAMPS = (2.5, 6.5, 10.5, 14.5, 18.5, 24.0, 28.0)

# 51.75 s hero: 7 timestamps × ~7 s spacing
TIMESTAMPS = (3, 9, 17, 25, 33, 41, 49)
```

## 2. Extract frames

```bash
mkdir -p /tmp/<name>_audit && rm -f /tmp/<name>_audit/*.png

for t in 2.5 6.5 10.5 14.5 18.5 24.0 28.0; do
    ffmpeg -hide_banner -loglevel error -ss $t \
        -i media/videos/<scene>/1080p60/<Name>-EN.mp4 \
        -frames:v 1 -update 1 -q:v 2 /tmp/<name>_audit/EN_${t}s.png -y
done
```

Notes:
- `-ss <t>` BEFORE `-i` is faster (input seek) and accurate enough for
  audit purposes.
- `-update 1 -q:v 2` is required for a single high-quality PNG output.
  Without `-update`, ffmpeg expects an image sequence pattern.
- `2>&1 | tail` if the loop fails — most failures are missing input file
  or wrong scene name.

## 3. Inspect via Read

```text
Read /tmp/<name>_audit/EN_2.5s.png
Read /tmp/<name>_audit/EN_6.5s.png
...
```

The `Read` tool surfaces images to the model directly. `Bash(cat ...)` or
`Bash(file ...)` won't — the model only sees bytes, not pixels.

Per frame, look for:

1. **Arrow defects** — head colour, head size at 1080p, label position vs.
   dashed line angle.
2. **Padding intrusion** — text touching box edge, row label near canvas
   edge, outline line spilling past box bottom.
3. **Glyph kerning** — words with spurious mid-word spaces; common
   regression words: "GE", "generation", "fitness", "critic", "Petri".
4. **Frame-order anomaly** — half-faded content, missing content that
   should have appeared by that timestamp, line endpoint disconnected from
   its dot.

## 4. KO audit separately

After EN audit, run KO. Korean text width differs from English (Hangul
characters are roughly square; English is variable-width). Padding and
overflow regressions found in EN may not transfer 1:1.

```bash
for t in 2.5 6.5 10.5 14.5 18.5 24.0 28.0; do
    ffmpeg -hide_banner -loglevel error -ss $t \
        -i media/videos/<scene>/1080p60/<Name>-KO.mp4 \
        -frames:v 1 -update 1 -q:v 2 /tmp/<name>_audit/KO_${t}s.png -y
done
```

The category 3 (glyph kerning drift) catalogue is mostly Helvetica Neue /
EN specific — Pretendard / KO rarely regresses, but English embedded in
KO scenes (axis labels, function names like "compute_fitness") still does.

## 5. Iteration loop

After a fix is applied:

```bash
rm -rf media/videos/<scene>
uv run manim -qh -o <Name>-EN scripts/visualizations/<scene>.py <SceneClass>
# extract same timestamps to /tmp/<name>_audit/EN2_<t>s.png
# Read each — compare against the EN_<t>s.png from the prior round
```

The before/after comparison must check:
- Did the targeted defect disappear?
- Did adjacent bits pick up new collateral regressions? (Box height
  changes in Bit 1 commonly affect Bit 2 spacing.)

When EN passes, re-render KO and audit the same way.

## 6. Test rendering quality

For fast iteration during fix loops, use `-ql` (480p15):

```bash
uv run manim -ql -o <Name>-draft scripts/visualizations/<scene>.py <SceneClass>
```

`-ql` finishes in 1-2 min vs 3-4 min for `-qh`. Use `-qh` only for final
verification and when copying to `~/Downloads/`.

## 7. Tools-not-used note

Do not use Image-diff CLI tools like `diff -q` or `cmp` on frames — they
fail on tiny anti-aliasing differences and produce too many false
positives. Step 3 (pixelmatch-py, see `rules/pixel-ratchet.md`) is the
right deterministic comparator and will replace manual Read for
categories 2 + 4 once integrated.
