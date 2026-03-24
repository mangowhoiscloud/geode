"""Convert standard Markdown to Slack mrkdwn format."""

from __future__ import annotations

import re

_CODE_SENTINEL = "\x00CODE"
_ZWS = "\u200b"  # zero-width space — Slack word-boundary fix

# Characters that Slack treats as word boundaries for *bold* formatting
_BOUNDARY_AFTER = frozenset(" \t\n,.\u2014!?;:)]>*_~`\"'\u200b")
_BOUNDARY_BEFORE = frozenset(" \t\n,.\u2014!?;:([<*_~`\"'\u200b")


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert Markdown to Slack mrkdwn.

    Conversions:
    - **bold** → *bold* with ZWS at non-boundary edges
    - ~~strike~~ → ~strike~
    - # Heading → *Heading*
    - [text](url) → <url|text>
    - Markdown tables → vertical section format
    - --- → removed
    """
    if not text:
        return text

    # ── 1. Protect code blocks ──
    code_blocks: list[str] = []

    def _save(m: re.Match[str]) -> str:
        code_blocks.append(m.group(0))
        return f"{_CODE_SENTINEL}{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _save, text)
    text = re.sub(r"`[^`\n]+`", _save, text)

    # ── 2. Tables → sections (before inline fmt) ──
    text = _convert_tables(text)

    # ── 3. Bold with Slack boundary fix ──
    text = _convert_bold(text)

    # ── 4. Strikethrough ──
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)

    # ── 5. Block-level ──
    def _heading(m: re.Match[str]) -> str:
        c = m.group(1)
        c = re.sub(r"\*\*(.+?)\*\*", r"\1", c)
        c = re.sub(r"^\*(.+)\*$", r"\1", c)
        return f"*{c}*"

    text = re.sub(r"^#{1,6}\s+(.+)$", _heading, text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)
    text = re.sub(r"^[\s]*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Collapse 3+ blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # ── 6. Restore code blocks ──
    for i, block in enumerate(code_blocks):
        text = text.replace(f"{_CODE_SENTINEL}{i}\x00", block)

    return text.strip()


def _convert_bold(text: str) -> str:
    """Convert **bold** → *bold* with ZWS at non-boundary edges.

    Slack mrkdwn requires word boundaries around *bold*.
    *LangGraph*가 won't render — needs *LangGraph*​가 (ZWS).
    """

    def _repl(m: re.Match[str]) -> str:
        content = m.group(1)
        result = f"*{content}*"

        end = m.end()
        if end < len(text) and text[end] not in _BOUNDARY_AFTER:
            result += _ZWS

        start = m.start()
        if start > 0 and text[start - 1] not in _BOUNDARY_BEFORE:
            result = _ZWS + result

        return result

    return re.sub(r"\*\*(.+?)\*\*", _repl, text)


# ── Table conversion ──


def _strip_md(text: str) -> str:
    """Strip Markdown formatting from cell text."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def _parse_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Parse table lines → (headers, data_rows) with formatting stripped."""
    rows: list[list[str]] = []
    for line in lines:
        s = line.strip()
        if re.match(r"^\|[\s\-:|]+\|$", s):
            continue
        cells = [_strip_md(c) for c in s.strip("|").split("|")]
        if any(c for c in cells):
            rows.append(cells)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _table_to_sections(headers: list[str], data: list[list[str]]) -> str:
    """Convert table to Slack-friendly vertical sections."""
    ncols = len(headers)

    if ncols > 2 and data:
        parts: list[str] = []
        for ci in range(1, ncols):
            title = headers[ci] if ci < ncols else ""
            lines = [f"*{title}*"]
            for row in data:
                label = row[0] if row else ""
                val = row[ci] if ci < len(row) else ""
                if val and val.strip() and val.strip() != "-":
                    lines.append(f"  • {label}: {val}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    out: list[str] = []
    for row in data:
        if len(row) >= 2:
            out.append(f"• *{row[0]}*: {row[1]}")
        elif row:
            out.append(f"• {row[0]}")
    return "\n".join(out)


def _convert_tables(text: str) -> str:
    """Find and convert Markdown tables."""
    lines = text.split("\n")
    result: list[str] = []
    buf: list[str] = []

    def _flush() -> None:
        if not buf:
            return
        h, d = _parse_table(buf)
        if h and d:
            result.append(_table_to_sections(h, d))
        else:
            result.extend(buf)
        buf.clear()

    for line in lines:
        if re.match(r"^\s*\|", line):
            buf.append(line)
        else:
            if buf:
                _flush()
            result.append(line)

    if buf:
        _flush()

    return "\n".join(result)
