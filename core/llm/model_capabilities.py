"""Anthropic model-capability sets — single SoT (PR-DRIFT-ANCHORS, 2026-06-10).

Before this module, the same "which Anthropic models support X" facts were
hardcoded independently in ``core/llm/providers/anthropic.py`` (adapter
request shaping) and ``core/cli/effort_picker.py`` (which knobs the picker
surfaces), with a "Keep these in sync" comment standing in for an actual
anchor. Model onboarding meant N independent edits and one missed edit
meant "the new model silently doesn't work on this one surface" — exactly
the 2026-05-29 incident where the opus-4-8 onboarding missed the
seed-generation role allowlist ([[reference_model_compat_surfaces]]).

Onboarding a new Anthropic model now means editing THIS file (plus pricing
TOML); both consumers import from here. The ``model-onboarding`` scaffold
skill points here.

Capability provenance (doc-before-behaviour, CANNOT §4d): adaptive thinking
+ sampling-parameter removal per the platform 4.6/4.7 model pages; xhigh
on 4.7/4.8 and opus-4-8 1M/compaction confirmed live by the running
harness (Claude Code /model configures claude-opus-4-8 with xhigh effort).
"""

from __future__ import annotations

# Models that support server-side context management + compaction beta
# (compact-2026-01-12). Haiku 4.5 predates the beta and rejects its header
# with a 400 whose message contains "context" — misclassified as
# context_overflow. Only 1M-context models are known to support it.
ANTHROPIC_CONTEXT_MGMT_MODELS: frozenset[str] = frozenset(
    {
        # Fable 5 (2026-06-09 GA): 1M ctx + compaction supported; adaptive
        # thinking always-on (thinking:{type:"disabled"} errors — omit or send
        # adaptive); sampling params 400; effort incl. xhigh supported.
        # ref: https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
    }
)

# Adaptive-thinking models (Opus 4.6+ / Sonnet 4.6). Sampling parameters
# (temperature/top_p/top_k) are rejected with 400 from Opus 4.7 and by
# Opus 4.6 under adaptive thinking — omit them entirely on these models.
# The effort knob (incl. xhigh) only exists for adaptive models.
ANTHROPIC_ADAPTIVE_MODELS: frozenset[str] = frozenset(
    {
        # Fable 5 (2026-06-09 GA): 1M ctx + compaction supported; adaptive
        # thinking always-on (thinking:{type:"disabled"} errors — omit or send
        # adaptive); sampling params 400; effort incl. xhigh supported.
        # ref: https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
    }
)

# Models that accept ``output_config.effort = "xhigh"`` (one step above
# high). 4.6 / Sonnet 4.6 reject it with 400.
ANTHROPIC_XHIGH_MODELS: frozenset[str] = frozenset(
    {
        # Fable 5 (2026-06-09 GA): 1M ctx + compaction supported; adaptive
        # thinking always-on (thinking:{type:"disabled"} errors — omit or send
        # adaptive); sampling params 400; effort incl. xhigh supported.
        # ref: https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
    }
)

# Models documented to support the ``web_search_20260209`` server tool.
# ref: https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
# (verified 2026-06-12) — "The latest web search tool version
# (web_search_20260209) supports dynamic filtering with Claude Fable 5,
# Claude Opus 4.8, Claude Mythos 5, Claude Mythos Preview, Claude Opus 4.7,
# Claude Opus 4.6, and Claude Sonnet 4.6." Mythos models are not in GEODE's
# routing set and are intentionally omitted. A session model outside this
# set escalates to ANTHROPIC_PRIMARY for the search call
# (core/llm/adapters/_capability_impls.py:resolve_web_search_model) instead
# of risking an undocumented model+tool pairing.
ANTHROPIC_WEB_SEARCH_20260209_MODELS: frozenset[str] = frozenset(
    {
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
    }
)

# Computer-use tool generation per model (doc-before-behaviour, CANNOT §4d).
# ref: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
#   beta "computer-use-2025-11-24" + tool type "computer_20251124"
#       → Opus 4.8 / 4.7 / 4.6, Sonnet 4.6, Opus 4.5  (the current generation)
#   beta "computer-use-2025-01-24" + tool type "computer_20250124"
#       → Sonnet 4.5, Haiku 4.5, (deprecated) Opus 4.1 / Sonnet 4 / Opus 4
# The SDK's ``AnthropicBetaParam`` Literal does NOT yet enumerate
# "computer-use-2025-11-24" ("typed constant pending in the Go SDK" per the
# docs example) — it is sent as a plain string, which the ``Union[str,
# Literal]`` type permits. ctx7's SDK snapshot lagged here; the docs page is
# the SoT.
#
# This set is the LEGACY (2025-01-24) generation; every other model — incl.
# Fable 5 and any future model — defaults to the 2025-11-24 generation so a
# newly onboarded model tracks the newer beta automatically.
ANTHROPIC_COMPUTER_USE_LEGACY_MODELS: frozenset[str] = frozenset(
    {
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
        "claude-opus-4-1",
        "claude-sonnet-4",
        "claude-opus-4",
    }
)
