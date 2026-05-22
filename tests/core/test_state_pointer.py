"""Tests for the CSP-7 cross-run state pointer (``core.paths``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import core.paths as cp


def _patch_state_root(monkeypatch: Any, root: Path) -> Path:
    monkeypatch.setattr(cp, "STATE_ROOT", root)
    monkeypatch.setattr(cp, "STATE_SELF_IMPROVING_LOOP_DIR", root / "self-improving-loop")
    monkeypatch.setattr(cp, "STATE_SEED_GENERATION_DIR", root / "seed-generation")
    monkeypatch.setattr(
        cp,
        "STATE_LATEST_POINTER_PATH",
        root / "self-improving-loop" / "latest_pointer.json",
    )
    return root


class TestWriteLatestPointer:
    def test_writes_relative_paths_inside_state_root(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        state_root = _patch_state_root(monkeypatch, tmp_path / "state")
        seed_pool = state_root / "seed-generation" / "r1" / "survivors"
        meta_review = state_root / "seed-generation" / "r1" / "meta_review.json"
        seed_pool.mkdir(parents=True)
        meta_review.parent.mkdir(parents=True, exist_ok=True)
        meta_review.write_text("{}", encoding="utf-8")
        cp.write_latest_pointer(
            run_id="r1",
            gen_tag="gen1",
            seed_pool=seed_pool,
            meta_review=meta_review,
        )
        payload = json.loads(cp.STATE_LATEST_POINTER_PATH.read_text(encoding="utf-8"))
        # Paths stored as STATE_ROOT-relative for cross-machine portability.
        assert payload["seed_pool"] == "seed-generation/r1/survivors"
        assert payload["meta_review"] == "seed-generation/r1/meta_review.json"
        assert payload["run_id"] == "r1"
        assert payload["version"] == 1

    def test_writes_absolute_paths_outside_state_root(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        """Tests / fixtures that stage artefacts outside STATE_ROOT — the
        writer stores the absolute path verbatim and the reader resolves
        it as-is."""
        _patch_state_root(monkeypatch, tmp_path / "state")
        outside = tmp_path / "elsewhere" / "survivors"
        outside.mkdir(parents=True)
        cp.write_latest_pointer(
            run_id="r2",
            gen_tag="gen1",
            seed_pool=outside,
            meta_review=None,
        )
        payload = json.loads(cp.STATE_LATEST_POINTER_PATH.read_text(encoding="utf-8"))
        assert payload["seed_pool"] == str(outside)
        assert "meta_review" not in payload

    def test_optional_meta_review(self, tmp_path: Path, monkeypatch: Any) -> None:
        """seed_pool-only write (meta_review may not exist this run)."""
        state_root = _patch_state_root(monkeypatch, tmp_path / "state")
        seed_pool = state_root / "seed-generation" / "r3" / "survivors"
        seed_pool.mkdir(parents=True)
        cp.write_latest_pointer(
            run_id="r3",
            gen_tag="gen1",
            seed_pool=seed_pool,
            meta_review=None,
        )
        payload = json.loads(cp.STATE_LATEST_POINTER_PATH.read_text(encoding="utf-8"))
        assert "seed_pool" in payload
        assert "meta_review" not in payload


class TestReadLatestPointer:
    def test_returns_none_when_missing(self, tmp_path: Path, monkeypatch: Any) -> None:
        _patch_state_root(monkeypatch, tmp_path / "state")
        assert cp.read_latest_pointer() is None

    def test_resolves_relative_paths_to_absolute(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        state_root = _patch_state_root(monkeypatch, tmp_path / "state")
        cp.STATE_LATEST_POINTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        cp.STATE_LATEST_POINTER_PATH.write_text(
            json.dumps(
                {
                    "version": 1,
                    "run_id": "r1",
                    "gen_tag": "gen1",
                    "seed_pool": "seed-generation/r1/survivors",
                    "meta_review": "seed-generation/r1/meta_review.json",
                }
            ),
            encoding="utf-8",
        )
        out = cp.read_latest_pointer()
        assert out is not None
        # Relative inputs resolve under STATE_ROOT.
        assert out["seed_pool"] == (state_root / "seed-generation" / "r1" / "survivors").resolve()
        assert (
            out["meta_review"]
            == (state_root / "seed-generation" / "r1" / "meta_review.json").resolve()
        )

    def test_returns_none_on_malformed_json(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        _patch_state_root(monkeypatch, tmp_path / "state")
        cp.STATE_LATEST_POINTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        cp.STATE_LATEST_POINTER_PATH.write_text("not-json {", encoding="utf-8")
        assert cp.read_latest_pointer() is None

    def test_returns_none_on_non_dict_payload(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        _patch_state_root(monkeypatch, tmp_path / "state")
        cp.STATE_LATEST_POINTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        cp.STATE_LATEST_POINTER_PATH.write_text("[1, 2, 3]", encoding="utf-8")
        assert cp.read_latest_pointer() is None


class TestRepoRelativeDefault:
    def test_state_root_defaults_inside_repo(self) -> None:
        """The default STATE_ROOT lives inside the repo (machine-portable).

        Note: ``cp.STATE_ROOT`` is monkeypatched by ``conftest._isolate_state_root``,
        so we exercise the underlying ``_resolve_repo_root`` directly to
        check the default the module would compute at import time.
        """
        default = cp._resolve_repo_root() / "state"
        assert "state" in default.parts
        assert default.is_absolute()
