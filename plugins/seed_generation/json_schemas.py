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

PR-STRICT-COMPATIBLE-SCHEMAS (2026-05-26) — Codex OAuth's
``text.format`` wire-through (PR-CODEX-OAUTH-RESPONSE-SCHEMA, v0.99.61)
auto-detects strict-mode via
``core.llm.adapters.codex_oauth._is_openai_strict_compatible``. The
detector requires every ``type:"object"`` subschema to set
``additionalProperties:false`` AND list every property in
``required``. Pre-fix all our schemas used ``_additive()`` (permissive),
so codex backend always landed on ``strict=False`` → text.format
became a *hint* rather than a *constraint* → gpt-5.5 reasoning models
could burn their output budget on encrypted-reasoning items and
return empty ``output_text`` (smoke 18 vote-m000-openai.openai-codex
turn 1: cost $0.0358, 0 assistant_message).

The ``_strict_additive()`` helper enforces both invariants. Schemas
whose shape allows it (no typed ``additionalProperties``, no truly
optional fields) are converted; the two exceptions (META_REVIEW,
LITERATURE_REVIEW) use ``additionalProperties: {"type": "number"}`` /
``true`` / ``{"type": "string"}`` to carry per-dim numeric maps or
per-arxiv-id snapshot path maps whose key set is determined at runtime
— enumerating those would couple the schema to a catalog this module
shouldn't import, and the actual failure mode for those roles is
``no field at all`` (caught by required-gate) not key drift.

The Pilot role no longer has a schema here: PR-PILOT-UNIFY-DIM-EXTRACT
(2026-06-04) reduced the Pilot to a direct ``run_audit`` +
``extract_dim_aggregates`` call (no LLM sub-agent), so there is no LLM
response to constrain — its ``dim_means`` come straight from the
audit's ``.eval`` archive on the campaign's raw-Petri scale.
"""

from __future__ import annotations

from typing import Any, Final


def _additive(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Wrap a properties dict + required list into a complete JSON Schema.

    Returns the dict-form schema. We DON'T set ``additionalProperties=False``
    — the model may emit auxiliary fields (e.g. ``rationale``, ``notes``)
    that the parser ignores via the required-field gate; declaring them
    forbidden would reject otherwise-valid responses.

    Use ``_strict_additive`` instead when the role's shape is fully
    enumerated (no auxiliary fields needed) — that variant unlocks
    strict-mode at the OpenAI Responses backend.
    """
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _strict_additive(properties: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict-mode compatible variant of ``_additive``.

    PR-STRICT-COMPATIBLE-SCHEMAS (2026-05-26) — for the codex
    backend's ``text.format`` to be a hard *constraint* (not a hint),
    ``_is_openai_strict_compatible`` (codex_oauth.py) requires:

    - ``additionalProperties: false`` on every ``type:"object"``
      subschema (typed-additional or True is rejected).
    - Every property key listed in ``required`` (no optionals).

    This helper enforces both: ``required`` is derived from
    ``properties.keys()`` (no separate list to drift from), and
    ``additionalProperties`` is set to False. The caller is
    responsible for nested objects + array ``items`` ALSO using
    ``_strict_additive`` (the detector recurses; one non-strict
    nested object disables strict mode for the whole schema).

    Use ``_additive`` (permissive) when:

    - The role's output uses typed-additional maps (``dim_means``
      with per-Petri-dim float keys — META_REVIEW, PILOT).
    - An auxiliary field is genuinely optional and must not be
      synthesized when absent (rare; usually better to make it
      required with an empty-string sentinel).
    """
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


PROXIMITY_SCHEMA: Final[dict[str, Any]] = _strict_additive(
    properties={
        "similarity_clusters": {
            "type": "array",
            "items": _strict_additive(
                properties={
                    "cluster_id": {"type": "string"},
                    "topic": {"type": "string"},
                    "similar_hypotheses": {
                        "type": "array",
                        "items": _strict_additive(
                            properties={
                                "candidate_id": {"type": "string"},
                                "similarity_degree": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                            }
                        ),
                    },
                }
            ),
        },
    },
)
"""Proximity agent — single-shot clustering output (strict-compatible)."""


CRITIQUE_SCHEMA: Final[dict[str, Any]] = _strict_additive(
    properties={
        "candidate_id": {"type": "string"},
        "target_dims_actual": {"type": "array", "items": {"type": "string"}},
        "intended_dim_match": {"type": "boolean"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "judge_risk": {"type": "string"},
        # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26, #1698) — pre-fix
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
        # PR-STRICT-COMPATIBLE-SCHEMAS (2026-05-26, Codex MCP catch) —
        # critic.md:47 + critic.py:304 advertise a ``rewrite_section``
        # field that the Evolver consumes
        # (``evolver.py:_consume_rewrite_target``) + that
        # ``eval_export.py:355`` serialises into the per-critique
        # action row. Pre-fix the field was tolerated because
        # ``_additive()`` allowed additional properties; the strict
        # variant rejects unknown keys, so the field MUST be declared.
        # Nullable per critic.md (``"otherwise null"``); OpenAI strict
        # mode accepts ``"type": ["string", "null"]``.
        "rewrite_section": {"type": ["string", "null"]},
    },
)
"""Critic agent — per-candidate critique (strict-compatible)."""


VOTE_SCHEMA: Final[dict[str, Any]] = _strict_additive(
    properties={
        "match_id": {"type": "string"},
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "rationale": {"type": "string"},
    },
)
"""Ranker voter — per-match A/B/tie verdict (strict-compatible).

PR-STRICT-COMPATIBLE-SCHEMAS (2026-05-26) — strict-mode required for
codex backend so gpt-5.5 cannot burn reasoning budget on empty
``output_text``. smoke 18 evidence: vote-m000-openai.openai-codex
turn 1 cost $0.0358 with 0 assistant_message (encrypted_reasoning
consumed the budget; permissive ``text.format`` did not constrain
the model to emit JSON). Prose-decomposed
``judgment_breakdown`` variant deferred to PR-CRITIQUE-PROSE-DECOMPOSE
(#95).
"""


EVOLVE_SCHEMA: Final[dict[str, Any]] = _strict_additive(
    properties={
        "parent_id": {"type": "string"},
        "evolved_id": {"type": "string"},
        "evolved_path": {"type": "string"},
        "rewrite_section": {"type": "string"},
        "verdict": {
            "type": "string",
            "enum": ["ok", "evolution_skipped", "failed"],
        },
        # PR-STRICT-COMPATIBLE-SCHEMAS (2026-05-26) — promoted from
        # optional to required (with empty-string sentinel). Pre-fix
        # ``required`` listed 5 keys; ``notes`` was the one optional
        # — keeping it optional disabled strict mode for the entire
        # schema. The evolver agent contract treats ``""`` as "no
        # notes worth surfacing", so requiring an explicit empty
        # string costs zero LLM behavior change.
        "notes": {"type": "string"},
    },
)
"""Evolver agent — per-candidate evolution output (strict-compatible)."""


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
"""Meta-reviewer agent — full-run coverage / quality summary.

NOT strict-compatible — ``coverage`` uses typed ``additionalProperties``
(per-dim float map), and ``next_gen_priors`` / ``elo_distribution`` /
``evolution_yield`` use ``additionalProperties: true`` (unstructured
audit maps the meta-reviewer designs at runtime). Codex backend falls
through to ``strict: False`` for this schema.
"""


LITERATURE_REVIEW_SCHEMA: Final[dict[str, Any]] = _additive(
    properties={
        # PR-STRICT-COMPATIBLE-SCHEMAS (2026-05-26) — fixed 2 type
        # drifts vs the parser + agent contract:
        # 1. Pre-fix the schema declared ``articles_with_reasoning``
        #    as an untyped ``array`` but literature_review.py:163
        #    reads it as
        #    ``str(parsed.get("articles_with_reasoning", "") or "")``
        #    — a markdown block, not a list. The agent contract
        #    (``literature_review.md``) treats this as a single prose
        #    block; aligned to ``"string"``.
        # 2. Pre-fix the schema declared ``snapshots`` as an untyped
        #    ``array`` but literature_review.py:165 reads it as
        #    ``parsed.get("snapshots", {}) or {}`` then ``isinstance(
        #    snapshots_raw, dict)`` — a ``{arxiv_id: snapshot_path}``
        #    map per the agent contract example. Aligned to
        #    ``"object"`` with typed-additional string values. This
        #    forces the schema to stay non-strict (typed-additional
        #    isn't strict-compatible), but the literature_review
        #    phase short-circuits with ``max_papers=0`` by default so
        #    the codex empty-output blast radius is limited compared
        #    to per-candidate roles.
        "articles_with_reasoning": {"type": "string"},
        "snapshots": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
    },
    required=["articles_with_reasoning", "snapshots"],
)
"""Literature review — augmentation snapshots.

NOT strict-compatible — ``snapshots`` is a ``{arxiv_id:
snapshot_path}`` map keyed on arbitrary arxiv IDs the literature
search produced at runtime; enumerating those would require
runtime-schema generation. The role short-circuits with
``max_papers=0`` by default (manifest knob), so the strict-mode
blast radius is limited. Operators flipping ``max_papers >= 1``
accept the trade-off.
"""


# PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26, #1698) — supervisor was the
# only Loop-1 phase with ``_REQUIRED_*_FIELDS`` (supervisor.py:86) but no
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
SUPERVISOR_SCHEMA: Final[dict[str, Any]] = _strict_additive(
    properties={
        "research_goal_analysis": _strict_additive(
            properties={
                "target_dim_focus": {"type": "string"},
                "sub_dim_priorities": {"type": "array", "items": {"type": "string"}},
                "key_constraints": {"type": "array", "items": {"type": "string"}},
            }
        ),
        "phase_guidance": _strict_additive(
            properties={
                "generation": {"type": "string"},
                "critique": {"type": "string"},
                "evolution": {"type": "string"},
            }
        ),
        "session_summary": {"type": "string"},
    },
)
"""Supervisor agent — run-level strategy synthesis (strict-compatible)."""


__all__ = [
    "CRITIQUE_SCHEMA",
    "EVOLVE_SCHEMA",
    "LITERATURE_REVIEW_SCHEMA",
    "META_REVIEW_SCHEMA",
    "PROXIMITY_SCHEMA",
    "SUPERVISOR_SCHEMA",
    "VOTE_SCHEMA",
]
