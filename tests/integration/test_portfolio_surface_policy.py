from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTFOLIO_PATH = REPO_ROOT / "site/src/app/portfolio/page.tsx"
LANDING_PATH = REPO_ROOT / "site/src/components/geode/landing-page.tsx"
INSTALL_PATH = REPO_ROOT / "site/src/components/geode/landing-install.tsx"
LOCALE_CONTEXT_PATH = REPO_ROOT / "site/src/components/geode/locale-context.tsx"
NAV_PATH = REPO_ROOT / "site/src/components/geode/sections/nav.tsx"


def test_portfolio_language_and_report_follow_the_query_locale() -> None:
    portfolio = LANDING_PATH.read_text(encoding="utf-8")
    locale_context = LOCALE_CONTEXT_PATH.read_text(encoding="utf-8")
    nav = NAV_PATH.read_text(encoding="utf-8")

    assert '<LocaleProvider defaultLocale="en">' in portfolio
    assert "allowQueryOverride={false}" not in portfolio
    assert "LocaleToggle" not in portfolio
    assert 'const lang = params.get("lang");' in locale_context
    assert "setQueryReady(true)" in locale_context
    for write in (
        'url.searchParams.delete("lang")',
        'url.searchParams.set("lang", locale)',
        "document.documentElement.lang = locale",
    ):
        assert locale_context.index("if (!queryReady) return;") < locale_context.index(write)
    assert 'href={locale === "en" ? "/geode/report-en.pdf" : "/geode/report.pdf"}' in portfolio
    assert (REPO_ROOT / "site/public/report.pdf").is_file()
    assert (REPO_ROOT / "site/public/report-en.pdf").is_file()
    assert "{showLocaleToggle ? <LocaleToggle /> : null}" in nav


def test_portfolio_install_surface_and_recorded_hero() -> None:
    portfolio = LANDING_PATH.read_text(encoding="utf-8")
    install = INSTALL_PATH.read_text(encoding="utf-8")
    run = LANDING_PATH.with_name("landing-run.tsx").read_text(encoding="utf-8")

    for provider in ("Anthropic", "OpenAI / Codex", "OpenRouter", "ZhipuAI GLM"):
        assert provider in portfolio
    assert 'aria-label="Supported providers"' in portfolio
    assert "Subscription authentication and metered APIs are separate routes." in portfolio
    assert "<RecordedRun />" in portfolio
    assert "evidence.astra" in run
    assert "not a full replay" in run
    assert "Command and result bodies are withheld." in run
    assert 'useState("uv-tool")' in install
    assert 'copy: "uv tool install geode-agent"' in install
    assert 'copy: "uvx --from geode-agent geode"' in install
    assert "navigator.clipboard.writeText" in install
    assert 'setCopyStatus("error")' in install
    assert ">/login</code>" in install


def test_current_routes_share_the_landing_without_restyling_archives() -> None:
    root_page = (REPO_ROOT / "site/src/app/page.tsx").read_text(encoding="utf-8")
    alias_page = PORTFOLIO_PATH.read_text(encoding="utf-8")
    alias_layout = PORTFOLIO_PATH.with_name("layout.tsx").read_text(encoding="utf-8")
    for page in (root_page, alias_page):
        assert "<GeodeLanding />" in page
        assert 'title: "GEODE | An agent runtime for tool-driven work"' in page
    assert "An agent runtime for tool-driven work" not in alias_layout
    assert '"@type": "SoftwareSourceCode"' in root_page


def test_landing_keeps_native_navigation_and_reduced_motion() -> None:
    landing = LANDING_PATH.read_text(encoding="utf-8")
    run = LANDING_PATH.with_name("landing-run.tsx").read_text(encoding="utf-8")
    css = LANDING_PATH.with_name("landing.css").read_text(encoding="utf-8")
    for anchor in ("hero", "install", "features", "distill", "lab"):
        assert f'id="{anchor}"' in landing
    assert 'id="run"' in run
    assert 'href="#main-content"' in landing
    assert '<details className="landing-mobile-menu">' in landing
    assert 'closest("details")?.removeAttribute("open")' in landing
    assert "focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "scroll-behavior: auto" in css
    assert "scrollIntoView" not in landing
