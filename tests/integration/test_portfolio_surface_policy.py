from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTFOLIO_PATH = REPO_ROOT / "site/src/app/portfolio/page.tsx"
LOCALE_CONTEXT_PATH = REPO_ROOT / "site/src/components/geode/locale-context.tsx"
NAV_PATH = REPO_ROOT / "site/src/components/geode/sections/nav.tsx"


def test_portfolio_is_fixed_to_english() -> None:
    portfolio = PORTFOLIO_PATH.read_text(encoding="utf-8")
    locale_context = LOCALE_CONTEXT_PATH.read_text(encoding="utf-8")
    nav = NAV_PATH.read_text(encoding="utf-8")

    assert '<LocaleProvider defaultLocale="en" allowQueryOverride={false}>' in portfolio
    assert '<main\n        lang="en"' in portfolio
    assert "<GeodeNav items={navItems} light showLocaleToggle={false} />" in portfolio
    assert "if (!allowQueryOverride) return;" in locale_context
    assert "{showLocaleToggle ? <LocaleToggle /> : null}" in nav


def test_portfolio_install_surface_and_static_hero() -> None:
    portfolio = PORTFOLIO_PATH.read_text(encoding="utf-8")

    assert "anthropic / claude-fable-5 · ~/workspace" in portfolio
    assert (
        'const supportedProviders = ["Anthropic", "OpenAI / Codex", "ZhipuAI GLM"] as const;'
        in portfolio
    )
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
    assert 'WebkitTextStroke: "1.25px #7F1747"' in hero
    assert "HeroPixelField" not in hero

    assert 'const ROSE_FIELD_INK = "#7F1747";' in portfolio
    assert "style={{ color: ROSE_FIELD_INK }}" in portfolio
    assert "text-[#7F1747]" in portfolio
