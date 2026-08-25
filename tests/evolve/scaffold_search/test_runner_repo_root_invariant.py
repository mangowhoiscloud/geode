"""Regression pin for the explicit scaffold mutation workspace."""

from core.paths import require_evolve_workspace


def test_mutation_workspace_contains_the_scaffold_entrypoint() -> None:
    root = require_evolve_workspace()

    assert (root / ".git").exists()
    assert (root / "evolve" / "scaffold_search" / "train.py").is_file()
