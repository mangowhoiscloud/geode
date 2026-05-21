"""PR-COSCI-1 — 3-item fix-up bundle for the co-scientist pipeline.

Pins:
- HIGH: seed_ranker.md naming mismatch resolved (``required_diversity_families`` → ``required_diversity_providers``).
- MEDIUM: seed_evolver.md contract now mandates preserving ``tags`` frontmatter (PR-OPS-1 parity).
- MEDIUM: orchestrator aborts early when generator/proximity leave ``state.candidates`` empty.
"""

from __future__ import annotations

from pathlib import Path


def _read_contract(name: str) -> str:
    repo_root = Path(__file__).resolve().parent.parent
    contract = repo_root / ".claude" / "agents" / name
    assert contract.is_file(), f"missing agent contract: {contract}"
    return contract.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# HIGH — seed_ranker.md naming alignment with manifest
# ---------------------------------------------------------------------------


def test_seed_ranker_contract_uses_providers_not_families() -> None:
    """The manifest field is ``required_diversity_providers`` (verify
    via grep on ``plugins/seed_generation/manifest.py:122``). The
    ranker contract pre-PR said ``required_diversity_families`` —
    misleading the agent. Pin the corrected name."""
    text = _read_contract("seed_ranker.md")
    # The correct manifest field name must appear
    assert "required_diversity_providers" in text
    # And the misleading legacy name must NOT
    assert "required_diversity_families" not in text


def test_seed_ranker_diversity_section_references_provider_not_family() -> None:
    """The diversity-guard sentence must reference ``provider`` (the
    actual ``VoterSpec`` field), not ``family`` (legacy term)."""
    text = _read_contract("seed_ranker.md")
    # Pin the corrected diversity-guard line phrase
    assert "Voters' `provider` must span" in text


# ---------------------------------------------------------------------------
# MEDIUM — seed_evolver.md tags-preservation contract
# ---------------------------------------------------------------------------


def test_seed_evolver_contract_mandates_tags_preservation() -> None:
    """PR-OPS-1 amended seed_generator.md to emit both ``target_dims``
    AND ``tags`` (Petri compat). Evolved seeds that strip ``tags``
    during rewrite silently lose Petri-side dim attribution. Pin
    the evolver contract requirement."""
    text = _read_contract("seed_evolver.md")
    assert "`tags`" in text
    assert "Petri-compatible attribution" in text or "Petri-compatible" in text


# ---------------------------------------------------------------------------
# MEDIUM — orchestrator empty-candidates abort gate
# ---------------------------------------------------------------------------


def test_orchestrator_aborts_on_empty_candidates_after_generator(
    monkeypatch,
) -> None:
    """When the generator phase leaves ``state.candidates == []``, the
    orchestrator must abort BEFORE running critic/pilot/ranker rather
    than emit a "successful but empty" run."""
    import inspect

    from plugins.seed_generation import orchestrator

    src = inspect.getsource(orchestrator.Pipeline.run)
    # The abort gate must check the post-phase state for empty
    # candidates after generator or proximity. Pin presence.
    assert "empty_candidates_abort" in src or "state.candidates empty" in src
    # The gate must fire only after generator/proximity (the two
    # phases that own the candidate pool's population/filtering).
    assert "generator" in src and "proximity" in src


def test_orchestrator_abort_emits_observability_event() -> None:
    """The abort must emit an observability event so an operator
    grepping the session journal sees the root cause."""
    import inspect

    from plugins.seed_generation import orchestrator

    src = inspect.getsource(orchestrator.Pipeline.run)
    assert '"empty_candidates_abort"' in src
    # Error level — abort is a failure, not a normal state.
    assert 'level="error"' in src
