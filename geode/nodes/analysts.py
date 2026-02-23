"""Layer 3: Analysts — 4 parallel analysts using Send API pattern.

Each analyst gets a Clean Context (no access to other analysts' scores)
to prevent anchoring bias.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from geode.infrastructure.ports.llm_port import get_llm_json
from geode.llm.prompts import ANALYST_SPECIFIC, ANALYST_SYSTEM, ANALYST_USER
from geode.state import AnalysisResult, GeodeState

log = logging.getLogger(__name__)

ANALYST_TYPES = ["game_mechanics", "player_experience", "growth_potential", "discovery"]


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_analyst_prompt(analyst_type: str, state: GeodeState) -> tuple[str, str]:
    """Build system + user prompt for an analyst, with Clean Context."""
    ip = state["ip_info"]
    ml = state["monolake"]
    sig = state["signals"]

    system = ANALYST_SYSTEM.format(analyst_type=analyst_type)
    user = ANALYST_USER.format(
        analyst_type=analyst_type,
        ip_name=ip["ip_name"],
        media_type=ip["media_type"],
        release_year=ip["release_year"],
        studio=ip["studio"],
        genre=", ".join(ip["genre"]) if isinstance(ip["genre"], list) else ip["genre"],
        synopsis=ip["synopsis"],
        dau_current=ml["dau_current"],
        revenue_ltm=ml["revenue_ltm"],
        active_game_count=ml["active_game_count"],
        last_game_year=ml["last_game_year"],
        youtube_views=sig["youtube_views"],
        reddit_subscribers=sig["reddit_subscribers"],
        fan_art_yoy_pct=sig["fan_art_yoy_pct"],
        google_trends_index=sig["google_trends_index"],
        twitter_mentions_monthly=sig["twitter_mentions_monthly"],
        analyst_specific_prompt=ANALYST_SPECIFIC[analyst_type],
    )
    return system, user


def _run_analyst(analyst_type: str, state: GeodeState) -> AnalysisResult:
    """Run a single analyst via Claude API."""
    system, user = _build_analyst_prompt(analyst_type, state)
    if state.get("verbose"):
        log.debug("Running %s analyst...", analyst_type)

    if state.get("dry_run"):
        return _dry_run_result(analyst_type, state.get("ip_name", ""))

    data = get_llm_json()(system, user)
    try:
        return AnalysisResult(**data)
    except ValidationError as ve:
        log.warning("Analyst %s LLM response failed schema validation: %s", analyst_type, ve)
        return AnalysisResult(
            analyst_type=analyst_type,
            score=1.0,
            key_finding="LLM response failed validation (degraded)",
            reasoning="Schema validation failed",
            evidence=[],
            confidence=0.0,
        )


def _dry_run_result(analyst_type: str, ip_name: str = "") -> AnalysisResult:
    """Return IP-specific mock results for dry-run mode."""
    key = ip_name.lower().strip()

    # --- Cowboy Bebop (B2: Mechanics 4.2, Experience 4.0, Growth 4.5, Discovery 3.8)
    cowboy_bebop = {
        "game_mechanics": AnalysisResult(
            analyst_type="game_mechanics",
            score=4.2,
            key_finding="Bounty hunting loop with martial arts combat",
            reasoning=(
                "The bounty-of-the-week structure maps directly to mission-based "
                "gameplay. Spike's Jeet Kune Do and Jigen's gunplay provide "
                "diverse combat archetypes with high skill ceiling."
            ),
            evidence=["Natural mission loop (bounty hunting)", "Diverse combat styles"],
            confidence=85.0,
        ),
        "player_experience": AnalysisResult(
            analyst_type="player_experience",
            score=4.0,
            key_finding="90s noir SF, iconic character arcs",
            reasoning=(
                "The 2071 solar system setting offers diverse environments from "
                "Mars cities to asteroid bases. The bounty hunting profession "
                "provides natural immersion and narrative depth."
            ),
            evidence=["Complex protagonist Spike Spiegel", "Multi-layered story arcs"],
            confidence=82.0,
        ),
        "growth_potential": AnalysisResult(
            analyst_type="growth_potential",
            score=4.5,
            key_finding="12M views, organic growth +42%",
            reasoning=(
                "Strong fandom with 12M YouTube views and 180K Reddit "
                "subscribers despite no active game. Fan art growth of "
                "+42% YoY indicates organic momentum."
            ),
            evidence=["YouTube 12M views", "Reddit 180K subs", "Fan art +42% YoY"],
            confidence=90.0,
        ),
        "discovery": AnalysisResult(
            analyst_type="discovery",
            score=3.8,
            key_finding="Action RPG gap, no direct rival",
            reasoning=(
                "No major anime-based space bounty hunter game exists. "
                "Action RPG genre fit with low competitor density creates "
                "a clear market opportunity."
            ),
            evidence=["No direct IP competitor in games", "Action RPG genre fit"],
            confidence=78.0,
        ),
    }

    # --- Berserk
    berserk = {
        "game_mechanics": AnalysisResult(
            analyst_type="game_mechanics",
            score=4.8,
            key_finding="Souls-like combat with Dragonslayer weapon system",
            reasoning=(
                "Guts' combat style maps perfectly to Souls-like mechanics. "
                "The Dragonslayer's weight, berserker armor risk/reward, and "
                "apostle boss fights create compelling gameplay loops."
            ),
            evidence=[
                "Natural Souls-like combat mapping",
                "Risk/reward berserker armor mechanic",
            ],
            confidence=92.0,
        ),
        "player_experience": AnalysisResult(
            analyst_type="player_experience",
            score=4.7,
            key_finding="Epic dark fantasy with profound character depth",
            reasoning=(
                "Midland, the Astral World, and the demonic Eclipse offer "
                "massive environmental variety. Guts' journey is one of the "
                "most compelling revenge narratives in manga."
            ),
            evidence=[
                "Multi-layered world (physical + astral)",
                "Complex Guts-Griffith dynamic",
            ],
            confidence=90.0,
        ),
        "growth_potential": AnalysisResult(
            analyst_type="growth_potential",
            score=4.9,
            key_finding="25M views, 520K Reddit, explosive +65% YoY",
            reasoning=(
                "One of the strongest fandoms in anime/manga. Reddit 520K "
                "subscribers, YouTube 25M views, fan art +65% YoY. Demand for "
                "a Souls-like Berserk game is extremely vocal."
            ),
            evidence=["YouTube 25M views", "Reddit 520K subs", "Fan art +65% YoY"],
            confidence=95.0,
        ),
        "discovery": AnalysisResult(
            analyst_type="discovery",
            score=4.2,
            key_finding="Souls-like gap, Elden Ring proves demand",
            reasoning=(
                "Elden Ring's success proves demand for dark fantasy action "
                "RPGs. Berserk's direct influence on the Souls genre creates "
                "a unique competitive advantage."
            ),
            evidence=[
                "Elden Ring/Dark Souls influenced by Berserk",
                "No direct Berserk Souls-like",
            ],
            confidence=88.0,
        ),
    }

    # --- Ghost in the Shell
    ghost_in_shell = {
        "game_mechanics": AnalysisResult(
            analyst_type="game_mechanics",
            score=3.8,
            key_finding="Stealth/hacking hybrid with cyberization upgrades",
            reasoning=(
                "Section 9 operations enable stealth-action gameplay. "
                "Cyberization technology creates natural upgrade/skill trees. "
                "Hacking mini-games add mechanical variety."
            ),
            evidence=["Stealth-action mission design", "Cyberization progression"],
            confidence=75.0,
        ),
        "player_experience": AnalysisResult(
            analyst_type="player_experience",
            score=4.0,
            key_finding="Philosophical cyberpunk with deep world immersion",
            reasoning=(
                "New Port City is a fully realized cyberpunk environment. "
                "Deep philosophical themes on consciousness and identity "
                "create memorable player experiences."
            ),
            evidence=[
                "Detailed urban environments",
                "Complex political narratives",
            ],
            confidence=80.0,
        ),
        "growth_potential": AnalysisResult(
            analyst_type="growth_potential",
            score=3.5,
            key_finding="8.5M views, stable but aging community",
            reasoning=(
                "Established fanbase but growth has stagnated. Reddit 95K "
                "and YouTube 8.5M are solid but not accelerating."
            ),
            evidence=["YouTube 8.5M views", "Reddit 95K subs", "Fan art +28% YoY"],
            confidence=70.0,
        ),
        "discovery": AnalysisResult(
            analyst_type="discovery",
            score=3.2,
            key_finding="Crowded cyberpunk market post-2077",
            reasoning=(
                "Cyberpunk 2077's dominance makes market entry harder. Need "
                "differentiation through stealth/hacking mechanics rather "
                "than open-world combat."
            ),
            evidence=["Cyberpunk 2077 market presence", "Stealth genre opportunity"],
            confidence=72.0,
        ),
    }

    ip_mocks = {
        "cowboy bebop": cowboy_bebop,
        "berserk": berserk,
        "ghost in the shell": ghost_in_shell,
    }

    mock = ip_mocks.get(key, cowboy_bebop)
    return mock.get(analyst_type, mock["game_mechanics"])


def analyst_node(state: GeodeState) -> dict[str, Any]:
    """Run a single analyst. Called via Send API for parallel execution."""
    try:
        analyst_type = state.get("_analyst_type", "narrative")
        result = _run_analyst(analyst_type, state)
        return {"analyses": [result]}
    except Exception as exc:
        log.error("Node analyst (%s) failed: %s", state.get("_analyst_type", "?"), exc)
        return {"analyses": [], "errors": [f"analyst: {exc}"]}


def make_analyst_sends(state: GeodeState) -> list:
    """Create Send objects for all 4 analysts."""
    from langgraph.types import Send

    sends = []
    for atype in ANALYST_TYPES:
        # Clean Context: only pass necessary data, NOT other analysts' results
        send_state = {
            "ip_name": state["ip_name"],
            "ip_info": state["ip_info"],
            "monolake": state["monolake"],
            "signals": state["signals"],
            "dry_run": state.get("dry_run", False),
            "verbose": state.get("verbose", False),
            "_analyst_type": atype,
            "analyses": [],
            "errors": [],
        }
        sends.append(Send("analyst", send_state))
    return sends
