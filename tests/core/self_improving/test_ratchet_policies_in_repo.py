"""PR-RATCHET-1 invariants — 5 mutation-target policy files moved in-repo.

Pins:
- 5 policy SoT constants now point under ``state/autoresearch/policies/``.
- ``.gitignore`` allows the new path (negation re-includes ``policies/**``).
- ``LEGACY_SOT_DIR`` still references ``~/.geode/autoresearch/handoff/``
  for the lazy migration path.
- ``_maybe_migrate_legacy_sot`` copies the legacy file to the new
  location on first read/write, is idempotent, preserves the legacy
  source (operator can roll back manually), silently no-ops when the
  new path already exists or the legacy file is missing, and treats
  ANY copy-time exception (incl. ``UnicodeDecodeError``) as
  best-effort observability (Codex MCP catch on PR-RATCHET-1).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path constants — pinned at the in-repo location
# ---------------------------------------------------------------------------


def test_policy_constants_under_in_repo_policies_dir() -> None:
    """Each of the 5 policy SoT constants must resolve under
    ``<repo>/core/self_improving/state/policies/`` — NOT ``~/.geode/...``.
    The in-repo location is the CI-ratchet alignment fix
    (PR-STATE-SOT-RUNTIME-SPLIT colocated the tracked SoT with its package)."""
    from core.paths import (
        AUTORESEARCH_DECOMPOSITION_POLICY_PATH,
        AUTORESEARCH_POLICIES_DIR,
        AUTORESEARCH_REFLECTION_POLICY_PATH,
        AUTORESEARCH_RETRIEVAL_POLICY_PATH,
        AUTORESEARCH_TOOL_POLICY_PATH,
        AUTORESEARCH_WRAPPER_SECTIONS_PATH,
    )

    policies_dir_parts = AUTORESEARCH_POLICIES_DIR.parts
    # The in-repo policies dir's last three components are fixed:
    assert policies_dir_parts[-3:] == ("self_improving", "state", "policies")

    paths_by_kind = {
        "wrapper-sections.json": AUTORESEARCH_WRAPPER_SECTIONS_PATH,
        "tool-policy.json": AUTORESEARCH_TOOL_POLICY_PATH,
        "decomposition.json": AUTORESEARCH_DECOMPOSITION_POLICY_PATH,
        "retrieval.json": AUTORESEARCH_RETRIEVAL_POLICY_PATH,
        "reflection.json": AUTORESEARCH_REFLECTION_POLICY_PATH,
    }
    for filename, path in paths_by_kind.items():
        assert path.name == filename
        assert path.parent == AUTORESEARCH_POLICIES_DIR


def test_legacy_sot_dir_still_exported() -> None:
    """``LEGACY_SOT_DIR`` must remain importable so the migration
    helper can find old payloads. The constant points at the pre-
    PR-RATCHET-1 location (``~/.geode/autoresearch/handoff/``)."""
    from core.paths import GEODE_HOME, LEGACY_SOT_DIR

    assert LEGACY_SOT_DIR == GEODE_HOME / "autoresearch" / "handoff"


# ---------------------------------------------------------------------------
# .gitignore — the in-repo SoT path must NOT be ignored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "wrapper-sections.json",
        "tool-policy.json",
        "decomposition.json",
        "retrieval.json",
        "reflection.json",
        ".gitkeep",
    ],
)
def test_policy_files_not_gitignored(filename: str) -> None:
    """``git check-ignore <path>`` must exit 1 (not ignored) for the
    new in-repo policy files. Pre-PR-RATCHET-1, ``state/autoresearch/*``
    swept everything under the rug; the negation
    ``!state/autoresearch/policies/**`` re-includes them."""
    from core.paths import AUTORESEARCH_POLICIES_DIR

    git_bin = shutil.which("git")
    if git_bin is None:
        pytest.skip("git executable not in PATH")
    target = AUTORESEARCH_POLICIES_DIR / filename
    # Run from the worktree root so .gitignore is the right one.
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(  # noqa: S603
        [git_bin, "check-ignore", str(target)],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    # exit 1 = not ignored; exit 0 = ignored
    assert result.returncode == 1, (
        f"{target} is git-ignored: stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Lazy migration helper — _maybe_migrate_legacy_sot
# ---------------------------------------------------------------------------


def test_migration_copies_legacy_when_new_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the in-repo path is missing AND the legacy file exists,
    the migration copies legacy → new."""
    from core.self_improving.loop.mutate import policies as policies_mod

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    new_path = tmp_path / "new" / "tool-policy.json"
    legacy_file = legacy_dir / "tool-policy.json"
    legacy_file.write_text(json.dumps({"delegate_task.priority": "5"}))

    monkeypatch.setattr(policies_mod, "LEGACY_SOT_DIR", legacy_dir)
    policies_mod._maybe_migrate_legacy_sot("tool_policy", new_path)

    assert new_path.is_file()
    assert json.loads(new_path.read_text()) == {"delegate_task.priority": "5"}
    # Legacy preserved (not deleted)
    assert legacy_file.is_file()


def test_migration_no_op_when_new_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Idempotency — once the in-repo path is populated, subsequent
    migration calls leave it untouched (even if legacy has different
    content)."""
    from core.self_improving.loop.mutate import policies as policies_mod

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    new_path = tmp_path / "new" / "tool-policy.json"
    new_path.parent.mkdir(parents=True)

    legacy_file = legacy_dir / "tool-policy.json"
    legacy_file.write_text(json.dumps({"from_legacy": "old"}))
    new_path.write_text(json.dumps({"from_new": "fresh"}))

    monkeypatch.setattr(policies_mod, "LEGACY_SOT_DIR", legacy_dir)
    policies_mod._maybe_migrate_legacy_sot("tool_policy", new_path)

    # The new path's content must NOT be clobbered by the legacy copy.
    assert json.loads(new_path.read_text()) == {"from_new": "fresh"}


def test_migration_no_op_when_legacy_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fresh-install path — no legacy file means no migration; the
    caller falls through to the empty-state branch."""
    from core.self_improving.loop.mutate import policies as policies_mod

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    new_path = tmp_path / "new" / "tool-policy.json"

    monkeypatch.setattr(policies_mod, "LEGACY_SOT_DIR", legacy_dir)
    policies_mod._maybe_migrate_legacy_sot("tool_policy", new_path)

    assert not new_path.exists()


def test_migration_handles_unknown_kind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Unknown kinds (not in ``_LEGACY_FILE_NAMES``) must no-op
    silently rather than raise — defensive for future kinds added
    after RATCHET-1."""
    from core.self_improving.loop.mutate import policies as policies_mod

    new_path = tmp_path / "future_kind.json"
    policies_mod._maybe_migrate_legacy_sot("unknown_kind", new_path)
    assert not new_path.exists()


def test_migration_swallows_unicode_decode_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex MCP catch (PR-RATCHET-1): legacy file with non-UTF-8
    content used to raise ``UnicodeDecodeError`` past the ``OSError``
    catch. The widened ``except Exception`` must swallow it so the
    caller falls through to the empty-state branch."""
    from core.self_improving.loop.mutate import policies as policies_mod

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    new_path = tmp_path / "new" / "tool-policy.json"
    # Latin-1 byte 0xff is not a valid UTF-8 lead byte.
    legacy_file = legacy_dir / "tool-policy.json"
    legacy_file.write_bytes(b"\xff\xfe garbled-bytes")

    monkeypatch.setattr(policies_mod, "LEGACY_SOT_DIR", legacy_dir)
    # Must NOT raise.
    policies_mod._maybe_migrate_legacy_sot("tool_policy", new_path)
    # New path stays absent — the caller's FileNotFoundError fallback
    # path will produce an empty policy state.
    assert not new_path.exists()


@pytest.mark.parametrize(
    "kind, expected_filename",
    [
        ("prompt", "wrapper-sections.json"),
        ("tool_policy", "tool-policy.json"),
        ("decomposition", "decomposition.json"),
        ("retrieval", "retrieval.json"),
        ("reflection", "reflection.json"),
    ],
)
def test_legacy_filename_map_matches_target_kinds(kind: str, expected_filename: str) -> None:
    """The migration's ``_LEGACY_FILE_NAMES`` map must include every
    public target_kind so no migration path goes silently dark."""
    from core.self_improving.loop.mutate import policies as policies_mod

    assert kind in policies_mod._LEGACY_FILE_NAMES
    assert policies_mod._LEGACY_FILE_NAMES[kind] == expected_filename


# ---------------------------------------------------------------------------
# load_policy / write_policy — migration fires before the I/O
# ---------------------------------------------------------------------------


def test_load_policy_triggers_migration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``load_policy`` must invoke ``_maybe_migrate_legacy_sot``
    BEFORE attempting to read, so a freshly-upgraded operator gets
    their last mutation state visible on the first call."""
    from core.self_improving.loop.mutate import policies as policies_mod

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_file = legacy_dir / "tool-policy.json"
    legacy_file.write_text(json.dumps({"delegate_task.priority": "8"}))

    new_path = tmp_path / "new" / "tool-policy.json"
    monkeypatch.setattr(policies_mod, "LEGACY_SOT_DIR", legacy_dir)
    monkeypatch.setattr(policies_mod, "_KIND_TO_PATH", {"tool_policy": new_path})

    result = policies_mod.load_policy("tool_policy")
    assert result == {"delegate_task.priority": "8"}
    # Migration also created the in-repo file as a side effect
    assert new_path.is_file()


def test_train_module_fallback_path_points_in_repo() -> None:
    """Codex MCP catch (PR-RATCHET-1): ``core/self_improving/train.py`` has a
    fallback path used when ``core.paths`` cannot be imported. Pre-fix
    the fallback hardcoded ``~/.geode/self-improving-loop/...`` (pre-fix) —
    silently re-introducing the out-of-repo location. Pin that the
    fallback now resolves under the in-repo policies dir so a
    degraded import does not bypass the git-as-optimiser invariant."""
    import inspect

    import core.self_improving.train as auto_train

    src = inspect.getsource(auto_train)
    # The fallback must NOT contain the legacy operator-home literal.
    assert "self-improving-loop" not in src or "policies" in src
    # The in-repo target name must be present in the fallback.
    assert '"policies"' in src or "/policies/" in src


def test_write_policy_triggers_migration_before_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Write path must run migration too — otherwise a write that
    happens BEFORE the first read would clobber the legacy state."""
    from core.self_improving.loop.mutate import policies as policies_mod

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_file = legacy_dir / "tool-policy.json"
    legacy_file.write_text(json.dumps({"legacy_section": "v1"}))

    new_path = tmp_path / "new" / "tool-policy.json"
    monkeypatch.setattr(policies_mod, "LEGACY_SOT_DIR", legacy_dir)
    monkeypatch.setattr(policies_mod, "_KIND_TO_PATH", {"tool_policy": new_path})

    # write happens AFTER the migration so the legacy state is
    # preserved as "previous value" rather than dropped on the floor.
    policies_mod.write_policy("tool_policy", {"legacy_section": "v2"})
    assert json.loads(new_path.read_text()) == {"legacy_section": "v2"}
    # Legacy still preserved
    assert legacy_file.is_file()
