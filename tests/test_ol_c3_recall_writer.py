"""OL-C3 — memory_recall MD writer invariants.

Pins:
- ``write_recall_entry`` writes frontmatter MD matching M4.4.1 reader's
  schema (name / description / metadata.type) so round-trip works.
- Idempotency: same slug → ``None`` (no overwrite) unless explicit
  ``overwrite=True``.
- Filename slugification: arbitrary names become filesystem-safe slugs.
- Resolution chain: ``$GEODE_MEMORY_RECALL_DIR`` env > default.
- Graceful: OSError logged + returns ``None`` (no raise).
- Round-trip with M4.4.1 reader (`load_memory_entries`).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def recall_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "recall"
    monkeypatch.setenv("GEODE_MEMORY_RECALL_DIR", str(target))
    yield target


# resolve_recall_dir --------------------------------------------------------


def test_resolve_uses_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from core.memory.recall_writer import resolve_recall_dir

    monkeypatch.setenv("GEODE_MEMORY_RECALL_DIR", str(tmp_path / "custom"))
    assert resolve_recall_dir() == tmp_path / "custom"


def test_resolve_default_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.memory.recall_writer import resolve_recall_dir

    monkeypatch.delenv("GEODE_MEMORY_RECALL_DIR", raising=False)
    # Default ends with `memory/recall`
    assert resolve_recall_dir().name == "recall"
    assert resolve_recall_dir().parent.name == "memory"


# slugify -------------------------------------------------------------------


def test_slugify_canonical_input() -> None:
    from core.memory.recall_writer import _slugify_name

    assert _slugify_name("feedback-cli-budget") == "feedback-cli-budget"


def test_slugify_strips_spaces_and_punctuation() -> None:
    from core.memory.recall_writer import _slugify_name

    assert _slugify_name("User Wants Terse Output!") == "user-wants-terse-output"


def test_slugify_empty_input_yields_untitled() -> None:
    from core.memory.recall_writer import _slugify_name

    assert _slugify_name("") == "untitled"
    assert _slugify_name("!!!") == "untitled"


# write_recall_entry --------------------------------------------------------


def test_write_creates_md_file(recall_dir: Path) -> None:
    from core.memory.recall_writer import write_recall_entry

    path = write_recall_entry(
        name="feedback-test",
        description="user prefers terse",
        body="The user told me they want short responses.",
        type_label="feedback",
    )
    assert path is not None
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "name: feedback-test" in content
    assert "description: user prefers terse" in content
    assert "type: feedback" in content
    assert "The user told me they want short responses." in content


def test_write_round_trips_with_m4_4_1_reader(recall_dir: Path) -> None:
    """Writer output must parse cleanly via M4.4.1's reader."""
    from core.memory.recall_writer import write_recall_entry
    from core.self_improving.loop.memory_recall import load_memory_entries

    write_recall_entry(
        name="feedback-roundtrip",
        description="round-trip check",
        body="Body content for the round-trip.",
        type_label="feedback",
    )
    entries = load_memory_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "feedback-roundtrip"
    assert entry.description == "round-trip check"
    assert entry.type == "feedback"
    assert "Body content for the round-trip." in entry.body


def test_write_idempotent_no_overwrite_default(recall_dir: Path) -> None:
    """Second write with same slug → None, file unchanged."""
    from core.memory.recall_writer import write_recall_entry

    p1 = write_recall_entry(name="same", description="first", body="b1", type_label="user")
    assert p1 is not None
    p2 = write_recall_entry(name="same", description="second", body="b2", type_label="user")
    assert p2 is None
    # Original content preserved
    assert "description: first" in p1.read_text(encoding="utf-8")
    assert "b1" in p1.read_text(encoding="utf-8")


def test_write_overwrites_when_flag_set(recall_dir: Path) -> None:
    from core.memory.recall_writer import write_recall_entry

    p1 = write_recall_entry(name="same", description="first", body="b1", type_label="user")
    p2 = write_recall_entry(
        name="same",
        description="second",
        body="b2",
        type_label="user",
        overwrite=True,
    )
    assert p2 is not None
    assert p2 == p1
    content = p2.read_text(encoding="utf-8")
    assert "description: second" in content
    assert "b2" in content


def test_write_strips_newlines_from_frontmatter(recall_dir: Path) -> None:
    """Newlines in name / description would break YAML-light parser."""
    from core.memory.recall_writer import write_recall_entry

    path = write_recall_entry(
        name="multi\nline\nname",
        description="multi\nline\ndesc",
        body="body keeps\nnewlines\nfine",
        type_label="user",
    )
    assert path is not None
    content = path.read_text(encoding="utf-8")
    # frontmatter section (before second ---) must NOT contain raw \n in values
    parts = content.split("---")
    assert len(parts) >= 3
    fm = parts[1]
    # Lines within fm starting with "name:" / "description:" must be single-line
    for line in fm.splitlines():
        if line.startswith(("name:", "description:")):
            assert "\n" not in line and "\r" not in line
    # body section keeps newlines
    body_section = parts[2]
    assert "body keeps\nnewlines\nfine" in body_section


def test_write_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing parent dir → created lazily."""
    from core.memory.recall_writer import write_recall_entry

    nested = tmp_path / "subdir" / "deeper" / "recall"
    monkeypatch.setenv("GEODE_MEMORY_RECALL_DIR", str(nested))
    assert not nested.exists()
    path = write_recall_entry(name="nested-test", description="d", body="b", type_label="user")
    assert path is not None
    assert nested.is_dir()


def test_write_unknown_type_label_still_writes(recall_dir: Path) -> None:
    """Non-canonical type_label is allowed (logged DEBUG, not rejected)."""
    from core.memory.recall_writer import write_recall_entry

    path = write_recall_entry(
        name="custom-type",
        description="d",
        body="b",
        type_label="custom_operator_type",
    )
    assert path is not None
    assert "type: custom_operator_type" in path.read_text(encoding="utf-8")


def test_write_escapes_newlines_in_type_label(recall_dir: Path) -> None:
    """type_label with embedded newlines must NOT inject frontmatter keys.

    Codex MCP catch (PR-OL-C3 fix-up). Without escaping,
    ``type_label="user\\nname: hijack"`` would write::

        metadata:
          type: user
        name: hijack
        ---

    and the reader would override the original ``name`` field.
    The escape collapses the newline so the injected key never reaches
    the reader's parser.
    """
    from core.memory.recall_writer import write_recall_entry
    from core.self_improving.loop.memory_recall import load_memory_entries

    write_recall_entry(
        name="original-name",
        description="d",
        body="b",
        type_label="user\nname: hijack",
    )
    entries = load_memory_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "original-name"
    assert "hijack" not in entry.name


# list_recall_entries -------------------------------------------------------


def test_list_returns_sorted_paths(recall_dir: Path) -> None:
    from core.memory.recall_writer import list_recall_entries, write_recall_entry

    for slug in ["zeta", "alpha", "mike"]:
        write_recall_entry(name=slug, description="d", body="b", type_label="user")
    paths = list_recall_entries()
    names = [p.stem for p in paths]
    assert names == sorted(names)


def test_list_empty_when_dir_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from core.memory.recall_writer import list_recall_entries

    monkeypatch.setenv("GEODE_MEMORY_RECALL_DIR", str(tmp_path / "no_such_dir"))
    assert list_recall_entries() == []


# write_recall_entries (batch) ----------------------------------------------


def test_batch_writes_all_entries(recall_dir: Path) -> None:
    from core.memory.recall_writer import (
        list_recall_entries,
        write_recall_entries,
    )

    paths = write_recall_entries(
        [
            {"name": "a", "description": "ad", "body": "ab"},
            {"name": "b", "description": "bd", "body": "bb", "type_label": "project"},
            {"name": "c", "description": "cd", "body": "cb"},
        ]
    )
    assert len(paths) == 3
    assert len(list_recall_entries()) == 3


def test_batch_skips_existing_without_overwrite(recall_dir: Path) -> None:
    from core.memory.recall_writer import write_recall_entries

    # First batch
    paths_a = write_recall_entries([{"name": "dup", "description": "d1", "body": "b1"}])
    assert len(paths_a) == 1
    # Second batch — same slug
    paths_b = write_recall_entries([{"name": "dup", "description": "d2", "body": "b2"}])
    assert len(paths_b) == 0
