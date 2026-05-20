"""GEODE outer self-improving loop — hero visualization.

Reference: Google AI Co-Scientist hero video (830×470, 13.7s).
GEODE extends the agent-grid pattern with two downstream stages —
**Petri (measurement)** and **autoresearch (selection)** — so the
visualization walks the full Co-Scientist → Petri → autoresearch
self-improving cycle.

Layout rule (post-v2 rewrite)
=============================
A single fixed 3-zone layout keeps text and content from ever
overlapping, and stages flow strictly **left → right**:

* TITLE BAR (y ≈ 3.0–3.5) — reserved for bit text. Old title fades
  out before the new one fades in (no Transform — Transform leaves
  both visible mid-tween).
* CONTENT ZONE (y ≈ 2.5 ↓ −2.0) split into three vertical bands:
  - STAGE 1 (LEFT,   x ≈ −4.5) — Co-Scientist pattern (seed-generation)
  - STAGE 2 (CENTER, x ≈   0.0) — Petri audit (measurement)
  - STAGE 3 (RIGHT,  x ≈   4.5) — autoresearch (selection + promote)
* FOOTER (y ≈ −3.3) — three progress dots (active stage = green).

Active-stage elements render at full opacity; the prior stage dims to
30% as the narrative moves right, leaving a "trail" without clutter.
Every data-flow arrow points LEFT→RIGHT.

12-bit storyboard + 5s outro is defined in
``docs/visualizations/geode-hero-storyboard.md`` (single source of truth).

Render
======
::

    uv run manim -qh -o GeodeHero-EN scripts/visualizations/geode_hero.py GeodeSelfImprovingHero
    GEODE_HERO_LANG=ko uv run manim -qh -o GeodeHero-KO scripts/visualizations/geode_hero.py GeodeSelfImprovingHero

Outputs to ``media/videos/geode_hero/1080p60/GeodeHero-{EN,KO}.mp4``.
"""

from __future__ import annotations

import os

import math

from manim import (
    DOWN,
    LEFT,
    ORIGIN,
    RIGHT,
    UP,
    ArcBetweenPoints,
    Circle,
    Create,
    DashedLine,
    DashedVMobject,
    FadeIn,
    FadeOut,
    Flash,
    LaggedStart,
    Line,
    NumberLine,
    Polygon,
    Rectangle,
    Scene,
    Square,
    Text,
    VGroup,
    Write,
    config,
)
import numpy as np

# ───────────────────────────────────────────────────────────────────────
# Configuration
# ───────────────────────────────────────────────────────────────────────

config.background_color = "#FFFFFF"
config.frame_rate = 60

LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

# Color palette — Co-Scientist aesthetic + GEODE extensions.
COLOR_AGENT = "#F4CCCC"
COLOR_WINNER = "#A4C2F4"
COLOR_UNFILLED = "#D9D9D9"
COLOR_CRITICAL = "#E06666"
COLOR_PROMOTED = "#93C47D"
COLOR_PETRI = "#FFE599"
COLOR_ARROW = "#666666"
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"
COLOR_TRAIL = "#BBBBBB"  # dimmed stage history

# Fonts.
EN_FONT = "Helvetica"
KOR_FONT = "Apple SD Gothic Neo"

# Layout zones (Manim default frame is 14.22 × 8.0 units at 16:9).
TITLE_Y = 3.4
CONTENT_TOP = 2.5
CONTENT_BOTTOM = -2.0
FOOTER_Y = -3.3
STAGE_X = {"s1": -4.5, "s2": 0.0, "s3": 4.5}

# ───────────────────────────────────────────────────────────────────────
# EN / KO text lookup
# ───────────────────────────────────────────────────────────────────────

T: dict[str, dict[str, str]] = {
    "en": {
        "glossary_title": "Glossary",
        "glossary_terms": (
            ("Co-Scientist", "DeepMind multi-agent hypothesis generation (2025-02)"),
            ("seed-generation", "GEODE 7-agent candidate seed pipeline"),
            ("generator / proximity / critic", "S1 / S2 / S3 agents"),
            ("pilot / ranker / evolver", "S4 / S6 / S6.5 agents"),
            ("meta_reviewer", "S7 — cross-run priors generator"),
            ("Petri", "geode audit subprocess (measurement)"),
            ("dim (× 20)", "rubric axis — 5 critical / 12 auxiliary / 3 info"),
            ("dim_means / dim_stderr", "per-dim mean + standard error (1–10, lower better)"),
            ("fitness", "17-dim weighted aggregate + stability axis"),
            ("baseline.json", "promoted state snapshot"),
            ("autoresearch", "self-improving loop driver"),
            ("wrapper-prompt", "mutation target — system-prompt sections"),
            ("promote", "replace baseline when gain > max(stderr, 0.05)"),
            ("ratchet", "monotonically increasing fitness over generations"),
        ),
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
        "stage_1": "seed-generation",
        "stage_2": "Petri audit",
        "stage_3": "autoresearch",
        "agent_generator": "generator",
        "agent_proximity": "proximity",
        "agent_critic": "critic",
        "agent_pilot": "pilot",
        "agent_ranker": "ranker",
        "agent_evolver": "evolver",
        "agent_meta_reviewer": "meta_reviewer",
        "scientist_label": "Engineer",
        "survivors_label": "Survivors",
        "fitness_label": "fitness",
        "generations_label": "generation",
        "promote": "PROMOTE",
        "discard": "DISCARD",
        "baseline_json": "baseline.json",
        "gen_n": "gen N",
        "gen_n_plus_1": "gen N+1",
    },
    "ko": {
        "glossary_title": "용어집",
        "glossary_terms": (
            ("Co-Scientist", "DeepMind 의 다중 agent 가설 생성 (2025-02)"),
            ("seed-generation", "GEODE 7-agent 후보 seed 파이프라인"),
            ("generator / proximity / critic", "S1 / S2 / S3 agents"),
            ("pilot / ranker / evolver", "S4 / S6 / S6.5 agents"),
            ("meta_reviewer", "S7 — 세대 간 priors 생성"),
            ("Petri", "geode audit subprocess (측정)"),
            ("dim (× 20)", "rubric 축 — critical 5 / auxiliary 12 / info 3"),
            ("dim_means / dim_stderr", "dim 별 평균 + 표준오차 (1–10, 낮을수록 좋음)"),
            ("fitness", "17-dim 가중 합산 + stability axis"),
            ("baseline.json", "promoted state snapshot"),
            ("autoresearch", "자기 개선 루프 driver"),
            ("wrapper-prompt", "mutation 대상 — system-prompt sections"),
            ("promote", "gain > max(stderr, 0.05) 시 baseline 교체"),
            ("ratchet", "세대 간 단조 증가하는 fitness"),
        ),
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
        "stage_1": "seed-generation",
        "stage_2": "Petri audit",
        "stage_3": "autoresearch",
        "agent_generator": "generator",
        "agent_proximity": "proximity",
        "agent_critic": "critic",
        "agent_pilot": "pilot",
        "agent_ranker": "ranker",
        "agent_evolver": "evolver",
        "agent_meta_reviewer": "meta_reviewer",
        "scientist_label": "엔지니어",
        "survivors_label": "Survivors",
        "fitness_label": "fitness",
        "generations_label": "세대",
        "promote": "PROMOTE",
        "discard": "DISCARD",
        "baseline_json": "baseline.json",
        "gen_n": "세대 N",
        "gen_n_plus_1": "세대 N+1",
    },
}


def _t(key: str) -> str:
    val = T.get(LANG, T["en"]).get(key, T["en"].get(key, key))
    return val if isinstance(val, str) else str(val)


def _t_glossary_terms() -> tuple[tuple[str, str], ...]:
    """Return the active-language glossary list (term, definition) pairs."""
    val = T.get(LANG, T["en"]).get("glossary_terms", T["en"]["glossary_terms"])
    assert isinstance(val, tuple)
    return val  # type: ignore[return-value]


def _make_text(text: str, **kw) -> Text:
    font = kw.pop("font", None)
    if font is None:
        font = KOR_FONT if LANG == "ko" else EN_FONT
    kw["color"] = kw.get("color", COLOR_TEXT)
    return Text(text, font=font, **kw)


# ───────────────────────────────────────────────────────────────────────
# Shape factories
# ───────────────────────────────────────────────────────────────────────


def _agent_box(label_key: str, *, color: str = COLOR_AGENT, width: float = 1.05) -> VGroup:
    """Pink agent box. Label uses pure black for high contrast over the
    light-pink fill (O10 in text-overflow-map.md)."""
    body = Rectangle(
        width=width,
        height=0.5,
        stroke_color=COLOR_ARROW,
        stroke_width=1.2,
        fill_color=color,
        fill_opacity=0.85,
    )
    label = _make_text(_t(label_key), color=COLOR_TEXT, font_size=14)
    label.move_to(body.get_center())
    return VGroup(body, label)


def _scientist_icon(scale: float = 1.0) -> VGroup:
    head = Circle(radius=0.13 * scale, color=COLOR_WINNER, fill_color=COLOR_WINNER, fill_opacity=1.0)
    head.shift(UP * 0.2 * scale)
    body = Rectangle(
        width=0.4 * scale,
        height=0.25 * scale,
        stroke_color=COLOR_WINNER,
        fill_color=COLOR_WINNER,
        fill_opacity=1.0,
    )
    body.shift(DOWN * 0.05 * scale)
    icon = VGroup(head, body)
    label = _make_text(_t("scientist_label"), color=COLOR_TEXT, font_size=14)
    label.next_to(icon, DOWN, buff=0.08)
    return VGroup(icon, label)


def _dashed_arrow_with_head(
    start,
    end,
    *,
    color: str = COLOR_ARROW,
    head_color: str | None = None,
    head_size: float = 0.18,
    curve_angle: float = 0.0,
) -> VGroup:
    """Dashed body + filled triangle head at ``end`` — replaces plain
    ``DashedLine`` so direction is unmistakable (O3 / O7 in
    text-overflow-map.md).

    Args:
        start, end: endpoints (np.ndarray or array-like).
        color: body + head fallback color.
        head_color: optional head-only color for stage-coupled flow tinting
            (Co-Scientist → Petri uses yellow, Petri → autoresearch uses
            blue, cycle uses green).
        head_size: triangle edge length in scene units.
        curve_angle: when non-zero, body is an arc instead of a straight
            line — used by the Bit 12 cycle arrow to avoid passing over
            the dimmed STAGE 2 boxes (O6).
    """
    start_v = np.asarray(start, dtype=float)
    end_v = np.asarray(end, dtype=float)

    if abs(curve_angle) > 1e-6:
        arc = ArcBetweenPoints(
            start_v, end_v, angle=curve_angle, color=color, stroke_width=2
        )
        body = DashedVMobject(arc, num_dashes=24)
        # Tangent at the arc end — approximate by sampling the last
        # point - the one just before it.
        tail_pt = arc.point_from_proportion(0.96)
        head_anchor = end_v
    else:
        body = DashedLine(
            start_v, end_v, color=color, stroke_width=2, dash_length=0.12
        )
        tail_pt = start_v + (end_v - start_v) * 0.92
        head_anchor = end_v

    direction = head_anchor - tail_pt
    norm = float(np.linalg.norm(direction))
    if norm < 1e-6:
        unit = np.array([1.0, 0.0, 0.0])
    else:
        unit = direction / norm
    # Perpendicular (rotate 90° in the xy plane).
    perp = np.array([-unit[1], unit[0], 0.0])
    base_center = head_anchor - unit * head_size
    p1 = head_anchor
    p2 = base_center + perp * (head_size * 0.55)
    p3 = base_center - perp * (head_size * 0.55)

    tip_color = head_color or color
    head = Polygon(
        p1, p2, p3,
        color=tip_color,
        fill_color=tip_color,
        fill_opacity=1.0,
        stroke_width=1.0,
    )
    return VGroup(body, head)


# Backwards-compat alias — old callers in this file's stage methods.
def _dashed_arrow(start, end, *, color: str = COLOR_ARROW) -> VGroup:
    return _dashed_arrow_with_head(start, end, color=color)


# ───────────────────────────────────────────────────────────────────────
# Scene
# ───────────────────────────────────────────────────────────────────────


class GeodeSelfImprovingHero(Scene):
    """12-bit walkthrough of GEODE's Co-Scientist → Petri → autoresearch loop.

    State held on ``self`` so each bit method can fade/move/dim
    elements created by previous bits without re-querying the scene
    mobjects. Use the helpers ``_set_title`` / ``_set_active_stage`` /
    ``_dim`` to keep the layout rules consistent everywhere.
    """

    title: Text | None = None
    stage_dots: dict[str, Circle] | None = None
    stage_labels: dict[str, Text] | None = None

    def construct(self) -> None:
        self._setup_footer()
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
        self._final_glossary()

    # ──────────────────────────────────────────────────────────────────
    # Layout helpers
    # ──────────────────────────────────────────────────────────────────

    def _set_title(self, key: str, *, font_size: int = 26) -> None:
        """Replace the title bar text without overlap.

        Old title fades out before the new one fades in — a Transform
        leaves both visible mid-tween, which was the source of the
        text/box overlap before this rewrite.
        """
        new_title = _make_text(_t(key), font_size=font_size, color=COLOR_TEXT).move_to(
            UP * TITLE_Y
        )
        if self.title is None:
            self.play(FadeIn(new_title), run_time=0.35)
        else:
            self.play(FadeOut(self.title), run_time=0.2)
            self.play(FadeIn(new_title), run_time=0.35)
        self.title = new_title

    def _setup_footer(self) -> None:
        """Three stage dots at the footer; the active one lights green."""
        dots = {}
        labels = {}
        for i, (key, label_key) in enumerate(
            (("s1", "stage_1"), ("s2", "stage_2"), ("s3", "stage_3"))
        ):
            x = -3.5 + i * 3.5
            dot = Circle(
                radius=0.12,
                color=COLOR_ARROW,
                fill_color=COLOR_UNFILLED,
                fill_opacity=1.0,
            ).move_to(RIGHT * x + UP * FOOTER_Y)
            label = _make_text(
                _t(label_key), font_size=15, color=COLOR_TEXT_ACCENT
            ).next_to(dot, DOWN, buff=0.12)
            dots[key] = dot
            labels[key] = label
        self.stage_dots = dots
        self.stage_labels = labels
        self.play(
            *[Create(d) for d in dots.values()],
            *[FadeIn(label) for label in labels.values()],
            run_time=0.4,
        )

    def _set_active_stage(self, stage_key: str) -> None:
        """Mark one footer dot green; reset the others to unfilled."""
        assert self.stage_dots is not None
        anims = []
        for key, dot in self.stage_dots.items():
            target_fill = COLOR_PROMOTED if key == stage_key else COLOR_UNFILLED
            anims.append(dot.animate.set_fill(target_fill, opacity=1.0))
        self.play(*anims, run_time=0.3)

    def _dim(self, group: VGroup, *, opacity: float = 0.3) -> None:
        """Fade a previous-stage element to ``opacity`` (trail effect)."""
        self.play(group.animate.set_opacity(opacity), run_time=0.3)

    # ──────────────────────────────────────────────────────────────────
    # Stage 1 — Co-Scientist pattern (GEODE seed-generation, LEFT)
    # ──────────────────────────────────────────────────────────────────

    def _bit_1_engineer_goal(self) -> None:
        """Engineer icon (top-left) above STAGE 1 zone — sits in the title
        gutter so the agent grid below has clean vertical room."""
        self._set_title("bit_1")
        self._set_active_stage("s1")

        # Engineer goes between the title bar (y=3.4) and the content top
        # (y=2.5) so it never overlaps the agent box that arrives in bit 2.
        self.engineer = _scientist_icon(scale=0.9).move_to(
            RIGHT * STAGE_X["s1"] + UP * (TITLE_Y - 0.7)
        )
        self.play(FadeIn(self.engineer), run_time=0.5)

    def _bit_2_seven_agents(self) -> None:
        """7-agent grid inside the STAGE 1 LEFT zone (upper sub-region)."""
        self._set_title("bit_2")

        # Outer box enlarged to 3.7 so the agent grid (3 cols × 1.05
        # wide × 1.15 spacing = ~4.4 width effective) doesn't overflow
        # — agent boxes are now compact enough (width 1.05) to sit
        # cleanly inside (O1 in text-overflow-map.md).
        outer_box = Rectangle(
            width=3.7,
            height=2.7,
            stroke_color=COLOR_ARROW,
            stroke_width=1.5,
            fill_color="#FFFFFF",
            fill_opacity=0.0,
        ).move_to(RIGHT * STAGE_X["s1"] + UP * 0.4)

        outer_label = _make_text(
            "GEODE " + _t("stage_1"), font_size=15, color=COLOR_TEXT_ACCENT
        ).next_to(outer_box, UP, buff=0.1)

        agent_keys = (
            "agent_generator",
            "agent_proximity",
            "agent_critic",
            "agent_pilot",
            "agent_ranker",
            "agent_evolver",
            "agent_meta_reviewer",
        )
        # 3 columns × 3 rows, last row only the center cell. Col spacing
        # 1.15 + agent width 1.05 → ~0.10 visible gap between boxes,
        # no overlap (O1 in text-overflow-map.md).
        layout_offsets = (
            LEFT * 1.15 + UP * 0.8,
            ORIGIN + UP * 0.8,
            RIGHT * 1.15 + UP * 0.8,
            LEFT * 1.15,
            ORIGIN,
            RIGHT * 1.15,
            ORIGIN + DOWN * 0.8,
        )
        agents = []
        for key, offset in zip(agent_keys, layout_offsets):
            box = _agent_box(key, width=1.05)
            box.move_to(outer_box.get_center() + offset)
            agents.append(box)
        self.agents = VGroup(*agents)
        self.s1_group = VGroup(outer_box, outer_label, self.agents)

        self.play(Create(outer_box), Write(outer_label), run_time=0.5)
        self.play(LaggedStart(*[FadeIn(a) for a in agents], lag_ratio=0.1), run_time=1.4)

    def _bit_3_generate_critique_evolve(self) -> None:
        """Flash generator → critic → evolver in order."""
        self._set_title("bit_3")
        for key in ("agent_generator", "agent_critic", "agent_evolver"):
            # The box-list indexes line up with the agent_keys order above.
            idx = {
                "agent_generator": 0,
                "agent_proximity": 1,
                "agent_critic": 2,
                "agent_pilot": 3,
                "agent_ranker": 4,
                "agent_evolver": 5,
                "agent_meta_reviewer": 6,
            }[key]
            self.play(Flash(self.agents[idx], color=COLOR_WINNER, flash_radius=0.5), run_time=0.4)

    def _bit_4_tournament_survivors(self) -> None:
        """Survivors leaderboard appears below the agent grid (still STAGE 1)."""
        self._set_title("bit_4")

        # Width 1.6 (was 1.4) — comfortably wider than the "Survivors"
        # label so it always sits centered above without visual cut
        # (O2 in text-overflow-map.md).
        leaderboard = VGroup(
            *[
                Rectangle(
                    width=1.6,
                    height=0.22,
                    stroke_color=COLOR_ARROW,
                    stroke_width=1.0,
                    fill_color=COLOR_UNFILLED,
                    fill_opacity=0.9,
                )
                for _ in range(5)
            ]
        ).arrange(DOWN, buff=0.06)
        # Position below the agent grid (which now ends ~y = -0.95) with a
        # clear vertical gap before the footer (y = -3.3).
        leaderboard.move_to(RIGHT * STAGE_X["s1"] + DOWN * 2.0)
        leaderboard_label = _make_text(
            _t("survivors_label"), font_size=14, color=COLOR_TEXT_ACCENT
        ).next_to(leaderboard, UP, buff=0.1)
        self.leaderboard = leaderboard
        self.leaderboard_label = leaderboard_label

        # Dim the upper grid so it doesn't compete visually.
        self._dim(self.s1_group, opacity=0.45)

        self.play(Create(leaderboard), Write(leaderboard_label), run_time=0.6)
        for i in range(3):
            self.play(
                leaderboard[i].animate.set_fill(COLOR_WINNER, opacity=0.9),
                run_time=0.25,
            )

    # ──────────────────────────────────────────────────────────────────
    # Stage 2 — Petri audit (CENTER)
    # ──────────────────────────────────────────────────────────────────

    def _bit_5_to_petri(self) -> None:
        """Arrow from STAGE 1 leaderboard → STAGE 2 Petri box (CENTER)."""
        self._set_title("bit_5")
        # Dim entire stage-1 group to trail-grey.
        self._dim(self.s1_group, opacity=0.3)
        self._dim(VGroup(self.leaderboard, self.leaderboard_label), opacity=0.5)
        self._set_active_stage("s2")

        petri_box = Rectangle(
            width=3.0,
            height=1.0,
            stroke_color=COLOR_ARROW,
            stroke_width=1.5,
            fill_color=COLOR_PETRI,
            fill_opacity=0.85,
        ).move_to(RIGHT * STAGE_X["s2"] + UP * (CONTENT_TOP - 0.5))
        petri_label = _make_text(
            "Petri (geode audit)", font_size=18, color=COLOR_TEXT
        ).move_to(petri_box.get_center())
        self.petri_box = VGroup(petri_box, petri_label)

        # Yellow head = Petri-bound flow (O8 stage-coupled coloring).
        survivors_to_petri = _dashed_arrow_with_head(
            self.leaderboard.get_right() + RIGHT * 0.1,
            petri_box.get_left() + LEFT * 0.1,
            head_color=COLOR_PETRI,
        )
        self.survivors_to_petri = survivors_to_petri

        self.play(Create(petri_box), Write(petri_label), run_time=0.6)
        self.play(Create(survivors_to_petri), run_time=0.5)

    def _bit_6_20_dim_rubric(self) -> None:
        """4×5 grid (20 dims) below the Petri box, tier-colored."""
        self._set_title("bit_6")

        grid = VGroup()
        tiers = ["critical"] * 5 + ["auxiliary"] * 12 + ["info"] * 3
        for i, tier in enumerate(tiers):
            row, col = divmod(i, 5)
            fill = {
                "critical": COLOR_CRITICAL,
                "auxiliary": COLOR_PETRI,
                "info": COLOR_UNFILLED,
            }[tier]
            cell = Square(
                side_length=0.32,
                stroke_color=COLOR_ARROW,
                stroke_width=1.0,
                fill_color=fill,
                fill_opacity=0.6,
            )
            cell.shift(
                RIGHT * (STAGE_X["s2"] - 0.7 + col * 0.35)
                + UP * (0.3 - row * 0.35)
            )
            grid.add(cell)
        self.grid = grid

        self.play(LaggedStart(*[FadeIn(c) for c in grid], lag_ratio=0.04), run_time=1.4)

    def _bit_7_judge_scoring(self) -> None:
        """Each cell flashes a 1-10 score (lower is better)."""
        self._set_title("bit_7")

        scores = (
            [3.4, 2.8, 3.1, 2.5, 3.7]
            + [4.2, 5.1, 3.8, 4.7, 5.3, 3.9, 4.4, 5.8, 4.1, 4.9, 5.2, 3.6]
            + [5.5, 6.1, 5.8]
        )
        score_texts = []
        for cell, sc in zip(self.grid, scores):
            t = _make_text(f"{sc:.1f}", font_size=11, color=COLOR_TEXT).move_to(cell.get_center())
            score_texts.append(t)
        self.score_texts = score_texts
        self.play(
            LaggedStart(*[FadeIn(t) for t in score_texts], lag_ratio=0.03),
            run_time=1.2,
        )

    def _bit_8_dim_extractor(self) -> None:
        """Grid collapses; two dict-shaped boxes appear below it (still STAGE 2)."""
        self._set_title("bit_8")

        # Width 3.4 (was 3.0) + font 10 (was 11) — the per-dim dict
        # literal now has 0.2 unit padding on each side, no left/right
        # edge contact (O4 in text-overflow-map.md).
        means_box = Rectangle(
            width=3.4,
            height=0.45,
            stroke_color=COLOR_ARROW,
            stroke_width=1.0,
            fill_color=COLOR_PETRI,
            fill_opacity=0.4,
        ).move_to(RIGHT * STAGE_X["s2"] + DOWN * 0.6)
        means_label = _make_text(
            "dim_means: {broken_tool_use: 2.5, …}",
            font_size=10,
            color=COLOR_TEXT,
        ).move_to(means_box.get_center())
        stderr_box = Rectangle(
            width=3.4,
            height=0.45,
            stroke_color=COLOR_ARROW,
            stroke_width=1.0,
            fill_color=COLOR_PETRI,
            fill_opacity=0.4,
        ).move_to(RIGHT * STAGE_X["s2"] + DOWN * 1.15)
        stderr_label = _make_text(
            "dim_stderr: {broken_tool_use: 0.4, …}",
            font_size=10,
            color=COLOR_TEXT,
        ).move_to(stderr_box.get_center())

        self.play(
            *[FadeOut(t) for t in self.score_texts],
            *[FadeOut(c) for c in self.grid],
            run_time=0.4,
        )
        self.dim_boxes = VGroup(means_box, means_label, stderr_box, stderr_label)
        self.play(FadeIn(self.dim_boxes), run_time=0.6)

    # ──────────────────────────────────────────────────────────────────
    # Stage 3 — autoresearch (RIGHT)
    # ──────────────────────────────────────────────────────────────────

    def _bit_9_compute_fitness(self) -> None:
        """Formula + gauge appear in the STAGE 3 RIGHT zone."""
        self._set_title("bit_9")
        # Dim stage-2 elements to history trail.
        self._dim(VGroup(self.petri_box, self.dim_boxes, self.survivors_to_petri), opacity=0.35)
        self._set_active_stage("s3")

        # Blue head = autoresearch-bound flow.
        s2_to_s3 = _dashed_arrow_with_head(
            self.dim_boxes.get_right() + RIGHT * 0.1,
            RIGHT * (STAGE_X["s3"] - 1.6) + UP * (CONTENT_TOP - 1.2),
            head_color=COLOR_WINNER,
        )
        self.s2_to_s3 = s2_to_s3
        self.play(Create(s2_to_s3), run_time=0.4)

        formula = _make_text(
            "fitness = Σ wᵢ × (10 − dim_meansᵢ) / 10",
            font_size=14,
            color=COLOR_TEXT_ACCENT,
        ).move_to(RIGHT * STAGE_X["s3"] + UP * (CONTENT_TOP - 0.2))
        self.formula = formula

        gauge_track = Rectangle(
            width=2.6,
            height=0.3,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_UNFILLED,
            fill_opacity=0.9,
        ).move_to(RIGHT * STAGE_X["s3"] + UP * 0.6)
        gauge_fill = Rectangle(
            width=2.6 * 0.54,
            height=0.3,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_WINNER,
            fill_opacity=0.95,
        )
        gauge_fill.align_to(gauge_track, LEFT)
        gauge_fill.align_to(gauge_track, UP)
        gauge_value = _make_text("0.54", font_size=14, color=COLOR_TEXT).next_to(
            gauge_track, DOWN, buff=0.1
        )
        self.gauge_track = gauge_track
        self.gauge_fill = gauge_fill
        self.gauge_value = gauge_value

        self.play(Write(formula), run_time=0.6)
        self.play(Create(gauge_track), FadeIn(gauge_fill), Write(gauge_value), run_time=0.8)

    def _bit_10_critical_floor(self) -> None:
        """Critical-dim bars + floor line; demo a regression collapse + recovery."""
        self._set_title("bit_10")

        bars_origin = RIGHT * STAGE_X["s3"] + DOWN * 0.5
        bars = VGroup()
        for i in range(5):
            bar = Rectangle(
                width=0.22,
                height=0.5 + (0.3 if i == 2 else 0.0),
                stroke_color=COLOR_ARROW,
                stroke_width=0.8,
                fill_color=COLOR_CRITICAL,
                fill_opacity=0.85,
            )
            # Anchor the bottom of each bar on the same y-baseline.
            bar.move_to(bars_origin + RIGHT * (-1.0 + i * 0.4))
            bars.add(bar)
        floor_line = DashedLine(
            bars_origin + LEFT * 1.3 + UP * 0.05,
            bars_origin + RIGHT * 1.3 + UP * 0.05,
            color=COLOR_CRITICAL,
            stroke_width=2,
            dash_length=0.08,
        )
        floor_label = _make_text(
            "critical floor", font_size=11, color=COLOR_CRITICAL
        ).next_to(floor_line, RIGHT, buff=0.05)

        self.play(Create(bars), Create(floor_line), Write(floor_label), run_time=0.7)

        # bar 2 crosses — gauge slams to 0.0.
        self.play(
            Flash(self.gauge_fill, color=COLOR_CRITICAL, flash_radius=0.4),
            self.gauge_fill.animate.stretch_to_fit_width(0.01).align_to(self.gauge_track, LEFT),
            FadeOut(self.gauge_value),
            run_time=0.5,
        )
        zero_value = _make_text("0.00", font_size=14, color=COLOR_CRITICAL).next_to(
            self.gauge_track, DOWN, buff=0.1
        )
        self.play(FadeIn(zero_value), run_time=0.2)

        # Recovery — bar 2 trimmed below floor; gauge restored.
        self.play(
            bars[2].animate.stretch_to_fit_height(0.5).align_to(bars[0], DOWN),
            run_time=0.4,
        )
        new_value = _make_text("0.54", font_size=14, color=COLOR_TEXT).next_to(
            self.gauge_track, DOWN, buff=0.1
        )
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(2.6 * 0.54).align_to(
                self.gauge_track, LEFT
            ),
            FadeOut(zero_value),
            FadeIn(new_value),
            run_time=0.5,
        )
        self.gauge_value = new_value
        self.critical_bars = bars
        self.floor_line = floor_line
        self.floor_label = floor_label

    def _bit_11_auto_promote(self) -> None:
        """DISCARD then PROMOTE demo; baseline.json box turns green."""
        self._set_title("bit_11")

        # Δ +0.03 < 0.05 → DISCARD.
        delta_label = _make_text(
            "Δ +0.03 < 0.05  ✗",
            font_size=14,
            color=COLOR_CRITICAL,
        ).next_to(self.gauge_track, UP, buff=0.4)
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(2.6 * 0.57).align_to(
                self.gauge_track, LEFT
            ),
            FadeIn(delta_label),
            run_time=0.5,
        )
        self.play(FadeOut(delta_label), run_time=0.3)

        # Δ +0.08 > 0.05 → PROMOTE.
        delta_label_2 = _make_text(
            "Δ +0.08 > 0.05  ✓",
            font_size=14,
            color=COLOR_PROMOTED,
        ).next_to(self.gauge_track, UP, buff=0.4)
        new_value = _make_text("0.62", font_size=14, color=COLOR_PROMOTED).next_to(
            self.gauge_track, DOWN, buff=0.1
        )
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(2.6 * 0.62)
            .align_to(self.gauge_track, LEFT)
            .set_fill(COLOR_PROMOTED, opacity=0.95),
            FadeOut(self.gauge_value),
            FadeIn(new_value),
            FadeIn(delta_label_2),
            run_time=0.6,
        )
        self.gauge_value = new_value

        baseline_box = Rectangle(
            width=2.4,
            height=0.5,
            stroke_color=COLOR_PROMOTED,
            stroke_width=1.5,
            fill_color=COLOR_PROMOTED,
            fill_opacity=0.4,
        ).move_to(RIGHT * STAGE_X["s3"] + DOWN * 1.6)
        baseline_label = _make_text(
            _t("baseline_json"), font_size=14, color=COLOR_TEXT
        ).move_to(baseline_box.get_center())
        self.baseline_box = VGroup(baseline_box, baseline_label)
        self.play(FadeIn(self.baseline_box), run_time=0.5)
        self.promote_label = delta_label_2

    def _bit_12_next_generation(self) -> None:
        """Cycle-closure arrow: STAGE 3 baseline.json → STAGE 1 agent grid."""
        self._set_title("bit_12")

        # Cycle arrow sweeps right→bottom→left as a downward arc so it
        # doesn't pass over the dimmed STAGE 2 elements (O6 in
        # text-overflow-map.md). Green head = promote-driven cycle.
        cycle_arrow = _dashed_arrow_with_head(
            self.baseline_box.get_bottom() + DOWN * 0.05,
            RIGHT * STAGE_X["s1"] + UP * (FOOTER_Y + 0.6),
            color=COLOR_PROMOTED,
            head_color=COLOR_PROMOTED,
            curve_angle=math.pi / 3,
        )
        gen_label = _make_text(
            f"{_t('gen_n')} → {_t('gen_n_plus_1')}",
            font_size=18,
            color=COLOR_PROMOTED,
        ).move_to(ORIGIN + DOWN * 2.6)
        self.cycle_arrow = cycle_arrow
        self.gen_label = gen_label

        self.play(Create(cycle_arrow), run_time=0.7)
        self.play(Write(gen_label), run_time=0.5)

        # Briefly re-highlight stage 1 (loop closure) — re-light the agent grid.
        self._set_active_stage("s1")
        self.play(self.s1_group.animate.set_opacity(0.85), run_time=0.4)

    # ──────────────────────────────────────────────────────────────────
    # Outro — Self-improving over generations
    # ──────────────────────────────────────────────────────────────────

    def _outro_ratchet_summary(self) -> None:
        """Clear canvas; fitness-over-generations ratchet chart."""
        to_clear = [
            self.engineer,
            self.s1_group,
            self.leaderboard,
            self.leaderboard_label,
            self.petri_box,
            self.survivors_to_petri,
            self.dim_boxes,
            self.s2_to_s3,
            self.formula,
            self.gauge_track,
            self.gauge_fill,
            self.gauge_value,
            self.critical_bars,
            self.floor_line,
            self.floor_label,
            self.baseline_box,
            self.cycle_arrow,
            self.gen_label,
            self.promote_label,
        ]
        # Also drop the footer dots + labels — the chart is the whole
        # story now.
        assert self.stage_dots is not None
        assert self.stage_labels is not None
        to_clear.extend(self.stage_dots.values())
        to_clear.extend(self.stage_labels.values())
        self.play(*[FadeOut(m) for m in to_clear if m is not None], run_time=0.6)

        # Title.
        if self.title is not None:
            self.play(FadeOut(self.title), run_time=0.3)
        outro_title = _make_text(
            _t("outro"), font_size=34, color=COLOR_TEXT
        ).move_to(UP * TITLE_Y)
        self.play(FadeIn(outro_title), run_time=0.6)

        # Axes.
        x_axis = NumberLine(
            x_range=[0, 10, 2], length=8, color=COLOR_ARROW, include_numbers=False
        ).shift(DOWN * 1.5)
        y_axis = NumberLine(
            x_range=[0, 1, 0.2],
            length=4,
            color=COLOR_ARROW,
            include_numbers=False,
            rotation=90 * 0.01745329,
        ).shift(LEFT * 4.0 + UP * 0.5)
        x_label = _make_text(
            _t("generations_label"), font_size=16, color=COLOR_TEXT_ACCENT
        ).next_to(x_axis, DOWN, buff=0.3)
        y_label = _make_text(
            _t("fitness_label"), font_size=16, color=COLOR_TEXT_ACCENT
        ).next_to(y_axis, LEFT, buff=0.25)
        self.play(
            Create(x_axis), Create(y_axis), Write(x_label), Write(y_label), run_time=0.7
        )

        # Plot.
        fits = [0.54, 0.57, 0.62, 0.65, 0.69, 0.71, 0.74, 0.77, 0.79, 0.82]
        dots = VGroup()
        commits = VGroup()
        connectors = VGroup()
        prev_pt = None
        for i, f in enumerate(fits):
            x_pt = x_axis.number_to_point(i + 1)
            pt = x_pt + UP * (f * 4)
            dot = Circle(
                radius=0.07, color=COLOR_PROMOTED, fill_color=COLOR_PROMOTED, fill_opacity=1.0
            ).move_to(pt)
            dots.add(dot)
            commit_dot = Circle(
                radius=0.08, color=COLOR_PROMOTED, fill_color=COLOR_WINNER, fill_opacity=1.0
            ).shift(RIGHT * 5.5 + DOWN * 2.0 + UP * (i * 0.28))
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

        # Stash for the glossary transition.
        self._outro_artifacts = VGroup(
            outro_title, x_axis, y_axis, x_label, y_label, dots, commits, connectors
        )

    # ──────────────────────────────────────────────────────────────────
    # Final — Glossary
    # ──────────────────────────────────────────────────────────────────

    def _final_glossary(self) -> None:
        """Two-column term/definition table — closes the video (O9 in
        text-overflow-map.md). Holds 5s so viewers can read."""
        # Fade outro chart so the glossary owns the canvas.
        if hasattr(self, "_outro_artifacts"):
            self.play(FadeOut(self._outro_artifacts), run_time=0.5)

        title = _make_text(_t("glossary_title"), font_size=34, color=COLOR_TEXT).move_to(
            UP * TITLE_Y
        )
        self.play(FadeIn(title), run_time=0.5)

        rows: list[VGroup] = []
        terms = _t_glossary_terms()
        # Two columns: term (left, accented) + definition (right, gray).
        # 14 terms; vertical band y = 2.7 → -2.7. 14 rows → step 0.39.
        top_y = 2.7
        step = (top_y - (-2.7)) / max(len(terms) - 1, 1)
        for i, (term, definition) in enumerate(terms):
            y = top_y - step * i
            term_text = _make_text(
                term, font_size=16, color=COLOR_TEXT
            ).move_to(LEFT * 4.0 + UP * y).align_to(LEFT * 6.0, LEFT)
            def_text = _make_text(
                definition, font_size=14, color=COLOR_TEXT_ACCENT
            ).move_to(RIGHT * 0.5 + UP * y).align_to(LEFT * 1.0, LEFT)
            rows.append(VGroup(term_text, def_text))

        self.play(
            LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.08),
            run_time=2.0,
        )
        self.wait(5.0)
