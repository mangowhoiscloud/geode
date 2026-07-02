"""Smoke tests for the native pixel-art Geodi mascot + brand block."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

from core.ui.geodi_art import GEODI_PALETTE, GEODI_PIXELS, geodi_pixel_lines
from core.ui.mascot import _collapse_home, _spec_lines, render_mascot

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class TestGeodiPixels:
    """The hand-authored sprite grid stays well-formed."""

    def test_grid_dimensions(self) -> None:
        assert len(GEODI_PIXELS) == 14  # even row count — pairs into half-blocks
        assert all(len(row) == 16 for row in GEODI_PIXELS)

    def test_only_palette_chars(self) -> None:
        assert set("".join(GEODI_PIXELS)) <= set(GEODI_PALETTE)

    def test_character_canon(self) -> None:
        joined = "".join(GEODI_PIXELS)
        # Deep-rose gills/blush, dark eyes/smile, light belly patch present.
        assert "r" in joined and "e" in joined and "l" in joined
        assert joined.count("w") == 2  # one 1px catchlight per eye

    def test_exactly_three_separated_gill_stalks_per_side(self) -> None:
        """Canon: 6 gills — 3 per side, each separated by a transparent row."""
        left_rows = [i for i, row in enumerate(GEODI_PIXELS) if "r" in row[:4]]
        right_rows = [i for i, row in enumerate(GEODI_PIXELS) if "r" in row[-4:]]
        assert left_rows == right_rows  # symmetric
        stalks: list[list[int]] = []
        for row_idx in left_rows:
            if stalks and row_idx == stalks[-1][-1] + 1:
                stalks[-1].append(row_idx)
            else:
                stalks.append([row_idx])  # a gap row starts a new stalk
        assert len(stalks) == 3

    def test_pixel_lines_render_constant_width(self) -> None:
        lines = geodi_pixel_lines()
        assert len(lines) == 7  # 14 px tall -> 7 half-block rows
        for line in lines:
            assert len(_ANSI.sub("", line)) == 16  # text can align beside it
            assert "▀" in line or "▄" in line or " " in line
        # Truecolor body rose must appear (244;155;196 = #F49BC4).
        assert any("38;2;244;155;196" in line for line in lines)

    def test_sprite_stays_compact(self) -> None:
        """Keep the welcome mascot as a Claude Code-scale accent, not a splash panel."""
        lines = geodi_pixel_lines()
        assert len(lines) <= 7
        assert max(len(_ANSI.sub("", line)) for line in lines) <= 16


class TestMascotBrandBlock:
    def test_collapse_home(self) -> None:
        home = str(Path.home())
        assert _collapse_home(home) == "~"
        assert _collapse_home(f"{home}/proj") == "~/proj"
        assert _collapse_home("/opt/other") == "/opt/other"

    def test_spec_lines(self) -> None:
        from core.ui import spinner_glyph

        lines = _spec_lines("1.2.3", "test-model", str(Path.home() / "proj"))
        assert spinner_glyph.GLYPH in lines[0] and "GEODE" in lines[0] and "v1.2.3" in lines[0]
        assert "test-model · ~/proj" in lines[1]
        assert "/help for commands · type naturally" in lines[2]

    def test_render_mascot_smoke(self) -> None:
        from core.ui.console import (
            make_session_console,
            reset_thread_console,
            set_thread_console,
        )

        sink = StringIO()
        set_thread_console(make_session_console(sink))
        try:
            render_mascot(version="9.9.9", model="smoke-model", cwd=str(Path.home() / "smoke"))
        finally:
            reset_thread_console()
        rendered = sink.getvalue()
        assert "GEODE" in rendered and "9.9.9" in rendered
        assert "smoke-model" in rendered
        assert "~/smoke" in rendered  # $HOME collapsed
        assert "/help for commands" in rendered
