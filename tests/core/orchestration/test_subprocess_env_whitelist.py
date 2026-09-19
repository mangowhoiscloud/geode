"""Anti-relapse pins for the subprocess env-var forwarding whitelist.

These tests pin:
1. The set of ``GEODE_*`` operator knobs already in the
   whitelist is preserved (regression guard against accidental
   removal).
2. The whitelist remains conservative — common shell / secret vars
   that should NOT leak (``OAUTH_TOKEN``, ``SSH_AUTH_SOCK``, …) are
   absent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from core.agent.loop._context import build_system_prompt
from core.agent.worker import WorkerRequest
from core.orchestration.isolated_execution import IsolatedRunner, IsolationConfig
from core.runtime_audit import (
    reset_runtime_audit_active,
    runtime_audit_active,
    set_runtime_audit_active,
)


def test_geode_operator_knobs_preserved() -> None:
    """Regression guard — these are documented operator knobs that
    callers configure on the parent process and expect to reach the
    worker. Removing any of them from the whitelist would silently
    break their effect."""
    required = {
        "GEODE_HOME",
        "GEODE_STATE_ROOT",
        "GEODE_CONFIG_PATH",
        "GEODE_DATA_DIR",
    }
    missing = required - IsolatedRunner._SUBPROCESS_ENV_WHITELIST
    assert not missing, f"required operator knobs missing from whitelist: {sorted(missing)}"


def test_credential_envs_present() -> None:
    """Provider API keys must continue to forward (used by PAYG
    adapters that read ``os.environ`` directly)."""
    assert "ANTHROPIC_API_KEY" in IsolatedRunner._SUBPROCESS_ENV_WHITELIST
    assert "OPENAI_API_KEY" in IsolatedRunner._SUBPROCESS_ENV_WHITELIST


def test_dangerous_envs_excluded() -> None:
    """Anti-leak guard — these are vars that frequently carry
    secrets / host-specific state that the worker has no business
    seeing. Keep the whitelist conservative."""
    forbidden = {
        "SSH_AUTH_SOCK",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "OAUTH_TOKEN",
    }
    leaked = forbidden & IsolatedRunner._SUBPROCESS_ENV_WHITELIST
    assert not leaked, f"sensitive envs must not enter the whitelist: {sorted(leaked)}"


@pytest.mark.parametrize(
    "persona,audit_env,audit_context,agent_prompt,expected_identity,expected_audit",
    [
        (None, None, None, "", True, False),
        ("off", None, None, "", False, False),
        ("on", "1", None, "", False, True),
        ("on", "0", True, "", False, True),
        ("on", "1", False, "", True, False),
        ("on", None, None, "ROLE_ONLY", False, False),
    ],
    ids=["default", "persona-off", "audit-env", "context-on", "context-off", "named-override"],
)
def test_prompt_mode_survives_worker_spawn(
    monkeypatch: pytest.MonkeyPatch,
    persona: str | None,
    audit_env: str | None,
    audit_context: bool | None,
    agent_prompt: str,
    expected_identity: bool,
    expected_audit: bool,
) -> None:
    # Exercise the actual spawn boundary without starting a worker or model.
    request = WorkerRequest(task_id="prompt-mode", agent_system_prompt=agent_prompt)
    runner = IsolatedRunner(worker_module="core.worker")
    config = IsolationConfig(session_id=request.task_id, post_to_main=False)
    parent_env = {}
    if persona is not None:
        parent_env["GEODE_PERSONA"] = persona
    if audit_env is not None:
        parent_env["GEODE_AUDIT_UNRESTRICTED"] = audit_env
    token = set_runtime_audit_active(audit_context)
    try:
        with (
            patch.dict("os.environ", parent_env, clear=True),
            patch("asyncio.create_subprocess_exec", side_effect=OSError("test spawn")) as spawn,
        ):
            assert runtime_audit_active() is expected_audit
            result = asyncio.run(runner.arun(request, config=config))
        assert result.success is False
        assert "test spawn" in (result.error or "")
        spawn.assert_awaited_once()
        worker_env = spawn.call_args.kwargs["env"]
    finally:
        reset_runtime_audit_active(token)

    # A new process starts without the parent's ContextVar. Read only the
    # captured env and the real default identity; exclude operator memory.
    for name in (
        "_build_geode_memory_context",
        "_build_learning_context",
        "_build_project_memory_context",
        "_build_user_context",
    ):
        monkeypatch.setattr(f"core.agent.system_prompt.{name}", lambda *_args: "")
    loop = SimpleNamespace(
        _system_prompt_override=request.agent_system_prompt or None,
        _skill_registry=None,
        _policy_sources={},
        _user_profile=None,
        _system_suffix="",
        model="",
    )
    token = set_runtime_audit_active(None)
    try:
        with patch.dict("os.environ", worker_env, clear=True):
            assert runtime_audit_active() is expected_audit
            prompt = build_system_prompt(loop)
    finally:
        reset_runtime_audit_active(token)
    assert ("<agent_identity>" in prompt) is expected_identity
    if agent_prompt:
        assert agent_prompt in prompt
