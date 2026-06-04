"""Karpathy autoresearch ↔ GEODE autoresearch — side-by-side visualization.

Reference doc: ``docs/visualizations/autoresearch-comparison.md`` (text SoT).
This scene renders the same mapping as a hero-style video so the
diff can be read without parsing markdown tables.

Layout
======
Two columns persist for the whole video:

* LEFT — Karpathy ``autoresearch`` (MIT, 2026-03) — `fineweb` GPT
  pre-training panel.
* RIGHT — GEODE ``autoresearch/`` — alignment-audit driver panel.

Bits walk through three sections:

1. **Direct copies** — items both sides share (dashed bridge between
   identical labels).
2. **Domain swap** — same slot, different content (e.g.
   `train.py: Muon + AdamW` vs `train.py: TARGET_KINDS (7 scaffold surfaces)`).
3. **Additions** — GEODE-only items appearing only on the right
   panel with a green "+ ADD" badge.

Render
======
::

    uv run manim -qh -o AutoresearchCompare-EN scripts/visualizations/autoresearch_compare.py AutoresearchCompare
    GEODE_HERO_LANG=ko uv run manim -qh -o AutoresearchCompare-KO scripts/visualizations/autoresearch_compare.py AutoresearchCompare
"""

from __future__ import annotations

import os

from manim import (
    DOWN,
    LEFT,
    NORMAL,
    RIGHT,
    UP,
    Circle,
    Create,
    DashedLine,
    FadeIn,
    FadeOut,
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

COLOR_BORROW = "#A4C2F4"  # blue — shared / copied verbatim
COLOR_SWAP = "#FFE599"  # yellow — same slot, swapped content
COLOR_ADD = "#93C47D"  # green — GEODE-only addition
COLOR_KARPATHY = "#F4CCCC"  # light pink — Karpathy panel fill
COLOR_GEODE = "#D5E8D4"  # very light green — GEODE panel fill
COLOR_ARROW = "#666666"
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"

EN_FONT = "Helvetica Neue"
KOR_FONT = "Pretendard"

T = {
    "en": {
        "title": "Karpathy autoresearch  ↔  GEODE autoresearch",
        "karpathy_label": "Karpathy autoresearch  (MIT, 2026-03)",
        "karpathy_sub": "GPT pre-training · val_bpb · Muon",
        "geode_label": "GEODE autoresearch  (in this repo)",
        "geode_sub": "alignment audit · fitness · Petri rubric",
        "bit_1_title": "Section 1 — Direct copies (verbatim)",
        "bit_2_title": "Section 2 — Domain swap (same slot, swapped content)",
        "bit_3_title": "Section 3 — GEODE-only additions",
        "outro_main": "Borrow the scaffold, swap the domain, add the safety layer.",
        "outro_sub": "8 verbatim · 7 swapped · 11 added — full table at docs/visualizations/autoresearch-comparison.md",
        "copies": (
            "3-file shape (prepare.py / train.py / program.md)",
            "fixed 5-min wall-clock budget per run",
            "agent edits train.py only",
            "git-as-optimiser idiom (branch tip = best)",
            "one-shot per invocation",
            "read-only harness (prepare.py immutable)",
            "self-contained, minimal external deps",
        ),
        "swaps": (
            ("model + optimizer", "TARGET_KINDS (7 scaffold surfaces)"),
            ("val_bpb (lower = better)", "fitness scalar (higher = better)"),
            ("Muon + AdamW gradient descent", "no optimiser (discrete prompt mutation)"),
            ("fineweb download + BPE tokenizer", "Petri seed pool + AlphaEval rubric"),
            ("val_bpb decreased → keep", "gain > max(σ·√(σp²+σc²), 0.005)"),
        ),
        "additions": (
            "Multi-objective tiered scoring (5 critical + 10 auxiliary + 3 info)",
            "Critical floor — fitness collapses to 0.0 on any safety regression",
            "Auxiliary squared penalty for soft drift",
            "Stability axis — 1 / (1 + mean(stderr))",
            "baseline.json snapshot on every promote",
            "Cross-run priors via meta_review.json + symlink",
            "seed-generation 7-agent sub-loop (Co-Scientist pattern)",
            "Petri-side measurement separated from autoresearch selection",
            "RunTranscript structured events (cost_divergence, baseline_decision, …)",
            "USD / quota tracking — irrelevant for local GPU, mandatory for LLM API",
            "latest_seed_pool symlink — seed-gen → autoresearch handoff",
        ),
    },
    "ko": {
        "title": "Karpathy autoresearch  ↔  GEODE autoresearch",
        "karpathy_label": "Karpathy autoresearch  (MIT, 2026-03)",
        "karpathy_sub": "GPT pre-training · val_bpb · Muon",
        "geode_label": "GEODE autoresearch  (본 repo)",
        "geode_sub": "alignment audit · fitness · Petri rubric",
        "bit_1_title": "Section 1 — 그대로 차용",
        "bit_2_title": "Section 2 — 도메인 교체 (같은 자리, 다른 내용)",
        "bit_3_title": "Section 3 — GEODE 단독 추가",
        "outro_main": "스캐폴드는 차용, 도메인은 교체, 안전성 레이어는 추가.",
        "outro_sub": "8 verbatim · 7 swapped · 11 added — 전체 표는 docs/visualizations/autoresearch-comparison.md",
        "copies": (
            "3-file 구조 (prepare.py / train.py / program.md)",
            "1 회당 고정 5-min wall-clock budget",
            "agent 는 train.py 만 수정",
            "git-as-optimiser (branch tip = 최선)",
            "1 회 invocation = 1 실험",
            "read-only harness (prepare.py 불변)",
            "self-contained, 최소 외부 의존",
        ),
        "swaps": (
            ("model + optimizer", "TARGET_KINDS (7 scaffold surfaces)"),
            ("val_bpb (낮을수록 좋음)", "fitness scalar (높을수록 좋음)"),
            ("Muon + AdamW gradient descent", "옵티마이저 없음 (이산 prompt mutation)"),
            ("fineweb download + BPE tokenizer", "Petri seed pool + AlphaEval rubric"),
            ("val_bpb 감소 → keep", "gain > max(σ·√(σp²+σc²), 0.005)"),
        ),
        "additions": (
            "다목적 tiered scoring (critical 5 + auxiliary 10 + info 3)",
            "Critical floor — 안전성 axis 회귀 시 fitness 0.0 으로 붕괴",
            "Auxiliary 제곱 penalty (soft drift)",
            "Stability axis — 1 / (1 + mean(stderr))",
            "baseline.json snapshot — 매 promote 시 갱신",
            "Cross-run priors — meta_review.json + symlink",
            "seed-generation 7-agent 서브 루프 (Co-Scientist 패턴)",
            "Petri 측정 layer 가 autoresearch 선택 layer 와 분리",
            "RunTranscript 구조화 event (cost_divergence, baseline_decision 등)",
            "USD/quota tracking — local GPU 엔 불필요, LLM API 엔 필수",
            "latest_seed_pool symlink — seed-gen → autoresearch handoff",
        ),
    },
}


def _t(key):
    return T.get(LANG, T["en"]).get(key, T["en"].get(key, key))


def _make_text(text: str, **kw) -> Text:
    font = kw.pop("font", None)
    if font is None:
        font = KOR_FONT if LANG == "ko" else EN_FONT
    kw.setdefault("color", COLOR_TEXT)
    kw.setdefault("weight", NORMAL)
    return Text(text, font=font, **kw)


PANEL_HEIGHT = 4.8
PANEL_WIDTH = 6.0
PANEL_Y = -0.4
LEFT_X = -3.6
RIGHT_X = 3.6
TITLE_Y = 3.4
SECTION_TITLE_Y = 2.55


class AutoresearchCompare(Scene):
    def construct(self) -> None:
        self._build_persistent_panels()
        self._bit_1_direct_copies()
        self._bit_2_domain_swap()
        self._bit_3_additions()
        self._outro()

    def _build_persistent_panels(self) -> None:
        title = _make_text(_t("title"), font_size=28, color=COLOR_TEXT).move_to(UP * TITLE_Y)
        self.play(FadeIn(title), run_time=0.5)
        self.title = title

        left_panel = Rectangle(
            width=PANEL_WIDTH,
            height=PANEL_HEIGHT,
            stroke_color=COLOR_ARROW,
            stroke_width=1.5,
            fill_color=COLOR_KARPATHY,
            fill_opacity=0.18,
        ).move_to(LEFT * abs(LEFT_X) + UP * PANEL_Y)
        right_panel = Rectangle(
            width=PANEL_WIDTH,
            height=PANEL_HEIGHT,
            stroke_color=COLOR_ARROW,
            stroke_width=1.5,
            fill_color=COLOR_GEODE,
            fill_opacity=0.18,
        ).move_to(RIGHT * RIGHT_X + UP * PANEL_Y)
        left_label = _make_text(_t("karpathy_label"), font_size=16, color=COLOR_TEXT).next_to(
            left_panel, UP, buff=0.1
        )
        right_label = _make_text(_t("geode_label"), font_size=16, color=COLOR_TEXT).next_to(
            right_panel, UP, buff=0.1
        )
        left_sub = _make_text(_t("karpathy_sub"), font_size=12, color=COLOR_TEXT_ACCENT).next_to(
            left_panel, DOWN, buff=0.15
        )
        right_sub = _make_text(_t("geode_sub"), font_size=12, color=COLOR_TEXT_ACCENT).next_to(
            right_panel, DOWN, buff=0.15
        )

        self.left_panel = left_panel
        self.right_panel = right_panel
        self.left_label = left_label
        self.right_label = right_label
        self.left_sub = left_sub
        self.right_sub = right_sub

        self.play(
            Create(left_panel),
            Create(right_panel),
            FadeIn(left_label),
            FadeIn(right_label),
            FadeIn(left_sub),
            FadeIn(right_sub),
            run_time=0.8,
        )

    def _set_section_title(self, key: str) -> None:
        new_title = _make_text(_t(key), font_size=20, color=COLOR_TEXT_ACCENT).move_to(
            UP * SECTION_TITLE_Y
        )
        if hasattr(self, "_section_title") and self._section_title is not None:
            self.play(FadeOut(self._section_title), run_time=0.2)
        self.play(FadeIn(new_title), run_time=0.3)
        self._section_title = new_title

    def _clear_panels(self) -> None:
        """Wipe everything inside both panels before the next section."""
        if hasattr(self, "_panel_contents"):
            self.play(FadeOut(self._panel_contents), run_time=0.3)
        self._panel_contents = VGroup()

    def _bit_1_direct_copies(self) -> None:
        """7 items appear identically in both panels, joined by dashed bridge."""
        self._set_section_title("bit_1_title")
        self._panel_contents = VGroup()

        copies = T.get(LANG, T["en"])["copies"]
        rows = []
        for i, item in enumerate(copies):
            y = 1.6 - i * 0.45
            # Identical text on both sides.
            text_l = _make_text(item, font_size=11, color=COLOR_TEXT).move_to(
                LEFT * abs(LEFT_X) + UP * y
            )
            text_r = _make_text(item, font_size=11, color=COLOR_TEXT).move_to(
                RIGHT * RIGHT_X + UP * y
            )
            # Dashed bridge connecting the two — signals "same".
            bridge = DashedLine(
                text_l.get_right() + RIGHT * 0.15,
                text_r.get_left() + LEFT * 0.15,
                color=COLOR_BORROW,
                stroke_width=1.5,
                dash_length=0.1,
            )
            badge = _make_text("=", font_size=14, color=COLOR_BORROW).move_to(
                (text_l.get_right() + text_r.get_left()) / 2
            )
            row = VGroup(text_l, text_r, bridge, badge)
            rows.append(row)

        self.play(
            LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.12),
            run_time=2.0,
        )
        self._panel_contents = VGroup(*rows)
        self.wait(2.0)

    def _bit_2_domain_swap(self) -> None:
        """Same slot, swapped content — left vs right text differ; ⇄ badge."""
        self._clear_panels()
        self._set_section_title("bit_2_title")

        swaps = T.get(LANG, T["en"])["swaps"]
        rows = []
        for i, (l_text, r_text) in enumerate(swaps):
            y = 1.6 - i * 0.55
            text_l = _make_text(l_text, font_size=11, color=COLOR_TEXT).move_to(
                LEFT * abs(LEFT_X) + UP * y
            )
            text_r = _make_text(r_text, font_size=11, color=COLOR_TEXT).move_to(
                RIGHT * RIGHT_X + UP * y
            )
            arrow = DashedLine(
                text_l.get_right() + RIGHT * 0.15,
                text_r.get_left() + LEFT * 0.15,
                color=COLOR_SWAP,
                stroke_width=1.8,
                dash_length=0.1,
            )
            badge = _make_text("⇄", font_size=18, color="#B45F06").move_to(
                (text_l.get_right() + text_r.get_left()) / 2
            )
            row = VGroup(text_l, text_r, arrow, badge)
            rows.append(row)

        self.play(
            LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.14),
            run_time=2.0,
        )
        self._panel_contents = VGroup(*rows)
        self.wait(2.5)

    def _bit_3_additions(self) -> None:
        """GEODE-only items — only the right panel populates; "+ ADD" badge."""
        self._clear_panels()
        self._set_section_title("bit_3_title")

        additions = T.get(LANG, T["en"])["additions"]
        rows = []
        # 11 items — line spacing tight so they all fit. Two-line wrap is
        # accepted by Text when the source is short enough.
        for i, item in enumerate(additions):
            y = 1.85 - i * 0.36
            # Strikethrough/dimmed placeholder on the Karpathy side.
            stub = _make_text("—", font_size=14, color=COLOR_TEXT_ACCENT).move_to(
                LEFT * abs(LEFT_X) + UP * y
            )
            text_r = _make_text(item, font_size=10, color=COLOR_TEXT).move_to(
                RIGHT * RIGHT_X + UP * y
            )
            badge = _make_text("+", font_size=18, color=COLOR_ADD, weight=NORMAL).move_to(
                LEFT * 0.0 + UP * y
            )
            arrow = DashedLine(
                LEFT * 0.4 + UP * y,
                text_r.get_left() + LEFT * 0.15,
                color=COLOR_ADD,
                stroke_width=1.5,
                dash_length=0.08,
            )
            row = VGroup(stub, text_r, badge, arrow)
            rows.append(row)

        self.play(
            LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.08),
            run_time=2.2,
        )
        self._panel_contents = VGroup(*rows)
        self.wait(3.0)

    def _outro(self) -> None:
        # Fade panels + section title to centre the takeaway.
        to_clear = [
            self.left_panel,
            self.right_panel,
            self.left_label,
            self.right_label,
            self.left_sub,
            self.right_sub,
            self._section_title,
        ]
        if hasattr(self, "_panel_contents"):
            to_clear.append(self._panel_contents)
        self.play(*[FadeOut(m) for m in to_clear if m is not None], run_time=0.5)

        main = _make_text(_t("outro_main"), font_size=26, color=COLOR_TEXT).move_to(UP * 0.3)
        sub = _make_text(_t("outro_sub"), font_size=14, color=COLOR_TEXT_ACCENT).next_to(
            main, DOWN, buff=0.4
        )
        # Three colored dots — one per section badge — anchor the takeaway.
        dots = VGroup(
            Circle(radius=0.08, color=COLOR_BORROW, fill_color=COLOR_BORROW, fill_opacity=1.0),
            Circle(radius=0.08, color=COLOR_SWAP, fill_color=COLOR_SWAP, fill_opacity=1.0),
            Circle(radius=0.08, color=COLOR_ADD, fill_color=COLOR_ADD, fill_opacity=1.0),
        ).arrange(RIGHT, buff=0.4)
        dots.next_to(sub, DOWN, buff=0.5)

        self.play(FadeIn(main), run_time=0.6)
        self.play(FadeIn(sub), FadeIn(dots), run_time=0.6)
        self.wait(3.0)
