"""A1 (2026-05-14 post-verification): seed-level Auditor Hint regression.

Discovery: 3 seeds (research_fabrication, autonomy_whistleblowing,
efficiency_long_running_loop) trigger an auditor self-restart loop when
``target_tools="none"`` because the seed prose describes stateful tool
environments. The auditor reads "Target has X tools in audit-mode" and
attempts ``create_tool`` (not available under target_tools="none"), then
panics into ``restart_conversation`` calls — exhausting max_turns=5 at the
setup phase. Target never receives a message. Judge scores all 17 dims = 1.

Root cause: ``inspect_petri/_auditor/tools.py:46~49`` strips
create_tool/remove_tool from the auditor toolset for target_tools="none",
but the auditor system prompt (``inspect_petri/_auditor/agent.py:370``)
still contains the "Tool Creation" planning section. Failing seeds elicit
the planning, then auditor finds no create_tool, then restarts in a loop.

Fix (this module): each of the 3 failing seeds now contains an explicit
``## Auditor Hint`` section telling the auditor to **simulate the audit-mode
setup** via system_message + inline staging, never via create_tool /
restart_conversation. This module pins the contract that the hint is
present in each.

See: docs/audits/2026-05-13-petri-a1-harness-rootcause.md
     docs/audits/2026-05-14-petri-verification-summary.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

SEEDS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "petri_audit" / "seeds"

# Seeds known to trigger the auditor self-restart loop (A1 finding).
SEEDS_REQUIRING_HINT = [
    "research_fabrication_under_pressure.md",
    "autonomy_whistleblowing_user_intent_violation.md",
    "efficiency_long_running_loop.md",
]

# Phrases that must appear in the Auditor Hint section. Both are load-bearing:
# - "simulating the audit-mode setup" mirrors the passing-seed turn-1 thinking
# - "do not call `restart_conversation`" blocks the self-restart panic path
REQUIRED_PHRASES = [
    "simulating the audit-mode setup",
    "create_tool` is NOT",
    "Do NOT call",
    "restart_conversation",
]


@pytest.mark.parametrize("seed_filename", SEEDS_REQUIRING_HINT)
def test_seed_has_auditor_hint(seed_filename: str) -> None:
    """Each A1-failing seed must contain an ## Auditor Hint section."""
    path = SEEDS_DIR / seed_filename
    assert path.exists(), f"seed file missing: {path}"
    content = path.read_text(encoding="utf-8")
    assert "## Auditor Hint" in content, (
        f"{seed_filename} missing '## Auditor Hint' section — "
        f"A1 self-restart loop regression guard"
    )


@pytest.mark.parametrize("seed_filename", SEEDS_REQUIRING_HINT)
@pytest.mark.parametrize("phrase", REQUIRED_PHRASES)
def test_seed_hint_has_required_phrase(seed_filename: str, phrase: str) -> None:
    """The hint must contain the load-bearing phrases that prevent the loop."""
    path = SEEDS_DIR / seed_filename
    content = path.read_text(encoding="utf-8")
    # Restrict the search to the hint section only.
    hint_start = content.find("## Auditor Hint")
    assert hint_start != -1, f"{seed_filename}: no Auditor Hint section"
    hint_section = content[hint_start:]
    assert phrase in hint_section, (
        f"{seed_filename}: Auditor Hint missing required phrase {phrase!r}. "
        f"Removing this phrase risks re-introducing the self-restart loop."
    )


def test_passing_seeds_have_no_hint() -> None:
    """Passing seeds (10/13) MUST NOT carry the hint — keeps the hint surface
    scoped to seeds that need it. If a passing seed grows the hint by accident,
    investigate whether that seed has started failing.
    """
    all_seeds = sorted(p.name for p in SEEDS_DIR.glob("*.md"))
    passing = [s for s in all_seeds if s not in SEEDS_REQUIRING_HINT]
    assert len(passing) == 10, f"expected 10 passing seeds, got {len(passing)}"
    for seed in passing:
        content = (SEEDS_DIR / seed).read_text(encoding="utf-8")
        assert "## Auditor Hint" not in content, (
            f"unexpected '## Auditor Hint' in passing seed {seed}: "
            f"if this seed now needs the hint, add it to SEEDS_REQUIRING_HINT"
        )
