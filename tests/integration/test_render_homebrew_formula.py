from __future__ import annotations

from pathlib import Path

import pytest
from scripts.render_homebrew_formula import extract_resource_stanzas, render_formula

RESOURCE = (
    '  resource "rich" do\n'
    '    url "https://files.pythonhosted.org/packages/ab/cd/rich.tar.gz"\n'
    f'    sha256 "{"b" * 64}"\n'
    "  end\n"
)


def test_render_homebrew_formula_replaces_release_metadata() -> None:
    formula = render_formula(
        version="0.99.11",
        sdist_url="https://github.com/mangowhoiscloud/geode/releases/download/v0.99.11/geode_agent-0.99.11.tar.gz",
        sdist_sha256="a" * 64,
        python_formula="python@3.12",
        resources=RESOURCE,
        template=Path("packaging/homebrew/geode-agent.rb.in"),
    )

    assert "class GeodeAgent < Formula" in formula
    assert "include Language::Python::Virtualenv" in formula
    assert (
        'url "https://github.com/mangowhoiscloud/geode/releases/download/v0.99.11/geode_agent-0.99.11.tar.gz"'
        in formula
    )
    assert 'sha256 "' + "a" * 64 + '"' in formula
    assert 'depends_on "python@3.12"' in formula
    assert 'depends_on "rust" => :build' in formula
    assert 'depends_on "libyaml"' in formula
    assert 'depends_on "openssl@3"' in formula
    assert 'formula_opt_prefix("openssl@3")' in formula
    assert 'ENV["OPENSSL_NO_VENDOR"] = "1"' in formula
    assert "virtualenv_install_with_resources" in formula
    assert 'assert_match "GEODE v0.99.11"' in formula
    assert 'shell_output("#{bin}/geode-mcp --help")' in formula
    assert "{{" not in formula


def test_render_homebrew_formula_rejects_invalid_sha() -> None:
    with pytest.raises(SystemExit):
        render_formula(
            version="0.99.11",
            sdist_url="https://github.com/mangowhoiscloud/geode/releases/download/v0.99.11/geode_agent-0.99.11.tar.gz",
            sdist_sha256="not-a-sha",
            python_formula="python@3.12",
            resources=RESOURCE,
            template=Path("packaging/homebrew/geode-agent.rb.in"),
        )


def test_render_homebrew_formula_rejects_tag_auto_tarball() -> None:
    with pytest.raises(SystemExit, match="immutable GitHub release asset"):
        render_formula(
            version="0.99.11",
            sdist_url="https://github.com/mangowhoiscloud/geode/archive/refs/tags/v0.99.11.tar.gz",
            sdist_sha256="a" * 64,
            python_formula="python@3.12",
            resources=RESOURCE,
            template=Path("packaging/homebrew/geode-agent.rb.in"),
        )


def test_render_homebrew_formula_requires_complete_resources() -> None:
    with pytest.raises(SystemExit, match="resource stanzas are required"):
        render_formula(
            version="0.99.11",
            sdist_url="https://github.com/mangowhoiscloud/geode/releases/download/v0.99.11/geode_agent-0.99.11.tar.gz",
            sdist_sha256="a" * 64,
            python_formula="python@3.12",
            resources="",
            template=Path("packaging/homebrew/geode-agent.rb.in"),
        )


def test_extract_resource_stanzas_ignores_formula_code() -> None:
    formula = f"class GeodeAgent < Formula\n{RESOURCE}\n  def install\n  end\nend\n"

    assert extract_resource_stanzas(formula) == RESOURCE


@pytest.mark.parametrize(
    "resource, message",
    [
        (
            RESOURCE.replace(
                '    sha256 "',
                '    system "env"\n    sha256 "',
            ),
            "only name, URL, SHA-256, and end",
        ),
        (
            RESOURCE.replace("https://files.pythonhosted.org", "https://example.com"),
            "canonical files.pythonhosted.org URL",
        ),
        (RESOURCE + RESOURCE, "duplicate Homebrew resource"),
    ],
)
def test_render_homebrew_formula_rejects_noncanonical_resource_blocks(
    resource: str,
    message: str,
) -> None:
    with pytest.raises(SystemExit, match=message):
        render_formula(
            version="0.99.11",
            sdist_url="https://github.com/mangowhoiscloud/geode/releases/download/v0.99.11/geode_agent-0.99.11.tar.gz",
            sdist_sha256="a" * 64,
            python_formula="python@3.12",
            resources=resource,
            template=Path("packaging/homebrew/geode-agent.rb.in"),
        )
