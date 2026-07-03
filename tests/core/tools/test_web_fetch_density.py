"""web_fetch repeated-list density compaction.

A list/feed/search-results page can carry hundreds of structurally
identical siblings; feeding them all in blows the char budget so the
blind head-truncation drops the page tail. ``_collapse_repeated_lists``
keeps a sample + an honest ``[... N more <tag> items omitted ...]``
marker so the tail survives. (Ported idea: GenericAgent simphtml cutlist.)
"""

from __future__ import annotations

from core.tools.web_tools import WebFetchTool


def _items(n: int) -> str:
    return "".join(
        f'<li class="result">Item {i} with enough text to count as real content here</li>'
        for i in range(n)
    )


def test_long_list_collapses_to_sample_plus_marker() -> None:
    html = f"<html><body><ul>{_items(40)}</ul></body></html>"
    text = WebFetchTool._html_to_text(html)

    # Kept sample survives (first KEEP items), later ones are dropped.
    assert "Item 0" in text
    assert f"Item {WebFetchTool._LIST_COLLAPSE_KEEP - 1}" in text
    assert "Item 39" not in text
    # Honest omission marker names the count + tag.
    dropped = 40 - WebFetchTool._LIST_COLLAPSE_KEEP
    assert f"{dropped} more <li> items omitted" in text


def test_page_tail_survives_after_long_list() -> None:
    # The whole point: content *after* a huge list must not vanish once the
    # list is collapsed and the char budget is applied downstream.
    html = (
        "<html><body>"
        f"<ul>{_items(200)}</ul>"
        '<div class="footer-note">UNIQUE-TAIL-MARKER</div>'
        "</body></html>"
    )
    text = WebFetchTool._html_to_text(html)
    assert "UNIQUE-TAIL-MARKER" in text
    assert len(text) < len(html)  # genuinely compacted


def test_short_list_is_left_intact() -> None:
    # Below threshold — do not touch (a 4-item nav must stay whole).
    html = f"<html><body><ul>{_items(4)}</ul></body></html>"
    text = WebFetchTool._html_to_text(html)
    assert "Item 3" in text
    assert "omitted" not in text


def test_trivial_repeats_are_not_collapsed() -> None:
    # Many tiny siblings (spacer chips, icons) carry < MIN_TEXT chars each;
    # collapsing them saves nothing and would add noise, so leave them.
    html = "<html><body><div>" + ("<span>x</span>" * 30) + "</div></body></html>"
    text = WebFetchTool._html_to_text(html)
    assert "omitted" not in text
