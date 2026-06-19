"""Guards for the consolidated duration formatters (PR-DEDUP-2).

``format_age`` is also exercised via the memory tests it was lifted from; this
pins both functions at their new home, and adds the ``format_elapsed`` coverage
the ``_fmt_elapsed`` / ``_format_seconds`` copies never had.
"""

from __future__ import annotations

import pytest
from core.time_format import format_age, format_elapsed


class TestFormatAge:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (-10, "now"),
            (0, "now"),
            (59, "now"),
            (60, "1m ago"),
            (300, "5m ago"),
            (3600, "1h ago"),
            (7200, "2h ago"),
            (86400, "1d ago"),
            (172800, "2d ago"),
        ],
    )
    def test_age(self, seconds: float, expected: str) -> None:
        assert format_age(seconds) == expected


class TestFormatElapsed:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "0s"),
            (5, "5s"),
            (59, "59s"),
            (60, "1m 0s"),
            (90, "1m 30s"),
            (3661, "61m 1s"),
        ],
    )
    def test_elapsed(self, seconds: float, expected: str) -> None:
        assert format_elapsed(seconds) == expected
