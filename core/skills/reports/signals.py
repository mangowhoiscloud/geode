"""External signals formatters (HTML + Markdown).

Originally lines 545-625 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Signals formatters
# ---------------------------------------------------------------------------


def _format_signals_html(signals: dict[str, Any]) -> str:
    if not signals:
        return ""
    rows = ""
    display_map = {
        "youtube_views": ("YouTube Views", ""),
        "reddit_subscribers": ("Reddit Subscribers", ""),
        "fan_art_yoy_pct": ("Fan Art YoY Growth", "%"),
        "google_trends_index": ("Google Trends Index", ""),
        "twitter_mentions_monthly": ("Twitter Mentions (Monthly)", ""),
        "cosplay_events_annual": ("Cosplay Events (Annual)", ""),
        "mod_patch_activity": ("Mod/Patch Activity", ""),
        "game_sales_data": ("Game Sales Data", ""),
    }
    for key, (label, suffix) in display_map.items():
        val = signals.get(key)
        if val is not None:
            if isinstance(val, int | float) and not isinstance(val, bool):
                display = f"{val:,.0f}{suffix}" if isinstance(val, int) else f"{val:.1f}{suffix}"
            else:
                display = str(val)
            rows += f"      <tr><td>{label}</td><td>{display}</td></tr>\n"

    # Genre fit keywords
    keywords = signals.get("genre_fit_keywords", [])
    if keywords:
        kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
        rows += f"      <tr><td>Genre Fit Keywords</td><td>{kw_str}</td></tr>\n"

    if not rows:
        return ""
    return f"""<div class="section">
    <h2><span class="icon">&#x1F4E1;</span> External Signals</h2>
    <table>
      <thead><tr><th>Signal</th><th>Value</th></tr></thead>
      <tbody>
{rows}      </tbody>
    </table>
  </div>"""


def _format_signals_md(signals: dict[str, Any]) -> str:
    if not signals:
        return ""
    display_map = {
        "youtube_views": ("YouTube Views", ""),
        "reddit_subscribers": ("Reddit Subscribers", ""),
        "fan_art_yoy_pct": ("Fan Art YoY Growth", "%"),
        "google_trends_index": ("Google Trends Index", ""),
        "twitter_mentions_monthly": ("Twitter Mentions (Monthly)", ""),
        "cosplay_events_annual": ("Cosplay Events (Annual)", ""),
        "mod_patch_activity": ("Mod/Patch Activity", ""),
        "game_sales_data": ("Game Sales Data", ""),
    }
    lines = [
        "## External Signals",
        "",
        "| Signal | Value |",
        "| --- | --- |",
    ]
    has_data = False
    for key, (label, suffix) in display_map.items():
        val = signals.get(key)
        if val is not None:
            has_data = True
            if isinstance(val, int | float) and not isinstance(val, bool):
                display = f"{val:,.0f}{suffix}" if isinstance(val, int) else f"{val:.1f}{suffix}"
            else:
                display = str(val)
            lines.append(f"| {label} | {display} |")

    keywords = signals.get("genre_fit_keywords", [])
    if keywords:
        has_data = True
        kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
        lines.append(f"| Genre Fit Keywords | {kw_str} |")

    if not has_data:
        return ""
    return "\n".join(lines)
