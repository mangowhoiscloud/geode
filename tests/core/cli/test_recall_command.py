"""``/recall`` slash command — D-3 decision ③ (2026-06-10).

The OL-C3 writer (``core/memory/recall_writer``) promised a CLI/REPL
surface in its docstring while the M4.4.1 reader was already live; these
tests pin the slash that closes the loop: save writes a frontmatter MD
the reader can parse, list renders via the reader's own parser
(one schema, one parser), and the no-TTY save path fails loudly instead
of writing empty fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.cli.commands.recall import cmd_recall
from core.memory.recall_writer import GEODE_MEMORY_RECALL_DIR_ENV


@pytest.fixture()
def recall_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pool_dir = tmp_path / "recall"
    pool_dir.mkdir()
    monkeypatch.setenv(GEODE_MEMORY_RECALL_DIR_ENV, str(pool_dir))
    return pool_dir


def test_save_writes_reader_parseable_entry(
    recall_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_recall('save quota-pref --type project --desc "Sonnet on quota" --body "Switch model."')

    entry_file = recall_dir / "quota-pref.md"
    assert entry_file.is_file()
    content = entry_file.read_text(encoding="utf-8")
    assert "name: quota-pref" in content
    assert "type: project" in content
    assert content.rstrip().endswith("Switch model.")
    assert "saved" in capsys.readouterr().out

    # Read-write parity — the M4.4.1 reader must parse what save wrote.
    from core.self_improving.loop.memory_recall import load_memory_entries

    entries = load_memory_entries()
    assert [e.name for e in entries] == ["quota-pref"]
    assert entries[0].type == "project"
    assert entries[0].description == "Sonnet on quota"


def test_save_refuses_duplicate_without_overwrite(
    recall_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_recall('save dup --desc "first" --body "first body"')
    cmd_recall('save dup --desc "second" --body "second body"')
    out = capsys.readouterr().out
    assert "not written" in out
    assert "first body" in (recall_dir / "dup.md").read_text(encoding="utf-8")

    cmd_recall('save dup --desc "second" --body "second body" --overwrite')
    assert "second body" in (recall_dir / "dup.md").read_text(encoding="utf-8")


def test_save_rejects_invalid_type(recall_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_recall('save bad --type nonsense --desc "d" --body "b"')
    assert "invalid type" in capsys.readouterr().out
    assert not (recall_dir / "bad.md").exists()


def test_save_without_body_and_no_tty_fails_loudly(
    recall_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # pytest's captured stdin is not a TTY — the interactive fallback must
    # refuse rather than write an empty field.
    cmd_recall('save no-body --desc "d"')
    assert "required without a TTY" in capsys.readouterr().out
    assert not (recall_dir / "no-body.md").exists()


def test_list_and_show_roundtrip(recall_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_recall('save alpha --type user --desc "alpha desc" --body "alpha body"')
    capsys.readouterr()

    cmd_recall("list")
    listed = capsys.readouterr().out
    assert "alpha" in listed
    assert "alpha desc" in listed
    assert "1 entries" in listed

    cmd_recall("show alpha")
    shown = capsys.readouterr().out
    assert "alpha body" in shown


def test_show_unknown_name_hints(recall_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_recall("show missing")
    assert "no entry named" in capsys.readouterr().out


def test_unknown_action_hints(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_recall("frobnicate")
    out = capsys.readouterr().out
    assert "Unknown action" in out
    assert "save" in out
