"""Per-role JSON Schemas for seed-generation sub-agent responses.

PR-JSON-WIRE (2026-05-25) — each role's expected output shape encoded
as a JSON Schema. Populated into ``SubTask.response_schema`` →
``WorkerRequest.response_schema`` → ``AgenticLoop.response_schema``
→ ``AdapterCallRequest.response_schema`` → claude-cli
``--json-schema`` / codex-cli ``--output-schema``. The provider then
constrains the model's response to the declared shape.

Without forcing, structured-output roles regularly hit invalid-JSON
responses (smoke 14 pilot: LLM emitted ``...all zero...`` prose
ellipsis inside a JSON object, breaking ``json.loads`` even after
codeblock unwrap). With forcing, the provider rejects responses that
don't match the schema before they reach the parser.

The required-field tuples here mirror the
``_REQUIRED_*_FIELDS`` constants in each role's agent module
(``plugins/seed_generation/agents/<role>.py``) — keeping them in
lockstep is a manual invariant for now; a future ratchet PR can
generate one from the other via a fixture if drift becomes a problem.
"""

from __future__ import annotations

from typing import Any, Final


def _additive(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Wrap a properties dict + required list into a complete JSON Schema.

    Returns the dict-form schema. We DON'T set ``additionalProperties=False``
    — the model may emit auxiliary fields (e.g. ``rationale``, ``notes``)
    that the parser ignores via the required-field gate; declaring them
    forbidden would reject otherwise-valid responses.
    """
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


PROXIMITY_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "similarity_clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cluster_id": {"type": "string"},
                    "topic": {"type": "string"},
                    "similar_hypotheses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "candidate_id": {"type": "string"},
                                "similarity_degree": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                            },
                            "required": ["candidate_id", "similarity_degree"],
                        },
                    },
                },
                "required": ["cluster_id", "topic", "similar_hypotheses"],
            },
        },
    },
    required=["similarity_clusters"],
)
"""Proximity agent — single-shot clustering output."""


CRITIQUE_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "candidate_id": {"type": "string"},
        "target_dims_actual": {"type": "array", "items": {"type": "string"}},
        "intended_dim_match": {"type": "boolean"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "judge_risk": {"type": "string"},
        # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — pre-fix
        # ``_REQUIRED_CRITIQUE_FIELDS`` (critic.py:70) gated this field
        # but ``CRITIQUE_SCHEMA.required`` omitted it. The worker-side
        # ``_needs_schema_retry`` only fires when a schema ``required``
        # key is missing, so the retry NEVER fired for missing
        # discrimination_estimate — the parent parser then rejected the
        # otherwise-valid payload (smoke 18: 4/12 critic sub-agents
        # malformed_critique with discrimination_estimate omitted).
        # Float 0.0-1.0 — prior on stderr-across-models per
        # ``critic.md`` (used by ``eval_export.py`` to compute
        # ``avg_discrimination_estimate``).
        "discrimination_estimate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    required=[
        "candidate_id",
        "target_dims_actual",
        "intended_dim_match",
        "strengths",
        "weaknesses",
        "judge_risk",
        "discrimination_estimate",
    ],
)
"""Critic agent — per-candidate critique."""


PILOT_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "candidate_id": {"type": "string"},
        "dim_means": {
            "type": "object",
            # Petri 24 substantive dims — additionalProperties allows the
            # full set without listing each (the LLM has the dim catalog
            # via the system prompt; this schema gates "no dim_means
            # field at all" + "values are wrong type", which is the
            # actual failure mode smoke 14 hit).
            "additionalProperties": {"type": "number"},
        },
        "dim_stderr": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "status": {
            "type": "string",
            "enum": ["ok", "timeout", "low_engagement"],
        },
    },
    required=["candidate_id", "dim_means", "dim_stderr", "status"],
)
"""Pilot agent — Petri inner-loop audit per candidate."""


VOTE_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "match_id": {"type": "string"},
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "rationale": {"type": "string"},
    },
    required=["match_id", "winner", "rationale"],
)
"""Ranker voter — per-match A/B/tie verdict."""


EVOLVE_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "parent_id": {"type": "string"},
        "evolved_id": {"type": "string"},
        "evolved_path": {"type": "string"},
        "rewrite_section": {"type": "string"},
        "verdict": {
            "type": "string",
            "enum": ["ok", "evolution_skipped", "failed"],
        },
        "notes": {"type": "string"},
    },
    required=["parent_id", "evolved_id", "evolved_path", "rewrite_section", "verdict"],
)
"""Evolver agent — per-candidate evolution output."""


META_REVIEW_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "coverage": {
            "type": "object",
            "additionalProperties": {"type": "number"},
        },
        "underrepresented_dims": {"type": "array", "items": {"type": "string"}},
        "overrepresented_dims": {"type": "array", "items": {"type": "string"}},
        "next_gen_priors": {
            "type": "object",
            "additionalProperties": True,
        },
        "elo_distribution": {
            "type": "object",
            "additionalProperties": True,
        },
        "evolution_yield": {
            "type": "object",
            "additionalProperties": True,
        },
        "session_summary": {"type": "string"},
    },
    required=[
        "coverage",
        "underrepresented_dims",
        "overrepresented_dims",
        "next_gen_priors",
        "elo_distribution",
        "evolution_yield",
        "session_summary",
    ],
)
"""Meta-reviewer agent — full-run coverage / quality summary."""


LITERATURE_REVIEW_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "articles_with_reasoning": {"type": "array"},
        "snapshots": {"type": "array"},
    },
    required=["articles_with_reasoning", "snapshots"],
)
"""Literature review — augmentation snapshots."""


# PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — supervisor was the only
# Loop-1 phase with ``_REQUIRED_*_FIELDS`` (supervisor.py:86) but no
# corresponding ``*_SCHEMA``. Its SubTask spawned without
# ``response_schema=``, so the worker-side
# ``_needs_schema_retry`` never fired on supervisor failures; the
# parent parser then dropped any payload not matching the 3-key shape
# (research_goal_analysis / phase_guidance / session_summary). This
# also explains the supervisor.json checkpoint regression in smoke 18
# (vs smoke 17 archive) — soft-failure supervisor output never made
# the schema-gated path, leaving ``phase_result.success`` False and
# the checkpoint un-written (PR-CHECKPOINT-ON-FAILURE invariant).
# Sub-property structure mirrors ``supervisor.md`` 's typed contract.
SUPERVISOR_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        "research_goal_analysis": {
            "type": "object",
            "properties": {
                "target_dim_focus": {"type": "string"},
                "sub_dim_priorities": {"type": "array", "items": {"type": "string"}},
                "key_constraints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["target_dim_focus", "sub_dim_priorities", "key_constraints"],
        },
        "phase_guidance": {
            "type": "object",
            "properties": {
                "generation": {"type": "string"},
                "critique": {"type": "string"},
                "evolution": {"type": "string"},
            },
            "required": ["generation", "critique", "evolution"],
        },
        "session_summary": {"type": "string"},
    },
    required=["research_goal_analysis", "phase_guidance", "session_summary"],
)
"""Supervisor agent — run-level strategy synthesis."""


__all__ = [
    "CRITIQUE_SCHEMA",
    "EVOLVE_SCHEMA",
    "LITERATURE_REVIEW_SCHEMA",
    "META_REVIEW_SCHEMA",
    "PILOT_SCHEMA",
    "PROXIMITY_SCHEMA",
    "SUPERVISOR_SCHEMA",
    "VOTE_SCHEMA",
]
