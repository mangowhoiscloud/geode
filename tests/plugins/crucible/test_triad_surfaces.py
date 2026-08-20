"""Pins for the loop's fixed preparation and treatment surfaces.

These tests keep preparation provenance and the mutable treatment path
load-bearing after the built-in candidate producer was retired.
"""

from pathlib import Path

from geode_product.benchmark_harness.tau2_turn_supervisor import _AGENT_POLICY_PATH
from geode_product.crucible import TRIAD_PREPARE, TRIAD_TRAIN_SURFACE
from geode_product.crucible.prepare import PREPARE_PROVENANCE_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_train_surface_matches_the_harness_policy_path() -> None:
    surface = _REPO_ROOT / TRIAD_TRAIN_SURFACE
    assert surface.is_file()
    # The harness must load exactly the declared surface — a rename or move
    # on either side breaks the experiment/artifact identity silently.
    assert _AGENT_POLICY_PATH.resolve() == surface.resolve()


def test_prepare_entry_matches_the_provenance_stamp() -> None:
    assert TRIAD_PREPARE == "geode_product.crucible.prepare"
    assert PREPARE_PROVENANCE_SCHEMA == "crucible.prepare-provenance.v1"
