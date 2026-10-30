"""Migration binds ownership and leaves only the canonical store readable."""

from __future__ import annotations

import json
import socket
import tempfile
from pathlib import Path

import pytest
from core.paths import encode_project_id
from core.wiring.layout_migrator import (
    WorkspaceMigrationError,
    ensure_project_layout,
    migrate_workspace_vault,
)


def test_dash_collisions_and_directory_aliases(tmp_path: Path) -> None:
    first, second = tmp_path / "a-b" / "c", tmp_path / "a" / "b-c"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    assert encode_project_id(first) != encode_project_id(second)
    alias = tmp_path / "alias"
    alias.symlink_to(first, target_is_directory=True)
    assert encode_project_id(alias) == encode_project_id(first)


def test_explicit_owner_binding_preserves_bytes_and_removes_legacy(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    projects = tmp_path / "home" / "projects"
    old = projects / str(workspace).replace("/", "-")
    old.mkdir(parents=True)
    (old / "data.db").write_bytes(b"durable-session-data")
    target = projects / encode_project_id(workspace)
    with pytest.raises(WorkspaceMigrationError, match="ambiguous"):
        ensure_project_layout(workspace, target)
    assert old.is_dir() and not target.exists()
    ensure_project_layout(workspace, target, legacy_project=old)
    ensure_project_layout(workspace, target)
    assert not old.exists()
    assert (target / "data.db").read_bytes() == b"durable-session-data"
    assert json.loads((target / ".workspace.json").read_text())["workspace"] == str(workspace)


def test_local_old_store_removed_and_empty_destination_adopted(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    old = workspace / ".geode" / "session"
    old.mkdir(parents=True)
    (old / "state.json").write_text('{"session_id":"one"}')
    target = tmp_path / "home" / "projects" / encode_project_id(workspace)
    ensure_project_layout(workspace, target)
    assert not old.exists()
    assert (target / "sessions" / "state.json").exists()
    vault = workspace / ".geode" / "vault"
    vault.mkdir()
    (vault / "receipt.md").write_text("keep")
    global_vault = tmp_path / "home" / "vault"
    global_vault.mkdir()
    migrate_workspace_vault(workspace, global_vault)
    assert not vault.exists() and (global_vault / "receipt.md").read_text() == "keep"


def test_live_legacy_runtime_blocks_data_move(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    old = workspace / ".geode" / "session"
    old.mkdir(parents=True)
    (old / "state.json").write_text("keep")
    with tempfile.TemporaryDirectory(prefix="gcut-", dir="/tmp") as short_home:
        home = Path(short_home)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(home / "cli.sock"))
            listener.listen()
            with pytest.raises(WorkspaceMigrationError, match="Stop the legacy"):
                ensure_project_layout(workspace, home / "projects" / encode_project_id(workspace))
    assert (old / "state.json").read_text() == "keep"


def test_offloaded_results_move_once_without_retaining_an_alternate_reader(tmp_path: Path):
    workspace = tmp_path / "work"
    old = workspace / ".geode" / "tool-offload"
    (old / "session").mkdir(parents=True)
    content = b'{"result":{"content":"keep complete result"},"offloaded_at":1}'
    (old / "session" / "ref.json").write_bytes(content)
    target = tmp_path / "home" / "projects" / encode_project_id(workspace)
    ensure_project_layout(workspace, target)
    ensure_project_layout(workspace, target)
    assert not old.exists()
    assert (target / "tool-offload" / "session" / "ref.json").read_bytes() == content


def test_empty_vault_categories_do_not_conflict_with_existing_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    old = workspace / ".geode" / "vault"
    for name in ("applications", "general/nested", "profile", "research"):
        (old / name).mkdir(parents=True)
    target = tmp_path / "home" / "vault"
    target.mkdir(parents=True)
    artifact = target / "keep.md"
    artifact.write_text("existing artifact")
    migrate_workspace_vault(workspace, target)
    assert not old.exists()
    assert list(target.iterdir()) == [artifact]
    assert artifact.read_text() == "existing artifact"


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("workspace_alias", [False, True])
def test_home_workspace_keeps_its_existing_global_vault(
    tmp_path: Path, populated: bool, workspace_alias: bool
) -> None:
    home = tmp_path / "home"
    vault = home / ".geode" / "vault"
    category = vault / "general"
    category.mkdir(parents=True)
    artifact = category / "keep.md"
    if populated:
        artifact.write_bytes(b"existing global artifact")
    inode = vault.stat().st_ino
    workspace = home
    if workspace_alias:
        workspace = tmp_path / "home-alias"
        workspace.symlink_to(home, target_is_directory=True)

    migrate_workspace_vault(workspace, vault)
    migrate_workspace_vault(workspace, vault)

    assert vault.stat().st_ino == inode
    assert category.is_dir()
    if populated:
        assert artifact.read_bytes() == b"existing global artifact"


@pytest.mark.parametrize(
    "filename,content", [("artifact.md", "keep"), ("empty", ""), (".keep", "")]
)
def test_any_vault_file_preserves_conflict(tmp_path: Path, filename: str, content: str) -> None:
    workspace = tmp_path / "work"
    old = workspace / ".geode" / "vault"
    old.mkdir(parents=True)
    (old / filename).write_text(content)
    target = tmp_path / "home" / "vault"
    target.mkdir(parents=True)
    (target / "existing.md").write_text("existing")
    with pytest.raises(WorkspaceMigrationError, match="Both migration stores exist"):
        migrate_workspace_vault(workspace, target)
    assert (old / filename).read_text() == content
    assert (target / "existing.md").read_text() == "existing"


def test_empty_vault_cleanup_preserves_concurrently_added_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "work"
    category = workspace / ".geode" / "vault" / "general"
    category.mkdir(parents=True)
    original = Path.rmdir

    def add_before_remove(path: Path) -> None:
        if path == category:
            (path / "new.md").write_text("concurrent writer")
        original(path)

    monkeypatch.setattr(Path, "rmdir", add_before_remove)
    with pytest.raises(OSError):
        migrate_workspace_vault(workspace, tmp_path / "home" / "vault")
    assert (category / "new.md").read_text() == "concurrent writer"


def test_symlink_root_is_rejected_before_any_destination_write(tmp_path: Path) -> None:
    workspace, outside = tmp_path / "work", tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / ".geode").symlink_to(outside, target_is_directory=True)
    target = tmp_path / "home" / "projects" / encode_project_id(workspace)
    with pytest.raises(WorkspaceMigrationError, match="symlink"):
        ensure_project_layout(workspace, target)
    assert not target.parent.exists() and not list(outside.iterdir())


def test_sessions_and_search_survive_global_cutover_and_retry(tmp_path: Path) -> None:
    from core.memory.search_index import SearchIndex
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState

    workspace = tmp_path / "work"
    projects = tmp_path / "home" / "projects"
    old = projects / str(workspace).replace("/", "-")
    SessionCheckpoint(old / "sessions").save(
        SessionState(
            session_id="source",
            messages=[
                {"role": "user", "content": "cutoverneedle"},
                {"role": "assistant", "content": "retained"},
            ],
        )
    )
    index_path = projects.parent / "search" / "global.db"
    with SearchIndex(index_path) as index:
        index.rebuild(projects)
        assert len(index.search("cutoverneedle", project_id=old.name)) == 1
    target = projects / encode_project_id(workspace)
    ensure_project_layout(workspace, target, legacy_project=old)
    ensure_project_layout(workspace, target)
    assert not old.exists() and not (target / ".search-index-cutover").exists()
    assert SessionCheckpoint(target / "sessions").load("source") is not None
    with SearchIndex(index_path) as index:
        hits = index.search("cutoverneedle", project_id=target.name)
        assert len(hits) == 1 and hits[0].project_slug == str(workspace)
        assert not index.search("cutoverneedle", project_id=old.name)
        index.rebuild(projects)
        assert index.search("cutoverneedle")[0].project_slug == str(workspace)


@pytest.mark.parametrize("commit_before_failure", [False, True])
def test_index_failure_retains_replay_marker_until_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_before_failure: bool
) -> None:
    import sqlite3

    from core.memory.search_index import SearchIndex
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState

    workspace = tmp_path / "work"
    projects = tmp_path / "home" / "projects"
    old = projects / str(workspace).replace("/", "-")
    SessionCheckpoint(old / "sessions").save(
        SessionState(session_id="one", messages=[{"role": "user", "content": "retryneedle"}])
    )
    index_path = projects.parent / "search" / "global.db"
    with SearchIndex(index_path) as index:
        index.rebuild(projects)
    target = projects / encode_project_id(workspace)
    relocate = SearchIndex.relocate_project

    def fail(self: SearchIndex, previous: str, current: str, *, workspace: str) -> None:
        if commit_before_failure:
            relocate(self, previous, current, workspace=workspace)
        raise sqlite3.OperationalError("injected index publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(SearchIndex, "relocate_project", fail)
        with pytest.raises(WorkspaceMigrationError, match="update is pending"):
            ensure_project_layout(workspace, target, legacy_project=old)
    assert not old.exists()
    assert (target / ".search-index-cutover").exists()
    assert SessionCheckpoint(target / "sessions").load("one") is not None
    ensure_project_layout(workspace, target)
    assert not (target / ".search-index-cutover").exists()
    with SearchIndex(index_path) as index:
        assert len(index.search("retryneedle", project_id=target.name)) == 1
        assert not index.search("retryneedle", project_id=old.name)


def test_index_rebuild_and_workspace_move_serialize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    import core.memory.search_index as search_module
    from core.memory.search_index import SearchIndex
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState

    workspace = tmp_path / "work"
    projects = tmp_path / "home" / "projects"
    old = projects / str(workspace).replace("/", "-")
    SessionCheckpoint(old / "sessions").save(
        SessionState(session_id="one", messages=[{"role": "user", "content": "raceneedle"}])
    )
    target = projects / encode_project_id(workspace)
    index_path = projects.parent / "search" / "global.db"
    discovered, resume, migration_started = Event(), Event(), Event()
    discover = search_module.iter_project_dbs

    def pause_discovery(root: Path):
        for item in discover(root):
            discovered.set()
            assert resume.wait(5)
            yield item

    def rebuild() -> None:
        with SearchIndex(index_path) as index:
            index.rebuild(projects)

    def migrate() -> None:
        migration_started.set()
        ensure_project_layout(workspace, target, legacy_project=old)

    monkeypatch.setattr(search_module, "iter_project_dbs", pause_discovery)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rebuilding = pool.submit(rebuild)
        assert discovered.wait(5)
        moving = pool.submit(migrate)
        try:
            assert migration_started.wait(5)
            with pytest.raises(TimeoutError):
                moving.result(timeout=0.1)
            assert old.exists() and not target.exists()
        finally:
            resume.set()
        rebuilding.result(timeout=5)
        moving.result(timeout=5)
    with SearchIndex(index_path) as index:
        assert len(index.search("raceneedle", project_id=target.name)) == 1
        assert not index.search("raceneedle", project_id=old.name)
    assert not old.exists() and not (target / ".search-index-cutover").exists()
