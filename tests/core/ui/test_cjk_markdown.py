"""CJK-safe Markdown emphasis preprocessing (2026-06-11 operator report).

CommonMark flanking rules drop ``**`` emphasis when the closer is
preceded by punctuation and followed by a Korean particle with no space;
the CLI then shows literal asterisks. These tests pin the preprocessing
contract and the end-to-end rich render.
"""

from __future__ import annotations

import io

from core.ui.cjk_markdown import cjk_safe_emphasis


def _render(text: str) -> str:
    from rich.console import Console
    from rich.markdown import Markdown

    buffer = io.StringIO()
    Console(file=buffer, width=120).print(Markdown(text))
    return buffer.getvalue()


def test_bracket_then_particle_renders_bold() -> None:
    """`**[추정]**이지만` was the reported literal-asterisk shape."""
    rendered = _render(cjk_safe_emphasis("전부 **[추정]**이지만 신호 기반입니다."))
    assert "**" not in rendered
    assert "추정" in rendered


def test_quote_then_particle_renders_bold() -> None:
    rendered = _render(cjk_safe_emphasis('**"운영 경력 없음"**로 분류됩니다.'))
    assert "**" not in rendered


def test_plain_emphasis_unaffected() -> None:
    rendered = _render(cjk_safe_emphasis("평범한 **굵게** 텍스트."))
    assert "**" not in rendered
    assert "굵게" in rendered


def test_inline_code_with_asterisks_untouched() -> None:
    source = "코드 `a ** b` 는 그대로, **강조**는 변환."
    transformed = cjk_safe_emphasis(source)
    assert "`a ** b`" in transformed


def test_fenced_block_untouched() -> None:
    source = "앞 **[강조]**뒤\n```python\nx = 2 ** 8  # **not emphasis**\n```\n끝"
    transformed = cjk_safe_emphasis(source)
    assert "x = 2 ** 8  # **not emphasis**" in transformed
    assert transformed.startswith("앞 **​[강조]​**뒤")


def test_no_double_asterisk_fast_path() -> None:
    source = "강조 없는 *기울임* 문장."
    assert cjk_safe_emphasis(source) is source
