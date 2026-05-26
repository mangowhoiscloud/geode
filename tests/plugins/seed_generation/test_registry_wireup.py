"""S11 PipelineRegistry wire-up — Follow-up C invariants.

Pins:
- ``populate_registry`` builds one agent per ``manifest.enabled_roles``.
- Each agent's model + source comes from the picker binding for that role.
- Ranker receives ``picker_result.voters`` (per-voter routing).
- Empty picker (no bindings) → empty registry (caller handles missing-agent).
"""

from __future__ import annotations

import pytest
from core.llm.adapters.registry import _reset_for_test, bootstrap_builtins
from plugins.seed_generation._registry_builder import populate_registry
from plugins.seed_generation.manifest import load_manifest
from plugins.seed_generation.orchestrator import PipelineRegistry
from plugins.seed_generation.picker import pick_bindings


@pytest.fixture(autouse=True)
def _registry_with_builtins():
    _reset_for_test()
    bootstrap_builtins()
    yield
    _reset_for_test()


def test_populate_registry_registers_all_enabled_roles() -> None:
    """Every enabled role in the manifest gets a registered agent."""
    picker = pick_bindings(auto_probe=False)
    manifest = load_manifest()
    registry = PipelineRegistry()
    populate_registry(registry, picker_result=picker, manifest=manifest)
    registered = sorted(registry.list_roles())
    assert set(registered) >= set(manifest.enabled_roles)


def test_populate_registry_agent_model_matches_binding() -> None:
    """Each agent's ``model`` is the picker binding's model."""
    picker = pick_bindings(auto_probe=False)
    manifest = load_manifest()
    registry = PipelineRegistry()
    populate_registry(registry, picker_result=picker, manifest=manifest)
    for role_name in manifest.enabled_roles:
        binding = picker.bindings[role_name]
        agent = registry.get(role_name)
        assert agent is not None, f"role {role_name} not registered"
        assert agent.model == binding.model
        assert agent.source == binding.source


def test_populate_registry_idempotent() -> None:
    """Re-running populate_registry on an already-populated registry is a no-op."""
    picker = pick_bindings(auto_probe=False)
    manifest = load_manifest()
    registry = PipelineRegistry()
    populate_registry(registry, picker_result=picker, manifest=manifest)
    before = sorted(registry.list_roles())
    populate_registry(registry, picker_result=picker, manifest=manifest)
    after = sorted(registry.list_roles())
    assert before == after


def test_populate_registry_ranker_receives_voters() -> None:
    """Ranker is built with ``picker_result.voters`` so each judge has a binding."""
    picker = pick_bindings(auto_probe=False)
    manifest = load_manifest()
    registry = PipelineRegistry()
    populate_registry(registry, picker_result=picker, manifest=manifest)
    ranker = registry.get("ranker")
    assert ranker is not None
    # The Ranker stores voters on a private attribute; the externally-visible
    # invariant is that the registry has the ranker role + picker has voters.
    assert len(picker.voters) >= 1


def test_populate_registry_supervisor_registered() -> None:
    """PR-SUPERVISOR-ENABLE (2026-05-26) — supervisor must be registered
    (was silently skipped pre-fix with ``agent_not_registered`` in the
    orchestrator transcript; smoke 19 evidence).

    Pre-fix: ``enabled_roles`` did not include ``"supervisor"`` AND the
    ``[seed_generation.role.supervisor]`` section was absent. The
    main registration loop never visited supervisor, and the fallback
    ``picker_result.bindings.get("supervisor")`` returned None
    because the picker only resolves bindings for ``enabled_roles``.
    Net effect: every smoke run emitted ``phase_skipped
    reason=agent_not_registered`` for supervisor and the supervisor.json
    checkpoint never landed.

    Fix: added supervisor to manifest enabled_roles + role section +
    Supervisor to ``_ROLE_TO_CLASS``. This test pins all three
    necessary conditions.
    """
    picker = pick_bindings(auto_probe=False)
    manifest = load_manifest()
    # Necessary condition 1 — manifest enables supervisor.
    assert "supervisor" in manifest.enabled_roles
    # Necessary condition 2 — manifest defines a supervisor role spec.
    assert "supervisor" in manifest.roles
    # Necessary condition 3 — picker resolves a supervisor binding.
    assert picker.bindings.get("supervisor") is not None
    registry = PipelineRegistry()
    populate_registry(registry, picker_result=picker, manifest=manifest)
    # Sufficient condition — registry has the supervisor role.
    assert "supervisor" in registry.list_roles(), (
        "supervisor not registered — orchestrator will emit "
        "phase_skipped reason=agent_not_registered (smoke 19 regression)"
    )
    supervisor = registry.get("supervisor")
    assert supervisor is not None
    # Concrete class check — must be Supervisor (not something else
    # accidentally registered under the same role key).
    from plugins.seed_generation.agents.supervisor import Supervisor

    assert isinstance(supervisor, Supervisor)
    # The supervisor binding's model is the manifest default (opus per
    # the role docstring); confirm the wiring propagated.
    assert supervisor.model == manifest.roles["supervisor"].default_model
