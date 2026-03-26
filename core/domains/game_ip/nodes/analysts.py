"""Layer 3: Analysts — 4 parallel analysts using Send API pattern.

Each analyst gets a Clean Context (no access to other analysts' scores)
to prevent anchoring bias.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from core.config import get_node_model
from core.domains.port import get_domain_or_none
from core.llm.prompts import ANALYST_SPECIFIC, ANALYST_SYSTEM, ANALYST_TOOLS_SUFFIX, ANALYST_USER
from core.llm.router import (
    call_llm_with_tools,
    get_llm_json,
    get_llm_parsed,
    get_secondary_llm_json,
    get_secondary_llm_parsed,
)
from core.state import AnalysisResult, GeodeState
from core.tools.port import get_tool_executor

log = logging.getLogger(__name__)

ANALYST_TYPES: list[str] = list(ANALYST_SPECIFIC.keys())  # Keep for backward compat


def _get_analyst_types() -> list[str]:
    """Get analyst types from domain adapter if available, else static."""
    domain = get_domain_or_none()
    if domain is not None:
        return domain.get_analyst_types()
    return list(ANALYST_SPECIFIC.keys())


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_analyst_prompt(analyst_type: str, state: GeodeState) -> tuple[str, str]:
    """Build system + user prompt for an analyst, with Clean Context."""
    ip = state["ip_info"]
    ml = state["monolake"]
    sig = state["signals"]

    # ADR-007 Phase 2 step 16: Check if skill .md exists for this analyst type.
    # If skill exists -> skill handles specific guidance, ANALYST_SPECIFIC becomes redundant.
    assembler: Any = state.get("_prompt_assembler")
    has_skill = False
    if assembler is not None:
        has_skill = bool(assembler._skills.get_skills(node="analyst", role_type=analyst_type))

    # Try domain adapter first, fall back to static config
    domain = get_domain_or_none()
    analyst_specific_map = domain.get_analyst_specific() if domain is not None else ANALYST_SPECIFIC
    analyst_specific = "" if has_skill else analyst_specific_map.get(analyst_type, "")

    # Phase 1: Base template rendering
    output_language = state.get("output_language", "English")
    base_system = ANALYST_SYSTEM.format(analyst_type=analyst_type, output_language=output_language)
    base_user = ANALYST_USER.format(
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
        analyst_specific_prompt=analyst_specific,
    )

    # Phase 2: PromptAssembler injection (ADR-007)
    if assembler is not None:
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=dict(state),
            node="analyst",
            role_type=analyst_type,
        )
        return result.system, result.user

    # Fallback: no assembler
    return base_system, base_user


# Default ensemble configuration (matches Settings defaults)
_DEFAULT_SECONDARY_ANALYSTS = "player_experience,discovery"
_DEFAULT_PRIMARY_ANALYSTS = "game_mechanics,growth_potential"
_DEFAULT_ENSEMBLE_MODE = "single"


def _should_use_secondary(
    analyst_type: str,
    *,
    ensemble_mode: str = _DEFAULT_ENSEMBLE_MODE,
    secondary_analysts: str = _DEFAULT_SECONDARY_ANALYSTS,
) -> bool:
    """Determine whether this analyst should use the secondary LLM in cross mode."""
    if ensemble_mode != "cross":
        return False
    return analyst_type in set(secondary_analysts.split(","))


def _run_analyst(analyst_type: str, state: GeodeState) -> AnalysisResult:
    """Run a single analyst via Claude API with structured output."""
    system, user = _build_analyst_prompt(analyst_type, state)
    if state.get("verbose"):
        log.debug("Running %s analyst...", analyst_type)

    if state.get("dry_run"):
        return get_dry_run_result(analyst_type, state.get("ip_name", ""))

    # Tool-augmented path: if _tool_definitions available, analyst can query
    # memory/monolake for historical context before generating analysis.
    tool_defs: Any = state.get("_tool_definitions", [])
    tool_executor = get_tool_executor()
    if tool_defs and tool_executor is not None:
        try:
            enhanced_system = system + "\n\n" + ANALYST_TOOLS_SUFFIX
            result = call_llm_with_tools(
                enhanced_system,
                user,
                tools=tool_defs,
                tool_executor=tool_executor,
                temperature=0.5,
                max_tool_rounds=2,
                model=get_node_model("analyst"),
            )
            if result.text:
                data = json.loads(result.text)
                analysis = AnalysisResult(**data)
                if analysis.analyst_type != analyst_type:
                    analysis = analysis.model_copy(update={"analyst_type": analyst_type})
                analysis = analysis.model_copy(update={"model_provider": "primary"})
                return analysis
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            log.warning(
                "Analyst %s tool-augmented path failed: %s — falling back",
                analyst_type,
                exc,
            )
        except Exception as exc:
            log.debug("Analyst %s tool-augmented path unexpected error: %s", analyst_type, exc)

    # Determine which LLM to use based on ensemble mode
    # Ensemble config injected via state from graph/runtime layer
    ensemble_mode = str(state.get("_ensemble_mode", _DEFAULT_ENSEMBLE_MODE))
    secondary_analysts_csv = str(state.get("_secondary_analysts", _DEFAULT_SECONDARY_ANALYSTS))
    use_secondary = _should_use_secondary(
        analyst_type,
        ensemble_mode=ensemble_mode,
        secondary_analysts=secondary_analysts_csv,
    )
    model_provider: str = "primary"

    if use_secondary:
        secondary_parsed = get_secondary_llm_parsed()
        secondary_json = get_secondary_llm_json()
        if secondary_parsed is not None or secondary_json is not None:
            model_provider = "secondary"
            log.debug("Analyst %s using secondary LLM (cross-ensemble mode)", analyst_type)
        else:
            log.debug(
                "Analyst %s: secondary LLM not available, falling back to primary",
                analyst_type,
            )
            use_secondary = False

    # Select the callable pair based on ensemble routing
    parsed_fn = get_secondary_llm_parsed() if use_secondary else get_llm_parsed()
    json_fn = get_secondary_llm_json() if use_secondary else get_llm_json()

    # Use Anthropic Structured Output (messages.parse) for guaranteed JSON
    # Analyst temperature 0.5 (higher than default 0.3 for diverse perspectives)
    if parsed_fn is not None:
        try:
            result = parsed_fn(
                system,
                user,
                output_model=AnalysisResult,
                temperature=0.5,
                model=get_node_model("analyst"),
            )
            # Ensure analyst_type matches
            if result.analyst_type != analyst_type:
                result = result.model_copy(update={"analyst_type": analyst_type})
            result = result.model_copy(update={"model_provider": model_provider})
            return result
        except Exception as exc:
            log.warning(
                "Analyst %s structured output failed: %s — falling back to legacy JSON parse",
                analyst_type,
                exc,
            )

    # Fallback: legacy JSON parse
    if json_fn is not None:
        try:
            data = json_fn(system, user, temperature=0.5, model=get_node_model("analyst"))
            result = AnalysisResult(**data)
            result = result.model_copy(update={"model_provider": model_provider})
            return result
        except (ValidationError, ValueError) as ve:
            log.warning("Analyst %s legacy fallback also failed: %s", analyst_type, ve)

    return AnalysisResult(
        analyst_type=analyst_type,
        score=1.0,
        key_finding="[DEGRADED] LLM response failed validation",
        reasoning="Schema validation failed — degraded result",
        evidence=["validation_error"],
        confidence=0.0,
        is_degraded=True,
        model_provider=model_provider,
    )


def get_dry_run_result(analyst_type: str, ip_name: str = "") -> AnalysisResult:
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
        # Defensive confidence clamp [0, 100] (Karpathy P1 #4)
        if result.confidence < 0.0 or result.confidence > 100.0:
            log.warning(
                "Analyst %s confidence out of range: %.1f → clamped to [0, 100]",
                analyst_type,
                result.confidence,
            )
            result = result.model_copy(
                update={"confidence": max(0.0, min(100.0, result.confidence))}
            )
        return {"analyses": [result]}
    except Exception as exc:
        log.error("Node analyst (%s) failed: %s", state.get("_analyst_type", "?"), exc)
        return {"analyses": [], "errors": [f"analyst: {exc}"]}


def make_analyst_sends(state: GeodeState) -> list[Any]:
    """Create Send objects for analysts.

    Phase 3-B partial retry: on iteration >= 2, only re-run analysts whose
    previous results were degraded or had zero confidence. Good results are
    preserved from the prior iteration.
    """
    from langgraph.types import Send

    iteration = state.get("iteration", 1)
    existing_analyses: list[AnalysisResult] = state.get("analyses", [])

    # Identify analysts that already have good results (skip on re-iteration)
    skip_types: set[str] = set()
    if iteration >= 2 and existing_analyses:
        for a in existing_analyses:
            if not getattr(a, "is_degraded", False) and getattr(a, "confidence", 0) > 0:
                skip_types.add(a.analyst_type)

    sends = []
    for atype in _get_analyst_types():
        if atype in skip_types:
            log.info("Partial retry: skipping %s analyst (good prior result)", atype)
            continue
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
            # ADR-007: bootstrap + memory key propagation
            "_prompt_overrides": state.get("_prompt_overrides", {}),
            "_extra_instructions": state.get("_extra_instructions", []),
            "memory_context": state.get("memory_context"),
            # Phase 2: tool definitions propagation for tool-augmented analysts
            "_tool_definitions": state.get("_tool_definitions", []),
            # Ensemble config propagation (L5→state injection)
            "_ensemble_mode": state.get("_ensemble_mode", _DEFAULT_ENSEMBLE_MODE),
            "_secondary_analysts": state.get("_secondary_analysts", _DEFAULT_SECONDARY_ANALYSTS),
        }
        sends.append(Send("analyst", send_state))
    return sends
