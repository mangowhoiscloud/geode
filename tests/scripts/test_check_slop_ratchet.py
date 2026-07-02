"""Guards for scripts/check_slop_ratchet.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import check_slop_ratchet as slop


def _init_git_repo(root: Path) -> None:
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(argv, cwd=root, check=True, capture_output=True)  # noqa: S603


def _write_repo(root: Path) -> None:
    _init_git_repo(root)
    (root / "pyproject.toml").write_text('version = "1.2.3"\n', encoding="utf-8")
    (root / "core").mkdir()
    (root / "scripts").mkdir()
    (root / "plugins").mkdir()
    (root / "core" / "a.py").write_text("def shared(x: int) -> int:\n    return x\n")
    (root / "core" / "b.py").write_text("def shared(x: int) -> int:\n    return x + 1\n")
    (root / "scripts" / "check_slop_ratchet.py").write_text("# TODO self literal ignored\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)  # noqa: S607


def _baseline(counts: dict[str, int], version: str = "1.2.3") -> dict[str, dict[str, int | str]]:
    return {name: {"count": counts.get(name, 0), "stamped": version} for name in slop.METRIC_NAMES}


def _patch_paths(monkeypatch, root: Path) -> Path:
    baseline = root / "scripts" / "slop_ratchet_baseline.json"
    monkeypatch.setattr(slop, "REPO_ROOT", root)
    monkeypatch.setattr(slop, "PYPROJECT", root / "pyproject.toml")
    monkeypatch.setattr(slop, "BASELINE_FILE", baseline)
    return baseline


def test_duplicate_signature_groups_skip_low_signal_modules() -> None:
    groups = slop.duplicate_signature_groups(
        [
            ("core/a.py", "def shared(x: int) -> int:"),
            ("core/b.py", "def shared(x: int) -> int:"),
            ("core/__init__.py", "def shared(x: int) -> int:"),
            ("core/test_a.py", "def shared(x: int) -> int:"),
            ("core/c.py", "def __repr__(self) -> str:"),
            ("core/d.py", "def __repr__(self) -> str:"),
        ]
    )

    assert groups == {
        "def shared(x: int) -> int:": ["core/a.py", "core/b.py"],
    }


def test_main_passes_when_counts_match_baseline(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_repo(tmp_path)
    baseline = _patch_paths(monkeypatch, tmp_path)
    counts = dict.fromkeys(slop.METRIC_NAMES, 0)
    counts["duplicated_signatures"] = 1
    baseline.write_text(json.dumps(_baseline(counts)) + "\n", encoding="utf-8")

    assert slop.main([]) == 0

    assert "slop ratchet OK" in capsys.readouterr().out


def test_main_fails_when_metric_grows(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_repo(tmp_path)
    baseline = _patch_paths(monkeypatch, tmp_path)
    baseline.write_text(json.dumps(_baseline({})) + "\n", encoding="utf-8")

    assert slop.main([]) == 1

    err = capsys.readouterr().err
    assert "duplicated_signatures" in err
    assert "baseline 0 -> current 1" in err


def test_update_baseline_writes_current_counts_and_version(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _write_repo(tmp_path)
    baseline = _patch_paths(monkeypatch, tmp_path)

    assert slop.main(["--update-baseline"]) == 0

    written = json.loads(baseline.read_text(encoding="utf-8"))
    assert written["duplicated_signatures"] == {"count": 1, "stamped": "1.2.3"}
    assert written["stale_todos"] == {"count": 0, "stamped": "1.2.3"}
    assert "baseline updated" in capsys.readouterr().out
