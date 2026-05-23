"""Key-frame manifest for the Step 3 pixel ratchet.

Shared by:
- ``tests/test_hero_frame_ratchet.py`` — diffs each frame against its
  baseline PNG using ``pixelmatch``.
- ``scripts/visualizations/update_frame_baselines.py`` — re-extracts
  the same frames from the rendered videos when a layout change is
  intentional.

Adding / removing frames here updates both ends in lock-step. Pick
timestamps from the *middle of each bit's wait phase* (avoid the
~0.4 s transition windows where bundled fade-out / fade-in produces
half-empty frames). See
``.claude/skills/viz-frame-audit/rules/audit-workflow.md`` §1 for the
timestamp-selection rationale.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeyFrame:
    """One reference frame in the ratchet manifest.

    ``scene`` + ``bit`` + ``lang`` uniquely identifies a baseline PNG.
    ``video_path`` is the rendered mp4 (relative to repo root).
    ``timestamp_s`` is the seek time inside that video.
    """

    scene: str  # e.g. "hero", "filewalk", "critical_floor"
    bit: str  # short slug ("bit_1", "rubric_detail", "outro")
    lang: str  # "en" or "ko"
    video_path: str
    timestamp_s: float
    tolerance_px: int  # max pixels allowed to differ from baseline

    @property
    def baseline_filename(self) -> str:
        return f"{self.scene}_{self.bit}_{self.lang}.png"


# Tolerance budget — calibrated 2026-05-22 on the v0.99.18 hero render.
# Headroom above anti-aliasing / font-hinting jitter (~200-400 px on
# 1080p frames at ``threshold=0.1``). Set higher for frames with text
# animation in progress; lower for static frames.
_TOL_STATIC = 800
_TOL_ANIMATED = 2500

KEY_FRAMES: tuple[KeyFrame, ...] = tuple(
    KeyFrame(
        scene="hero",
        bit=bit,
        lang=lang,
        video_path=f"media/videos/geode_hero/1080p60/GeodeHero-{lang.upper()}.mp4",
        timestamp_s=ts,
        tolerance_px=tol,
    )
    for bit, ts, tol in (
        ("bit_2_agent_grid", 9.0, _TOL_STATIC),
        ("bit_5_petri", 17.0, _TOL_ANIMATED),
        ("bit_9_fitness_formula", 25.0, _TOL_ANIMATED),
        ("outro_ratchet", 33.0, _TOL_STATIC),
        ("rubric_detail", 41.0, _TOL_STATIC),
        ("glossary", 49.0, _TOL_STATIC),
    )
    for lang in ("en", "ko")
)
