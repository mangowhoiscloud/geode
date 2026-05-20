"""L5 — /login help carries eligibility-verdict legend + /login health subcommand.

Pre-fix the `/login` status dashboard rendered each profile with an
inline reject badge (cooldown / expired / disabled / etc.), but the
reason codes were opaque to a user reading them for the first time and
there was no per-profile health view. ``/login help`` now documents
every verdict code and ``/login health [<profile>]`` walks the
``ProfileStore.evaluate_eligibility`` output with an actionable
suggestion per profile.

Contracts pinned here:

1. ``_login_help`` mentions every ``ProfileRejectReason`` value
   (``missing_key``, ``expired``, ``cooling_down``, ``disabled``,
   ``provider_mismatch``) plus the ``ok`` baseline.
2. ``/login health`` dispatches to ``_login_health`` from ``cmd_login``.
3. ``/login health`` with no profile lists every profile's verdict.
4. ``/login health <profile>`` narrows to that profile.
5. ``/login health <unknown>`` prints a warning + how-to-list hint.
6. Empty store path prints the "no profiles" hint, never crashes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.auth.profiles import (
    AuthProfile,
    CredentialType,
    EligibilityResult,
    ProfileRejectReason,
    ProfileStore,
)

# ---------------------------------------------------------------------------
# Contract 1 — help text documents every verdict code
# ---------------------------------------------------------------------------


def test_login_help_documents_eligibility_codes(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_help

    _login_help()
    out = capsys.readouterr().out

    for code in (
        "ok",
        "missing_key",
        "expired",
        "cooling_down",
        "disabled",
        "provider_mismatch",
    ):
        assert code in out, f"verdict code {code!r} missing from /login help"

    # Health subcommand must be discoverable from /login help too.
    assert "/login health" in out


# ---------------------------------------------------------------------------
# Contract 2 — cmd_login routes "health" to _login_health
# ---------------------------------------------------------------------------


def test_cmd_login_health_dispatches() -> None:
    from core.cli.commands.login import cmd_login

    with patch("core.cli.commands.login._login_health") as fake:
        cmd_login("health")
        fake.assert_called_once_with("")

        fake.reset_mock()
        cmd_login("health anthropic:work")
        fake.assert_called_once_with("anthropic:work")


# ---------------------------------------------------------------------------
# Helpers — build a populated ProfileStore + matching eligibility verdicts
# ---------------------------------------------------------------------------


def _build_store() -> ProfileStore:
    store = ProfileStore()
    store.add(
        AuthProfile(
            name="anthropic:work",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key="dummy-token",
        )
    )
    store.add(
        AuthProfile(
            name="openai:payg",
            provider="openai",
            credential_type=CredentialType.TOKEN,
            key="",  # missing key → reason_code == "missing_key"
        )
    )
    return store


def _patch_health(store: ProfileStore) -> object:
    return patch(
        "core.wiring.container.ensure_profile_store",
        return_value=store,
    )


# ---------------------------------------------------------------------------
# Contract 3 — /login health (no arg) lists every profile
# ---------------------------------------------------------------------------


def test_login_health_lists_all_profiles(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_health

    store = _build_store()
    with _patch_health(store):
        _login_health("")

    out = capsys.readouterr().out
    assert "anthropic:work" in out
    assert "openai:payg" in out
    # Section header surfaces so the operator knows what the block means.
    assert "Eligibility" in out


# ---------------------------------------------------------------------------
# Contract 4 — /login health <profile> narrows
# ---------------------------------------------------------------------------


def test_login_health_narrows_to_single_profile(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_health

    store = _build_store()
    with _patch_health(store):
        _login_health("anthropic:work")

    out = capsys.readouterr().out
    assert "anthropic:work" in out
    assert "openai:payg" not in out


# ---------------------------------------------------------------------------
# Contract 5 — /login health <unknown> warns instead of crashing
# ---------------------------------------------------------------------------


def test_login_health_unknown_profile_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_health

    store = _build_store()
    with _patch_health(store):
        _login_health("does-not-exist")

    out = capsys.readouterr().out
    assert "No profile named" in out
    assert "does-not-exist" in out


# ---------------------------------------------------------------------------
# Contract 6 — empty store path
# ---------------------------------------------------------------------------


def test_login_health_empty_store(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_health

    store = ProfileStore()  # empty
    with _patch_health(store):
        _login_health("")

    out = capsys.readouterr().out
    assert "No profiles registered" in out


# ---------------------------------------------------------------------------
# Contract 7 — verdict suggestion text surfaces
# ---------------------------------------------------------------------------


def test_login_health_renders_actionable_suggestion(capsys: pytest.CaptureFixture[str]) -> None:
    """Each verdict line must carry the `→ suggestion` row so the user
    sees *what to do next*, not just the bare reason code."""
    from core.cli.commands.login import _login_health

    store = _build_store()
    # Force a cooldown verdict so we exercise a non-trivial suggestion path.
    fake_verdict = EligibilityResult(
        profile_name="openai:payg",
        provider="openai",
        credential_type=CredentialType.TOKEN,
        eligible=False,
        reason=ProfileRejectReason.COOLING_DOWN,
        detail="cooldown until +120s after 3 errors",
        cooldown_until=9_999_999_999.0,
    )

    def fake_eval(provider: str, **_kwargs: object) -> list[EligibilityResult]:
        return [fake_verdict] if provider == "openai" else []

    store_mock = MagicMock(spec=ProfileStore)
    store_mock.list_all.return_value = list(store.list_all())
    store_mock.evaluate_eligibility.side_effect = fake_eval

    with patch(
        "core.wiring.container.ensure_profile_store",
        return_value=store_mock,
    ):
        _login_health("openai:payg")

    out = capsys.readouterr().out
    assert "cooling_down" in out
    assert "Backoff" in out, (
        "actionable suggestion missing — `_HEALTH_SUGGESTIONS[cooling_down]` "
        "must surface so the user sees how to recover"
    )
