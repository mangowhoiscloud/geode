"""L3 — Profiles table surfaces full Plan binding detail.

Pre-fix the ``/login`` status dashboard printed ``plan=<id>`` next to
each profile but never explained which subscription / PAYG kind the
plan represented or what tier it sat in. A user looking at
``glm:work`` saw ``plan=glm-coding-lite`` and had no way to know it
was a subscription plan (vs PAYG) or that the tier was ``Lite``.

Contracts pinned here:

1. ``_format_plan_binding(registry, plan_id)`` renders the binding as
   ``<id> (<kind>·<tier> · <display_name>)`` when the Plan resolves.
2. The helper falls back to ``(none)`` on an empty plan_id and to
   ``<id> (unbound)`` when the Plan vanished after the AuthProfile was
   created.
3. ``_login_show_status`` calls the helper so every profile row in the
   dashboard carries the full label.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Contract 1 — full label when Plan resolves
# ---------------------------------------------------------------------------


class _FakePlanKind:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakePlan:
    def __init__(
        self,
        id: str,
        kind: str,
        display_name: str,
        subscription_tier: str | None = None,
    ) -> None:
        self.id = id
        self.kind = _FakePlanKind(kind)
        self.display_name = display_name
        self.subscription_tier = subscription_tier


class _FakeRegistry:
    def __init__(self, plans: dict[str, _FakePlan]) -> None:
        self._plans = plans

    def get(self, plan_id: str) -> _FakePlan | None:
        return self._plans.get(plan_id)


def test_format_plan_binding_full_label() -> None:
    from core.cli.commands.login import _format_plan_binding

    registry = _FakeRegistry(
        {
            "glm-coding-lite": _FakePlan(
                id="glm-coding-lite",
                kind="subscription",
                display_name="GLM Coding Lite",
                subscription_tier="Lite",
            )
        }
    )
    out = _format_plan_binding(registry, "glm-coding-lite")
    assert "glm-coding-lite" in out
    assert "subscription" in out
    assert "Lite" in out
    assert "GLM Coding Lite" in out


def test_format_plan_binding_no_subscription_tier() -> None:
    """PAYG plans have no tier — label omits the ``·tier`` segment."""
    from core.cli.commands.login import _format_plan_binding

    registry = _FakeRegistry(
        {
            "openai-payg": _FakePlan(
                id="openai-payg",
                kind="payg",
                display_name="OpenAI (PAYG)",
                subscription_tier=None,
            )
        }
    )
    out = _format_plan_binding(registry, "openai-payg")
    assert "openai-payg" in out
    assert "payg" in out
    assert "OpenAI (PAYG)" in out


# ---------------------------------------------------------------------------
# Contract 2 — fallbacks
# ---------------------------------------------------------------------------


def test_format_plan_binding_empty_plan_id() -> None:
    from core.cli.commands.login import _format_plan_binding

    registry = _FakeRegistry({})
    out = _format_plan_binding(registry, "")
    assert "none" in out.lower(), "empty plan_id must collapse to (none) so the row stays readable"


def test_format_plan_binding_missing_plan() -> None:
    """A profile bound to a deleted Plan must surface ``(unbound)`` so
    the operator notices the dangling reference rather than seeing an
    opaque id with no context."""
    from core.cli.commands.login import _format_plan_binding

    registry = _FakeRegistry({})  # plan_id "stale-plan" not in registry
    out = _format_plan_binding(registry, "stale-plan")
    assert "stale-plan" in out
    assert "unbound" in out.lower()


# ---------------------------------------------------------------------------
# Contract 3 — _login_show_status uses the helper
# ---------------------------------------------------------------------------


def test_login_show_status_renders_plan_label(capsys: pytest.CaptureFixture[str]) -> None:
    """End-to-end — the dashboard must carry the Plan display name +
    kind for any profile bound to a registered Plan."""
    from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
    from core.cli.commands.login import _login_show_status

    store = ProfileStore()
    store.add(
        AuthProfile(
            name="glm:work",
            provider="glm",
            credential_type=CredentialType.TOKEN,
            key="dummy-key-with-enough-length",
            plan_id="glm-coding-lite",
        )
    )

    # Plan registry stub that returns a Plan for glm-coding-lite.
    fake_registry = _FakeRegistry(
        {
            "glm-coding-lite": _FakePlan(
                id="glm-coding-lite",
                kind="subscription",
                display_name="GLM Coding Lite",
                subscription_tier="Lite",
            )
        }
    )

    # The dashboard also calls ``list_all`` on the plan registry — give
    # it a minimal stub that returns the one Plan so the Plans header
    # branch doesn't trip on attribute errors.
    fake_registry.list_all = lambda: [fake_registry._plans["glm-coding-lite"]]  # type: ignore[attr-defined]
    fake_registry.all_routing = lambda: {}  # type: ignore[attr-defined]
    fake_registry.usage_for = lambda plan_id: type(  # type: ignore[attr-defined]
        "U", (), {"weighted_calls": 0.0, "remaining_in_window": lambda self, plan: 0}
    )()
    # ``_login_show_status`` reads quota off the plan; the fake has none,
    # so it must not break the bullet — patch ``plan.quota`` to None.
    fake_registry._plans["glm-coding-lite"].quota = None  # type: ignore[attr-defined]
    fake_registry._plans["glm-coding-lite"].base_url = "https://api.z.ai/api/coding/paas/v4"  # type: ignore[attr-defined]

    with (
        patch("core.wiring.container.ensure_profile_store", return_value=store),
        patch("core.llm.strategies.plan_registry.get_plan_registry", return_value=fake_registry),
        patch("core.auth.oauth_login.get_auth_status", return_value=[]),
    ):
        _login_show_status()

    out = capsys.readouterr().out
    assert "glm-coding-lite" in out
    assert "GLM Coding Lite" in out, (
        "plan binding must surface Plan.display_name so the row tells "
        f"the user *which* subscription they're bound to: {out!r}"
    )
    assert "subscription" in out
    assert "Lite" in out
