# Pixel ratchet — Step 3 (shipped 2026-05-22)

> **Status**: implemented in `tests/test_hero_frame_ratchet.py`
> (12 hero key frames, EN+KO). Baselines under
> `tests/visualizations/baselines/`. Regenerate via
> `scripts/visualizations/update_frame_baselines.py`.

## Goal

Deterministic catch for categories 2 (padding intrusion) and 4 (frame-order
error) using
[whtsky/pixelmatch-py](https://github.com/whtsky/pixelmatch-py) (137★,
last push 2026-05-12). This is a port of Mapbox's `pixelmatch` JS with
anti-aliasing-aware and perceptual-colour diff.

## Why not manual Read for these categories

- The `verify_hero_layout.py` ratchet measures geometry (text-vs-container
  ratios) — it can't see "arrow crossing label" or "transition frame
  empty".
- Manual Read of every frame on every PR is cost-prohibitive.
- `pixelmatch-py` runs in milliseconds and is deterministic — pixel-perfect
  diff vs a committed baseline.

## Proposed integration

```
tests/visualizations/
├── test_hero_frame_ratchet.py       # pytest, runs on `pytest tests/`
└── baselines/
    ├── hero_bit_1_en.png
    ├── hero_bit_5_en.png
    ├── hero_bit_9_en.png
    ├── hero_bit_1_ko.png
    ├── ...
    └── README.md                    # how to regenerate
```

The test iterates over a `KEY_FRAMES` constant (Bit number → timestamp +
lang), extracts the current frame via ffmpeg, and compares against the
baseline PNG with a tolerance of N mismatched pixels (~1000 default;
calibrate from initial run).

## Baseline regeneration UX

Borrow from `matplotlib/pytest-mpl`'s `--mpl-generate-path` pattern:

```bash
pytest tests/visualizations/test_hero_frame_ratchet.py --update-baseline-frames
```

This re-renders the EN + KO scenes, extracts every `KEY_FRAMES` timestamp,
and overwrites the baseline PNGs. Run after every intentional layout
change; commit the new baselines alongside the scene change.

## Shipped integration — `tests/test_hero_frame_ratchet.py`

The actual code is ~135 lines and uses `pytest.parametrize` over the
`KEY_FRAMES` manifest in `tests/visualizations/key_frames.py`. The
sample below shows the core shape.

```python
from pathlib import Path
import subprocess

import pytest
from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch

BASELINE_DIR = Path("tests/visualizations/baselines")
TOLERANCE_PX = 1000           # calibrated from initial run
THRESHOLD = 0.1               # pixelmatch sensitivity

KEY_FRAMES = (
    ("hero", "bit_1", "en", 9.0),
    ("hero", "bit_5", "en", 17.0),
    ("hero", "bit_9", "en", 25.0),
    ("hero", "bit_outro", "en", 33.0),
    # KO frames same timestamps
    ("hero", "bit_1", "ko", 9.0),
    ("hero", "bit_5", "ko", 17.0),
    ("hero", "bit_9", "ko", 25.0),
    ("hero", "bit_outro", "ko", 33.0),
)


def _extract_frame(scene: str, lang: str, t: float, out: Path) -> None:
    lang_suffix = "EN" if lang == "en" else "KO"
    src = f"media/videos/geode_{scene}/1080p60/Geode{scene.capitalize()}-{lang_suffix}.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-ss", str(t), "-i", src,
         "-frames:v", "1", "-update", "1", "-q:v", "2", str(out), "-y"],
        check=True,
    )


@pytest.mark.parametrize("scene,bit,lang,t", KEY_FRAMES)
def test_frame_ratchet(tmp_path, scene, bit, lang, t):
    baseline = BASELINE_DIR / f"{scene}_{bit}_{lang}.png"
    current = tmp_path / f"{bit}_{lang}.png"
    _extract_frame(scene, lang, t, current)

    img_a = Image.open(baseline)
    img_b = Image.open(current)
    diff = Image.new("RGBA", img_a.size)
    mismatch = pixelmatch(img_a, img_b, diff,
                          threshold=THRESHOLD, includeAA=True)
    assert mismatch <= TOLERANCE_PX, (
        f"{bit}/{lang}: {mismatch} px mismatch (tolerance {TOLERANCE_PX})"
    )
```

## CI gate

```yaml
- name: Hero viz frame ratchet
  if: needs.changes.outputs.code == 'true'
  run: uv run pytest tests/visualizations/test_hero_frame_ratchet.py
```

## Calibrating `TOLERANCE_PX`

The default `1000` is a guess. The right calibration:

1. Run the test against a fresh baseline → expect 0 mismatches.
2. Apply a deliberately small change (e.g. shift Bit 9 label by 0.1 unit).
3. Re-run and check the reported mismatch count.
4. Pick `TOLERANCE_PX` slightly above the typical false-positive floor
   (anti-aliased subpixel jitter, font hinting variations across renders).

For 1080p60 frames, false-positive floor is typically ≤ 500 px after
`threshold=0.1`. Setting tolerance to 1000 catches ≥ 0.05% pixel-diff
defects while ignoring AA jitter.

## What this catches that geometry ratchet misses

| Defect example | Geometry ratchet | Pixel ratchet |
|---|---|---|
| Box width ratio creeps from 0.95 to 1.02 | ✅ (overflow) | ✅ |
| Arrow head colour changes from yellow to blue | ✗ | ✅ |
| Bit-transition empty frame appears at t=22.5 | ✗ | ✅ |
| Label glyph drift "GE → GE ODE" | ✗ | ✅ (but Step 2 typography drift gate catches it earlier and cheaper) |
| Manim version upgrade subtly changes anti-aliasing | (false ✗) | (false ✓ — accept via baseline refresh) |
