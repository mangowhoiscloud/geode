"""Convert standard Markdown to Slack mrkdwn format."""

from __future__ import annotations

import re


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert Markdown to Slack mrkdwn.

    Conversions:
    - **bold** → *bold*
    - # Heading → *Heading*
    - ## Heading → *Heading*
    - [text](url) → <url|text>
    - Markdown tables → code block wrapped
    """
    # Headers: # Heading → *Heading*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Bold: **text** → *text* (must do before italic)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Links: [text](url) → <url|text>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Tables: wrap in code block if detected
    # (Slack doesn't render tables, so wrap them for readability)
    lines = text.split("\n")
    result: list[str] = []
    in_table = False
    for line in lines:
        is_table_line = bool(re.match(r"^\s*\|", line))
        is_separator = bool(re.match(r"^\s*\|[\s\-:|]+\|", line))

        if is_table_line and not in_table:
            in_table = True
            result.append("```")
        elif not is_table_line and in_table:
            in_table = False
            result.append("```")

        if is_separator:
            continue  # Skip Markdown table separators

        result.append(line)

    if in_table:
        result.append("```")

    return "\n".join(result)
