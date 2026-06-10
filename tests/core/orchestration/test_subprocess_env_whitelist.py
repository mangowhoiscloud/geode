"""PR-ENV-WHITELIST-CODEX-BYPASS (2026-05-25) — anti-relapse pins for
the subprocess env-var forwarding whitelist.

Smoke 13 vote-m000-* (codex voter route) failed with
``codex-cli-subagent lane blocked — Codex 5-hour OAuth bucket >=
throttle threshold (see GEODE_CODEX_OAUTH_POLL_DISABLED to bypass)``
even though the operator had set the env on the parent ``geode
serve`` process. Root cause: ``IsolatedRunner._SUBPROCESS_ENV_WHITELIST``
did NOT include ``GEODE_CODEX_OAUTH_POLL_DISABLED``, so the
``safe_env`` built for the child subprocess dropped it.

These tests pin:
1. The bypass env is in the whitelist (literal name presence).
2. The set of other ``GEODE_*`` operator knobs already in the
   whitelist is preserved (regression guard against accidental
   removal).
3. The whitelist remains conservative — common shell / secret vars
   that should NOT leak (``OAUTH_TOKEN``, ``SSH_AUTH_SOCK``, …) are
   absent.
"""

from __future__ import annotations

from core.orchestration.isolated_execution import IsolatedRunner


def test_codex_oauth_poll_disabled_is_whitelisted() -> None:
    """The exact env name documented in
    ``core/orchestration/codex_cli_lane.py:CODEX_CLI_LANE_THROTTLED_MSG``
    must reach the worker subprocess for the bypass to take effect."""
    assert "GEODE_CODEX_OAUTH_POLL_DISABLED" in IsolatedRunner._SUBPROCESS_ENV_WHITELIST


def test_geode_operator_knobs_preserved() -> None:
    """Regression guard — these are documented operator knobs that
    callers configure on the parent process and expect to reach the
    worker. Removing any of them from the whitelist would silently
    break their effect."""
    required = {
        "GEODE_CONFIG_PATH",
        "GEODE_DATA_DIR",
        "GEODE_CODEX_OAUTH_POLL_DISABLED",
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
