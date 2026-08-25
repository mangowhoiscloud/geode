"""Pins for the loop's fixed preparation and treatment surfaces.

These tests keep preparation provenance and the mutable treatment path
load-bearing after the built-in candidate producer was retired.
"""

from pathlib import Path

from evals.benchmarks.tau2.turn_supervisor import _AGENT_POLICY_PATH
from evolve.crucible import TRIAD_PREPARE, TRIAD_TRAIN_SURFACE
from evolve.crucible.admission.prepare import PREPARE_PROVENANCE_SCHEMA, prepare_campaign
from evolve.crucible.prepare import prepare_campaign as legacy_prepare_campaign
from evolve.crucible.search.supervisor import PromotionSupervisor
from evolve.crucible.supervisor import PromotionSupervisor as LegacyPromotionSupervisor

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_train_surface_matches_the_harness_policy_path() -> None:
    surface = _REPO_ROOT / TRIAD_TRAIN_SURFACE
    assert surface.is_file()
    # The harness must load exactly the declared surface — a rename or move
    # on either side breaks the experiment/artifact identity silently.
    assert _AGENT_POLICY_PATH.resolve() == surface.resolve()


def test_prepare_entry_matches_the_provenance_stamp() -> None:
    assert TRIAD_PREPARE == "evolve.crucible.prepare"
    assert PREPARE_PROVENANCE_SCHEMA == "crucible.prepare-provenance.v1"


def test_v1_crucible_facades_preserve_public_imports() -> None:
    assert legacy_prepare_campaign is prepare_campaign
    assert LegacyPromotionSupervisor is PromotionSupervisor
