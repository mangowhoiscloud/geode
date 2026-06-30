"""C-3 guards — one dotenv precedence + daemon behavior-env drop.

Config-unification sprint, 2026-06-11. Pins:

1. pydantic ``env_file`` order is (project, global) so the LATER (global)
   file wins — the GLOBAL ~/.geode/.env is the authoritative secret store and
   a project ``.env`` only fills keys it lacks (2026-06-15, Hermes-aligned;
   supersedes C-3's project-wins for the .env layer). config.toml keeps
   project>global.
2. The serve daemon's ``load_daemon_env`` drops behavior(model-pick) keys
   from its inherited os.environ and never promotes them from .env files,
   so per-session settings reloads always win (hazard H2) — with the
   ``GEODE_SERVE_KEEP_MODEL_ENV=1`` escape hatch.
3. Files never clobber manual exports (env > files), and secrets still
   promote for MCP ``${VAR}`` expansion / subprocess inheritance.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from core.cli.bootstrap import load_daemon_env
from core.config.env_io import BEHAVIOR_ENV_KEYS


def test_settings_env_file_order_is_project_then_global() -> None:
    """Later file wins in pydantic — global must come AFTER project so the
    global secret store is authoritative (Hermes-aligned)."""
    import core.config._settings as settings_mod

    source = inspect.getsource(settings_mod)
    assert 'env_file=(".env", str(GLOBAL_ENV_FILE))' in source


def test_settings_global_env_wins_over_empty_project(tmp_path, monkeypatch) -> None:
    """The reported bug, pydantic path: a project .env with an empty key must
    NOT shadow the real global key — Settings reads the global value."""
    from core.config._settings import Settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    proj = tmp_path / ".env"
    proj.write_text("ANTHROPIC_API_KEY=\n")
    glob = tmp_path / "global.env"
    glob.write_text("ANTHROPIC_API_KEY=sk-real\n")
    s = Settings(_env_file=(str(proj), str(glob)))
    assert s.anthropic_api_key == "sk-real"


def test_behavior_keys_cover_all_model_pick_surfaces() -> None:
    expected = {
        "GEODE_MODEL",
        "GEODE_ACT_MODEL",
        "GEODE_JUDGE_MODEL",
        "GEODE_COGNITIVE_REFLECTION_MODEL",
        "GEODE_LEARNING_EXTRACT_MODEL",
        "GEODE_AGENTIC_EFFORT",
        "GEODE_ANTHROPIC_CREDENTIAL_SOURCE",
        "GEODE_OPENAI_CREDENTIAL_SOURCE",
    }
    assert set(BEHAVIOR_ENV_KEYS) == expected


@pytest.fixture()
def daemon_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated global .env + project .env + cwd for load_daemon_env."""
    import core.cli.bootstrap as bootstrap_mod

    global_env_file = tmp_path / "global.env"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", global_env_file, raising=True)
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("GEODE_SERVE_KEEP_MODEL_ENV", raising=False)
    for behavior_key in BEHAVIOR_ENV_KEYS:
        monkeypatch.delenv(behavior_key, raising=False)
    monkeypatch.delenv("C3_TEST_SECRET", raising=False)
    return {
        "module": bootstrap_mod,
        "global_env": global_env_file,
        "project_env": project_dir / ".env",
    }


def test_daemon_drops_inherited_behavior_env(daemon_env, monkeypatch) -> None:
    import os

    monkeypatch.setenv("GEODE_MODEL", "stale-shell-pick")
    monkeypatch.setenv("GEODE_AGENTIC_EFFORT", "low")
    load_daemon_env()
    assert "GEODE_MODEL" not in os.environ
    assert "GEODE_AGENTIC_EFFORT" not in os.environ


def test_daemon_never_promotes_behavior_keys_from_env_files(daemon_env, monkeypatch) -> None:
    import os

    daemon_env["global_env"].write_text("GEODE_MODEL=global-pick\nC3_TEST_SECRET=g\n")
    daemon_env["project_env"].write_text("GEODE_JUDGE_MODEL=project-pick\n")
    load_daemon_env()
    assert "GEODE_MODEL" not in os.environ
    assert "GEODE_JUDGE_MODEL" not in os.environ
    # secrets still promote
    assert os.environ.get("C3_TEST_SECRET") == "g"
    monkeypatch.delenv("C3_TEST_SECRET", raising=False)


def test_keep_model_env_escape_hatch(daemon_env, monkeypatch) -> None:
    import os

    monkeypatch.setenv("GEODE_SERVE_KEEP_MODEL_ENV", "1")
    monkeypatch.setenv("GEODE_MODEL", "pinned-pick")
    load_daemon_env()
    assert os.environ.get("GEODE_MODEL") == "pinned-pick"


def test_global_env_beats_project_env_in_promotion(daemon_env, monkeypatch) -> None:
    """Hermes-aligned: the global secret store wins over a project .env key."""
    import os

    daemon_env["global_env"].write_text("C3_TEST_SECRET=from-global\n")
    daemon_env["project_env"].write_text("C3_TEST_SECRET=from-project\n")
    load_daemon_env()
    assert os.environ.get("C3_TEST_SECRET") == "from-global"
    monkeypatch.delenv("C3_TEST_SECRET", raising=False)


def test_empty_project_env_does_not_shadow_global_secret(daemon_env, monkeypatch) -> None:
    """The reported bug, promotion path: an auto-generated project .env with an
    empty key must NOT shadow the real global key."""
    import os

    daemon_env["global_env"].write_text("C3_TEST_SECRET=real-global\n")
    daemon_env["project_env"].write_text("C3_TEST_SECRET=\n")
    load_daemon_env()
    assert os.environ.get("C3_TEST_SECRET") == "real-global"
    monkeypatch.delenv("C3_TEST_SECRET", raising=False)


def test_files_never_clobber_manual_exports(daemon_env, monkeypatch) -> None:
    import os

    monkeypatch.setenv("C3_TEST_SECRET", "manual-export")
    daemon_env["global_env"].write_text("C3_TEST_SECRET=from-global\n")
    daemon_env["project_env"].write_text("C3_TEST_SECRET=from-project\n")
    load_daemon_env()
    assert os.environ.get("C3_TEST_SECRET") == "manual-export"


def test_empty_values_do_not_clobber(daemon_env, monkeypatch) -> None:
    import os

    monkeypatch.setenv("C3_TEST_SECRET", "real-value")
    daemon_env["project_env"].write_text("C3_TEST_SECRET=\n")
    load_daemon_env()
    assert os.environ.get("C3_TEST_SECRET") == "real-value"
