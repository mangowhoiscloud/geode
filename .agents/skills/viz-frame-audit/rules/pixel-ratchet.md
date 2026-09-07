# Pixel ratchet — Step 3 (shipped 2026-05-22)

The current implementation compares selected rendered frames against committed
baselines with `pixelmatch-py`. Read the actual owners rather than reproducing
the original proposal's example comparator or pytest options:

| Responsibility | Current owner |
|---|---|
| Frame comparison and skip conditions | [`test_hero_frame_ratchet.py`](../../../../tests/visualizations/test_hero_frame_ratchet.py) |
| Timestamps, video paths, languages, and per-frame tolerance | [`key_frames.py`](../../../../tests/visualizations/key_frames.py) |
| Baseline extraction | [`update_frame_baselines.py`](../../../../scripts/visualizations/update_frame_baselines.py) |
| Committed images | `tests/visualizations/baselines/` |

## Verify

```bash
uv run pytest tests/visualizations/test_hero_frame_ratchet.py
```

Inspect the actual result, including skips. The test skips when ffmpeg, the
expected rendered video, a baseline image, or optional image dependencies are
missing. A skipped comparison is not evidence that the frame matches. A passing
comparison covers only the selected frames and their configured tolerances;
inspect changed sections or transition states outside that manifest separately.

## Update an intentional baseline

1. Render and visually approve the intended change using the
   [isolated render procedure](../../manim-scene-craft/rules/multilingual-render.md#render-commands).
   Preserve the previous render and baseline evidence.
2. Resolve the exact video path expected by the selected `KEY_FRAMES` entries.
   Place the reviewed render there only within the owned worktree and without
   overwriting another task's evidence. A temporary render elsewhere is not
   automatically the test's input.
3. Inspect the planned writes before updating only the intended scene:

   ```bash
   uv run python scripts/visualizations/update_frame_baselines.py --scene <scene-id> --dry-run
   uv run python scripts/visualizations/update_frame_baselines.py --scene <scene-id>
   ```

4. Rerun the comparison and inspect changed baseline files before committing
   them with the reviewed scene change. Never refresh a baseline or widen a
   tolerance merely to hide an unexplained failure.

The helper extracts frames from already-rendered videos; it does not render
EN/KO scenes. `--update-baseline-frames` is not a supported pytest option here.
Use the current per-frame manifest, not a copied global pixel-count threshold.

## Evidence boundaries

Geometry checks measure text/container dimensions, typography checks measure
font-shaping evidence, and frame comparisons detect visible differences from
an approved image. These checks complement visual review; none establishes
that a benchmark claim, source mapping, or animation meaning is correct.
Preserve the source/render/environment identity when comparing frames and
report any unmeasured frames or missing dependencies explicitly.
