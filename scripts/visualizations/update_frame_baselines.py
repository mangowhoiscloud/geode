"""Regenerate the hero-viz frame baselines used by the Step 3 pixel ratchet.

Pulls key-frame timestamps from ``tests/visualizations/key_frames.py``
so the test file and this regen script share the same source of truth.
Each frame is extracted via ``ffmpeg`` from the already-rendered
``media/videos/.../{Scene}-{EN,KO}.mp4`` and written to
``tests/visualizations/baselines/<scene>_<bit>_<lang>.png``.

Usage
=====

::

    # Default — re-extract all key frames into baselines/.
    uv run python scripts/visualizations/update_frame_baselines.py

    # Only one scene.
    uv run python scripts/visualizations/update_frame_baselines.py --scene hero

    # Print what would be written without touching disk.
    uv run python scripts/visualizations/update_frame_baselines.py --dry-run

This script does NOT render videos. Run the ``manim`` commands in
[[manim-scene-craft]]'s `rules/multilingual-render.md` first so the
``.mp4`` inputs exist; the script then extracts frames from those
existing renders.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO_ROOT / "tests" / "visualizations" / "baselines"

# Make tests/ importable so we can re-use KEY_FRAMES.
sys.path.insert(0, str(REPO_ROOT))


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _extract_frame(video: Path, timestamp_s: float, out: Path) -> None:
    """Extract a single PNG frame from ``video`` at ``timestamp_s``."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
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
    ]
    subprocess.run(cmd, check=True)  # noqa: S603


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scene",
        default=None,
        help="Limit to one scene id (e.g. 'hero'). Default: every scene.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the extractions that would happen without touching disk.",
    )
    args = parser.parse_args()

    if not _ffmpeg_available():
        print(
            "update_frame_baselines: ffmpeg not on PATH. "
            "Install via `brew install ffmpeg` (macOS) or "
            "`apt-get install ffmpeg` (Linux).",
            file=sys.stderr,
        )
        return 1

    from tests.visualizations.key_frames import KEY_FRAMES

    targets = [k for k in KEY_FRAMES if args.scene is None or k.scene == args.scene]
    if not targets:
        print(
            f"update_frame_baselines: no key frames match --scene={args.scene!r}",
            file=sys.stderr,
        )
        return 1

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"update_frame_baselines: writing {len(targets)} baseline PNG(s) to {BASELINE_DIR}")

    written = 0
    skipped = 0
    for kf in targets:
        video = REPO_ROOT / kf.video_path
        if not video.is_file():
            print(
                f"  SKIP  {kf.scene}/{kf.bit}/{kf.lang} — input video missing: {video}",
                file=sys.stderr,
            )
            skipped += 1
            continue

        out = BASELINE_DIR / kf.baseline_filename
        action = "DRY  " if args.dry_run else "WRITE"
        print(f"  {action} {out.name:50}  ({kf.timestamp_s:6.2f} s from {video.name})")
        if not args.dry_run:
            _extract_frame(video, kf.timestamp_s, out)
            written += 1

    if args.dry_run:
        print(f"update_frame_baselines: dry-run; {len(targets)} frame(s) would be written.")
        return 0
    print(f"update_frame_baselines: wrote {written} baseline(s), skipped {skipped}.")
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
