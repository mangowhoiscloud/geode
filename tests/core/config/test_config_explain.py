"""C-1 config explainer guards (2026-06-11).

Pins the layer ladder's honesty: winner selection follows real precedence
(os.environ > global .env > project .env > project toml > global toml >
default — pydantic's later-env-file-wins order for the dotenv layer),
masked layers are reported, and the `geode about` mask warning fires
exactly when an env-layer model hides a toml pick (hazard H3/H4 class).
"""

from __future__ import annotations

from pathlib import Path

import core.config.explain as explain_mod
import pytest
from core.config.explain import explain_field, model_mask_warning


@pytest.fixture()
def isolated_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    global_env = tmp_path / "global.env"
    project_env = tmp_path / "project.env"
    global_toml = tmp_path / "global-config.toml"
    project_toml = tmp_path / "project-config.toml"
    monkeypatch.setattr(explain_mod, "GLOBAL_ENV_FILE", global_env)
    monkeypatch.setattr(explain_mod, "PROJECT_ENV_FILE", project_env)
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(global_toml))
    monkeypatch.setattr(explain_mod, "PROJECT_CONFIG_PATH", project_toml)
    monkeypatch.delenv("GEODE_MODEL", raising=False)
    return {
        "global_env": global_env,
        "project_env": project_env,
        "global_toml": global_toml,
        "project_toml": project_toml,
    }


def test_default_wins_when_nothing_set(isolated_layers) -> None:
    report = explain_field("model")
    assert report.winner is not None
    assert report.winner.layer == "code default"
    assert report.masked_layers == []


def test_toml_pick_wins_over_default_and_global_over_nothing(isolated_layers) -> None:
    isolated_layers["global_toml"].write_text('[llm]\nprimary_model = "claude-sonnet-4-6"\n')
    report = explain_field("model")
    assert report.winner.layer == "global config.toml"
    assert report.winner.value == "claude-sonnet-4-6"


def test_project_toml_beats_global_toml(isolated_layers) -> None:
    isolated_layers["global_toml"].write_text('[llm]\nprimary_model = "claude-haiku-4-5"\n')
    isolated_layers["project_toml"].write_text('[llm]\nprimary_model = "claude-sonnet-4-6"\n')
    report = explain_field("model")
    assert report.winner.layer == "project config.toml"
    assert [entry.layer for entry in report.masked_layers] == ["global config.toml", "code default"]


def test_env_file_masks_toml_and_warning_fires(isolated_layers) -> None:
    isolated_layers["global_env"].write_text("GEODE_MODEL=gpt-5.5\n")
    isolated_layers["project_toml"].write_text('[llm]\nprimary_model = "claude-sonnet-4-6"\n')
    report = explain_field("model")
    assert report.winner.layer == "global .env"
    masked = {entry.layer for entry in report.masked_layers}
    assert "project config.toml" in masked

    warning = model_mask_warning()
    assert warning is not None
    assert "GEODE_MODEL" in warning and "masking" in warning


def test_global_env_beats_project_env_matching_pydantic_order(isolated_layers) -> None:
    """Hermes-aligned: env_file=(project, global), later wins → global .env beats project."""
    isolated_layers["global_env"].write_text("GEODE_MODEL=global-pick\n")
    isolated_layers["project_env"].write_text("GEODE_MODEL=project-pick\n")
    report = explain_field("model")
    assert report.winner.layer == "global .env"
    assert report.winner.value == "global-pick"


def test_os_environ_tops_everything(isolated_layers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_MODEL", "env-pick")
    isolated_layers["global_env"].write_text("GEODE_MODEL=file-pick\n")
    report = explain_field("model")
    assert report.winner.layer == "os.environ"
    assert report.winner.value == "env-pick"


def test_no_warning_when_no_toml_is_masked(isolated_layers) -> None:
    isolated_layers["global_env"].write_text("GEODE_MODEL=gpt-5.5\n")
    assert model_mask_warning() is None


def test_empty_dotenv_role_choice_matches_actual_settings(isolated_layers, monkeypatch) -> None:
    import core.config as cfg
    from core.config import Settings

    isolated_layers["global_env"].write_text("GEODE_JUDGE_MODEL=\n")
    isolated_layers["global_toml"].write_text('[llm]\njudge_model="gpt-6-sol"\n')
    monkeypatch.delenv("GEODE_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(cfg, "PROJECT_CONFIG_PATH", isolated_layers["project_toml"])
    candidate = Settings(_env_file=(isolated_layers["project_env"], isolated_layers["global_env"]))
    cfg._apply_toml_overlay(candidate)
    monkeypatch.setattr(cfg, "settings", candidate)
    report = explain_field("judge_model")
    assert candidate.judge_model == report.effective == ""
    assert report.winner.layer == "global .env"
    assert report.winner.value == ""
    assert any(e.layer == "global config.toml" for e in report.masked_layers)
