from __future__ import annotations

from pathlib import Path

import pytest
from scripts.render_homebrew_formula import render_formula


def test_render_homebrew_formula_replaces_release_metadata() -> None:
    formula = render_formula(
        version="0.99.11",
        sdist_url="https://github.com/mangowhoiscloud/geode/releases/download/v0.99.11/geode-0.99.11.tar.gz",
        sdist_sha256="a" * 64,
        python_formula="python@3.12",
        resources='  resource "rich" do\n    url "https://files.pythonhosted.org/rich.tar.gz"\n    sha256 "'
        + "b" * 64
        + '"\n  end\n',
        template=Path("packaging/homebrew/geode.rb.in"),
    )

    assert "class Geode < Formula" in formula
    assert "include Language::Python::Virtualenv" in formula
    assert (
        'url "https://github.com/mangowhoiscloud/geode/releases/download/v0.99.11/geode-0.99.11.tar.gz"'
        in formula
    )
    assert 'sha256 "' + "a" * 64 + '"' in formula
    assert 'depends_on "python@3.12"' in formula
    assert "virtualenv_install_with_resources" in formula
    assert 'assert_match "GEODE v0.99.11"' in formula
    assert "{{" not in formula


def test_render_homebrew_formula_rejects_invalid_sha() -> None:
    with pytest.raises(SystemExit):
        render_formula(
            version="0.99.11",
            sdist_url="https://example.com/geode-0.99.11.tar.gz",
            sdist_sha256="not-a-sha",
            python_formula="python@3.12",
            resources="",
            template=Path("packaging/homebrew/geode.rb.in"),
        )
