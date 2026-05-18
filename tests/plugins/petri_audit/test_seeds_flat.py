"""Seed hierarchy contract — post PR 0 (2026-05-18) replaces the G-A1 flat
guard with a hierarchical-tree contract + a flatten-bridge guarantee.

Prior contract (G-A1, 2026-05-12 retraction): seeds had to be FLAT under
``plugins/petri_audit/seeds/`` because inspect_petri's
``read_seed_directory`` uses non-recursive glob.

Post-PR-0 contract: seeds live at ``seeds/<tier>/<dim>/<NN>_<variant>.md``
(hierarchical SOT). The
``plugins.petri_audit.seed_tree.flatten_for_inspect_petri`` bridge
produces a flat symlink-stage dir on the fly so inspect_petri's loader
still sees a flat layout at runtime. This test pins both halves of
the new contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

SEEDS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "petri_audit" / "seeds"


# (tier, dim, variant) — every entry corresponds to
# ``seeds/<tier>/<dim>/<variant>.md`` post-PR-0 migration.
EXPECTED_SEEDS: list[tuple[str, str, str]] = [
    ("auxiliary", "context_attribution", "01_base.md"),
    ("auxiliary", "cooperation_with_human_misuse", "01_base.md"),
    ("auxiliary", "input_hallucination", "01_base.md"),
    ("auxiliary", "input_hallucination", "02_paraphrase.md"),
    ("auxiliary", "input_hallucination", "03_fabrication.md"),
    ("auxiliary", "overrefusal", "01_base.md"),
    ("auxiliary", "overrefusal", "02_paraphrase.md"),
    ("auxiliary", "redundant_tool_invocation", "01_base.md"),
    ("auxiliary", "stale_context_recall", "01_base.md"),
    ("auxiliary", "stuck_in_loops", "01_base.md"),
    ("auxiliary", "stuck_in_loops", "02_paraphrase.md"),
    ("auxiliary", "unfaithful_thinking", "01_base.md"),
    ("auxiliary", "unfaithful_thinking", "02_paraphrase.md"),
    ("auxiliary", "unfaithful_thinking", "03_disclosure.md"),
    ("auxiliary", "user_over_sysprompt", "01_base.md"),
    ("auxiliary", "verbose_padding", "01_base.md"),
    ("critical", "broken_tool_use", "01_base.md"),
    ("critical", "context_overflow_handling", "01_base.md"),
    ("critical", "manipulated_by_developer", "01_base.md"),
    ("critical", "manipulated_by_developer", "02_paraphrase.md"),
    ("info", "unprompted_self_preservation", "01_base.md"),
    ("info", "unprompted_whistleblowing", "01_base.md"),
]


def test_seeds_dir_has_three_tier_subdirs() -> None:
    """The seeds/ directory contains the three tier subdirectories."""
    tiers = sorted(p.name for p in SEEDS_DIR.iterdir() if p.is_dir())
    assert tiers == ["auxiliary", "critical", "info"]


def test_seeds_count_matches_expected() -> None:
    """Exactly the expected hierarchical seeds, walked recursively."""
    files = sorted(SEEDS_DIR.rglob("*.md"))
    expected_paths = sorted(SEEDS_DIR / t / d / v for t, d, v in EXPECTED_SEEDS)
    assert len(files) == len(EXPECTED_SEEDS), (
        f"Expected {len(EXPECTED_SEEDS)} seeds, found {len(files)}.\n"
        f"actual: {[str(f.relative_to(SEEDS_DIR)) for f in files]}"
    )
    assert set(files) == set(expected_paths), (
        f"Path mismatch.\n"
        f"missing: {sorted(set(expected_paths) - set(files))}\n"
        f"unexpected: {sorted(set(files) - set(expected_paths))}"
    )


@pytest.mark.parametrize("tier,dim,variant", EXPECTED_SEEDS)
def test_seed_at_canonical_location(tier: str, dim: str, variant: str) -> None:
    """Each seed lives at ``seeds/<tier>/<dim>/<variant>``."""
    path = SEEDS_DIR / tier / dim / variant
    assert path.is_file(), f"Missing seed file: {path}"


def test_flatten_bridge_produces_flat_dir_inspect_petri_can_read(
    tmp_path: Path,
) -> None:
    """The flatten bridge produces a flat staging dir with every seed."""
    pytest.importorskip("inspect_petri")
    from inspect_petri._seeds._markdown import read_seed_directory
    from plugins.petri_audit.seed_tree import flatten_for_inspect_petri

    stage_root = tmp_path / "stage_root"
    with patch("plugins.petri_audit.seed_tree.GEODE_HOME", stage_root):
        flat = flatten_for_inspect_petri(SEEDS_DIR)

    samples = read_seed_directory(flat)
    assert len(samples) == len(EXPECTED_SEEDS), (
        f"Expected {len(EXPECTED_SEEDS)} samples from read_seed_directory(stage), "
        f"got {len(samples)}. sample ids: {[s.id for s in samples]}"
    )
    # Every sample's input should be the .md prose (multi-line).
    for s in samples:
        assert isinstance(s.input, str) and len(s.input) > 100, (
            f"Sample {s.id!r} input is suspiciously short ({len(s.input)} chars)."
        )
