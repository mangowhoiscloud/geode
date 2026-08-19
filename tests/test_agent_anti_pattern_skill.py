from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_agent_anti_pattern_skill_is_shared_and_fail_closed() -> None:
    canonical = ROOT / ".agents/skills/agent-anti-pattern"
    claude_alias = ROOT / ".claude/skills/agent-anti-pattern"
    skill = (canonical / "SKILL.md").read_text(encoding="utf-8")
    guide = (canonical / "references/field-guide.md").read_text(encoding="utf-8")

    assert claude_alias.is_symlink()
    assert claude_alias.resolve() == canonical.resolve()
    assert "Candidate discovery only" in guide
    assert "Unknown is `MEASURE` or `DEFER`, never `DELETE`" in guide
    assert all(f"AP-{index}" in guide for index in range(1, 7))
    assert all(verdict in skill for verdict in ("KEEP", "SHRINK", "DELETE", "MEASURE", "DEFER"))
    assert "Do not impose universal tool-count" in skill
