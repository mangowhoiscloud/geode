"""Guards for the consolidated config-TOML read-path + section editor.

``core.config.toml_edit`` folds four duplicated helpers (PR-DEDUP-CONFIG-TOML)
into one home: the ``GEODE_CONFIG_TOML`` resolver and the string-splice section
writer. These pin the precedence + delete-on-empty contract every caller relies
on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.config import toml_edit as te


class TestResolveConfigTomlPath:
    def test_explicit_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEODE_CONFIG_TOML", "/env/path.toml")
        assert te.resolve_config_toml_path("/explicit/path.toml") == Path("/explicit/path.toml")

    def test_explicit_expands_tilde(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEODE_CONFIG_TOML", raising=False)
        resolved = str(te.resolve_config_toml_path("~/sub/config.toml"))
        assert "~" not in resolved and resolved.endswith("sub/config.toml")

    def test_env_used_when_no_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEODE_CONFIG_TOML", "~/from/env.toml")
        resolved = str(te.resolve_config_toml_path())
        assert "~" not in resolved and resolved.endswith("from/env.toml")

    def test_falls_back_to_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.paths import GLOBAL_CONFIG_TOML

        monkeypatch.delenv("GEODE_CONFIG_TOML", raising=False)
        assert te.resolve_config_toml_path() == GLOBAL_CONFIG_TOML

    def test_blank_env_falls_back_to_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.paths import GLOBAL_CONFIG_TOML

        monkeypatch.setenv("GEODE_CONFIG_TOML", "   ")
        assert te.resolve_config_toml_path() == GLOBAL_CONFIG_TOML


class TestSpliceTomlSection:
    def test_empty_value_deletes_existing_key(self) -> None:
        src = '[s]\nkeep = "x"\ndrop = "y"\n'
        out = te.splice_toml_section(src, "s", {"drop": ""})
        assert "drop" not in out and 'keep = "x"' in out

    def test_empty_value_no_op_when_key_absent(self) -> None:
        # A delete request for an absent key must not materialise a blank line.
        out = te.splice_toml_section('[s]\nkeep = "x"\n', "s", {"missing": ""})
        assert "missing" not in out

    def test_escapes_quote_and_backslash(self) -> None:
        out = te.splice_toml_section("", "s", {"k": 'a " b \\ c'})
        assert 'k = "a \\" b \\\\ c"' in out

    def test_replaces_key_with_tab_before_equals(self) -> None:
        # TOML allows arbitrary whitespace before ``=`` — a tab-separated key must
        # be replaced in place, not duplicated by an appended line (Codex MEDIUM:
        # the old single-key bash splicer matched this; the generic one must too).
        out = te.splice_toml_section('[s]\nmode\t= "off"\n', "s", {"mode": "strict"})
        assert out == '[s]\nmode = "strict"\n'
        assert out.count("mode") == 1  # not duplicated

    def test_prefix_key_not_clobbered(self) -> None:
        # ``model`` must not match the sibling ``model_extra`` line.
        out = te.splice_toml_section(
            '[s]\nmodel_extra = "keep"\n', "s", {"model": "claude-opus-4-8"}
        )
        assert 'model_extra = "keep"' in out
        assert 'model = "claude-opus-4-8"' in out


class TestPersistTomlSection:
    def test_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "config.toml"
        monkeypatch.setenv("GEODE_CONFIG_TOML", str(cfg))
        path = te.persist_toml_section("demo", {"model": "claude-opus-4-8"})
        assert path == cfg
        assert 'model = "claude-opus-4-8"' in cfg.read_text(encoding="utf-8")

    def test_empty_updates_is_noop_but_returns_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "config.toml"
        monkeypatch.setenv("GEODE_CONFIG_TOML", str(cfg))
        path = te.persist_toml_section("demo", {})
        assert path == cfg
        assert not cfg.exists()  # no write on empty updates
