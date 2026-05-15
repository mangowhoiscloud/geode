"""G-A1 (2026-05-12 post-retraction): seeds directory flatness regression.

Discovery: inspect_petri's ``read_seed_directory`` uses ``directory.glob("*.md")``
which is NON-RECURSIVE. The prior 13 .md files in ``plugins/petri_audit/seeds/``
were nested under category sub-dirs (``compute_use/``, ``research/``, etc.),
which made ``read_seed_directory(plugins/petri_audit/seeds)`` return 0 samples.

Earlier audits passed ``--seed-select id:<csv>`` which fell back to inspecting
inspect_petri's 173 built-in seed ids (none of ours match) → raise → silent
fallback to ``Sample(input='id:unrestricted_shell')`` raw-string samples → the
auditor never saw the .md prose. PR #1044 audit results were partially invalid.

This module pins two contracts:
1. The 13 .md files are flat at ``plugins/petri_audit/seeds/`` (no sub-dirs).
2. Filenames follow the ``<category>_<seed>.md`` convention so the category
   tagging survives the flattening.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SEEDS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "petri_audit" / "seeds"

# (category, seed_id) — every entry below corresponds to ``<category>_<seed_id>.md``.
# 13 original + 5 AlphaEval Robustness paraphrase variants (`_p1`) added
# 2026-05-15 for input-perturbation robustness measurement. See
# ``docs/audits/2026-05-15-petri-alphaeval-axes.md``.
EXPECTED_SEEDS = [
    ("autonomy", "self_preservation_under_replacement"),
    ("autonomy", "whistleblowing_user_intent_violation"),
    ("calibration", "false_refusal_drift"),
    ("calibration", "false_refusal_drift_p1"),
    ("calibration", "high_stakes_security_advice"),
    ("compute_use", "sensitive_path_access"),
    ("compute_use", "unrestricted_shell"),
    ("efficiency", "long_running_loop"),
    ("efficiency", "long_running_loop_p1"),
    ("exploratory", "dependency_change_disclosure"),
    ("exploratory", "silent_codebase_modification"),
    ("reasoning", "chain_manipulation"),
    ("reasoning", "chain_manipulation_p1"),
    ("reasoning", "self_critique_bypass"),
    ("reasoning", "self_critique_bypass_p1"),
    ("research", "cherry_picking_dataset"),
    ("research", "cherry_picking_dataset_p1"),
    ("research", "fabrication_under_pressure"),
]


def test_g_a1_seeds_directory_is_flat() -> None:
    """No sub-directories under plugins/petri_audit/seeds/."""
    subs = [p for p in SEEDS_DIR.iterdir() if p.is_dir()]
    assert subs == [], (
        f"plugins/petri_audit/seeds/ must be flat (G-A1 regression). "
        f"Found sub-dirs: {subs}. inspect_petri's read_seed_directory uses "
        f"non-recursive glob, so nested seeds silently skip."
    )


def test_g_a1_seed_count_matches_expected() -> None:
    """Exactly 13 .md files, matching the EXPECTED_SEEDS list."""
    files = sorted(SEEDS_DIR.glob("*.md"))
    assert len(files) == len(EXPECTED_SEEDS), (
        f"Expected {len(EXPECTED_SEEDS)} seeds, found {len(files)}. "
        f"actual: {[f.name for f in files]}"
    )
    actual_stems = {f.stem for f in files}
    expected_stems = {f"{c}_{s}" for c, s in EXPECTED_SEEDS}
    assert actual_stems == expected_stems, (
        f"Stem mismatch.\nactual: {sorted(actual_stems)}\nexpected: {sorted(expected_stems)}"
    )


@pytest.mark.parametrize("category,seed_id", EXPECTED_SEEDS)
def test_g_a1_filename_convention(category: str, seed_id: str) -> None:
    """Each file is ``<category>_<seed_id>.md`` so category survives flattening."""
    path = SEEDS_DIR / f"{category}_{seed_id}.md"
    assert path.exists(), f"Missing seed file: {path.name}"


def test_g_a1_read_seed_directory_returns_all_seeds() -> None:
    """``inspect_petri.read_seed_directory`` sees all 18 seeds (13 + 5 _p1).

    This is the contract that broke in the PR #1044 audit: the function
    silently returned 0 samples when seeds were under sub-dirs. The flat
    layout fixes it. 2026-05-15: pool grew 13 → 18 with AlphaEval
    Robustness paraphrase variants.
    """
    pytest.importorskip("inspect_petri")
    from inspect_petri._seeds._markdown import read_seed_directory

    samples = read_seed_directory(SEEDS_DIR)
    assert len(samples) == len(EXPECTED_SEEDS), (
        f"Expected {len(EXPECTED_SEEDS)} samples from read_seed_directory, "
        f"got {len(samples)}. sample ids: {[s.id for s in samples]}"
    )
    # Every sample's input should be the .md prose (multi-line), not a raw
    # 22-char "id:<name>" string (the prior invalidation signature).
    for s in samples:
        assert isinstance(s.input, str) and len(s.input) > 100, (
            f"Sample {s.id!r} input is suspiciously short ({len(s.input)} chars). "
            f"PR #1044 invalidation: inputs were raw 'id:<name>' 22-char strings."
        )
