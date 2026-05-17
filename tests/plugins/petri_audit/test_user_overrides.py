"""Unit tests for plugins.petri_audit.user_overrides (P1-F)."""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.petri_audit import user_overrides as uo


@pytest.fixture
def petri_toml(tmp_path: Path, monkeypatch) -> Path:
    """Redirect petri.toml to a tmp path via the env override hook."""
    target = tmp_path / "petri.toml"
    monkeypatch.setenv("GEODE_PETRI_TOML", str(target))
    return target


# ── load_user_overrides ────────────────────────────────────────────────────


def test_load_missing_file_returns_empty(petri_toml: Path):
    assert uo.load_user_overrides() == {}


def test_load_valid_file(petri_toml: Path):
    petri_toml.write_text(
        """
[petri.auditor]
model = "claude-opus-4-7"
source = "claude-cli"

[petri.target]
model = "gpt-5.4-mini"
""",
        encoding="utf-8",
    )
    out = uo.load_user_overrides()
    assert out == {
        "auditor": {"model": "claude-opus-4-7", "source": "claude-cli"},
        "target": {"model": "gpt-5.4-mini"},
    }


def test_load_malformed_toml_returns_empty(petri_toml: Path):
    petri_toml.write_text("this is not toml [[[", encoding="utf-8")
    assert uo.load_user_overrides() == {}


def test_load_missing_petri_section_returns_empty(petri_toml: Path):
    petri_toml.write_text('[other]\nkey = "value"\n', encoding="utf-8")
    assert uo.load_user_overrides() == {}


def test_load_drops_non_string_fields(petri_toml: Path):
    petri_toml.write_text(
        """
[petri.auditor]
model = 42
source = "claude-cli"
""",
        encoding="utf-8",
    )
    assert uo.load_user_overrides() == {"auditor": {"source": "claude-cli"}}


def test_load_drops_non_table_role(petri_toml: Path):
    """A non-table value under [petri] (e.g. petri.something = "x") is skipped."""
    petri_toml.write_text(
        """
[petri]
auditor = "not a table"

[petri.target]
model = "claude-sonnet-4-6"
""",
        encoding="utf-8",
    )
    out = uo.load_user_overrides()
    assert "auditor" not in out
    assert out["target"]["model"] == "claude-sonnet-4-6"


# ── read_role_override ─────────────────────────────────────────────────────


def test_read_role_unknown_returns_empty(petri_toml: Path):
    assert uo.read_role_override("auditor") == {}


def test_read_role_existing(petri_toml: Path):
    petri_toml.write_text('[petri.judge]\nmodel = "claude-opus-4-7"\n', encoding="utf-8")
    assert uo.read_role_override("judge") == {"model": "claude-opus-4-7"}


# ── save_role_override ─────────────────────────────────────────────────────


def test_save_creates_file(petri_toml: Path):
    assert not petri_toml.exists()
    uo.save_role_override("auditor", model="claude-opus-4-7")
    assert petri_toml.exists()
    assert uo.read_role_override("auditor") == {"model": "claude-opus-4-7"}


def test_save_preserves_other_roles(petri_toml: Path):
    uo.save_role_override("auditor", model="claude-opus-4-7")
    uo.save_role_override("judge", source="claude-cli")
    assert uo.read_role_override("auditor")["model"] == "claude-opus-4-7"
    assert uo.read_role_override("judge")["source"] == "claude-cli"


def test_save_empty_string_deletes_axis(petri_toml: Path):
    """Passing source='' removes the source entry but keeps model."""
    uo.save_role_override("auditor", model="claude-opus-4-7", source="claude-cli")
    uo.save_role_override("auditor", source="")
    assert uo.read_role_override("auditor") == {"model": "claude-opus-4-7"}


def test_save_none_keeps_existing(petri_toml: Path):
    """source=None leaves the existing source untouched."""
    uo.save_role_override("auditor", model="claude-opus-4-7", source="claude-cli")
    uo.save_role_override("auditor", model="claude-sonnet-4-6")  # source=None
    out = uo.read_role_override("auditor")
    assert out == {"model": "claude-sonnet-4-6", "source": "claude-cli"}


def test_save_empties_role_when_all_axes_removed(petri_toml: Path):
    uo.save_role_override("auditor", model="claude-opus-4-7", source="claude-cli")
    uo.save_role_override("auditor", model="", source="")
    assert uo.read_role_override("auditor") == {}


def test_save_atomic_write_no_partial(petri_toml: Path, monkeypatch):
    """A crashed write leaves the original file intact (atomic rename)."""
    uo.save_role_override("auditor", model="claude-opus-4-7")
    original = petri_toml.read_text(encoding="utf-8")

    # Force a failure mid-write by patching replace().
    real_replace = Path.replace

    def _boom(self: Path, target: Path) -> Path:
        raise OSError("simulated crash")

    monkeypatch.setattr(Path, "replace", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        uo.save_role_override("auditor", source="claude-cli")
    monkeypatch.setattr(Path, "replace", real_replace)

    # Original content untouched.
    assert petri_toml.read_text(encoding="utf-8") == original


# ── clear_overrides ────────────────────────────────────────────────────────


def test_clear_single_role(petri_toml: Path):
    uo.save_role_override("auditor", model="claude-opus-4-7")
    uo.save_role_override("judge", source="claude-cli")
    uo.clear_overrides("auditor")
    assert uo.read_role_override("auditor") == {}
    assert uo.read_role_override("judge")["source"] == "claude-cli"


def test_clear_all(petri_toml: Path):
    uo.save_role_override("auditor", model="claude-opus-4-7")
    uo.save_role_override("judge", source="claude-cli")
    uo.clear_overrides()
    assert uo.load_user_overrides() == {}


def test_clear_idempotent(petri_toml: Path):
    uo.clear_overrides()  # no file, no raise
    uo.clear_overrides("auditor")  # no role, no raise
    assert uo.load_user_overrides() == {}


# ── Explicit path argument ─────────────────────────────────────────────────


def test_save_with_explicit_path_arg(tmp_path: Path):
    target = tmp_path / "other.toml"
    uo.save_role_override("auditor", model="claude-opus-4-7", path=target)
    assert target.exists()
    assert uo.read_role_override("auditor", path=target)["model"] == "claude-opus-4-7"


def test_load_quoting_robust(petri_toml: Path):
    """Values with embedded double quotes round-trip safely."""
    uo.save_role_override("auditor", model='gpt-5.5 "tactical"')
    assert uo.read_role_override("auditor")["model"] == 'gpt-5.5 "tactical"'
