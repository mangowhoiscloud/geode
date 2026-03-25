# GEODE Cause Classification Decision Tree

> SOT: `architecture-v6.md` §13.9.2

## Decision Tree (Code-based, NOT LLM)

```python
def _classify_cause(d_score, e_score, f_score, release_timing_issue=False):
    # Priority 1: Timing
    if release_timing_issue and d_score >= 3:
        return "timing_mismatch"

    # Priority 2: D >= 3 (marketing/exposure issues)
    if d_score >= 3:
        if e_score >= 3:
            return "conversion_failure"   # Both marketing + monetization
        return "undermarketed"            # Marketing only

    # Priority 3: D <= 2 (users arrive, problem elsewhere)
    if e_score >= 3:
        return "monetization_misfit"      # Users come, money doesn't

    if f_score >= 3:
        return "niche_gem"                # Quality, needs expansion

    return "discovery_failure"            # Complex multi-factor
```

## D-E-F Profile Matrix

| D (Acquisition) | E (Monetization) | F (Expansion) | Cause |
|:---:|:---:|:---:|-------|
| >= 3 | >= 3 | any | conversion_failure |
| >= 3 | < 3 | any | undermarketed |
| <= 2 | >= 3 | any | monetization_misfit |
| <= 2 | <= 2 | >= 3 | niche_gem |
| <= 2 | <= 2 | <= 2 | discovery_failure |
| >= 3 | any | any | timing_mismatch (if timing_issue) |

## Cause → Action Mapping (§13.9.3)

| Cause | Action | Description |
|-------|--------|-------------|
| undermarketed | marketing_boost | Marketing budget increase + channel diversification |
| conversion_failure | marketing_boost | Funnel + monetization simultaneous improvement |
| monetization_misfit | monetization_pivot | Pricing strategy + payment model redesign |
| niche_gem | platform_expansion | New platform launch or regional expansion |
| timing_mismatch | timing_optimization | Relaunch, remaster, or seasonal event |
| discovery_failure | community_activation | Community events + UGC activation |

## Timing Issue Detection

```python
def _detect_timing_issue(monolake):
    last_game = monolake.get("last_game_year", 0)
    active = monolake.get("active_game_count", 0)
    metacritic = monolake.get("metacritic_score", 0)
    return last_game > 0 and active == 0 and metacritic >= 60
```

Game existed, now inactive, was decent quality → timing problem, not quality problem.

## Fixture Validation

| IP | D | E | F | Timing? | Cause |
|----|---|---|---|---------|-------|
| Cowboy Bebop | 5 | 2 | 4 | No | undermarketed |
| Berserk | 4 | 4.5 | 4.5 | No | conversion_failure |
| Ghost in the Shell | 2 | 2 | 2 | No | discovery_failure |
