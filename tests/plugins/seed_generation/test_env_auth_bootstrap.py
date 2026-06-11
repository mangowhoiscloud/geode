"""Guard: seed-generation entry bootstraps .env + auth (v0.99.182).

The thin CLI seed-generation entry never runs GeodeRuntime.create, so
without an explicit bootstrap the ranker's voter sub-agents resolve
credentials through an empty wiring ProfileStore and fail with
``openai.api_key — unknown`` (tournament quorum loss). The pilot's
inspect subprocess reads os.environ directly so an exported key masks the
gap there — but the voter path needs the profile store hydrated.
"""

from __future__ import annotations

import inspect

from plugins.seed_generation import cli as seedgen_cli


def test_bootstrap_helper_loads_env_and_hydrates_auth() -> None:
    source = inspect.getsource(seedgen_cli._bootstrap_seed_generation_env)
    assert "load_env_files(" in source
    assert "ensure_profile_store(" in source


def test_run_audit_seeds_calls_bootstrap() -> None:
    source = inspect.getsource(seedgen_cli.run_audit_seeds)
    assert "_bootstrap_seed_generation_env()" in source


def test_run_audit_seeds_resume_calls_bootstrap() -> None:
    source = inspect.getsource(seedgen_cli.run_audit_seeds_resume)
    assert "_bootstrap_seed_generation_env()" in source


def test_bootstrap_invokes_loaders(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("core.config.env_io.load_env_files", lambda **_k: calls.append("env"))
    monkeypatch.setattr("core.wiring.container.ensure_profile_store", lambda: calls.append("auth"))
    seedgen_cli._bootstrap_seed_generation_env()
    assert calls == ["env", "auth"]
