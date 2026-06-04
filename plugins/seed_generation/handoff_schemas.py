"""Per-role INPUT handoff JSON Schemas — symmetric counterpart to
``plugins/seed_generation/json_schemas.py`` (which declares the OUTPUT
shape each role produces).

PR-HANDOFF-SCHEMAS (2026-05-25) — when each role's ``_build_tasks``
runs, it composes a typed dict matching the matching ``*_HANDOFF``
schema below, then serializes it as a ``## HANDOFF CONTEXT``
JSON block appended to the LLM user message. The sub-agent reads
the prose for instruction and the JSON for accurate values
(``candidate_id``, dim_means, rewrite_section, etc.).

Drift between this file and the actual handoff dict shape is a
real bug: if the role's ``_build_description`` adds a new field
without updating the schema, the structured handoff loses its
type contract. Tests in
``tests/plugins/seed_generation/test_handoff_schemas.py`` enforce
the lockstep.

Design notes
============

- ``target_dim`` is a single ``str`` everywhere (the run's intended
  dim; ``PipelineState.target_dim: str`` is the SoT). Multi-dim
  attribution lives in seed frontmatter's ``target_dims: list[str]``
  and in critic OUTPUT's ``target_dims_actual: array of string``.
- Optional fields (baseline_evidence / supervisor_guidance /
  literature_articles / priors) are NOT in ``required`` — smoke 14
  and smoke 15 ran with some of these absent.
- ``additionalProperties`` is left default (true) so future
  optional fields can be added without breaking back-compat.
"""

from __future__ import annotations

from typing import Any, Final


def _additive(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Wrap a properties dict + required list into a complete JSON Schema.

    Mirror of ``plugins.seed_generation.json_schemas._additive`` —
    duplicated here to keep the two files mutually independent so
    one can be deleted without breaking the other.
    """
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# PR-SG-SELECTION-ALIGN (2026-05-25) — G1 anchor 3 dims field.
# Mirrors ``core.self_improving.loop.anchor_confidence.ANCHOR_DIMS_*``
# so the seed-gen LLM sees the same three dim names that drive the
# fitness multiplier (P3, ``anchor_confidence.compute_anchor_
# confidence_multiplier``). Surface fields are optional — when
# baseline_snapshot lacks anchor entries the key is omitted entirely
# and the LLM falls back to general framing.
ANCHOR_MEANS_FIELD: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "admirable": {"type": "number"},
        "disappointing": {"type": "number"},
        "needs_attention": {"type": "number"},
    },
}


GENERATOR_HANDOFF: Final[dict[str, Any]] = _additive(
    properties={
        "target_dim": {"type": "string"},
        "gen_tag": {"type": "string"},
        "candidate_id": {"type": "string"},
        "output_path": {"type": "string"},
        "existing_pool": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["id", "path"],
            },
        },
        "supervisor_guidance": {"type": "object"},
        "articles_with_reasoning": {"type": "string"},
        "baseline_evidence": {"type": "object"},
    },
    required=["target_dim", "gen_tag", "candidate_id", "output_path"],
)
"""Generator — writes a candidate `.md` file. No OUTPUT schema
(generator returns a file path, not JSON)."""


LITERATURE_REVIEW_HANDOFF: Final[dict[str, Any]] = _additive(
    properties={
        "target_dim": {"type": "string"},
        "max_papers": {"type": "integer"},
        "queries_per_run": {"type": "integer"},
        "supervisor_guidance": {"type": "object"},
    },
    required=["target_dim", "max_papers", "queries_per_run"],
)
"""LiteratureReview — Phase A of the 4-phase literature pipeline."""


PROXIMITY_HANDOFF: Final[dict[str, Any]] = _additive(
    properties={
        "run_id": {"type": "string"},
        "target_dim": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "path": {"type": "string"},
                    "target_dim": {"type": "string"},
                    "body_preview": {"type": "string"},
                },
                "required": ["id", "path", "target_dim"],
            },
        },
    },
    required=["run_id", "target_dim", "candidates"],
)
"""Proximity — single-shot clustering across all candidates."""


CRITIC_HANDOFF: Final[dict[str, Any]] = _additive(
    properties={
        "candidate_id": {"type": "string"},
        "candidate_path": {"type": "string"},
        "target_dim": {"type": "string"},
        "baseline_evidence": {"type": "object"},
        "priors": {"type": "object"},
        "supervisor_guidance": {"type": "object"},
        "literature_articles": {"type": "string"},
        # PR-SG-SELECTION-ALIGN (2026-05-25) — selection-layer signals.
        "target_dims_attribution": {"type": "array", "items": {"type": "string"}},
        "anchor_means": ANCHOR_MEANS_FIELD,
        "scenario_realism": {"type": "number"},
    },
    required=["candidate_id", "candidate_path", "target_dim"],
)
"""Critic — per-candidate critique. Optional fields carry
baseline / priors / guidance / literature context when present.
PR-SG-SELECTION-ALIGN — adds anchor_means + scenario_realism +
target_dims_attribution so the critic 's strengths/weaknesses verdict
incorporates the same signals autoresearch fitness uses."""


# PILOT_HANDOFF was removed in PR-PILOT-UNIFY-DIM-EXTRACT (2026-06-04) — the
# Pilot no longer spawns an LLM sub-agent (and so builds no HANDOFF CONTEXT
# block); it runs the Petri audit directly and reads the ``.eval`` archive.


VOTE_HANDOFF: Final[dict[str, Any]] = _additive(
    properties={
        "match_id": {"type": "string"},
        "target_dim": {"type": "string"},
        "candidate_a": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                # PR-VOTER-PROMPT-ANTI-PHANTOM (2026-05-26) — pre-fix
                # this carried a literal ``run_dir/candidates/<cid>.md``
                # relative-path string + instructed the voter to "Read
                # both candidate seeds". The model couldn't resolve
                # the fake path (per-task isolated cwd per
                # PR-RESUME-NO-PERSIST-FIX, not the orchestrator
                # run_dir) so claude-cli hallucinated session
                # continuity ("I already read both candidate files in
                # the previous turn") and exited turn 1 with empty
                # output. Now the full seed body is inlined per the
                # co-scientist debate_pair pattern; no Read tool
                # needed, no phantom-continuity confusion.
                "body": {"type": "string"},
                "pilot_means": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["id", "body"],
        },
        "candidate_b": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "body": {"type": "string"},
                "pilot_means": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["id", "body"],
        },
    },
    required=["match_id", "target_dim", "candidate_a", "candidate_b"],
)
"""Ranker voter — per-match A/B vote with pilot dim_means
attached so the judge sees the per-dim signal alongside the
inlined seed bodies (PR-VOTER-PROMPT-ANTI-PHANTOM, 2026-05-26)."""


EVOLVE_HANDOFF: Final[dict[str, Any]] = _additive(
    properties={
        "parent_id": {"type": "string"},
        "parent_path": {"type": "string"},
        "target_dim": {"type": "string"},
        "rewrite_section": {"type": "string"},
        "reflection_weaknesses": {"type": "array", "items": {"type": "string"}},
        "pilot_dim_means": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "baseline_evidence": {"type": "object"},
        "supervisor_guidance": {"type": "object"},
        "literature_articles": {"type": "string"},
        # PR-SG-SELECTION-ALIGN (2026-05-25) — selection-layer signals.
        "target_dims_attribution": {"type": "array", "items": {"type": "string"}},
        "anchor_means": ANCHOR_MEANS_FIELD,
        "scenario_realism": {"type": "number"},
    },
    required=["parent_id", "parent_path", "target_dim", "rewrite_section"],
)
"""Evolver — rewrites ONE section of a survivor candidate.
Pulls Critic's ``rewrite_section`` + ``weaknesses`` and Pilot's
``dim_means`` so the LLM knows which dim regressed.
PR-SG-SELECTION-ALIGN — adds anchor_means + scenario_realism +
target_dims_attribution so the rewrite respects the selection layer's
anchor confidence."""


META_REVIEW_HANDOFF: Final[dict[str, Any]] = _additive(
    properties={
        "run_id": {"type": "string"},
        "target_dim": {"type": "string"},
        "counts": {
            "type": "object",
            "properties": {
                "candidates": {"type": "integer"},
                "reflections": {"type": "integer"},
                "pilot_rows": {"type": "integer"},
                "survivors": {"type": "integer"},
                "evolved": {"type": "integer"},
            },
            "required": ["candidates", "reflections", "pilot_rows", "survivors", "evolved"],
        },
        "elo_distribution": {"type": "object"},
        "candidate_ids": {"type": "array", "items": {"type": "string"}},
    },
    required=["run_id", "target_dim", "counts", "candidate_ids"],
)
"""Meta-reviewer — full-run aggregate. Counts (not raw rows) per
the AgentDef contract: ``Meta-reviewer caps output at one paragraph
+ a few aggregate dicts.``"""


def extract_anchor_means(dim_means: dict[str, Any]) -> dict[str, float]:
    """Project ``dim_means`` to the anchor 3 triplet only.

    PR-SG-SELECTION-ALIGN (2026-05-25, G1) — mirrors
    ``core.self_improving.loop.anchor_confidence.ANCHOR_DIMS_POSITIVE``
    + ``ANCHOR_DIMS_NEGATIVE``. Returns ``{}`` when none of the three
    dims are present so the handoff JSON omits the ``anchor_means``
    key entirely (avoids surfacing empty dicts that the LLM may
    interpret as "all-zero").
    """
    anchor_keys = ("admirable", "disappointing", "needs_attention")
    out: dict[str, float] = {}
    for key in anchor_keys:
        value = dim_means.get(key)
        if isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def extract_scenario_realism(dim_means: dict[str, Any]) -> float | None:
    """Return ``scenario_realism`` from ``dim_means`` when present, else None.

    PR-SG-SELECTION-ALIGN (2026-05-25, G2) — D2 routing. Surfaces
    the scenario_realism Petri dim as a separate handoff field so
    the critic / evolver can weight judge_risk independently of the
    other 22 dims.
    """
    value = dim_means.get("scenario_realism")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def embed_handoff(description: str, handoff: dict[str, Any]) -> str:
    """Append a ``## HANDOFF CONTEXT`` JSON block to the LLM user message.

    The sub-agent reads the prose for instruction and the JSON for
    accurate values (candidate_id / dim_means / rewrite_section etc.).
    The block uses a labeled fenced code block so the LLM cannot
    mistake the handoff for its expected JSON output. claude-cli
    `--json-schema` enforcement applies to the response, not the
    prompt — embedding JSON in the prompt is safe.
    """
    import json

    body = json.dumps(handoff, indent=2, ensure_ascii=False, default=str)
    return f"{description}\n\n## HANDOFF CONTEXT\n```json\n{body}\n```\n"


__all__ = [
    "ANCHOR_MEANS_FIELD",
    "CRITIC_HANDOFF",
    "EVOLVE_HANDOFF",
    "GENERATOR_HANDOFF",
    "LITERATURE_REVIEW_HANDOFF",
    "META_REVIEW_HANDOFF",
    "PROXIMITY_HANDOFF",
    "VOTE_HANDOFF",
    "embed_handoff",
    "extract_anchor_means",
    "extract_scenario_realism",
]
