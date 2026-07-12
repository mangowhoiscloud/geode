"""Pins for the loop's three fixed surfaces (the autoresearch projection).

The 2026-07 fragmentation happened silently: prepare dissolved into hand
steps and program.md into code literals, with nothing failing. These tests
make the triad declaration in ``plugins/crucible/__init__`` load-bearing.
"""

import subprocess
import sys
from pathlib import Path

from plugins.benchmark_harness.tau2_turn_supervisor import _AGENT_POLICY_PATH
from plugins.crucible import TRIAD_PREPARE, TRIAD_PROGRAM, TRIAD_TRAIN_SURFACE
from plugins.crucible.prepare import PREPARE_PROVENANCE_SCHEMA
from plugins.crucible.producers.codex_kg import _DEFAULT_PROGRAM_PATH

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_program_surface_is_the_producer_program() -> None:
    assert TRIAD_PROGRAM.is_file()
    assert _DEFAULT_PROGRAM_PATH == TRIAD_PROGRAM
    source = TRIAD_PROGRAM.read_text(encoding="utf-8")
    for section in ("## Objective", "## Experimentation", "## Constraints"):
        assert section in source


def test_train_surface_matches_the_harness_policy_path() -> None:
    surface = _REPO_ROOT / TRIAD_TRAIN_SURFACE
    assert surface.is_file()
    # The harness must load exactly the declared surface — a rename or move
    # on either side breaks the experiment/artifact identity silently.
    assert _AGENT_POLICY_PATH.resolve() == surface.resolve()


def test_prepare_entry_matches_the_provenance_stamp() -> None:
    assert TRIAD_PREPARE == "plugins.crucible.prepare"
    assert PREPARE_PROVENANCE_SCHEMA == "crucible.prepare-provenance.v1"


def test_codex_kg_imports_cold_as_the_first_crucible_import() -> None:
    """The producer module pulls TRIAD_PROGRAM from the package root, which
    eagerly imports the whole kernel — a cycle would only surface on a cold
    interpreter, not inside this already-warmed test session."""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and argv
        [sys.executable, "-c", "import plugins.crucible.producers.codex_kg"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
