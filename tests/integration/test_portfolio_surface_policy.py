from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTFOLIO_PATH = REPO_ROOT / "site/src/app/portfolio/page.tsx"
LOCALE_CONTEXT_PATH = REPO_ROOT / "site/src/components/geode/locale-context.tsx"
NAV_PATH = REPO_ROOT / "site/src/components/geode/sections/nav.tsx"


def test_portfolio_language_and_report_follow_the_query_locale() -> None:
    portfolio = PORTFOLIO_PATH.read_text(encoding="utf-8")
    locale_context = LOCALE_CONTEXT_PATH.read_text(encoding="utf-8")
    nav = NAV_PATH.read_text(encoding="utf-8")

    assert '<LocaleProvider defaultLocale="en">' in portfolio
    assert "allowQueryOverride={false}" not in portfolio
    assert "<GeodeNav items={navItems} light showLocaleToggle={false} />" in portfolio
    assert 'const lang = params.get("lang");' in locale_context
    assert 'href={locale === "en" ? "/geode/report-en.pdf" : "/geode/report.pdf"}' in portfolio
    assert (REPO_ROOT / "site/public/report.pdf").is_file()
    assert (REPO_ROOT / "site/public/report-en.pdf").is_file()
    assert "{showLocaleToggle ? <LocaleToggle /> : null}" in nav


def test_portfolio_install_surface_and_static_hero() -> None:
    portfolio = PORTFOLIO_PATH.read_text(encoding="utf-8")

    assert "anthropic / claude-fable-5 · ~/workspace" in portfolio
    assert "const supportedProviders = [" in portfolio
    for provider in ("Anthropic", "OpenAI / Codex", "ZhipuAI GLM"):
        assert f'"{provider}"' in portfolio
    assert "supported providers" in portfolio
    assert 'aria-label="Supported providers"' in portfolio
    assert 'noteEn: "Latest stable release in an isolated tool environment."' in portfolio
    assert "flex flex-nowrap items-center justify-between" in portfolio
    assert "min-w-0 flex-1" in portfolio
    assert "shrink-0 touch-manipulation" in portfolio

    hero = portfolio.split("function HeroField()", 1)[1].split("function LoopDiagram()", 1)[0]
    assert "geode-sky.png" in hero
    assert 'className="pointer-events-none absolute inset-y-0 right-0 hidden w-[44%]' in hero
    assert "lg:w-[74%] xl:w-[62%]" in hero
    assert "WebkitTextStroke" not in hero
    assert "0 3px 0 rgba(127, 23, 71, 0.32)" in hero
    assert "HeroPixelField" not in hero

    assert '<section id="install" className="bg-[var(--acc-artifact)]">' in portfolio
    assert 'className="install-terminal ' in portfolio and "ROSE_FIELD_INK" not in portfolio
    assert "--paper-deep: #55263a;" in PORTFOLIO_PATH.with_name("astryx-geode.css").read_text()
