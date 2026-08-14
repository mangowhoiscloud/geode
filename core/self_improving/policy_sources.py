"""Self-improving product policy-source composition.

The feature owns its filesystem layout.  Kernel readers receive only this
immutable neutral bundle and therefore do not know autoresearch path names.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from core.config.policy_source import PolicySourceBundle, PolicySourcePaths
from core.paths import (
    AUTORESEARCH_AGENT_CONTRACTS_PATH,
    AUTORESEARCH_CACHE_POLICY_PATH,
    AUTORESEARCH_DECOMPOSITION_POLICY_PATH,
    AUTORESEARCH_FEW_SHOT_POOL_PATH,
    AUTORESEARCH_HEURISTICS_PATH,
    AUTORESEARCH_IN_CONTEXT_SLOTS_PATH,
    AUTORESEARCH_PROVIDER_ROUTING_PATH,
    AUTORESEARCH_REFLECTION_POLICY_PATH,
    AUTORESEARCH_SKILL_CATALOG_PATH,
    AUTORESEARCH_STYLE_GUIDE_PATH,
    AUTORESEARCH_TOOL_DESCRIPTIONS_PATH,
    AUTORESEARCH_TOOL_POLICY_PATH,
    AUTORESEARCH_WRAPPER_SECTIONS_PATH,
    OPERATOR_LOCAL_AGENT_CONTRACTS_PATH,
    OPERATOR_LOCAL_CACHE_POLICY_PATH,
    OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH,
    OPERATOR_LOCAL_FEW_SHOT_POOL_PATH,
    OPERATOR_LOCAL_HEURISTICS_PATH,
    OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH,
    OPERATOR_LOCAL_PROVIDER_ROUTING_PATH,
    OPERATOR_LOCAL_REFLECTION_POLICY_PATH,
    OPERATOR_LOCAL_SKILL_CATALOG_PATH,
    OPERATOR_LOCAL_STYLE_GUIDE_PATH,
    OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH,
    OPERATOR_LOCAL_TOOL_POLICY_PATH,
)


def build_policy_source_bundle() -> PolicySourceBundle:
    """Return the product's immutable policy candidates."""

    def paths(
        override_env: str,
        operator_local: Path,
        packaged_default: Path,
    ) -> PolicySourcePaths:
        return PolicySourcePaths(override_env, operator_local, packaged_default)

    return MappingProxyType(
        {
            "wrapper_sections": PolicySourcePaths(
                "GEODE_WRAPPER_OVERRIDE",
                packaged_default=AUTORESEARCH_WRAPPER_SECTIONS_PATH,
                override_is_strict=True,
            ),
            "tool_policy": paths(
                "GEODE_TOOL_POLICY_OVERRIDE",
                OPERATOR_LOCAL_TOOL_POLICY_PATH,
                AUTORESEARCH_TOOL_POLICY_PATH,
            ),
            "decomposition": paths(
                "GEODE_DECOMPOSITION_POLICY_OVERRIDE",
                OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH,
                AUTORESEARCH_DECOMPOSITION_POLICY_PATH,
            ),
            "reflection": paths(
                "GEODE_REFLECTION_POLICY_OVERRIDE",
                OPERATOR_LOCAL_REFLECTION_POLICY_PATH,
                AUTORESEARCH_REFLECTION_POLICY_PATH,
            ),
            "tool_descriptions": paths(
                "GEODE_TOOL_DESCRIPTIONS_OVERRIDE",
                OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH,
                AUTORESEARCH_TOOL_DESCRIPTIONS_PATH,
            ),
            "skill_catalog": paths(
                "GEODE_SKILL_CATALOG_OVERRIDE",
                OPERATOR_LOCAL_SKILL_CATALOG_PATH,
                AUTORESEARCH_SKILL_CATALOG_PATH,
            ),
            "style_guide": paths(
                "GEODE_STYLE_GUIDE_OVERRIDE",
                OPERATOR_LOCAL_STYLE_GUIDE_PATH,
                AUTORESEARCH_STYLE_GUIDE_PATH,
            ),
            "provider_routing": paths(
                "GEODE_PROVIDER_ROUTING_OVERRIDE",
                OPERATOR_LOCAL_PROVIDER_ROUTING_PATH,
                AUTORESEARCH_PROVIDER_ROUTING_PATH,
            ),
            "cache_policy": paths(
                "GEODE_CACHE_POLICY_OVERRIDE",
                OPERATOR_LOCAL_CACHE_POLICY_PATH,
                AUTORESEARCH_CACHE_POLICY_PATH,
            ),
            "heuristics": paths(
                "GEODE_HEURISTICS_OVERRIDE",
                OPERATOR_LOCAL_HEURISTICS_PATH,
                AUTORESEARCH_HEURISTICS_PATH,
            ),
            "in_context_slots": paths(
                "GEODE_IN_CONTEXT_SLOTS_OVERRIDE",
                OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH,
                AUTORESEARCH_IN_CONTEXT_SLOTS_PATH,
            ),
            "agent_contracts": paths(
                "GEODE_AGENT_CONTRACTS_OVERRIDE",
                OPERATOR_LOCAL_AGENT_CONTRACTS_PATH,
                AUTORESEARCH_AGENT_CONTRACTS_PATH,
            ),
            "few_shot_pool": paths(
                "GEODE_FEW_SHOT_POOL_OVERRIDE",
                OPERATOR_LOCAL_FEW_SHOT_POOL_PATH,
                AUTORESEARCH_FEW_SHOT_POOL_PATH,
            ),
        }
    )


__all__ = ["build_policy_source_bundle"]
