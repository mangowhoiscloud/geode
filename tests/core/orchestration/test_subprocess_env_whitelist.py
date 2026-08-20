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

from core.orchestration.isolated_execution import IsolatedRunner


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
