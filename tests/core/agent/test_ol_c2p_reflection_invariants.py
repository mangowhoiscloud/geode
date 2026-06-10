"""OL-C2' — Reflection module invariant pins.

Roadmap (`docs/plans/2026-05-22-self-improving-roadmap.md` C-section)
positioned OL-C2' as **신규 `core/agent/reflection.py`** — claimed
``episodic.py`` docstring mentioned a "reflection node populates
hypotheses" but no module existed.

**GAP audit (2026-05-22)**: the reflection node *does* exist at
``core/agent/loop/_reflection.py`` (321 lines) — PR-3 C-2 of the
cognitive-loop-uplift sprint shipped it. Surface area:

- ``reflect_async(state, tool_results, ...) -> CognitiveState``
- ``REFLECTION_TOOL_NAME = "record_reflection"``
- ``_REFLECTION_TOOL`` (tool_use schema with hypotheses / confidence /
  next_action_hint)
- ``_apply_reflection`` (state mutator)
- ``HookEvent.COGNITIVE_REFLECT`` emit at the agentic-loop call site

Three existing test files cover the module:
- ``tests/core/agent/test_reflection_node.py``
- ``tests/core/config/test_reflection_cost_gate.py``
- ``tests/core/agent/test_s0b_reflection_reader.py``

This file adds *drift-prevention pins* — 4 invariants ensuring:

1. The reflection module lives where downstream call sites import it
   (single canonical path, no parallel duplicate at ``core/agent/reflection.py``).
2. Load-bearing identifiers (``reflect_async``, ``REFLECTION_TOOL_NAME``,
   ``_REFLECTION_TOOL`` schema fields) remain exposed.
3. ``HookEvent.COGNITIVE_REFLECT`` is the emit point (cognitive cycle
   telemetry parity).
4. No naive parallel module is created — if a future PR adds
   ``core/agent/reflection.py``, this test surfaces the duplication.
"""

from __future__ import annotations

from pathlib import Path


def test_c2p_canonical_reflection_module_path() -> None:
    """The reflection node MUST live at ``core/agent/loop/_reflection.py``.

    Roadmap's hypothetical ``core/agent/reflection.py`` path is NOT
    where the module is — verifying so the next reader of the roadmap
    doesn't re-create a parallel module at the wrong location.
    """
    from core.agent.loop import _reflection

    module_path = Path(_reflection.__file__)
    assert module_path.name == "_reflection.py"
    assert module_path.parent.name == "loop"
    assert module_path.parent.parent.name == "agent"


def test_c2p_no_naive_top_level_reflection_module() -> None:
    """Pin: no parallel ``core/agent/reflection.py`` shim file exists.

    If someone later creates that file (intending to follow the stale
    roadmap entry), this test fails — forcing the author to reconcile
    the duplication with the existing canonical module at
    ``core/agent/loop/_reflection.py``.

    Note: ``core/agent/reflection_policy.py`` (S0a-style policy
    reader) IS a different module — it provides operator-editable
    schema overrides, not the reflection-node implementation. Its
    presence is allowed and asserted separately so a refactor that
    deletes it can be caught too.
    """
    import core.agent

    agent_dir = Path(core.agent.__file__).parent
    # Bare `reflection.py` would be the anti-pattern.
    assert not (agent_dir / "reflection.py").exists(), (
        "C2' regressed: `core/agent/reflection.py` was created as a "
        "parallel reflection module. The canonical one lives at "
        "`core/agent/loop/_reflection.py` (PR-3 C-2). Either delete "
        "the new file or merge it into the existing module."
    )
    # The policy reader (operator-editable schema overrides) is the
    # one allowed sibling — its presence is the C2' wiring SoT.
    assert (agent_dir / "reflection_policy.py").exists(), (
        "C2' regressed: `core/agent/reflection_policy.py` deleted. "
        "This module reads operator-local reflection.json overrides "
        "and is a load-bearing dependency of the reflection node."
    )


def test_c2p_reflection_module_exposes_load_bearing_surface() -> None:
    """Verify the API surface that callers depend on hasn't drifted."""
    from core.agent.loop import _reflection

    # The canonical tool name — used in test_reflection_node.py + the
    # agentic-loop call site to filter tool_use blocks.
    assert _reflection.REFLECTION_TOOL_NAME == "record_reflection"

    # The async entrypoint that agent_loop.py invokes.
    assert callable(getattr(_reflection, "reflect_async", None)), (
        "C2' regressed: reflect_async coroutine removed"
    )

    # Tool schema fields — pre-PR-B free-form JSON, post-PR-B
    # structured tool_use. Pin the contract.
    tool_schema = _reflection._REFLECTION_TOOL
    assert tool_schema["name"] == "record_reflection"
    schema_fields = tool_schema["input_schema"]["properties"]
    for required_field in ("hypotheses", "confidence", "next_action_hint"):
        assert required_field in schema_fields, (
            f"C2' regressed: tool_use schema missing field {required_field!r}"
        )


def test_c2p_cognitive_reflect_hook_event_canonical() -> None:
    """`HookEvent.COGNITIVE_REFLECT` is the cognitive-cycle telemetry
    point for the reflection step. Pin the enum entry + its value so a
    future telemetry refactor cannot rename it silently.
    """
    from core.hooks import HookEvent

    assert hasattr(HookEvent, "COGNITIVE_REFLECT")
    assert HookEvent.COGNITIVE_REFLECT.value == "cognitive_reflect"
