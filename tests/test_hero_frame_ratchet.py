"""Step 3 — pixel ratchet for the hero scene's key frames.

Each (scene, bit, lang) frame in ``KEY_FRAMES`` is extracted from the
rendered video via ffmpeg and diffed against its committed baseline
PNG using ``pixelmatch``. Mismatches above the per-frame
``tolerance_px`` cap fail the test.

Catches categories 2 (padding intrusion) and 4 (frame-order error)
that the typography drift gate (Step 2) cannot see — see
``.claude/skills/viz-frame-audit/rules/pixel-ratchet.md`` for the full
positioning vs the geometry + typography ratchets.

Auto-skip behavior
==================

The test auto-skips when:
- ffmpeg is missing on PATH (Linux CI without ffmpeg installed)
- the rendered video at ``video_path`` doesn't exist (PR didn't touch
  scene code → no re-render needed)
- the baseline PNG for the (scene, bit, lang) is missing (new frame
  added but ``scripts/visualizations/update_frame_baselines.py`` not
  run yet — the helper run prints a TODO so this is loud)

Updating baselines after an intentional layout change
=====================================================

::

    # 1) Re-render the changed scene(s)
    uv run manim -qh -o GeodeSelfImprovingHero-EN scripts/visualizations/geode_hero.py GeodeSelfImprovingHero
    GEODE_HERO_LANG=ko uv run manim -qh -o GeodeSelfImprovingHero-KO scripts/visualizations/geode_hero.py GeodeSelfImprovingHero

    # 2) Re-extract baselines
    uv run python scripts/visualizations/update_frame_baselines.py

    # 3) Confirm the test passes against the new baselines
    uv run pytest tests/test_hero_frame_ratchet.py -v

    # 4) Commit the changed baselines alongside the scene change
    git add tests/visualizations/baselines/
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.visualizations.key_frames import KEY_FRAMES, KeyFrame

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO_ROOT / "tests" / "visualizations" / "baselines"
DIFF_OUTPUT_DIR = Path(tempfile.gettempdir()) / "geode_hero_frame_diffs"
PIXELMATCH_THRESHOLD = 0.1


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _extract_frame(video: Path, timestamp_s: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_s}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-update",
            "1",
            "-q:v",
            "2",
            str(out),
            "-y",
        ],
        check=True,
    )


@pytest.mark.parametrize(
    "kf",
    KEY_FRAMES,
    ids=lambda kf: f"{kf.scene}/{kf.bit}/{kf.lang}",
)
def test_frame_matches_baseline(tmp_path: Path, kf: KeyFrame) -> None:
    """Pixel-ratchet a single key frame against its baseline PNG."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg not on PATH — frame ratchet requires ffmpeg")

    video = REPO_ROOT / kf.video_path
    if not video.is_file():
        pytest.skip(
            f"rendered video missing at {video} — run `manim -qh` first to "
            "produce the input for the ratchet"
        )

    baseline_path = BASELINE_DIR / kf.baseline_filename
    if not baseline_path.is_file():
        pytest.skip(
            f"baseline missing at {baseline_path} — run "
            f"`uv run python scripts/visualizations/update_frame_baselines.py "
            f"--scene {kf.scene}` to create it"
        )

    pytest.importorskip("pixelmatch.contrib.PIL")
    pytest.importorskip("PIL.Image")
    from PIL import Image
    from pixelmatch.contrib.PIL import pixelmatch

    current_path = tmp_path / f"{kf.scene}_{kf.bit}_{kf.lang}_current.png"
    _extract_frame(video, kf.timestamp_s, current_path)

    baseline_img = Image.open(baseline_path).convert("RGBA")
    current_img = Image.open(current_path).convert("RGBA")

    assert baseline_img.size == current_img.size, (
        f"frame size mismatch: baseline {baseline_img.size} vs "
        f"current {current_img.size} for {kf.baseline_filename}"
    )

    diff_img = Image.new("RGBA", baseline_img.size)
    mismatch = pixelmatch(
        baseline_img,
        current_img,
        diff_img,
        threshold=PIXELMATCH_THRESHOLD,
        includeAA=True,
    )

    if mismatch > kf.tolerance_px:
        # Persist the diff so the developer can inspect *what* moved.
        DIFF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        diff_out = DIFF_OUTPUT_DIR / f"{kf.scene}_{kf.bit}_{kf.lang}_diff.png"
        diff_img.save(diff_out)
        pytest.fail(
            f"{kf.baseline_filename}: {mismatch} mismatched px "
            f"(tolerance {kf.tolerance_px}). Diff written to {diff_out}.\n"
            "If this change is intentional, re-render and run "
            "`update_frame_baselines.py --scene <name>` before committing."
        )
