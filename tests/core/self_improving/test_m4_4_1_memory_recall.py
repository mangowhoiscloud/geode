"""ADR-012 M4.4.1 — memory_recall reader + orchestrator wiring invariants.

Pins:
- ``resolve_recall_dir`` honours ``$GEODE_MEMORY_RECALL_DIR`` override,
  falls back to ``~/.geode/memory/recall/`` when it exists, returns
  ``None`` otherwise.
- ``load_memory_entries`` parses frontmatter MD files; malformed /
  unreadable files silently skipped (per-file graceful).
- ``rank_memory_entries`` orders by ``overlap × recency_weight``;
  ties stable by insertion order; ``top_k=0`` → empty.
- ``format_memory_block`` renders a ``<memory-recall>`` block, empty
  list → empty string.
- Orchestrator integration: when SoT has ``memory_recall`` + recall
  dir has entries, the system prompt receives the rendered block.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def recall_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Override the recall directory via env var."""
    target = tmp_path / "recall"
    target.mkdir()
    monkeypatch.setenv("GEODE_MEMORY_RECALL_DIR", str(target))
    yield target


def _write_memory(
    path: Path,
    *,
    name: str,
    description: str,
    body: str,
    type_label: str = "feedback",
    mtime: float | None = None,
) -> None:
    content = (
        f"---\nname: {name}\ndescription: {description}\n"
        f"metadata:\n  type: {type_label}\n---\n\n{body}\n"
    )
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


# resolve_recall_dir --------------------------------------------------------


def test_resolve_returns_env_override(recall_dir: Path) -> None:
    from core.self_improving.loop.inject.memory_recall import resolve_recall_dir

    assert resolve_recall_dir() == recall_dir


def test_resolve_env_override_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GEODE_MEMORY_RECALL_DIR", str(tmp_path / "nope"))
    from core.self_improving.loop.inject.memory_recall import resolve_recall_dir

    assert resolve_recall_dir() is None


def test_resolve_default_dir_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEODE_MEMORY_RECALL_DIR", raising=False)
    # Point default dir at a guaranteed-missing path
    monkeypatch.setattr(
        "core.self_improving.loop.inject.memory_recall._DEFAULT_RECALL_DIR",
        Path("/no/such/dir/exists"),
    )
    from core.self_improving.loop.inject.memory_recall import resolve_recall_dir

    assert resolve_recall_dir() is None


# load_memory_entries -------------------------------------------------------


def test_load_returns_empty_when_no_recall_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_MEMORY_RECALL_DIR", raising=False)
    monkeypatch.setattr(
        "core.self_improving.loop.inject.memory_recall._DEFAULT_RECALL_DIR",
        Path("/no/such/dir"),
    )
    from core.self_improving.loop.inject.memory_recall import load_memory_entries

    assert load_memory_entries() == []


def test_load_parses_frontmatter(recall_dir: Path) -> None:
    from core.self_improving.loop.inject.memory_recall import load_memory_entries

    _write_memory(
        recall_dir / "feedback-sample.md",
        name="feedback-sample",
        description="user prefers terse output",
        body="Body text here.",
        type_label="feedback",
    )
    entries = load_memory_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "feedback-sample"
    assert entry.type == "feedback"
    assert entry.description == "user prefers terse output"
    assert "Body text here." in entry.body


def test_load_skips_malformed_files(recall_dir: Path) -> None:
    """Files without frontmatter delimiters are silently dropped."""
    from core.self_improving.loop.inject.memory_recall import load_memory_entries

    (recall_dir / "broken.md").write_text("no frontmatter at all\n", encoding="utf-8")
    _write_memory(
        recall_dir / "valid.md",
        name="valid",
        description="ok",
        body="b",
    )
    entries = load_memory_entries()
    assert len(entries) == 1
    assert entries[0].name == "valid"


# rank_memory_entries -------------------------------------------------------


def test_rank_by_overlap(recall_dir: Path) -> None:
    """Memory with matching keywords beats one without (same mtime)."""
    from core.self_improving.loop.inject.memory_recall import (
        load_memory_entries,
        rank_memory_entries,
    )

    now = time.time()
    _write_memory(
        recall_dir / "match.md",
        name="match",
        description="DPO training pipeline notes",
        body="prefer DPO over PPO",
        mtime=now,
    )
    _write_memory(
        recall_dir / "unrelated.md",
        name="unrelated",
        description="kitchen recipe ideas",
        body="pasta carbonara recipe",
        mtime=now,
    )
    entries = load_memory_entries()
    ranked = rank_memory_entries(entries, "explain DPO training", top_k=2, now=now + 1)
    assert ranked[0].name == "match"


def test_rank_recency_tiebreak(recall_dir: Path) -> None:
    """Zero overlap on both → fresher file wins."""
    from core.self_improving.loop.inject.memory_recall import (
        load_memory_entries,
        rank_memory_entries,
    )

    now = time.time()
    _write_memory(
        recall_dir / "old.md",
        name="old",
        description="topic alpha",
        body="b",
        mtime=now - 30 * 86400,  # 30 days old
    )
    _write_memory(
        recall_dir / "fresh.md",
        name="fresh",
        description="topic beta",
        body="b",
        mtime=now - 1 * 86400,  # 1 day old
    )
    entries = load_memory_entries()
    ranked = rank_memory_entries(entries, "unrelated query gamma delta", top_k=2, now=now)
    assert ranked[0].name == "fresh"


def test_rank_top_k_zero_returns_empty(recall_dir: Path) -> None:
    from core.self_improving.loop.inject.memory_recall import (
        load_memory_entries,
        rank_memory_entries,
    )

    _write_memory(recall_dir / "a.md", name="a", description="d", body="b", mtime=time.time())
    assert rank_memory_entries(load_memory_entries(), "q", top_k=0) == []


def test_rank_top_k_caps_results(recall_dir: Path) -> None:
    from core.self_improving.loop.inject.memory_recall import (
        load_memory_entries,
        rank_memory_entries,
    )

    now = time.time()
    for i in range(5):
        _write_memory(recall_dir / f"e{i}.md", name=f"e{i}", description="d", body="b", mtime=now)
    ranked = rank_memory_entries(load_memory_entries(), "q", top_k=3, now=now)
    assert len(ranked) == 3


# format_memory_block -------------------------------------------------------


def test_format_empty_returns_empty_string() -> None:
    from core.self_improving.loop.inject.memory_recall import format_memory_block

    assert format_memory_block([]) == ""


def test_format_preserves_description_when_body_empty() -> None:
    """Regression — earlier ``desc = a or b.splitlines()[0] if b else ""`` had
    wrong precedence (ternary binds looser than ``or``), dropping a valid
    description when ``body == ""``. Pin the explicit-branches form."""
    from core.self_improving.loop.inject.memory_recall import (
        MemoryEntry,
        format_memory_block,
    )

    entry = MemoryEntry(
        name="desc-only",
        type="feedback",
        description="kept even though body is empty",
        body="",
        mtime=0.0,
    )
    block = format_memory_block([entry])
    assert "kept even though body is empty" in block
    assert "[feedback]" in block


def test_format_falls_back_to_body_first_line_when_no_description() -> None:
    """No description but non-empty body → first body line surfaces."""
    from core.self_improving.loop.inject.memory_recall import (
        MemoryEntry,
        format_memory_block,
    )

    entry = MemoryEntry(
        name="body-only",
        type="project",
        description="",
        body="first body line\nsecond ignored",
        mtime=0.0,
    )
    block = format_memory_block([entry])
    assert "first body line" in block
    assert "second ignored" not in block


def test_format_renders_block_with_type_tags(recall_dir: Path) -> None:
    from core.self_improving.loop.inject.memory_recall import (
        format_memory_block,
        load_memory_entries,
    )

    _write_memory(
        recall_dir / "fb.md",
        name="fb",
        description="user wants terse",
        body="b",
        type_label="feedback",
        mtime=time.time(),
    )
    block = format_memory_block(load_memory_entries())
    assert block.startswith("<memory-recall>")
    assert block.endswith("</memory-recall>")
    assert "[feedback] user wants terse" in block


# Orchestrator wiring -------------------------------------------------------


def test_orchestrator_prepends_memory_block(
    recall_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """memory_recall slot active + recall dir has match → block lands in system."""
    from core.self_improving.loop.inject.in_context_slots import (
        SLOT_MEMORY_RECALL,
        InContextSlot,
    )
    from core.self_improving.loop.inject.in_context_wiring import apply_in_context_slots

    monkeypatch.setattr(
        "core.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_MEMORY_RECALL: InContextSlot(
                name=SLOT_MEMORY_RECALL,
                max_entries=3,
                rank_by="recency",
                injection_point="system_prompt",
            )
        },
    )
    _write_memory(
        recall_dir / "matching.md",
        name="matching",
        description="DPO preference signals",
        body="signal body",
        mtime=time.time(),
    )
    msgs = [{"role": "user", "content": "explain DPO training"}]
    _, new_sys = apply_in_context_slots(msgs, system="ORIGINAL")
    assert "<memory-recall>" in new_sys
    assert "[feedback] DPO preference signals" in new_sys
    assert new_sys.endswith("ORIGINAL")


def test_orchestrator_no_op_when_recall_dir_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """memory_recall slot active but no recall dir → system unchanged."""
    from core.self_improving.loop.inject.in_context_slots import (
        SLOT_MEMORY_RECALL,
        InContextSlot,
    )
    from core.self_improving.loop.inject.in_context_wiring import apply_in_context_slots

    monkeypatch.delenv("GEODE_MEMORY_RECALL_DIR", raising=False)
    monkeypatch.setattr(
        "core.self_improving.loop.inject.memory_recall._DEFAULT_RECALL_DIR",
        Path("/no/such/dir"),
    )
    monkeypatch.setattr(
        "core.self_improving.loop.inject.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_MEMORY_RECALL: InContextSlot(
                name=SLOT_MEMORY_RECALL,
                max_entries=3,
                rank_by="recency",
                injection_point="system_prompt",
            )
        },
    )
    _, new_sys = apply_in_context_slots([{"role": "user", "content": "task"}], system="SYS")
    assert new_sys == "SYS"
