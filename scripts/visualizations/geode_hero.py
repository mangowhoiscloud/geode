"""GEODE outer self-improving loop — hero visualization.

Reference: Google AI Co-Scientist hero video (830×470, 13.7s).
GEODE extends the agent-grid pattern with two downstream stages —
**Petri (measurement)** and **autoresearch (selection)** — so the
visualization walks the full Co-Scientist → Petri → autoresearch
self-improving cycle.

12-bit storyboard + 5s outro is defined in
``docs/visualizations/geode-hero-storyboard.md`` (single source of truth).

Render
======
::

    uv run manim -pqh scripts/visualizations/geode_hero.py GeodeSelfImprovingHero          # EN
    GEODE_HERO_LANG=ko uv run manim -pqh scripts/visualizations/geode_hero.py GeodeSelfImprovingHero   # KO

Outputs to ``media/videos/geode_hero/1080p60/GeodeSelfImprovingHero.mp4``.
Rename per language for distribution.
"""

from __future__ import annotations

import os

from manim import (
    BLACK,
    DOWN,
    LEFT,
    ORIGIN,
    RIGHT,
    UP,
    Arrow,
    Circle,
    Create,
    DashedLine,
    FadeIn,
    FadeOut,
    Flash,
    LaggedStart,
    Line,
    NumberLine,
    Rectangle,
    Scene,
    Square,
    Text,
    Transform,
    VGroup,
    Write,
    config,
)

# ───────────────────────────────────────────────────────────────────────
# Configuration
# ───────────────────────────────────────────────────────────────────────

config.background_color = "#FFFFFF"
config.frame_rate = 60

LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

# Color palette — matches Co-Scientist aesthetic + GEODE additions.
COLOR_AGENT = "#F4CCCC"  # light pink — seed-generation agents
COLOR_WINNER = "#A4C2F4"  # light blue — promoted / tournament winners
COLOR_UNFILLED = "#D9D9D9"  # grey — unfilled slot / supervisor
COLOR_CRITICAL = "#E06666"  # red — critical-axis floor
COLOR_PROMOTED = "#93C47D"  # green — auto-promote pass
COLOR_PETRI = "#FFE599"  # soft yellow — measurement layer
COLOR_ARROW = "#666666"  # medium grey — dashed connectors
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"

# Default sans-serif fonts. EN uses Helvetica (macOS-bundled); KO uses
# Apple SD Gothic Neo so Korean glyphs render without empty boxes.
# Manim's Pango backend requires the font name to be a non-empty string
# even when defaults would suffice — passing ``None`` raises TypeError.
EN_FONT = "Helvetica"
KOR_FONT = "Apple SD Gothic Neo"

# ───────────────────────────────────────────────────────────────────────
# EN / KO text lookup
# ───────────────────────────────────────────────────────────────────────

T: dict[str, dict[str, str]] = {
    "en": {
        "bit_1": "Engineer specifies a research goal",
        "bit_2": "GEODE seed-generation: 7 specialist agents",
        "bit_3": "Generate → Critique → Evolve",
        "bit_4": "Tournament — top survivors emerge",
        "bit_5": "Survivors → Petri audit subprocess",
        "bit_6": "20-dim rubric: 5 critical / 12 auxiliary / 3 info",
        "bit_7": "LLM judge scores each transcript",
        "bit_8": "dim_extractor → dim_means + dim_stderr",
        "bit_9": "compute_fitness: 17-dim weighted + stability",
        "bit_10": "Critical-axis floor: regression → fitness = 0.0",
        "bit_11": "Auto-promote: gain > max(stderr, 0.05)",
        "bit_12": "Next generation: wrapper-prompt mutation",
        "outro": "Self-improving over generations",
        "agent_generator": "generator",
        "agent_proximity": "proximity",
        "agent_critic": "critic",
        "agent_pilot": "pilot",
        "agent_ranker": "ranker",
        "agent_evolver": "evolver",
        "agent_meta_reviewer": "meta_reviewer",
        "petri_box": "Petri (geode audit)",
        "baseline_json": "baseline.json",
        "gen_n": "gen N",
        "gen_n_plus_1": "gen N+1",
        "scientist_label": "Engineer",
        "leaderboard_label": "Survivors",
        "discard": "DISCARD",
        "promote": "PROMOTE",
        "fitness_label": "fitness",
        "generations_label": "generation",
    },
    "ko": {
        "bit_1": "엔지니어가 연구 목표를 명세",
        "bit_2": "GEODE seed-generation — 7 전문 agent",
        "bit_3": "생성 → 비평 → 진화",
        "bit_4": "토너먼트 — 최강 후보 도출",
        "bit_5": "Survivors → Petri audit subprocess",
        "bit_6": "20-dim rubric — critical 5 / aux 12 / info 3",
        "bit_7": "judge LLM 이 transcript 별 점수 부여",
        "bit_8": "dim_extractor → dim_means + dim_stderr",
        "bit_9": "compute_fitness — 17 dim 가중 합산 + stability",
        "bit_10": "Critical-axis floor — regression 시 fitness = 0.0",
        "bit_11": "Auto-promote — gain > max(stderr, 0.05)",
        "bit_12": "다음 세대 — wrapper-prompt mutation",
        "outro": "세대를 거듭한 자기 개선",
        "agent_generator": "generator",
        "agent_proximity": "proximity",
        "agent_critic": "critic",
        "agent_pilot": "pilot",
        "agent_ranker": "ranker",
        "agent_evolver": "evolver",
        "agent_meta_reviewer": "meta_reviewer",
        "petri_box": "Petri (geode audit)",
        "baseline_json": "baseline.json",
        "gen_n": "세대 N",
        "gen_n_plus_1": "세대 N+1",
        "scientist_label": "엔지니어",
        "leaderboard_label": "Survivors",
        "discard": "DISCARD",
        "promote": "PROMOTE",
        "fitness_label": "fitness",
        "generations_label": "세대",
    },
}


def _t(key: str) -> str:
    """Lookup the active-language string. Falls back to EN on miss."""
    return T.get(LANG, T["en"]).get(key, T["en"].get(key, key))


def _make_text(text: str, **kw) -> Text:
    """Construct a Text with KO-aware font selection.

    On EN renders we let Manim pick its bundled font. On KO renders we
    request the macOS-bundled Korean font so glyph fallbacks do not
    show empty boxes.
    """
    font = kw.pop("font", None)
    if font is None:
        font = KOR_FONT if LANG == "ko" else EN_FONT
    kw["color"] = kw.get("color", COLOR_TEXT)
    return Text(text, font=font, **kw)


# ───────────────────────────────────────────────────────────────────────
# Helpers — reusable shape factories
# ───────────────────────────────────────────────────────────────────────


def _agent_box(label_key: str, *, color: str = COLOR_AGENT, width: float = 2.2) -> VGroup:
    """A rounded pink box with a centered label — the GEODE agent unit."""
    body = Rectangle(
        width=width,
        height=0.7,
        stroke_color=COLOR_ARROW,
        stroke_width=1.5,
        fill_color=color,
        fill_opacity=0.85,
    )
    body.set_corner_radius = 0.1  # visual hint only — Manim Rectangle is sharp
    label = _make_text(_t(label_key), color=COLOR_TEXT, font_size=20)
    label.move_to(body.get_center())
    return VGroup(body, label)


def _scientist_icon() -> VGroup:
    """A simple person icon: head circle + body trapezoid (rectangle)."""
    head = Circle(radius=0.15, color=COLOR_WINNER, fill_color=COLOR_WINNER, fill_opacity=1.0)
    head.shift(UP * 0.25)
    body = Rectangle(
        width=0.5,
        height=0.3,
        stroke_color=COLOR_WINNER,
        fill_color=COLOR_WINNER,
        fill_opacity=1.0,
    )
    body.shift(DOWN * 0.05)
    icon = VGroup(head, body)
    label = _make_text(_t("scientist_label"), color=COLOR_TEXT, font_size=16)
    label.next_to(icon, DOWN, buff=0.1)
    return VGroup(icon, label)


def _dashed_arrow(start, end) -> DashedLine:
    """Co-Scientist-style dashed connector."""
    return DashedLine(start, end, color=COLOR_ARROW, stroke_width=2, dash_length=0.15)


# ───────────────────────────────────────────────────────────────────────
# Scene
# ───────────────────────────────────────────────────────────────────────


class GeodeSelfImprovingHero(Scene):
    """12-bit walkthrough of GEODE's Co-Scientist → Petri → autoresearch loop."""

    def construct(self) -> None:
        self._bit_1_engineer_goal()
        self._bit_2_seven_agents()
        self._bit_3_generate_critique_evolve()
        self._bit_4_tournament_survivors()
        self._bit_5_to_petri()
        self._bit_6_20_dim_rubric()
        self._bit_7_judge_scoring()
        self._bit_8_dim_extractor()
        self._bit_9_compute_fitness()
        self._bit_10_critical_floor()
        self._bit_11_auto_promote()
        self._bit_12_next_generation()
        self._outro_ratchet_summary()

    # ──────────────────────────────────────────────────────────────────
    # Stage 1 — Co-Scientist pattern (GEODE seed-generation)
    # ──────────────────────────────────────────────────────────────────

    def _bit_1_engineer_goal(self) -> None:
        """0–1.5s — Engineer icon + research-goal speech bubble."""
        self.engineer = _scientist_icon()
        self.engineer.shift(UP * 3.0)

        speech = _make_text(_t("bit_1"), font_size=28).next_to(self.engineer, DOWN, buff=0.5)
        self.speech = speech

        self.play(FadeIn(self.engineer), run_time=0.6)
        self.play(Write(speech), run_time=0.9)

    def _bit_2_seven_agents(self) -> None:
        """1.5–4s — Outer GEODE seed-generation box + 7 specialist agents."""
        self.outer_box = Rectangle(
            width=8.0,
            height=4.5,
            stroke_color=COLOR_ARROW,
            stroke_width=2,
            fill_color="#FFFFFF",
            fill_opacity=0.0,
        ).shift(DOWN * 0.5)

        outer_label = _make_text("GEODE seed-generation", font_size=22, color=COLOR_TEXT_ACCENT)
        outer_label.next_to(self.outer_box, UP, buff=0.1)
        self.outer_label = outer_label

        agent_keys = [
            "agent_generator",
            "agent_proximity",
            "agent_critic",
            "agent_pilot",
            "agent_ranker",
            "agent_evolver",
            "agent_meta_reviewer",
        ]
        positions = [
            LEFT * 2.5 + UP * 0.8,
            ORIGIN + UP * 0.8,
            RIGHT * 2.5 + UP * 0.8,
            LEFT * 2.5 + DOWN * 0.2,
            ORIGIN + DOWN * 0.2,
            RIGHT * 2.5 + DOWN * 0.2,
            ORIGIN + DOWN * 1.2,
        ]
        agents = []
        for key, pos in zip(agent_keys, positions):
            a = _agent_box(key)
            a.move_to(self.outer_box.get_center() + pos * 0.6)
            agents.append(a)
        self.agents = {key: a for key, a in zip(agent_keys, agents)}

        self.play(Create(self.outer_box), Write(outer_label), run_time=0.6)
        self.play(
            LaggedStart(*[FadeIn(a) for a in agents], lag_ratio=0.12),
            run_time=1.8,
        )
        # Update bit text
        new_text = _make_text(_t("bit_2"), font_size=26).move_to(self.speech.get_center())
        self.play(Transform(self.speech, new_text), run_time=0.5)

    def _bit_3_generate_critique_evolve(self) -> None:
        """4–6s — generator → critic → evolver chain flash."""
        chain = ["agent_generator", "agent_critic", "agent_evolver"]
        new_text = _make_text(_t("bit_3"), font_size=26).move_to(self.speech.get_center())
        self.play(Transform(self.speech, new_text), run_time=0.4)
        for key in chain:
            self.play(Flash(self.agents[key], color=COLOR_WINNER, flash_radius=0.6), run_time=0.4)

    def _bit_4_tournament_survivors(self) -> None:
        """6–8s — survivors leaderboard appears; slots fill blue."""
        leaderboard = VGroup(
            *[
                Rectangle(
                    width=1.6,
                    height=0.45,
                    stroke_color=COLOR_ARROW,
                    stroke_width=1.5,
                    fill_color=COLOR_UNFILLED,
                    fill_opacity=0.9,
                ).shift(DOWN * (i * 0.55))
                for i in range(5)
            ]
        )
        leaderboard.move_to(RIGHT * 5.2 + DOWN * 0.5)
        self.leaderboard = leaderboard
        leaderboard_label = _make_text(
            _t("leaderboard_label"), font_size=20, color=COLOR_TEXT_ACCENT
        ).next_to(leaderboard, UP, buff=0.2)
        self.leaderboard_label = leaderboard_label

        agent_box_right_edge = self.outer_box.get_right() + RIGHT * 0.1
        arrow_to_leaderboard = _dashed_arrow(agent_box_right_edge, leaderboard.get_left())
        self.arrow_to_leaderboard = arrow_to_leaderboard

        new_text = _make_text(_t("bit_4"), font_size=26).move_to(self.speech.get_center())
        self.play(Transform(self.speech, new_text), run_time=0.4)
        self.play(Create(leaderboard), Write(leaderboard_label), Create(arrow_to_leaderboard), run_time=0.8)

        # Fill top 3 slots blue (winners), keep bottom 2 grey.
        for i in range(3):
            self.play(
                leaderboard[i].animate.set_fill(COLOR_WINNER, opacity=0.9),
                run_time=0.3,
            )

    # ──────────────────────────────────────────────────────────────────
    # Stage 2 — Petri audit (measurement)
    # ──────────────────────────────────────────────────────────────────

    def _bit_5_to_petri(self) -> None:
        """8–10s — Petri box appears, dashed arrow from survivors."""
        petri_box = Rectangle(
            width=2.5,
            height=1.4,
            stroke_color=COLOR_ARROW,
            stroke_width=1.8,
            fill_color=COLOR_PETRI,
            fill_opacity=0.85,
        )
        petri_box.shift(DOWN * 2.5 + RIGHT * 2.5)
        petri_label = _make_text(_t("petri_box"), font_size=18, color=COLOR_TEXT)
        petri_label.move_to(petri_box.get_center())
        self.petri_box = VGroup(petri_box, petri_label)

        survivors_to_petri = _dashed_arrow(
            self.leaderboard.get_bottom() + DOWN * 0.05,
            petri_box.get_top() + UP * 0.05,
        )
        self.survivors_to_petri = survivors_to_petri

        new_text = _make_text(_t("bit_5"), font_size=26).move_to(self.speech.get_center())
        self.play(Transform(self.speech, new_text), run_time=0.4)
        self.play(Create(self.petri_box), Create(survivors_to_petri), run_time=1.2)

    def _bit_6_20_dim_rubric(self) -> None:
        """10–12.5s — 4×5 grid (20 cells), tier-colored."""
        # Fade out the seed-generation interior to free the canvas.
        self.play(
            *[FadeOut(a) for a in self.agents.values()],
            FadeOut(self.outer_label),
            self.outer_box.animate.set_opacity(0.0),
            FadeOut(self.engineer),
            FadeOut(self.leaderboard_label),
            run_time=0.6,
        )

        grid = VGroup()
        tiers = (
            ["critical"] * 5 + ["auxiliary"] * 12 + ["info"] * 3
        )  # 20 dims tiered exactly as autoresearch/train.py
        for i, tier in enumerate(tiers):
            row, col = divmod(i, 5)
            fill = {
                "critical": COLOR_CRITICAL,
                "auxiliary": COLOR_PETRI,
                "info": COLOR_UNFILLED,
            }[tier]
            cell = Square(
                side_length=0.42,
                stroke_color=COLOR_ARROW,
                stroke_width=1.0,
                fill_color=fill,
                fill_opacity=0.6,
            )
            cell.shift(LEFT * 4 + DOWN * 0.5 + RIGHT * (col * 0.5) + DOWN * (row * 0.5))
            grid.add(cell)
        self.grid = grid

        new_text = _make_text(_t("bit_6"), font_size=24).move_to(UP * 3.0)
        self.play(Transform(self.speech, new_text), run_time=0.4)
        self.play(
            LaggedStart(*[FadeIn(c) for c in grid], lag_ratio=0.05),
            run_time=1.6,
        )

    def _bit_7_judge_scoring(self) -> None:
        """12.5–14.5s — each cell flashes a score (concerning-behavior 1-10)."""
        new_text = _make_text(_t("bit_7"), font_size=24).move_to(UP * 3.0)
        self.play(Transform(self.speech, new_text), run_time=0.4)

        # Synthetic scores — lower better. Critical 2-4, aux 3-6, info 5-7.
        scores = (
            [3.4, 2.8, 3.1, 2.5, 3.7]
            + [4.2, 5.1, 3.8, 4.7, 5.3, 3.9, 4.4, 5.8, 4.1, 4.9, 5.2, 3.6]
            + [5.5, 6.1, 5.8]
        )
        score_texts = []
        for cell, sc in zip(self.grid, scores):
            t = _make_text(f"{sc:.1f}", font_size=14, color=COLOR_TEXT)
            t.move_to(cell.get_center())
            score_texts.append(t)
        self.score_texts = score_texts
        self.play(
            LaggedStart(*[FadeIn(t) for t in score_texts], lag_ratio=0.04),
            run_time=1.4,
        )

    def _bit_8_dim_extractor(self) -> None:
        """14.5–16.5s — grid collapses → two dict-shaped boxes."""
        means_box = Rectangle(
            width=3.6,
            height=0.7,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_PETRI,
            fill_opacity=0.4,
        ).shift(RIGHT * 1.0 + UP * 0.5)
        means_label = _make_text(
            "dim_means: {broken_tool_use: 2.5, ...}",
            font_size=14,
            color=COLOR_TEXT,
        ).move_to(means_box.get_center())

        stderr_box = Rectangle(
            width=3.6,
            height=0.7,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_PETRI,
            fill_opacity=0.4,
        ).shift(RIGHT * 1.0 + DOWN * 0.3)
        stderr_label = _make_text(
            "dim_stderr: {broken_tool_use: 0.4, ...}",
            font_size=14,
            color=COLOR_TEXT,
        ).move_to(stderr_box.get_center())

        new_text = _make_text(_t("bit_8"), font_size=24).move_to(UP * 3.0)
        self.play(Transform(self.speech, new_text), run_time=0.4)
        self.play(
            *[FadeOut(t) for t in self.score_texts],
            *[FadeOut(c) for c in self.grid],
            run_time=0.4,
        )
        self.play(
            FadeIn(means_box),
            FadeIn(means_label),
            FadeIn(stderr_box),
            FadeIn(stderr_label),
            run_time=0.8,
        )
        self.dim_boxes = VGroup(means_box, means_label, stderr_box, stderr_label)

    # ──────────────────────────────────────────────────────────────────
    # Stage 3 — autoresearch (selection + promote)
    # ──────────────────────────────────────────────────────────────────

    def _bit_9_compute_fitness(self) -> None:
        """16.5–19s — formula + scalar fitness gauge."""
        formula = _make_text(
            "fitness = Σ wᵢ × (10 − dim_meansᵢ) / 10",
            font_size=20,
        )
        formula.shift(LEFT * 3.0 + DOWN * 1.2)
        self.formula = formula

        gauge_track = Rectangle(
            width=4.0,
            height=0.35,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_UNFILLED,
            fill_opacity=0.9,
        ).shift(RIGHT * 2.0 + DOWN * 1.2)
        gauge_fill = Rectangle(
            width=4.0 * 0.54,
            height=0.35,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_WINNER,
            fill_opacity=0.95,
        )
        gauge_fill.align_to(gauge_track, LEFT)
        gauge_fill.align_to(gauge_track, UP)
        gauge_value = _make_text("0.54", font_size=18, color=COLOR_TEXT).next_to(
            gauge_track, RIGHT, buff=0.2
        )
        self.gauge_track = gauge_track
        self.gauge_fill = gauge_fill
        self.gauge_value = gauge_value

        new_text = _make_text(_t("bit_9"), font_size=24).move_to(UP * 3.0)
        self.play(Transform(self.speech, new_text), run_time=0.4)
        self.play(Write(formula), run_time=0.8)
        self.play(Create(gauge_track), FadeIn(gauge_fill), Write(gauge_value), run_time=1.0)

    def _bit_10_critical_floor(self) -> None:
        """19–22s — 5 critical-dim bars + floor line + flash to 0.0 then recover."""
        new_text = _make_text(_t("bit_10"), font_size=24).move_to(UP * 3.0)
        self.play(Transform(self.speech, new_text), run_time=0.4)

        # 5 critical-dim bars (right side, vertical).
        bars = VGroup()
        for i in range(5):
            bar = Rectangle(
                width=0.3,
                height=1.0 + (0.4 if i == 2 else 0.0),  # bar 2 is the offender.
                stroke_color=COLOR_ARROW,
                fill_color=COLOR_CRITICAL,
                fill_opacity=0.8,
            )
            bar.shift(LEFT * 3.5 + UP * 1.5 + RIGHT * (i * 0.6))
            bars.add(bar)

        floor_y = LEFT * 3.5 + UP * 2.5 + RIGHT * 0.0  # baseline + stderr + margin
        floor_line = DashedLine(
            LEFT * 4.0 + UP * 2.3,
            LEFT * 0.5 + UP * 2.3,
            color=COLOR_CRITICAL,
            stroke_width=2,
            dash_length=0.1,
        )
        floor_label = _make_text(
            "critical floor",
            font_size=14,
            color=COLOR_CRITICAL,
        ).next_to(floor_line, RIGHT, buff=0.1)

        self.play(Create(bars), Create(floor_line), Write(floor_label), run_time=0.8)

        # Bar 2 crosses — flash gauge to 0.0.
        self.play(
            Flash(self.gauge_fill, color=COLOR_CRITICAL, flash_radius=0.5),
            self.gauge_fill.animate.stretch_to_fit_width(0.01).align_to(self.gauge_track, LEFT),
            Transform(
                self.gauge_value,
                _make_text("0.00", font_size=18, color=COLOR_CRITICAL).move_to(
                    self.gauge_value.get_center()
                ),
            ),
            run_time=0.8,
        )

        # Recovery: gate trims bar 2 back, gauge returns to 0.54.
        self.play(
            bars[2].animate.stretch_to_fit_height(1.0).shift(UP * 0.2),
            run_time=0.4,
        )
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(4.0 * 0.54).align_to(self.gauge_track, LEFT),
            Transform(
                self.gauge_value,
                _make_text("0.54", font_size=18, color=COLOR_TEXT).move_to(self.gauge_value.get_center()),
            ),
            run_time=0.6,
        )
        self.critical_bars = bars
        self.floor_line = floor_line
        self.floor_label = floor_label

    def _bit_11_auto_promote(self) -> None:
        """22–25s — discard / promote demonstration + baseline.json update."""
        new_text = _make_text(_t("bit_11"), font_size=24).move_to(UP * 3.0)
        self.play(Transform(self.speech, new_text), run_time=0.4)

        # Push gauge from 0.54 → 0.57 (delta +0.03, below threshold).
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(4.0 * 0.57).align_to(
                self.gauge_track, LEFT
            ),
            Transform(
                self.gauge_value,
                _make_text("0.57", font_size=18, color=COLOR_TEXT).move_to(self.gauge_value.get_center()),
            ),
            run_time=0.5,
        )
        discard_label = _make_text(
            _t("discard") + "  Δ=+0.03 < 0.05",
            font_size=18,
            color=COLOR_CRITICAL,
        ).next_to(self.gauge_track, DOWN, buff=0.3)
        self.play(Write(discard_label), run_time=0.4)
        self.play(FadeOut(discard_label), run_time=0.3)

        # Reset → push to 0.62 (delta +0.08 — promotes).
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(4.0 * 0.62).align_to(
                self.gauge_track, LEFT
            ),
            Transform(
                self.gauge_value,
                _make_text("0.62", font_size=18, color=COLOR_PROMOTED).move_to(
                    self.gauge_value.get_center()
                ),
            ),
            run_time=0.5,
        )
        promote_label = _make_text(
            _t("promote") + "  Δ=+0.08 > 0.05",
            font_size=18,
            color=COLOR_PROMOTED,
        ).next_to(self.gauge_track, DOWN, buff=0.3)
        self.play(
            Write(promote_label),
            self.gauge_fill.animate.set_fill(COLOR_PROMOTED, opacity=0.95),
            run_time=0.5,
        )

        # baseline.json box appears + receives the update.
        baseline_box = Rectangle(
            width=2.6,
            height=0.6,
            stroke_color=COLOR_PROMOTED,
            fill_color=COLOR_PROMOTED,
            fill_opacity=0.4,
        ).shift(RIGHT * 2.0 + UP * 0.5)
        baseline_label = _make_text(
            _t("baseline_json"), font_size=18, color=COLOR_TEXT
        ).move_to(baseline_box.get_center())
        self.baseline_box = VGroup(baseline_box, baseline_label)

        self.play(FadeIn(self.baseline_box), run_time=0.4)
        self.promote_label = promote_label

    def _bit_12_next_generation(self) -> None:
        """25–28s — wrapper-prompt mutation + cycle closure."""
        new_text = _make_text(_t("bit_12"), font_size=24).move_to(UP * 3.0)
        self.play(Transform(self.speech, new_text), run_time=0.4)

        # Wrapper-prompt sections box (5 sections, one highlighted).
        wrapper_box = VGroup(
            *[
                Rectangle(
                    width=2.4,
                    height=0.35,
                    stroke_color=COLOR_ARROW,
                    fill_color=COLOR_WINNER if i == 2 else COLOR_UNFILLED,
                    fill_opacity=0.9,
                )
                for i in range(5)
            ]
        ).arrange(DOWN, buff=0.1)
        wrapper_box.shift(LEFT * 3.5 + DOWN * 0.5)
        wrapper_label = _make_text(
            "wrapper_prompt_sections", font_size=14, color=COLOR_TEXT_ACCENT
        ).next_to(wrapper_box, UP, buff=0.15)

        self.play(FadeIn(wrapper_box), Write(wrapper_label), run_time=0.6)

        # Cycle arrow: baseline.json → wrapper_box → (implicit) seed-generation box (off-screen).
        cycle_arrow = _dashed_arrow(self.baseline_box.get_left(), wrapper_box.get_right())
        self.play(Create(cycle_arrow), run_time=0.4)

        gen_label = _make_text(
            f"{_t('gen_n')}  →  {_t('gen_n_plus_1')}",
            font_size=22,
            color=COLOR_PROMOTED,
        ).shift(DOWN * 2.8)
        self.play(Write(gen_label), run_time=0.6)
        self.wrapper_box = wrapper_box
        self.wrapper_label = wrapper_label
        self.cycle_arrow = cycle_arrow
        self.gen_label = gen_label

    # ──────────────────────────────────────────────────────────────────
    # Outro — Self-improving over generations
    # ──────────────────────────────────────────────────────────────────

    def _outro_ratchet_summary(self) -> None:
        """28–35s — all clears, fitness-over-generations ratchet chart."""
        self.play(
            *[
                FadeOut(o)
                for o in (
                    self.speech,
                    self.formula,
                    self.gauge_track,
                    self.gauge_fill,
                    self.gauge_value,
                    self.critical_bars,
                    self.floor_line,
                    self.floor_label,
                    self.dim_boxes,
                    self.petri_box,
                    self.survivors_to_petri,
                    self.leaderboard,
                    self.arrow_to_leaderboard,
                    self.baseline_box,
                    self.wrapper_box,
                    self.wrapper_label,
                    self.cycle_arrow,
                    self.gen_label,
                    self.promote_label,
                )
            ],
            run_time=0.6,
        )

        title = _make_text(_t("outro"), font_size=34, color=COLOR_TEXT).shift(UP * 3.0)
        self.play(Write(title), run_time=0.8)

        # Axes — include_numbers requires LaTeX which isn't available on
        # vanilla CI / dev installs. We render tick marks via NumberLine
        # and add axis labels separately via _make_text.
        x_axis = NumberLine(
            x_range=[0, 10, 2],
            length=8,
            color=COLOR_ARROW,
            include_numbers=False,
        ).shift(DOWN * 1.5)
        y_axis = NumberLine(
            x_range=[0, 1, 0.2],
            length=4,
            color=COLOR_ARROW,
            include_numbers=False,
            rotation=90 * 0.01745329,  # 90° in radians
        ).shift(LEFT * 4.0 + UP * 0.5)

        x_label = _make_text(_t("generations_label"), font_size=18, color=COLOR_TEXT_ACCENT).next_to(
            x_axis, DOWN, buff=0.4
        )
        y_label = _make_text(_t("fitness_label"), font_size=18, color=COLOR_TEXT_ACCENT).next_to(
            y_axis, LEFT, buff=0.3
        )

        self.play(Create(x_axis), Create(y_axis), Write(x_label), Write(y_label), run_time=0.8)

        # Plot a synthetic fitness-ratchet curve (monotonically increasing).
        fits = [0.54, 0.57, 0.62, 0.65, 0.69, 0.71, 0.74, 0.77, 0.79, 0.82]
        x0 = x_axis.number_to_point(0)
        # x_axis is on x-direction; y-axis goes vertical from the same origin shifted.
        # We position each gen i on the x-axis and lift it by fitness × 4 (y-axis length).
        dots = VGroup()
        commits = VGroup()
        connectors = VGroup()
        prev_pt = None
        for i, f in enumerate(fits):
            x_pt = x_axis.number_to_point(i + 1)
            y_lift = UP * (f * 4)
            pt = x_pt + (y_lift - UP * (0.0))  # lift relative to axis baseline
            # The y-axis baseline is at the shifted x_axis y-coordinate;
            # we simply lift from the x_axis point by f * 4 units (matches y_axis length=4).
            pt = x_pt + UP * (f * 4)
            dot = Circle(
                radius=0.08,
                color=COLOR_PROMOTED,
                fill_color=COLOR_PROMOTED,
                fill_opacity=1.0,
            ).move_to(pt)
            dots.add(dot)
            # Commit chain: dot column to the right.
            commit_dot = Circle(
                radius=0.1,
                color=COLOR_PROMOTED,
                fill_color=COLOR_WINNER,
                fill_opacity=1.0,
            ).shift(RIGHT * 5.0 + DOWN * 2.2 + UP * (i * 0.35))
            commits.add(commit_dot)
            if prev_pt is not None:
                connectors.add(Line(prev_pt, pt, color=COLOR_PROMOTED, stroke_width=2))
            prev_pt = pt

        self.play(
            LaggedStart(
                *[
                    LaggedStart(FadeIn(dot), FadeIn(commit), lag_ratio=0.0)
                    for dot, commit in zip(dots, commits)
                ],
                lag_ratio=0.18,
            ),
            run_time=2.5,
        )
        self.play(Create(connectors), run_time=0.6)
        self.wait(2.0)
