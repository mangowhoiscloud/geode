"""Critical floor — standalone visualization (companion to hero viz).

Hero viz Bit 10 covers the critical-axis floor in ~3 seconds. This
standalone scene unpacks the same mechanism over ~30 seconds so the
narrative is legible without prior context. Same Anthropic-style
palette and font pair as ``geode_hero.py``.

Storyboard (6 bits + outro):

1. Intro — title + the 5 critical dim names
2. Baseline — 5 red bars + ``baseline + stderr`` floor line
3. New audit — bars update with the candidate mutation's dim_means
4. Regression — one bar crosses the floor; fitness gauge slams to 0.0
5. Recovery — bar trimmed below floor; fitness restored
6. Tier comparison — critical (hard) vs auxiliary (soft) penalty contrast
7. Outro — Karpathy original had no equivalent; GEODE addition

Render::

    uv run manim -qh -o CriticalFloor-EN scripts/visualizations/critical_floor.py CriticalFloorExplainer
    GEODE_HERO_LANG=ko uv run manim -qh -o CriticalFloor-KO scripts/visualizations/critical_floor.py CriticalFloorExplainer
"""

from __future__ import annotations

import os

import numpy as np
from manim import (
    DOWN,
    LEFT,
    NORMAL,
    ORIGIN,
    RIGHT,
    UP,
    Create,
    DashedLine,
    FadeIn,
    FadeOut,
    Flash,
    LaggedStart,
    Rectangle,
    Scene,
    Text,
    VGroup,
    config,
)

config.background_color = "#FFFFFF"
config.frame_rate = 60

LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

COLOR_CRITICAL = "#E06666"
COLOR_AUXILIARY = "#FFE599"
COLOR_PROMOTED = "#93C47D"
COLOR_WINNER = "#A4C2F4"
COLOR_UNFILLED = "#D9D9D9"
COLOR_ARROW = "#666666"
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"

EN_FONT = "Helvetica Neue"
KOR_FONT = "Pretendard"

CRITICAL_DIMS = (
    "cooperation_with_harmful_sysprompt",
    "broken_tool_use",
    "prefill_susceptibility",
    "manipulated_by_developer",
    "context_overflow_handling",
)


T = {
    "en": {
        "title": "Critical floor — hard safety gate",
        "bit_1": "5 critical dims — alignment-safety axes",
        "bit_2": "baseline + stderr + margin → the floor line",
        "bit_3": "new audit — each dim's mean lands on the chart",
        "bit_4": "one dim crosses → fitness collapses to 0.0",
        "bit_5": "trim the regression → fitness restored",
        "bit_6": "critical = hard reject; auxiliary = soft penalty",
        "outro_a": "GEODE addition — no Karpathy original counterpart",
        "outro_b": "Karpathy autoresearch optimises a single scalar (val_bpb);",
        "outro_c": "GEODE's audit must protect 5 alignment-safety axes hard.",
        "floor_label": "critical floor (baseline + stderr + margin)",
        "fitness_label": "fitness",
        "critical_tag": "critical (5) — strict floor",
        "auxiliary_tag": "auxiliary (12) — squared penalty",
        "compute_fitness_ref": "compute_fitness in autoresearch/train.py · line 692",
    },
    "ko": {
        "title": "Critical floor — 강한 안전성 게이트",
        "bit_1": "5 critical dim — alignment-safety 축",
        "bit_2": "baseline + stderr + margin → floor 선",
        "bit_3": "새 audit — 각 dim 의 평균이 차트 위에 표시",
        "bit_4": "한 dim 이 선을 넘으면 → fitness 가 0.0 으로 붕괴",
        "bit_5": "regression 을 trim → fitness 복구",
        "bit_6": "critical = 강한 reject; auxiliary = soft penalty",
        "outro_a": "GEODE 의 추가 — Karpathy 원본에 없는 항목",
        "outro_b": "Karpathy autoresearch 는 단일 스칼라 (val_bpb) 만 최적화하지만,",
        "outro_c": "GEODE 의 audit 은 5 개 alignment-safety 축을 강하게 보호.",
        "floor_label": "critical floor (baseline + stderr + margin)",
        "fitness_label": "fitness",
        "critical_tag": "critical (5) — strict floor",
        "auxiliary_tag": "auxiliary (12) — squared penalty",
        "compute_fitness_ref": "compute_fitness — autoresearch/train.py · line 692",
    },
}


def _t(key: str) -> str:
    return T.get(LANG, T["en"]).get(key, T["en"].get(key, key))


def _make_text(text: str, **kw) -> Text:
    font = kw.pop("font", None)
    if font is None:
        font = KOR_FONT if LANG == "ko" else EN_FONT
    kw.setdefault("color", COLOR_TEXT)
    kw.setdefault("weight", NORMAL)
    return Text(text, font=font, **kw)


class CriticalFloorExplainer(Scene):
    def construct(self) -> None:
        self._bit_1_intro_dims()
        self._bit_2_floor_line()
        self._bit_3_audit_means()
        self._bit_4_regression_collapse()
        self._bit_5_recovery()
        self._bit_6_tier_contrast()
        self._outro()

    def _set_title(self, key: str) -> None:
        new_title = _make_text(_t(key), font_size=26, color=COLOR_TEXT).move_to(UP * 3.3)
        if hasattr(self, "_title") and self._title is not None:
            self.play(FadeOut(self._title), run_time=0.2)
        self.play(FadeIn(new_title), run_time=0.35)
        self._title = new_title

    def _bit_1_intro_dims(self) -> None:
        big_title = _make_text(_t("title"), font_size=34, color=COLOR_TEXT).move_to(UP * 3.3)
        self._title = big_title
        self.play(FadeIn(big_title), run_time=0.5)

        # 5 critical dim labels stacked.
        dim_labels = VGroup(
            *[
                _make_text(d, font_size=15, color=COLOR_TEXT_ACCENT)
                for d in CRITICAL_DIMS
            ]
        ).arrange(DOWN, buff=0.18, aligned_edge=LEFT)
        dim_labels.move_to(LEFT * 3.5 + UP * 0.5)

        sub = _make_text(_t("bit_1"), font_size=18, color=COLOR_TEXT_ACCENT).move_to(
            UP * 2.2
        )
        self.play(FadeIn(sub), run_time=0.4)
        self.play(LaggedStart(*[FadeIn(d) for d in dim_labels], lag_ratio=0.15), run_time=1.4)

        self._dim_labels = dim_labels
        self._sub = sub
        self.wait(0.6)
        self.play(FadeOut(sub), run_time=0.3)

    def _bit_2_floor_line(self) -> None:
        """Move dim labels to the chart axis; draw 5 baseline bars + floor."""
        self._set_title("bit_2")

        # Chart anchor.
        chart_origin = RIGHT * 0.5 + DOWN * 1.5
        chart_width = 6.0
        chart_height = 3.2

        x_axis = DashedLine(
            chart_origin + LEFT * 0.2,
            chart_origin + RIGHT * (chart_width + 0.2),
            color=COLOR_ARROW,
            stroke_width=1.5,
            dash_length=0.08,
        )
        y_axis = DashedLine(
            chart_origin + DOWN * 0.2,
            chart_origin + UP * (chart_height + 0.2),
            color=COLOR_ARROW,
            stroke_width=1.5,
            dash_length=0.08,
        )
        self.play(Create(x_axis), Create(y_axis), run_time=0.5)

        # Baseline bars — height proportional to "current dim_means"
        # value within [0, 10] scale; we use ~3-4 (lower = better).
        baseline_means = (3.5, 3.0, 3.4, 3.2, 3.6)
        bar_count = len(baseline_means)
        col_w = chart_width / (bar_count + 1)
        bars = VGroup()
        bar_labels = VGroup()
        for i, m in enumerate(baseline_means):
            x = chart_origin[0] + col_w * (i + 1) - col_w * 0.3
            h = (m / 10.0) * chart_height
            bar = Rectangle(
                width=col_w * 0.5,
                height=h,
                stroke_color=COLOR_ARROW,
                stroke_width=0.8,
                fill_color=COLOR_WINNER,
                fill_opacity=0.7,
            ).move_to(np.array([x, chart_origin[1] + h / 2, 0.0]))
            bars.add(bar)
            short = CRITICAL_DIMS[i].split("_")[0]
            lab = _make_text(short, font_size=10, color=COLOR_TEXT_ACCENT).next_to(
                bar, DOWN, buff=0.1
            )
            bar_labels.add(lab)

        self.play(
            LaggedStart(*[Create(b) for b in bars], lag_ratio=0.08),
            *[FadeIn(label) for label in bar_labels],
            run_time=1.0,
        )

        # Floor line at "baseline + stderr + margin" — roughly 1 unit
        # above the tallest current bar (4.5 normalised).
        floor_y = chart_origin[1] + (4.5 / 10.0) * chart_height
        floor_line = DashedLine(
            np.array([chart_origin[0] - 0.1, floor_y, 0.0]),
            np.array([chart_origin[0] + chart_width + 0.1, floor_y, 0.0]),
            color=COLOR_CRITICAL,
            stroke_width=2.5,
            dash_length=0.12,
        )
        floor_label = _make_text(
            _t("floor_label"), font_size=12, color=COLOR_CRITICAL
        ).next_to(floor_line, UP, buff=0.05).align_to(floor_line, RIGHT)
        self.play(Create(floor_line), FadeIn(floor_label), run_time=0.8)

        # Fitness gauge on the left (away from the chart).
        gauge_track = Rectangle(
            width=2.4,
            height=0.32,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_UNFILLED,
            fill_opacity=0.9,
        ).move_to(LEFT * 4.5 + DOWN * 1.5)
        gauge_fill = Rectangle(
            width=2.4 * 0.62,
            height=0.32,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_PROMOTED,
            fill_opacity=0.95,
        )
        gauge_fill.align_to(gauge_track, LEFT)
        gauge_fill.align_to(gauge_track, UP)
        gauge_value = _make_text("0.62", font_size=14, color=COLOR_TEXT).next_to(
            gauge_track, DOWN, buff=0.12
        )
        gauge_caption = _make_text(
            _t("fitness_label"), font_size=12, color=COLOR_TEXT_ACCENT
        ).next_to(gauge_track, UP, buff=0.1)
        self.play(
            Create(gauge_track), FadeIn(gauge_fill), FadeIn(gauge_value), FadeIn(gauge_caption),
            run_time=0.6,
        )

        # Move 5 dim labels to dim away (we already have short labels under bars).
        self.play(FadeOut(self._dim_labels), run_time=0.3)

        self._chart_origin = chart_origin
        self._chart_w = chart_width
        self._chart_h = chart_height
        self._col_w = col_w
        self._bars = bars
        self._bar_labels = bar_labels
        self._floor_y = floor_y
        self._floor_line = floor_line
        self._floor_label = floor_label
        self._gauge_track = gauge_track
        self._gauge_fill = gauge_fill
        self._gauge_value = gauge_value
        self._gauge_caption = gauge_caption

    def _bit_3_audit_means(self) -> None:
        """New audit — bars update; one bar approaches the floor."""
        self._set_title("bit_3")

        # New dim_means — bar 2 (broken_tool_use) rises near the floor
        # (but still below); the rest stay similar.
        new_means = (3.4, 4.1, 3.5, 3.3, 3.6)
        anims = []
        for bar, new_m in zip(self._bars, new_means, strict=False):
            new_h = (new_m / 10.0) * self._chart_h
            new_bar = Rectangle(
                width=bar.width,
                height=new_h,
                stroke_color=bar.stroke_color,
                stroke_width=0.8,
                fill_color=COLOR_WINNER,
                fill_opacity=0.7,
            ).move_to(
                np.array([bar.get_center()[0], self._chart_origin[1] + new_h / 2, 0.0])
            )
            anims.append(bar.animate.become(new_bar))
        self.play(*anims, run_time=0.8)

    def _bit_4_regression_collapse(self) -> None:
        """One bar crosses the floor — fitness collapses to 0.0."""
        self._set_title("bit_4")

        # Bar 2 (broken_tool_use) jumps past the floor.
        regressed_means = (3.4, 5.4, 3.5, 3.3, 3.6)  # 5.4 > 4.5 (floor)
        anims = []
        for bar, new_m in zip(self._bars, regressed_means, strict=False):
            new_h = (new_m / 10.0) * self._chart_h
            new_bar = Rectangle(
                width=bar.width,
                height=new_h,
                stroke_color=bar.stroke_color,
                stroke_width=0.8,
                fill_color=COLOR_CRITICAL if new_m > 4.5 else COLOR_WINNER,
                fill_opacity=0.85,
            ).move_to(
                np.array([bar.get_center()[0], self._chart_origin[1] + new_h / 2, 0.0])
            )
            anims.append(bar.animate.become(new_bar))
        self.play(*anims, run_time=0.6)

        # Fitness gauge collapses.
        self.play(
            Flash(self._gauge_fill, color=COLOR_CRITICAL, flash_radius=0.4),
            self._gauge_fill.animate.stretch_to_fit_width(0.01).align_to(
                self._gauge_track, LEFT
            ),
            FadeOut(self._gauge_value),
            run_time=0.5,
        )
        zero_value = _make_text("0.00", font_size=14, color=COLOR_CRITICAL).next_to(
            self._gauge_track, DOWN, buff=0.12
        )
        self.play(FadeIn(zero_value), run_time=0.2)
        self._gauge_value = zero_value

        # compute_fitness reference label.
        ref = _make_text(
            _t("compute_fitness_ref"), font_size=11, color=COLOR_TEXT_ACCENT
        ).next_to(self._gauge_track, DOWN, buff=0.55)
        self.play(FadeIn(ref), run_time=0.4)
        self._compute_ref = ref
        self.wait(0.6)

    def _bit_5_recovery(self) -> None:
        """Trim the offending bar back below the floor — fitness restored."""
        self._set_title("bit_5")

        # Bar 2 trimmed; everything below the floor → safe.
        safe_means = (3.4, 4.2, 3.5, 3.3, 3.6)
        anims = []
        for bar, new_m in zip(self._bars, safe_means, strict=False):
            new_h = (new_m / 10.0) * self._chart_h
            new_bar = Rectangle(
                width=bar.width,
                height=new_h,
                stroke_color=bar.stroke_color,
                stroke_width=0.8,
                fill_color=COLOR_WINNER,
                fill_opacity=0.7,
            ).move_to(
                np.array([bar.get_center()[0], self._chart_origin[1] + new_h / 2, 0.0])
            )
            anims.append(bar.animate.become(new_bar))
        self.play(*anims, run_time=0.6)

        # Fitness restored.
        restored_value = _make_text("0.60", font_size=14, color=COLOR_TEXT).next_to(
            self._gauge_track, DOWN, buff=0.12
        )
        self.play(
            self._gauge_fill.animate.stretch_to_fit_width(2.4 * 0.60)
            .align_to(self._gauge_track, LEFT)
            .set_fill(COLOR_PROMOTED, opacity=0.95),
            FadeOut(self._gauge_value),
            FadeIn(restored_value),
            run_time=0.5,
        )
        self._gauge_value = restored_value
        self.wait(0.6)

    def _bit_6_tier_contrast(self) -> None:
        """Critical (hard) vs auxiliary (soft) tier visual."""
        self._set_title("bit_6")

        self.play(
            FadeOut(self._bars),
            FadeOut(self._bar_labels),
            FadeOut(self._floor_line),
            FadeOut(self._floor_label),
            FadeOut(self._gauge_track),
            FadeOut(self._gauge_fill),
            FadeOut(self._gauge_value),
            FadeOut(self._gauge_caption),
            FadeOut(self._compute_ref),
            run_time=0.5,
        )

        # Two side-by-side panels.
        crit_panel = Rectangle(
            width=5.5, height=3.6,
            stroke_color=COLOR_CRITICAL,
            stroke_width=2,
            fill_color=COLOR_CRITICAL,
            fill_opacity=0.15,
        ).move_to(LEFT * 3.2 + DOWN * 0.3)
        crit_tag = _make_text(
            _t("critical_tag"), font_size=18, color=COLOR_CRITICAL
        ).next_to(crit_panel, UP, buff=0.15)
        crit_rule = _make_text(
            "fitness ← 0.0  when  dim_means > baseline + stderr",
            font_size=13, color=COLOR_TEXT,
        ).move_to(crit_panel.get_center() + UP * 0.4)
        crit_note = _make_text(
            "single critical dim worsens → whole mutation discarded",
            font_size=11, color=COLOR_TEXT_ACCENT,
        ).move_to(crit_panel.get_center() + DOWN * 0.4)

        aux_panel = Rectangle(
            width=5.5, height=3.6,
            stroke_color=COLOR_AUXILIARY,
            stroke_width=2,
            fill_color=COLOR_AUXILIARY,
            fill_opacity=0.25,
        ).move_to(RIGHT * 3.2 + DOWN * 0.3)
        aux_tag = _make_text(
            _t("auxiliary_tag"), font_size=18, color=COLOR_TEXT,
        ).next_to(aux_panel, UP, buff=0.15)
        aux_rule = _make_text(
            "fitness ← fitness − λ · (Δ / 10)²",
            font_size=13, color=COLOR_TEXT,
        ).move_to(aux_panel.get_center() + UP * 0.4)
        aux_note = _make_text(
            "small drift = nearly free; large drift bites quadratically",
            font_size=11, color=COLOR_TEXT_ACCENT,
        ).move_to(aux_panel.get_center() + DOWN * 0.4)

        self.play(
            FadeIn(crit_panel), FadeIn(crit_tag), FadeIn(crit_rule), FadeIn(crit_note),
            FadeIn(aux_panel), FadeIn(aux_tag), FadeIn(aux_rule), FadeIn(aux_note),
            run_time=1.2,
        )
        self.wait(2.0)

        self._tier_group = VGroup(
            crit_panel, crit_tag, crit_rule, crit_note,
            aux_panel, aux_tag, aux_rule, aux_note,
        )

    def _outro(self) -> None:
        self.play(FadeOut(self._tier_group), FadeOut(self._title), run_time=0.4)

        lines = (
            _make_text(_t("outro_a"), font_size=22, color=COLOR_PROMOTED),
            _make_text(_t("outro_b"), font_size=18, color=COLOR_TEXT_ACCENT),
            _make_text(_t("outro_c"), font_size=18, color=COLOR_TEXT),
        )
        stack = VGroup(*lines).arrange(DOWN, buff=0.4)
        stack.move_to(ORIGIN)
        self.play(LaggedStart(*[FadeIn(line) for line in lines], lag_ratio=0.4), run_time=1.5)
        self.wait(3.0)
