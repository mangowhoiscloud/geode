"""Karpathy ↔ GEODE — file-by-file walk + LoC bar chart + change heatmap.

Companion to ``autoresearch_compare.py`` (which gave a 3-section
overview) and ``docs/visualizations/autoresearch-comparison.md`` (full
text SoT). This scene walks the three files side-by-side, then shows a
LoC bar chart and a 3×3 change heatmap so the diff is legible as a
diagram instead of a table.

Source data (verified 2026-05-21):

* Karpathy autoresearch (228791f) — https://github.com/karpathy/autoresearch
  - ``prepare.py``  ~390 LoC  (5 functions + 1 class + dataloader)
  - ``train.py``    724 LoC   (5 classes: GPTConfig / CausalSelfAttention /
    MLP / Block / GPT / MuonAdamW; 10+ functions; optimiser = Muon+AdamW;
    final metric = val_bpb)
  - ``program.md``  ~200 LoC  (agent loop instructions; single goal:
    lower val_bpb)

* GEODE autoresearch (this repo) —
  - ``prepare.py``  203 LoC   (seed pool + rubric sanity check + audit
    CLI dry-run reachability)
  - ``train.py``    1308 LoC  (WRAPPER_PROMPT_SECTIONS — the prompt kind's
    SoT, 1 of the 7 ``TARGET_KINDS`` mutation surfaces in
    ``loop/policies.py`` — + run_audit + compute_dim_scores +
    _stability_score + compute_fitness + critical floor branch +
    auto-promote rule + 24 def/class total)
  - ``program.md``  360 LoC   (agent loop + role split with petri +
    3-stage cycle + 18-dim rubric + auto-promote rule)

Fact-sync note (2026-06-04): the rubric is 18-dim (5 critical / 10
auxiliary / 3 info), 15 weighted, after PR-DROP-ANALYTICS-DIMS (#1964)
removed the two script-computed analytics dims; the promote margin is
``max(_MARGIN_GAIN_SIGMA·√(σp²+σc²), 0.005)``. LoC figures are the
2026-05-21 snapshot and are intentionally left as the bar-chart's
recorded provenance.

Render
======
::

    uv run manim -qh -o AutoresearchFilewalk-EN \\
        scripts/visualizations/autoresearch_filewalk.py AutoresearchFilewalk
    GEODE_HERO_LANG=ko uv run manim -qh -o AutoresearchFilewalk-KO \\
        scripts/visualizations/autoresearch_filewalk.py AutoresearchFilewalk
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
    FadeIn,
    FadeOut,
    LaggedStart,
    Line,
    Rectangle,
    Scene,
    Square,
    Text,
    VGroup,
    config,
)

config.background_color = "#FFFFFF"
config.frame_rate = 60

LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

# Anthropic-style palette (matches geode_hero.py / critical_floor.py).
COLOR_BORROW = "#A4C2F4"  # blue — verbatim copy
COLOR_SWAP = "#FFE599"  # yellow — same slot, different content
COLOR_ADD = "#93C47D"  # green — GEODE-only addition
COLOR_REMOVE = "#E06666"  # red — Karpathy-only / removed
COLOR_KARPATHY = "#F4CCCC"  # light pink — Karpathy panel fill
COLOR_GEODE = "#D5E8D4"  # very light green — GEODE panel fill
COLOR_ARROW = "#666666"
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"

EN_FONT = "Helvetica Neue"
KOR_FONT = "Pretendard"

# Source-of-truth LoC measurements (see module docstring).
LOC = {
    "karpathy": {"prepare.py": 390, "train.py": 724, "program.md": 200},
    "geode": {"prepare.py": 203, "train.py": 1308, "program.md": 360},
}

# Outline summaries (top symbols) per file.
OUTLINE_KARPATHY = {
    "prepare.py": (
        "download_single_shard()",
        "download_data()",
        "train_tokenizer()",
        "make_dataloader()",
        "evaluate_bpb()  ← fixed metric",
        "class Tokenizer",
    ),
    "train.py": (
        "class GPTConfig",
        "class CausalSelfAttention",
        "class MLP",
        "class Block",
        "class GPT",
        "class MuonAdamW",
        "training loop → val_bpb",
    ),
    "program.md": (
        "Setup — branch from master",
        "Experimentation — edit train.py only",
        "Output: val_bpb / vram / mfu",
        "results.tsv: commit / val_bpb / status",
        "Loop forever — lower val_bpb",
    ),
}
OUTLINE_GEODE = {
    "prepare.py": (
        "check Petri seed pool",
        "verify AlphaEval rubric",
        "audit CLI dry-run reachability",
        "(no fineweb / no BPE)",
        "→ sanity-report.txt",
    ),
    "train.py": (
        "WRAPPER_PROMPT_SECTIONS (1 of 7 TARGET_KINDS)",
        "AXIS_TIERS (5/10/3)",
        "DIM_WEIGHTS + STABILITY_WEIGHT",
        "run_audit() — geode audit subproc",
        "_dim_score() / _stability_score()",
        "compute_fitness() + critical floor",
        "_should_promote() — gain > margin",
    ),
    "program.md": (
        "Setup — branch from develop",
        "Role split: petri ↔ autoresearch",
        "3-stage cycle (generate / eval / improve)",
        "18-dim rubric + critical floor",
        "Auto-promote: gain > max(σ·√(σp²+σc²), 0.005)",
        "Loop forever — raise fitness",
    ),
}

# 3×3 heatmap intensity grid: rows = files, cols = (verbatim / swap / add).
# Values in [0, 1] — bigger = stronger presence of that change kind.
HEATMAP = {
    "prepare.py": (0.6, 0.7, 0.1),
    "train.py": (0.3, 0.5, 0.9),
    "program.md": (0.3, 0.5, 0.8),
}

T = {
    "en": {
        "title": "Karpathy ↔ GEODE — three files, side by side",
        "bit_1_title": "Section 1 — the three files",
        "bit_2_title": "Section 2 — prepare.py",
        "bit_3_title": "Section 3 — train.py",
        "bit_4_title": "Section 4 — program.md",
        "bit_5_title": "Section 5 — lines-of-code chart",
        "bit_6_title": "Section 6 — change heatmap",
        "karpathy_label": "Karpathy autoresearch",
        "geode_label": "GEODE autoresearch",
        "loc_label": "LoC",
        "outro_main": "Same scaffold. Different objective. Bigger safety perimeter.",
        "outro_sub": "prepare.py shrank (data → sanity); train.py grew (1 metric → 18-dim taxonomy / 15 weighted + floor); program.md grew (1 goal → 3-stage cycle).",
        "heatmap_col_a": "verbatim",
        "heatmap_col_b": "swapped",
        "heatmap_col_c": "added",
    },
    "ko": {
        "title": "Karpathy ↔ GEODE — 세 파일, 나란히",
        "bit_1_title": "Section 1 — 세 파일 헤더",
        "bit_2_title": "Section 2 — prepare.py",
        "bit_3_title": "Section 3 — train.py",
        "bit_4_title": "Section 4 — program.md",
        "bit_5_title": "Section 5 — LoC 막대 차트",
        "bit_6_title": "Section 6 — 변화 히트맵",
        "karpathy_label": "Karpathy autoresearch",
        "geode_label": "GEODE autoresearch",
        "loc_label": "LoC",
        "outro_main": "같은 scaffold. 다른 목적. 더 두꺼운 safety perimeter.",
        "outro_sub": "prepare.py 는 줄고 (data → sanity); train.py 는 커지고 (1 metric → 18-dim taxonomy / 15 weighted + floor); program.md 는 커짐 (1 goal → 3-stage cycle).",
        "heatmap_col_a": "verbatim",
        "heatmap_col_b": "swapped",
        "heatmap_col_c": "added",
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


TITLE_Y = 3.45
SECTION_TITLE_Y = 2.85


class AutoresearchFilewalk(Scene):
    def construct(self) -> None:
        self._section_title = None
        self._section_content = VGroup()
        self._show_title()
        self._bit_1_six_panel_grid()
        self._bit_2_prepare_detail()
        self._bit_3_train_detail()
        self._bit_4_program_detail()
        self._bit_5_loc_bars()
        self._bit_6_heatmap()
        self._outro()

    # ---------------------------------------------------------------- utility

    def _show_title(self) -> None:
        title = _make_text(_t("title"), font_size=26, color=COLOR_TEXT).move_to(UP * TITLE_Y)
        self.title = title
        self.play(FadeIn(title), run_time=0.6)

    def _set_section_title(self, key: str) -> None:
        """Swap the current section title in one shot, clearing prior content.

        Doing the fade-out, content clear, and title fade-in in a single
        ``play`` call eliminates the empty/half-empty transition frames
        previous versions had between bits.
        """
        new_title = _make_text(_t(key), font_size=18, color=COLOR_TEXT_ACCENT).move_to(
            UP * SECTION_TITLE_Y
        )
        fade_outs = []
        if self._section_title is not None:
            fade_outs.append(FadeOut(self._section_title))
        if len(self._section_content) > 0:
            fade_outs.append(FadeOut(self._section_content))
        if fade_outs:
            self.play(*fade_outs, FadeIn(new_title), run_time=0.4)
        else:
            self.play(FadeIn(new_title), run_time=0.3)
        self._section_title = new_title
        self._section_content = VGroup()

    def _file_card(
        self,
        filename: str,
        loc: int,
        outline: tuple[str, ...],
        fill: str,
        *,
        width: float = 4.0,
        height: float = 4.2,
        line_size: int = 11,
        header_size: int = 16,
        loc_size: int = 11,
        top_padding: float = 0.18,
        header_lines_buff: float = 0.22,
        outline_buff: float = 0.13,
    ) -> VGroup:
        body = Rectangle(
            width=width,
            height=height,
            stroke_color=COLOR_ARROW,
            stroke_width=1.5,
            fill_color=fill,
            fill_opacity=0.25,
        )
        header = _make_text(filename, font_size=header_size, color=COLOR_TEXT)
        loc_pill = _make_text(
            f"{loc} {_t('loc_label')}", font_size=loc_size, color=COLOR_TEXT_ACCENT
        )
        header_block = VGroup(header, loc_pill).arrange(DOWN, buff=0.06)
        lines = VGroup(
            *[_make_text(line, font_size=line_size, color=COLOR_TEXT) for line in outline]
        ).arrange(DOWN, buff=outline_buff, aligned_edge=LEFT)
        content = VGroup(header_block, lines).arrange(DOWN, buff=header_lines_buff)
        content.next_to(body.get_top(), DOWN, buff=top_padding)
        return VGroup(body, content)

    # ---------------------------------------------------------------- bit 1

    def _bit_1_six_panel_grid(self) -> None:
        self._set_section_title("bit_1_title")

        karpathy_label = _make_text(_t("karpathy_label"), font_size=13, color=COLOR_TEXT).move_to(
            LEFT * 5.6 + UP * 1.25
        )
        geode_label = _make_text(_t("geode_label"), font_size=13, color=COLOR_TEXT).move_to(
            LEFT * 5.6 + DOWN * 1.4
        )

        cards = []
        for col_i, filename in enumerate(("prepare.py", "train.py", "program.md")):
            x = -3.6 + col_i * 3.6
            k_card = self._file_card(
                filename,
                LOC["karpathy"][filename],
                OUTLINE_KARPATHY[filename],
                COLOR_KARPATHY,
                width=3.3,
                height=2.5,
                line_size=10,
                header_size=14,
                loc_size=10,
                top_padding=0.16,
                header_lines_buff=0.18,
                outline_buff=0.10,
            )
            k_card.move_to(RIGHT * x + UP * 1.25)
            g_card = self._file_card(
                filename,
                LOC["geode"][filename],
                OUTLINE_GEODE[filename],
                COLOR_GEODE,
                width=3.3,
                height=2.5,
                line_size=10,
                header_size=14,
                loc_size=10,
                top_padding=0.16,
                header_lines_buff=0.18,
                outline_buff=0.10,
            )
            g_card.move_to(RIGHT * x + DOWN * 1.4)
            cards.append((k_card, g_card))

        all_panels = VGroup(*[item for pair in cards for item in pair])
        self.play(
            FadeIn(karpathy_label),
            FadeIn(geode_label),
            LaggedStart(*[FadeIn(card) for card in all_panels], lag_ratio=0.08),
            run_time=2.0,
        )
        self._section_content = VGroup(karpathy_label, geode_label, all_panels)
        self.wait(2.5)

    # ---------------------------------------------------------------- bit 2/3/4

    def _file_detail(self, filename: str) -> None:
        """One file, two large side-by-side panels."""
        k_card = self._file_card(
            filename,
            LOC["karpathy"][filename],
            OUTLINE_KARPATHY[filename],
            COLOR_KARPATHY,
            width=5.4,
            height=3.8,
            line_size=14,
            header_size=18,
            loc_size=12,
            top_padding=0.25,
            header_lines_buff=0.30,
            outline_buff=0.18,
        ).move_to(LEFT * 3.4 + DOWN * 0.2)
        g_card = self._file_card(
            filename,
            LOC["geode"][filename],
            OUTLINE_GEODE[filename],
            COLOR_GEODE,
            width=5.4,
            height=3.8,
            line_size=14,
            header_size=18,
            loc_size=12,
            top_padding=0.25,
            header_lines_buff=0.30,
            outline_buff=0.18,
        ).move_to(RIGHT * 3.4 + DOWN * 0.2)
        karpathy_label = _make_text(_t("karpathy_label"), font_size=14, color=COLOR_TEXT).next_to(
            k_card, UP, buff=0.1
        )
        geode_label = _make_text(_t("geode_label"), font_size=14, color=COLOR_TEXT).next_to(
            g_card, UP, buff=0.1
        )

        k_loc = LOC["karpathy"][filename]
        g_loc = LOC["geode"][filename]
        delta = g_loc - k_loc
        delta_sign = "+" if delta > 0 else "−"
        delta_color = COLOR_ADD if delta > 0 else COLOR_REMOVE
        delta_text = _make_text(
            f"{_t('loc_label')}  {k_loc}  →  {g_loc}   {delta_sign}{abs(delta)}",
            font_size=14,
            color=delta_color,
        ).move_to(DOWN * 2.55)

        group = VGroup(k_card, g_card, karpathy_label, geode_label, delta_text)
        self.play(FadeIn(group), run_time=0.6)
        self._section_content = group
        self.wait(2.4)

    def _bit_2_prepare_detail(self) -> None:
        self._set_section_title("bit_2_title")
        self._file_detail("prepare.py")

    def _bit_3_train_detail(self) -> None:
        self._set_section_title("bit_3_title")
        self._file_detail("train.py")

    def _bit_4_program_detail(self) -> None:
        self._set_section_title("bit_4_title")
        self._file_detail("program.md")

    # ---------------------------------------------------------------- bit 5

    def _bit_5_loc_bars(self) -> None:
        self._set_section_title("bit_5_title")

        files = ("prepare.py", "train.py", "program.md")
        max_loc = max(LOC["geode"][f] for f in files)
        chart_w = 9.0
        chart_h = 2.9
        x_base = -chart_w / 2 + 0.5
        baseline_y = -1.8
        bar_width = 0.55
        bar_dx = 0.35

        bars = []
        labels = []
        loc_texts = []
        for i, f in enumerate(files):
            x_center = x_base + i * (chart_w / 3) + 1.0
            k_h = LOC["karpathy"][f] / max_loc * chart_h
            g_h = LOC["geode"][f] / max_loc * chart_h
            k_bar = Rectangle(
                width=bar_width,
                height=k_h,
                stroke_color=COLOR_ARROW,
                stroke_width=0.8,
                fill_color=COLOR_KARPATHY,
                fill_opacity=0.85,
            )
            k_bar.move_to([x_center - bar_dx, baseline_y + k_h / 2, 0])
            g_bar = Rectangle(
                width=bar_width,
                height=g_h,
                stroke_color=COLOR_ARROW,
                stroke_width=0.8,
                fill_color=COLOR_GEODE,
                fill_opacity=0.85,
            )
            g_bar.move_to([x_center + bar_dx, baseline_y + g_h / 2, 0])

            file_label = _make_text(f, font_size=14, color=COLOR_TEXT).move_to(
                [x_center, baseline_y - 0.35, 0]
            )
            k_count = _make_text(
                str(LOC["karpathy"][f]), font_size=11, color=COLOR_TEXT_ACCENT
            ).next_to(k_bar, UP, buff=0.08)
            g_count = _make_text(
                str(LOC["geode"][f]), font_size=11, color=COLOR_TEXT_ACCENT
            ).next_to(g_bar, UP, buff=0.08)

            bars.extend([k_bar, g_bar])
            labels.append(file_label)
            loc_texts.extend([k_count, g_count])

        legend_k = VGroup(
            Square(
                side_length=0.18, color=COLOR_ARROW, fill_color=COLOR_KARPATHY, fill_opacity=0.85
            ),
            _make_text(_t("karpathy_label"), font_size=12, color=COLOR_TEXT_ACCENT),
        ).arrange(RIGHT, buff=0.15)
        legend_g = VGroup(
            Square(side_length=0.18, color=COLOR_ARROW, fill_color=COLOR_GEODE, fill_opacity=0.85),
            _make_text(_t("geode_label"), font_size=12, color=COLOR_TEXT_ACCENT),
        ).arrange(RIGHT, buff=0.15)
        legend = VGroup(legend_k, legend_g).arrange(RIGHT, buff=0.8).move_to(UP * 2.05)

        baseline = Line(
            [-chart_w / 2 + 0.3, baseline_y, 0],
            [chart_w / 2 - 0.3, baseline_y, 0],
            color=COLOR_ARROW,
            stroke_width=1.5,
        )

        self.play(
            FadeIn(legend),
            Create(baseline),
            LaggedStart(*[Create(b) for b in bars], lag_ratio=0.1),
            LaggedStart(*[FadeIn(t) for t in loc_texts], lag_ratio=0.08),
            LaggedStart(*[FadeIn(label) for label in labels], lag_ratio=0.08),
            run_time=1.6,
        )
        self._section_content = VGroup(legend, baseline, *bars, *loc_texts, *labels)
        self.wait(2.5)

    # ---------------------------------------------------------------- bit 6

    def _bit_6_heatmap(self) -> None:
        self._set_section_title("bit_6_title")

        rows = ("prepare.py", "train.py", "program.md")
        cols = ("heatmap_col_a", "heatmap_col_b", "heatmap_col_c")
        col_colors = (COLOR_BORROW, COLOR_SWAP, COLOR_ADD)

        cell_size = 1.05
        grid_center_x = 0.4  # nudge grid right so left-side row labels clear cleanly
        grid_center_y = -0.2

        # Cell column centers: index 0,1,2 → x − cell_size, x, x + cell_size
        def col_x(j):
            return grid_center_x + (j - 1) * cell_size

        def row_y(i):
            return grid_center_y - (i - 1) * cell_size

        # Column headers — each centered on the column x_center via VGroup arrange + move_to.
        col_headers = VGroup()
        header_y = row_y(0) + cell_size * 0.5 + 0.45
        for j, ckey in enumerate(cols):
            hdr_dot = Circle(
                radius=0.09,
                color=col_colors[j],
                fill_color=col_colors[j],
                fill_opacity=1.0,
            )
            hdr_text = _make_text(_t(ckey), font_size=13, color=COLOR_TEXT_ACCENT)
            hdr_group = VGroup(hdr_dot, hdr_text).arrange(RIGHT, buff=0.08)
            hdr_group.move_to([col_x(j), header_y, 0])
            col_headers.add(hdr_group)

        cells = VGroup()
        row_labels = VGroup()
        row_label_x = col_x(0) - cell_size * 0.5 - 0.35  # right edge of left cell minus 0.35
        for i, fname in enumerate(rows):
            y_center = row_y(i)
            label = _make_text(fname, font_size=13, color=COLOR_TEXT)
            label.move_to([row_label_x - label.width / 2, y_center, 0])
            row_labels.add(label)
            intensities = HEATMAP[fname]
            for j, intensity in enumerate(intensities):
                cell_bg = Square(
                    side_length=cell_size * 0.94,
                    stroke_color=COLOR_ARROW,
                    stroke_width=0.8,
                    fill_color=col_colors[j],
                    fill_opacity=max(0.18, intensity),
                ).move_to([col_x(j), y_center, 0])
                txt = _make_text(
                    f"{intensity:.1f}",
                    font_size=13,
                    color=COLOR_TEXT,
                ).move_to(cell_bg.get_center())
                cells.add(cell_bg)
                cells.add(txt)

        legend_lines = (
            VGroup(
                _make_text("0.0 = absent", font_size=11, color=COLOR_TEXT_ACCENT),
                _make_text("1.0 = dominant", font_size=11, color=COLOR_TEXT_ACCENT),
            )
            .arrange(DOWN, buff=0.12)
            .move_to([col_x(2) + cell_size * 0.5 + 1.2, row_y(1), 0])
        )

        self.play(
            LaggedStart(*[FadeIn(h) for h in col_headers], lag_ratio=0.08),
            LaggedStart(*[FadeIn(r) for r in row_labels], lag_ratio=0.08),
            LaggedStart(*[FadeIn(c) for c in cells], lag_ratio=0.04),
            FadeIn(legend_lines),
            run_time=1.8,
        )
        self._section_content = VGroup(col_headers, row_labels, cells, legend_lines)
        self.wait(2.6)

    # ---------------------------------------------------------------- outro

    def _outro(self) -> None:
        fade_outs = []
        if len(self._section_content) > 0:
            fade_outs.append(FadeOut(self._section_content))
        if self._section_title is not None:
            fade_outs.append(FadeOut(self._section_title))
        fade_outs.append(FadeOut(self.title))
        self.play(*fade_outs, run_time=0.4)

        main = _make_text(_t("outro_main"), font_size=24, color=COLOR_TEXT).move_to(UP * 0.5)
        sub = _make_text(_t("outro_sub"), font_size=12, color=COLOR_TEXT_ACCENT).next_to(
            main, DOWN, buff=0.35
        )
        dots = (
            VGroup(
                Circle(radius=0.08, color=COLOR_BORROW, fill_color=COLOR_BORROW, fill_opacity=1.0),
                Circle(radius=0.08, color=COLOR_SWAP, fill_color=COLOR_SWAP, fill_opacity=1.0),
                Circle(radius=0.08, color=COLOR_ADD, fill_color=COLOR_ADD, fill_opacity=1.0),
            )
            .arrange(RIGHT, buff=0.5)
            .next_to(sub, DOWN, buff=0.5)
        )

        self.play(FadeIn(main), run_time=0.6)
        self.play(FadeIn(sub), FadeIn(dots), run_time=0.5)
        self.wait(3.0)
