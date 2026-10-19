"""ProjectMemory mutation integrity: outcomes, locking, containment (S2)."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest
from core.memory.project import MemoryWrite, ProjectMemory

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def memory(tmp_path: Path) -> ProjectMemory:
    mem = ProjectMemory(tmp_path)
    mem.ensure_structure()
    return mem


def test_outcomes_distinguish_missing_invalid_duplicate_and_written(tmp_path: Path) -> None:
    bare = ProjectMemory(tmp_path)
    assert bare.record_insight("a perfectly valid insight") is MemoryWrite.NOT_FOUND
    assert not bare.memory_file.exists()  # a failed save never creates the file

    bare.ensure_structure()
    assert bare.record_insight("short") is MemoryWrite.INVALID
    assert bare.record_insight("two\nlines of text here") is MemoryWrite.INVALID
    assert bare.record_insight("a perfectly valid insight") is MemoryWrite.APPLIED
    assert bare.record_insight("a perfectly valid insight") is MemoryWrite.UNCHANGED
    assert bare.memory_file.read_text().count("a perfectly valid insight") == 1


def test_write_failure_is_reported_and_leaves_content_unchanged(
    memory: ProjectMemory, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = memory.memory_file.read_bytes()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("core.memory.project.atomic_write_text", fail)
    assert memory.record_insight("an insight that cannot be written") is MemoryWrite.FAILED
    assert memory.change_rule("create", "r", content="body") is MemoryWrite.FAILED
    assert memory.memory_file.read_bytes() == before


def test_unreadable_memory_is_left_byte_identical(memory: ProjectMemory) -> None:
    corrupt = b"# Project Memory\n\xff\xfe not utf-8\n"
    memory.memory_file.write_bytes(corrupt)
    assert memory.record_insight("an insight over corrupt content") is MemoryWrite.FAILED
    assert memory.purge_bad_insights() == 0
    assert memory.memory_file.read_bytes() == corrupt


def test_threads_never_lose_insights(memory: ProjectMemory) -> None:
    def write(n: int) -> None:
        for i in range(5):
            assert memory.record_insight(f"thread {n} recorded fact number {i}") is (
                MemoryWrite.APPLIED
            )

    threads = [threading.Thread(target=write, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    content = memory.memory_file.read_text()
    assert all(
        f"thread {n} recorded fact number {i}" in content for n in range(6) for i in range(5)
    )


_WRITER = """
import sys
from pathlib import Path
from core.memory.project import MemoryWrite, ProjectMemory
mem = ProjectMemory(Path(sys.argv[1]))
for i in range(int(sys.argv[3])):
    assert mem.record_insight(f"process {sys.argv[2]} fact {i:02d}") is MemoryWrite.APPLIED
"""


def test_processes_never_lose_insights(memory: ProjectMemory, tmp_path: Path) -> None:
    procs = [
        subprocess.Popen(  # noqa: S603  # nosec B603 - fixed test interpreter argv
            [sys.executable, "-c", _WRITER, str(tmp_path), f"p{n}", "10"],
            cwd=_REPO_ROOT,
        )
        for n in range(4)
    ]
    assert [proc.wait(timeout=120) for proc in procs] == [0, 0, 0, 0]
    content = memory.memory_file.read_text()
    missing = [
        (n, i) for n in range(4) for i in range(10) if f"process p{n} fact {i:02d}" not in content
    ]
    assert missing == []


def test_concurrent_rule_create_has_one_winner(memory: ProjectMemory) -> None:
    outcomes: list[MemoryWrite] = []
    barrier = threading.Barrier(5)

    def create(n: int) -> None:
        barrier.wait()
        outcomes.append(memory.change_rule("create", "shared", content=f"writer {n}"))

    threads = [threading.Thread(target=create, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(outcomes) == sorted([MemoryWrite.APPLIED] + [MemoryWrite.CONFLICT] * 4)


def test_rule_crud_outcomes(memory: ProjectMemory) -> None:
    assert memory.change_rule("update", "absent", content="x") is MemoryWrite.NOT_FOUND
    assert memory.change_rule("delete", "absent") is MemoryWrite.NOT_FOUND
    for name in ("", "   ", "///", "-" * 3, "x" * 100):
        assert memory.change_rule("create", name, content="x") is MemoryWrite.INVALID, name
    assert not list(memory.rules_dir.glob("*.md"))
    assert memory.change_rule("create", "../escape", content="safe") is MemoryWrite.APPLIED
    assert [p.name for p in memory.rules_dir.glob("*.md")] == ["---escape.md"]


def test_symlinked_rule_is_not_read_or_written_through(
    memory: ProjectMemory, tmp_path: Path
) -> None:
    secret = tmp_path.parent / f"{tmp_path.name}-secret.txt"
    secret.write_text("TOP SECRET CREDENTIAL")
    (memory.rules_dir / "planted.md").symlink_to(secret)

    assert all(rule["name"] != "planted" for rule in memory.list_rules())
    assert all("TOP SECRET" not in rule["content"] for rule in memory.load_rules())
    assert memory.change_rule("update", "planted", content="overwrite") is MemoryWrite.INVALID
    assert memory.change_rule("delete", "planted") is MemoryWrite.INVALID
    assert secret.read_text() == "TOP SECRET CREDENTIAL"


def test_symlinked_memory_and_rules_dir_outside_project_are_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "PROJECT.md").write_text("# outside secret\n## 최근 인사이트\n")
    project = tmp_path / "project"
    (project / ".geode" / "memory").mkdir(parents=True)
    (project / ".geode" / "memory" / "PROJECT.md").symlink_to(outside / "PROJECT.md")
    (project / ".geode" / "rules").symlink_to(outside)
    mem = ProjectMemory(project)

    assert "outside secret" not in mem.load_memory()
    assert mem.record_insight("must not land outside the project") is MemoryWrite.INVALID
    assert mem.change_rule("create", "escape", content="x") is MemoryWrite.INVALID
    assert sorted(p.name for p in outside.iterdir()) == ["PROJECT.md"]
    assert "must not land" not in (outside / "PROJECT.md").read_text()


def test_root_is_frozen_at_construction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    monkeypatch.chdir(tmp_path / "a")
    mem = ProjectMemory()
    mem.ensure_structure()
    monkeypatch.chdir(tmp_path / "b")
    assert mem.record_insight("written to the construction root") is MemoryWrite.APPLIED
    assert "construction root" in (tmp_path / "a/.geode/memory/PROJECT.md").read_text()
    assert not (tmp_path / "b/.geode").exists()


def test_rejected_write_through_symlinked_tier_touches_nothing_outside(tmp_path: Path) -> None:
    """Review 6: containment is checked before any lock file or directory is made."""
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".geode").symlink_to(outside)
    mem = ProjectMemory(project)

    assert mem.change_rule("create", "r", content="x") is MemoryWrite.INVALID
    assert mem.record_insight("a valid insight that must not land") is MemoryWrite.INVALID
    assert mem.purge_bad_insights() == 0
    with pytest.raises(PermissionError):
        mem.ensure_structure()
    assert list(outside.iterdir()) == []
