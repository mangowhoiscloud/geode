"""PR-HANDOFF-SCHEMAS (2026-05-25) — handoff schema + embed + prompt
skeleton + sub_agent.py fallback parser tests.

Why these tests exist
=====================

Smoke 15 (archive ``.audit/smoke-archives/smoke-15-1779677713/``)
established the pilot + evolver failure mode: tool-using sub-agents
end with prose summaries when the only JSON-forcing signal is
``--json-schema`` (a soft hint, not enforced). This PR adds three
layers of defence and these tests pin each:

1. **Typed handoff** — every role's user message carries a
   ``## HANDOFF CONTEXT`` JSON block matching the role's
   ``*_HANDOFF`` schema in ``handoff_schemas.py``.
2. **Prompt skeleton** — pilot.md / evolver.md / ranker.md prose
   instructs "FINAL response must be ONLY the JSON object".
3. **Fallback parser** — ``sub_agent._last_balanced_json_object``
   recovers a JSON block embedded inside prose responses.

Drift between schema and the actual handoff dict the role emits
is a real bug. The drift test enumerates the required fields of
each HANDOFF schema and asserts they appear in the corresponding
role's serialized handoff dict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plugins.seed_generation.handoff_schemas import (
    CRITIC_HANDOFF,
    EVOLVE_HANDOFF,
    GENERATOR_HANDOFF,
    LITERATURE_REVIEW_HANDOFF,
    META_REVIEW_HANDOFF,
    PILOT_HANDOFF,
    PROXIMITY_HANDOFF,
    VOTE_HANDOFF,
    embed_handoff,
)

ROLE_PROMPTS = Path(__file__).parents[3] / "plugins" / "seed_generation" / "agents"


# ─────────────────────────── Schema shape pinning ─────────────────────────────


class TestSchemaShape:
    """Each handoff schema must be a valid additive JSON Schema dict."""

    @pytest.mark.parametrize(
        "schema",
        [
            CRITIC_HANDOFF,
            EVOLVE_HANDOFF,
            GENERATOR_HANDOFF,
            LITERATURE_REVIEW_HANDOFF,
            META_REVIEW_HANDOFF,
            PILOT_HANDOFF,
            PROXIMITY_HANDOFF,
            VOTE_HANDOFF,
        ],
    )
    def test_top_level_shape(self, schema: dict) -> None:
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert isinstance(schema["required"], list)
        assert schema["required"], "required list must be non-empty"
        # every required key must appear in properties
        missing = [k for k in schema["required"] if k not in schema["properties"]]
        assert not missing, f"required keys missing from properties: {missing}"


# ─────────────────────────── embed_handoff format ─────────────────────────────


class TestEmbedHandoff:
    def test_prose_preserved_above_block(self) -> None:
        out = embed_handoff("Do X.", {"a": 1})
        assert out.startswith("Do X.")

    def test_block_uses_json_fence(self) -> None:
        out = embed_handoff("prose", {"a": 1})
        assert "## HANDOFF CONTEXT" in out
        assert "```json" in out
        assert out.rstrip().endswith("```")

    def test_block_round_trips(self) -> None:
        payload = {"candidate_id": "abc", "target_dim": "redundant_tool_invocation"}
        out = embed_handoff("p", payload)
        # Extract the fenced block body and json.loads it.
        marker = "```json\n"
        start = out.index(marker) + len(marker)
        end = out.rindex("```")
        body = out[start:end].strip()
        assert json.loads(body) == payload

    def test_non_string_values_serialise_via_default_str(self) -> None:
        class _Obj:
            def __str__(self) -> str:
                return "obj-repr"

        out = embed_handoff("p", {"obj": _Obj()})
        # default=str makes the obj serialisable.
        assert "obj-repr" in out


# ─────────────────────────── Schema ↔ role drift ──────────────────────────────


class TestRoleHandoffDrift:
    """Each role's ``_build_description`` must produce a HANDOFF
    CONTEXT block matching the required keys of its schema."""

    def _extract_handoff(self, description: str) -> dict:
        marker = "```json\n"
        start = description.index(marker) + len(marker)
        end = description.rindex("```")
        return json.loads(description[start:end].strip())

    def test_pilot_handoff_matches_schema(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from plugins.seed_generation.agents.pilot import Pilot

        agent = Pilot(MagicMock())
        desc = agent._build_description(
            candidate_id="gen1-000-deadbeef",
            candidate_path="/tmp/seed.md",  # noqa: S108
            target_dim="redundant_tool_invocation",
        )
        handoff = self._extract_handoff(desc)
        for key in PILOT_HANDOFF["required"]:
            assert key in handoff, f"pilot handoff missing required key: {key}"
        assert handoff["candidate_id"] == "gen1-000-deadbeef"
        assert handoff["budget"]["models"] == 2

    def test_evolver_handoff_matches_schema(self) -> None:
        from unittest.mock import MagicMock

        from plugins.seed_generation.agents.evolver import Evolver

        agent = Evolver(MagicMock())
        desc = agent._build_description(
            candidate={
                "id": "gen1-001-cafebabe",
                "path": "/tmp/parent.md",  # noqa: S108
                "target_dim": "stuck_in_loops",
            },
            rewrite_section="## Look for — rewrite policy bullet",
            weaknesses=["judge cannot score this dim"],
            dim_means={"stuck_in_loops": 1.5},
            baseline_snapshot=None,
            supervisor_guidance=None,
            articles_with_reasoning="",
        )
        handoff = self._extract_handoff(desc)
        for key in EVOLVE_HANDOFF["required"]:
            assert key in handoff, f"evolver handoff missing required key: {key}"
        assert handoff["parent_id"] == "gen1-001-cafebabe"
        assert handoff["reflection_weaknesses"] == ["judge cannot score this dim"]

    def test_ranker_voter_handoff_matches_schema(self) -> None:
        from unittest.mock import MagicMock

        from plugins.seed_generation.agents.ranker import Ranker
        from plugins.seed_generation.tournament import MatchPlan

        ranker = Ranker.__new__(Ranker)
        match = MatchPlan(match_id="m-0", a="cand-a", b="cand-b")
        voter = MagicMock()
        voter.provider = "anthropic"
        voter.source = "claude-cli"
        voter.model = "claude-opus-4-7"
        desc = Ranker._build_description(
            ranker,
            match=match,
            voter=voter,
            means_a={"redundant_tool_invocation": 1.2},
            means_b={"redundant_tool_invocation": 0.9},
        )
        handoff = self._extract_handoff(desc)
        for key in VOTE_HANDOFF["required"]:
            assert key in handoff, f"voter handoff missing required key: {key}"
        assert handoff["candidate_a"]["id"] == "cand-a"
        assert handoff["candidate_b"]["pilot_means"]["redundant_tool_invocation"] == 0.9


# ─────────────────────────── Prompt-md JSON skeleton ──────────────────────────


class TestPromptOutputSection:
    """pilot.md / evolver.md / ranker.md must contain a strong
    'FINAL response only JSON' directive plus a concrete skeleton.

    Smoke 15 evidence: critic.md (which has this section) passed;
    pilot.md / evolver.md (which lacked it) emitted prose summaries.
    """

    @pytest.mark.parametrize(
        ("md_name", "must_contain"),
        [
            ("pilot.md", ["## Output JSON (structured)", "dim_means", "dim_stderr", '"status"']),
            (
                "evolver.md",
                ["## Output JSON (structured)", '"verdict"', "evolved_path", "parent_id"],
            ),
        ],
    )
    def test_prompt_includes_output_skeleton(self, md_name: str, must_contain: list[str]) -> None:
        body = (ROLE_PROMPTS / md_name).read_text(encoding="utf-8")
        for token in must_contain:
            assert token in body, f"{md_name} missing required token: {token}"

    @pytest.mark.parametrize("md_name", ["pilot.md", "evolver.md"])
    def test_prompt_demands_pure_json_final(self, md_name: str) -> None:
        body = (ROLE_PROMPTS / md_name).read_text(encoding="utf-8")
        # Strong JSON-only directive (allows minor wording variation).
        body_lc = body.lower()
        assert "final response" in body_lc or "final output" in body_lc
        assert "only the json" in body_lc or "only json" in body_lc


# ─────────────────────────── Fallback parser ──────────────────────────────────


class TestLastBalancedJsonObject:
    def test_returns_object_at_end_of_prose(self) -> None:
        from core.agent.sub_agent import _last_balanced_json_object

        text = 'I did the work. Result: {"a": 1, "b": 2}'
        assert _last_balanced_json_object(text) == '{"a": 1, "b": 2}'

    def test_picks_last_when_multiple(self) -> None:
        from core.agent.sub_agent import _last_balanced_json_object

        text = 'Intermediate {"step": 1}. Final {"answer": 42}.'
        assert _last_balanced_json_object(text) == '{"answer": 42}'

    def test_returns_none_when_no_braces(self) -> None:
        from core.agent.sub_agent import _last_balanced_json_object

        assert _last_balanced_json_object("plain prose with no json") is None

    def test_ignores_braces_inside_strings(self) -> None:
        from core.agent.sub_agent import _last_balanced_json_object

        text = 'final {"msg": "has } embedded", "ok": true}'
        out = _last_balanced_json_object(text)
        assert out is not None
        assert json.loads(out) == {"msg": "has } embedded", "ok": True}

    def test_handles_escaped_quotes_in_strings(self) -> None:
        from core.agent.sub_agent import _last_balanced_json_object

        text = r'{"text": "she said \"hi\"", "n": 1}'
        out = _last_balanced_json_object(text)
        assert out is not None
        assert json.loads(out) == {"text": 'she said "hi"', "n": 1}

    def test_nested_objects_balance_correctly(self) -> None:
        from core.agent.sub_agent import _last_balanced_json_object

        text = 'prose {"outer": {"inner": {"deep": 1}}, "k": "v"} more prose'
        out = _last_balanced_json_object(text)
        assert out is not None
        parsed = json.loads(out)
        assert parsed["outer"]["inner"]["deep"] == 1

    def test_skips_unparseable_blocks(self) -> None:
        from core.agent.sub_agent import _last_balanced_json_object

        # First block (later in text — scanned first) is malformed; second
        # block is valid; the function falls back to the valid one.
        text = '{"good": 1} ... and now broken {bad,}'
        out = _last_balanced_json_object(text)
        # The right-to-left scan tries `{bad,}` first (fails),
        # then `{"good": 1}` (succeeds).
        assert out is not None
        assert json.loads(out) == {"good": 1}


class TestSubAgentParseFallback:
    """End-to-end: a SubAgentManager parsing an isolation output that's
    PROSE + embedded JSON recovers the JSON via the fallback parser.

    Smoke 15 grounding: pilot emitted prose with audit JSON embedded
    inside; the previous parser fell back to `{"raw": ...}` and the
    orchestrator marked the candidate `malformed_pilot`.
    """

    def test_parse_returns_dict_when_prose_wraps_json(self) -> None:
        from unittest.mock import MagicMock

        from core.agent.sub_agent import SubAgentManager, SubTask
        from core.orchestration.isolated_execution import IsolatedRunner, IsolationResult

        runner = MagicMock(spec=IsolatedRunner)
        mgr = SubAgentManager(runner=runner)
        task = SubTask(task_id="t1", description="d", task_type="seed-pilot")
        prose_output = (
            "I'll run the audit. "
            "Now I see the results. "
            '{"candidate_id": "abc", "dim_means": {"x": 1}, '
            '"dim_stderr": {"x": 0}, "status": "ok"}'
        )
        isolation = IsolationResult(
            session_id="s",
            success=True,
            output=prose_output,
            error=None,
            duration_ms=10.0,
        )
        result = mgr._to_sub_result(task, isolation)  # type: ignore[attr-defined]
        assert result.success is True
        assert isinstance(result.output, dict)
        # Fallback path must NOT return `{"raw": ...}`.
        assert "raw" not in result.output
        assert result.output["candidate_id"] == "abc"
        assert result.output["status"] == "ok"
