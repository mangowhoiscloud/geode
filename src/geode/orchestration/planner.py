"""Planner — route user input to the optimal pipeline mode.

Layer 4 orchestration component that classifies user requests
and selects the best execution route (rule-based for demo,
LLM-powered in production).

Routes:
    script_route    — /command shortcuts ($0.05, ~15s)
    direct_answer   — Memory cache hit within TTL ($0.02, ~3s)
    data_refresh    — Data TTL expired, re-fetch only ($0.30, ~45s)
    partial_rerun   — Re-analyze a specific aspect ($0.15, ~30s)
    prospect        — Non-gamified IP analysis ($0.80, ~80s)
    full_pipeline   — Full end-to-end analysis ($1.50, ~120s)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)

# Memory cache TTL for direct_answer route (seconds)
DEFAULT_MEMORY_TTL_S = 600.0  # 10 minutes


class Route(Enum):
    """Available pipeline execution routes."""

    FULL_PIPELINE = "full_pipeline"
    PROSPECT = "prospect"
    DIRECT_ANSWER = "direct_answer"
    PARTIAL_RERUN = "partial_rerun"
    DATA_REFRESH = "data_refresh"
    SCRIPT_ROUTE = "script_route"


@dataclass(frozen=True)
class RouteProfile:
    """Cost and time profile for a route."""

    route: Route
    estimated_cost: float  # USD
    estimated_time_s: float  # seconds
    description: str


# Pre-defined profiles for each route
ROUTE_PROFILES: dict[Route, RouteProfile] = {
    Route.SCRIPT_ROUTE: RouteProfile(
        route=Route.SCRIPT_ROUTE,
        estimated_cost=0.05,
        estimated_time_s=15.0,
        description="Execute a CLI command shortcut",
    ),
    Route.DIRECT_ANSWER: RouteProfile(
        route=Route.DIRECT_ANSWER,
        estimated_cost=0.02,
        estimated_time_s=3.0,
        description="Answer from memory cache (no pipeline execution)",
    ),
    Route.DATA_REFRESH: RouteProfile(
        route=Route.DATA_REFRESH,
        estimated_cost=0.30,
        estimated_time_s=45.0,
        description="Re-fetch stale data without full re-analysis",
    ),
    Route.PARTIAL_RERUN: RouteProfile(
        route=Route.PARTIAL_RERUN,
        estimated_cost=0.15,
        estimated_time_s=30.0,
        description="Re-analyze a specific dimension or aspect",
    ),
    Route.PROSPECT: RouteProfile(
        route=Route.PROSPECT,
        estimated_cost=0.80,
        estimated_time_s=80.0,
        description="Full analysis for a non-gamified IP",
    ),
    Route.FULL_PIPELINE: RouteProfile(
        route=Route.FULL_PIPELINE,
        estimated_cost=1.50,
        estimated_time_s=120.0,
        description="Full end-to-end pipeline analysis",
    ),
}

# Patterns for aspect-specific re-analysis
_ASPECT_PATTERNS: list[str] = [
    r"\bre[- ]?(analyz|evaluat|scor|check)",
    r"\b(only|just)\s+(the\s+)?(scoring|evaluation|synthesis|signal)",
    r"\bpartial\b",
]

# Patterns for prospect (non-gamified) IPs
_PROSPECT_PATTERNS: list[str] = [
    r"\b(novel|manga|anime|webtoon|film|movie|book|drama|show)\b",
    r"\bnon-?gam(e|ified)\b",
    r"\bprospect\b",
]


@dataclass(frozen=True)
class PlannerDecision:
    """Result of the planner's routing decision."""

    route: Route
    intent: str
    requires_plan_mode: bool
    estimated_cost: float
    estimated_time_s: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def profile(self) -> RouteProfile:
        """Get the full route profile."""
        return ROUTE_PROFILES[self.route]


@dataclass
class _CacheEntry:
    """Internal memory cache record."""

    ip_name: str
    timestamp: float
    data: dict[str, Any]


class Planner:
    """Route user input to the optimal pipeline execution mode.

    Uses rule-based classification (no LLM dependency for demo).
    In production, this would use an LLM for intent classification.

    Usage:
        planner = Planner()
        decision = planner.classify("Analyze Berserk")
        # → PlannerDecision(route=FULL_PIPELINE, ...)

        decision = planner.classify("/status")
        # → PlannerDecision(route=SCRIPT_ROUTE, ...)
    """

    def __init__(
        self,
        *,
        memory_ttl_s: float = DEFAULT_MEMORY_TTL_S,
    ) -> None:
        self._memory_ttl_s = memory_ttl_s
        self._cache: dict[str, _CacheEntry] = {}
        self._stats = _PlannerStats()

    @property
    def stats(self) -> _PlannerStats:
        return self._stats

    @property
    def memory_ttl_s(self) -> float:
        return self._memory_ttl_s

    def cache_result(self, ip_name: str, data: dict[str, Any]) -> None:
        """Store a pipeline result in the memory cache."""
        self._cache[ip_name.lower()] = _CacheEntry(
            ip_name=ip_name,
            timestamp=time.time(),
            data=data,
        )

    def get_cached(self, ip_name: str) -> dict[str, Any] | None:
        """Retrieve a cached result if within TTL."""
        entry = self._cache.get(ip_name.lower())
        if entry is None:
            return None
        elapsed = time.time() - entry.timestamp
        if elapsed > self._memory_ttl_s:
            return None
        return entry.data

    def invalidate_cache(self, ip_name: str) -> bool:
        """Remove a specific entry from the cache. Returns True if found."""
        return self._cache.pop(ip_name.lower(), None) is not None

    def clear_cache(self) -> int:
        """Clear the entire memory cache. Returns entries removed."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def classify(self, user_input: str, *, ip_name: str | None = None) -> PlannerDecision:
        """Classify user input and return a routing decision.

        Args:
            user_input: Raw user input text.
            ip_name: Optional IP name for cache lookups.

        Returns:
            PlannerDecision with the selected route and metadata.
        """
        self._stats.classifications += 1
        text = user_input.strip()

        # Rule 1: /command → script_route
        if text.startswith("/"):
            self._stats.by_route[Route.SCRIPT_ROUTE] = (
                self._stats.by_route.get(Route.SCRIPT_ROUTE, 0) + 1
            )
            return self._make_decision(
                Route.SCRIPT_ROUTE,
                intent="command_shortcut",
                metadata={"command": text},
            )

        # Rule 2: Memory cache hit → direct_answer
        if ip_name:
            cached = self.get_cached(ip_name)
            if cached is not None:
                self._stats.cache_hits += 1
                self._stats.by_route[Route.DIRECT_ANSWER] = (
                    self._stats.by_route.get(Route.DIRECT_ANSWER, 0) + 1
                )
                return self._make_decision(
                    Route.DIRECT_ANSWER,
                    intent="cache_hit",
                    metadata={"ip_name": ip_name, "cached": True},
                )

        # Rule 3: Explicit refresh keywords → data_refresh
        if self._matches_refresh(text):
            self._stats.by_route[Route.DATA_REFRESH] = (
                self._stats.by_route.get(Route.DATA_REFRESH, 0) + 1
            )
            return self._make_decision(
                Route.DATA_REFRESH,
                intent="data_refresh",
            )

        # Rule 4: Aspect-specific re-analysis → partial_rerun
        if self._matches_aspect(text):
            self._stats.by_route[Route.PARTIAL_RERUN] = (
                self._stats.by_route.get(Route.PARTIAL_RERUN, 0) + 1
            )
            return self._make_decision(
                Route.PARTIAL_RERUN,
                intent="partial_reanalysis",
            )

        # Rule 5: Non-gamified IP → prospect
        if self._matches_prospect(text):
            self._stats.by_route[Route.PROSPECT] = self._stats.by_route.get(Route.PROSPECT, 0) + 1
            return self._make_decision(
                Route.PROSPECT,
                intent="non_gamified_ip",
                requires_plan=True,
            )

        # Rule 6: Default → full_pipeline
        self._stats.by_route[Route.FULL_PIPELINE] = (
            self._stats.by_route.get(Route.FULL_PIPELINE, 0) + 1
        )
        return self._make_decision(
            Route.FULL_PIPELINE,
            intent="full_analysis",
            requires_plan=True,
        )

    def _make_decision(
        self,
        route: Route,
        *,
        intent: str,
        requires_plan: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> PlannerDecision:
        profile = ROUTE_PROFILES[route]
        decision = PlannerDecision(
            route=route,
            intent=intent,
            requires_plan_mode=requires_plan,
            estimated_cost=profile.estimated_cost,
            estimated_time_s=profile.estimated_time_s,
            metadata=metadata or {},
        )
        log.info(
            "Planner → %s (intent=%s, cost=$%.2f, time=%.0fs)",
            route.value,
            intent,
            profile.estimated_cost,
            profile.estimated_time_s,
        )
        return decision

    @staticmethod
    def _matches_refresh(text: str) -> bool:
        """Check if input requests a data refresh."""
        pattern = r"\b(refresh|update|re-?fetch|stale|outdated)\b"
        return bool(re.search(pattern, text, re.IGNORECASE))

    @staticmethod
    def _matches_aspect(text: str) -> bool:
        """Check if input requests aspect-specific re-analysis."""
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in _ASPECT_PATTERNS)

    @staticmethod
    def _matches_prospect(text: str) -> bool:
        """Check if input describes a non-gamified IP."""
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in _PROSPECT_PATTERNS)


class _PlannerStats:
    """Track planner statistics."""

    def __init__(self) -> None:
        self.classifications: int = 0
        self.cache_hits: int = 0
        self.by_route: dict[Route, int] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "classifications": self.classifications,
            "cache_hits": self.cache_hits,
            "by_route": {r.value: c for r, c in self.by_route.items()},
        }
