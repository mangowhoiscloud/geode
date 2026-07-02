"""PR-MEMORY-LIFECYCLE — project-memory decay + dedup promotion proposals.

Covers: resolution frontmatter parsing, guard-test existence (static ast,
never pytest), decay verdicts incl. missing-guard resurface + WARNING,
archive move idempotency, `_archive/` exclusion from the prompt-injection
reader, Jaccard clustering threshold, the >=3-distinct-sessions gate,
proposal file shape, hook firing, and the rules/PROJECT.md no-write pin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from core.hooks import HookEvent, HookSystem
from core.memory.memory_lifecycle import (
    ARCHIVE_DIR_NAME,
    PROPOSALS_DIR_NAME,
    PromotionSource,
    apply_decay,
    cluster_sources,
    evaluate_decay,
    guard_test_exists,
    load_lifecycle_entries,
    propose_memory_promotions,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_entry(
    memory_dir: Path,
    name: str,
    *,
    body: str = "insight body",
    description: str = "an insight",
    guard_test: str = "",
    sessions: list[str] | None = None,
) -> Path:
    lines = ["---", f"name: {name}", f"description: {description}"]
    if sessions:
        lines.append("sessions:")
        lines.extend(f"  - {sid}" for sid in sessions)
    if guard_test:
        lines.extend(
            [
                "resolution:",
                '  pr: "#2400"',
                f"  guard_test: {guard_test}",
                "  resolved_at: 2026-06-20T09:00:00",
            ]
        )
    lines.extend(["---", "", body])
    path = memory_dir / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Fixture tree with a memory dir and a guard test file."""
    memory_dir = tmp_path / ".geode" / "memory"
    memory_dir.mkdir(parents=True)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_guard.py").write_text(
        "class TestGroup:\n"
        "    def test_in_class(self):\n"
        "        pass\n"
        "\n"
        "def test_cron_dedup():\n"
        "    pass\n"
        "\n"
        "async def test_async_guard():\n"
        "    pass\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def memory_dir(repo_root: Path) -> Path:
    return repo_root / ".geode" / "memory"


@dataclass
class _FakeArtifact:
    artifact_id: str
    session_id: str
    content: str


class _FakeSessionManager:
    def __init__(self, artifacts: list[_FakeArtifact]) -> None:
        self._artifacts = artifacts
        self.requested_kinds: tuple[str, ...] | None = None

    def list_context_artifacts(self, *, kinds=None, limit=20, session_id=None):
        self.requested_kinds = tuple(kinds or ())
        return self._artifacts[:limit]


_DUP_TEXT = (
    "scheduler fired duplicate cron jobs in the same minute causing "
    "double execution of weekly engineering reports"
)


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------


class TestEntryParsing:
    def test_resolution_frontmatter_parsed(self, memory_dir: Path):
        _write_entry(
            memory_dir,
            "defect-cron",
            guard_test="tests/test_guard.py::test_cron_dedup",
            sessions=["sess-1", "sess-2"],
        )
        entries = load_lifecycle_entries(memory_dir)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.resolution is not None
        assert entry.resolution.pr == "#2400"
        assert entry.resolution.guard_test == "tests/test_guard.py::test_cron_dedup"
        assert entry.resolution.resolved_at == "2026-06-20T09:00:00"
        assert entry.sessions == ("sess-1", "sess-2")
        assert entry.archived is False

    def test_entry_without_resolution_has_none(self, memory_dir: Path):
        _write_entry(memory_dir, "plain-insight")
        entries = load_lifecycle_entries(memory_dir)
        assert entries[0].resolution is None

    def test_missing_frontmatter_warned_and_skipped(
        self, memory_dir: Path, caplog: pytest.LogCaptureFixture
    ):
        (memory_dir / "raw.md").write_text("no frontmatter here", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            entries = load_lifecycle_entries(memory_dir)
        assert entries == []
        assert "no frontmatter" in caplog.text

    def test_project_md_is_never_an_entry(self, memory_dir: Path):
        (memory_dir / "PROJECT.md").write_text("---\nname: PROJECT\n---\nindex", encoding="utf-8")
        assert load_lifecycle_entries(memory_dir) == []


# ---------------------------------------------------------------------------
# Guard-test existence (static parse — never pytest)
# ---------------------------------------------------------------------------


class TestGuardTestExists:
    def test_module_level_function(self, repo_root: Path):
        assert guard_test_exists("tests/test_guard.py::test_cron_dedup", repo_root=repo_root)

    def test_class_method(self, repo_root: Path):
        assert guard_test_exists(
            "tests/test_guard.py::TestGroup::test_in_class", repo_root=repo_root
        )

    def test_async_function_and_parametrize_id(self, repo_root: Path):
        assert guard_test_exists("tests/test_guard.py::test_async_guard", repo_root=repo_root)
        assert guard_test_exists(
            "tests/test_guard.py::test_cron_dedup[case-a]", repo_root=repo_root
        )

    def test_missing_test_name(self, repo_root: Path):
        assert not guard_test_exists("tests/test_guard.py::test_vanished", repo_root=repo_root)

    def test_missing_file_and_malformed_ref(self, repo_root: Path):
        assert not guard_test_exists("tests/nope.py::test_x", repo_root=repo_root)
        assert not guard_test_exists("tests/test_guard.py", repo_root=repo_root)


# ---------------------------------------------------------------------------
# Decay verdicts + archive moves
# ---------------------------------------------------------------------------


class TestDecay:
    def test_guard_exists_verdict_archived(self, memory_dir: Path, repo_root: Path):
        _write_entry(memory_dir, "resolved", guard_test="tests/test_guard.py::test_cron_dedup")
        verdicts = evaluate_decay(load_lifecycle_entries(memory_dir), repo_root=repo_root)
        assert [v.verdict for v in verdicts] == ["archived"]

    def test_missing_guard_verdict_resurface_with_warning(
        self, memory_dir: Path, repo_root: Path, caplog: pytest.LogCaptureFixture
    ):
        _write_entry(memory_dir, "stale", guard_test="tests/test_guard.py::test_vanished")
        with caplog.at_level(logging.WARNING):
            verdicts = evaluate_decay(load_lifecycle_entries(memory_dir), repo_root=repo_root)
        assert [v.verdict for v in verdicts] == ["resurface"]
        assert "no longer exists" in caplog.text

    def test_no_resolution_verdict_active_no_time_decay(self, memory_dir: Path, repo_root: Path):
        _write_entry(memory_dir, "open-insight")
        verdicts = evaluate_decay(load_lifecycle_entries(memory_dir), repo_root=repo_root)
        assert [v.verdict for v in verdicts] == ["active"]

    def test_apply_moves_to_archive_and_is_idempotent(self, memory_dir: Path, repo_root: Path):
        entry_path = _write_entry(
            memory_dir, "resolved", guard_test="tests/test_guard.py::test_cron_dedup"
        )
        verdicts = evaluate_decay(load_lifecycle_entries(memory_dir), repo_root=repo_root)
        moves = apply_decay(verdicts, memory_dir=memory_dir)
        archived_path = memory_dir / ARCHIVE_DIR_NAME / "resolved.md"
        assert moves == [(entry_path, archived_path)]
        assert archived_path.exists() and not entry_path.exists()

        # Second pass: entry already archived, guard still exists — no move.
        verdicts2 = evaluate_decay(load_lifecycle_entries(memory_dir), repo_root=repo_root)
        assert [v.verdict for v in verdicts2] == ["archived"]
        assert apply_decay(verdicts2, memory_dir=memory_dir) == []
        assert archived_path.exists()

    def test_resurface_moves_back_from_archive(self, memory_dir: Path, repo_root: Path):
        archive = memory_dir / ARCHIVE_DIR_NAME
        _write_entry(archive, "was-resolved", guard_test="tests/test_guard.py::test_vanished")
        verdicts = evaluate_decay(load_lifecycle_entries(memory_dir), repo_root=repo_root)
        assert [v.verdict for v in verdicts] == ["resurface"]
        apply_decay(verdicts, memory_dir=memory_dir)
        assert (memory_dir / "was-resolved.md").exists()
        assert not (archive / "was-resolved.md").exists()

    def test_archived_excluded_from_active_load(self, memory_dir: Path):
        _write_entry(memory_dir / ARCHIVE_DIR_NAME, "gone", body="archived body")
        _write_entry(memory_dir, "live", body="live body")
        active = load_lifecycle_entries(memory_dir, include_archived=False)
        assert [e.name for e in active] == ["live"]

    def test_injection_reader_skips_archive_subdir(
        self, memory_dir: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Pin the prompt-injection exclusion: the recall reader's walk must
        never surface `_archive/` (or `_proposals/`) entries."""
        from core.self_improving.loop.inject.memory_recall import load_memory_entries

        _write_entry(memory_dir, "live", description="live memory")
        _write_entry(memory_dir / ARCHIVE_DIR_NAME, "dead", description="archived memory")
        (memory_dir / PROPOSALS_DIR_NAME).mkdir()
        _write_entry(memory_dir / PROPOSALS_DIR_NAME, "pending", description="proposal")
        monkeypatch.setenv("GEODE_MEMORY_RECALL_DIR", str(memory_dir))
        names = [entry.name for entry in load_memory_entries()]
        assert "live" in names
        assert "dead" not in names
        assert "pending" not in names


# ---------------------------------------------------------------------------
# Dedup clustering + promotion proposals
# ---------------------------------------------------------------------------


class TestClustering:
    def test_near_duplicates_cluster_together(self):
        sources = [
            PromotionSource("dream", f"a{i}", f"s{i}", _DUP_TEXT + f" occurrence {i}")
            for i in range(3)
        ]
        clusters = cluster_sources(sources)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_below_threshold_stays_separate(self):
        sources = [
            PromotionSource("dream", "a1", "s1", _DUP_TEXT),
            PromotionSource(
                "dream", "a2", "s2", "docs link checker found broken anchors in site pages"
            ),
        ]
        assert len(cluster_sources(sources)) == 2


class TestPromotionProposals:
    def _sources(self, session_count: int) -> _FakeSessionManager:
        return _FakeSessionManager(
            [
                _FakeArtifact(f"art-{i}", f"sess-{i}", _DUP_TEXT + f" occurrence {i}")
                for i in range(session_count)
            ]
        )

    def test_two_sessions_below_gate_no_proposal(self, memory_dir: Path):
        proposals = propose_memory_promotions(
            memory_dir=memory_dir, session_manager=self._sources(2)
        )
        assert proposals == []

    def test_three_distinct_sessions_yields_proposal(self, memory_dir: Path):
        session_manager = self._sources(3)
        proposals = propose_memory_promotions(
            memory_dir=memory_dir, session_manager=session_manager
        )
        assert len(proposals) == 1
        assert proposals[0].session_ids == ("sess-0", "sess-1", "sess-2")
        assert session_manager.requested_kinds == ("dream",)

    def test_repeated_sessions_do_not_count_as_distinct(self, memory_dir: Path):
        artifacts = [
            _FakeArtifact(f"art-{i}", "sess-same", _DUP_TEXT + f" occurrence {i}") for i in range(4)
        ]
        proposals = propose_memory_promotions(
            memory_dir=memory_dir, session_manager=_FakeSessionManager(artifacts)
        )
        assert proposals == []

    def test_dry_run_writes_nothing_and_fires_no_hook(self, memory_dir: Path):
        fired: list[dict] = []
        hooks = HookSystem()
        hooks.register(HookEvent.MEMORY_PROMOTION_PROPOSED, lambda _e, d: fired.append(d))
        proposals = propose_memory_promotions(
            memory_dir=memory_dir, session_manager=self._sources(3), hooks=hooks
        )
        assert len(proposals) == 1
        assert not (memory_dir / PROPOSALS_DIR_NAME).exists()
        assert fired == []

    def test_apply_writes_proposal_file_shape(self, memory_dir: Path):
        proposals = propose_memory_promotions(
            memory_dir=memory_dir, session_manager=self._sources(3), apply=True
        )
        proposal = proposals[0]
        assert proposal.path.parent == memory_dir / PROPOSALS_DIR_NAME
        content = proposal.path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert f"slug: {proposal.slug}" in content
        assert "session_count: 3" in content
        assert "## Merged insight" in content
        assert _DUP_TEXT.split()[0] in content
        assert "## Source sessions" in content
        for sid in ("sess-0", "sess-1", "sess-2"):
            assert f"`{sid}`" in content
        assert "## Lineage" in content
        assert "superseded_by this proposal: dream `art-0`" in content

    def test_apply_fires_hook_with_payload(self, memory_dir: Path):
        fired: list[dict] = []
        hooks = HookSystem()
        hooks.register(HookEvent.MEMORY_PROMOTION_PROPOSED, lambda _e, d: fired.append(d))
        proposals = propose_memory_promotions(
            memory_dir=memory_dir, session_manager=self._sources(3), apply=True, hooks=hooks
        )
        assert len(fired) == 1
        payload = fired[0]
        assert payload["slug"] == proposals[0].slug
        assert payload["session_ids"] == ["sess-0", "sess-1", "sess-2"]
        assert payload["source_count"] == 3
        assert payload["proposal_path"].endswith(".md")

    def test_apply_is_idempotent_same_slug(self, memory_dir: Path):
        for _round in range(2):
            propose_memory_promotions(
                memory_dir=memory_dir, session_manager=self._sources(3), apply=True
            )
        files = list((memory_dir / PROPOSALS_DIR_NAME).glob("*.md"))
        assert len(files) == 1

    def test_active_memory_entries_join_clusters(self, memory_dir: Path):
        _write_entry(
            memory_dir,
            "dup-insight",
            description=_DUP_TEXT,
            body=_DUP_TEXT,
            sessions=["sess-x"],
        )
        proposals = propose_memory_promotions(
            memory_dir=memory_dir, session_manager=self._sources(2)
        )
        # 2 dream sessions + 1 entry session = 3 distinct → proposal.
        assert len(proposals) == 1
        kinds = {source.kind for source in proposals[0].sources}
        assert kinds == {"dream", "memory_entry"}

    def test_never_writes_rules_or_project_md(self, memory_dir: Path, repo_root: Path):
        rules_dir = repo_root / ".geode" / "rules"
        rules_dir.mkdir(parents=True)
        rule = rules_dir / "existing.md"
        rule.write_text("---\nname: existing\n---\nrule body", encoding="utf-8")
        project_md = memory_dir / "PROJECT.md"
        project_md.write_text("# Project Memory\n", encoding="utf-8")

        propose_memory_promotions(
            memory_dir=memory_dir, session_manager=self._sources(3), apply=True
        )
        assert rule.read_text(encoding="utf-8") == "---\nname: existing\n---\nrule body"
        assert project_md.read_text(encoding="utf-8") == "# Project Memory\n"
        assert list(rules_dir.glob("*.md")) == [rule]
