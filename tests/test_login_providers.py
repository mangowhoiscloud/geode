"""X3 — /login providers exposes the provider variant + equivalence map.

Pre-fix the equivalence map (``openai ↔ openai-codex``,
``glm ↔ glm-coding``) lived only in ``core.llm.registry``; users saw the
``provider`` label in ``/login`` / ``/model`` and had no way to discover
that a Codex Plus token and an OpenAI PAYG key both serve a ``gpt-5.x``
request, or that a GLM Coding key shadows the PAYG endpoint.

Contracts pinned here:

1. ``cmd_login`` routes ``providers`` (and the singular alias
   ``provider``) to ``_login_providers``.
2. ``_login_providers`` lists every entry in
   ``PROVIDER_VARIANTS`` with its display name + auth type + base URL.
3. The equivalence map section surfaces every multi-member class
   (``openai`` ↔ ``openai-codex``, ``glm`` ↔ ``glm-coding``) without
   duplicating the same member list under a sibling key.
4. ``/login help`` mentions the new subcommand.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Contract 1 — cmd_login dispatch
# ---------------------------------------------------------------------------


def test_cmd_login_providers_dispatches() -> None:
    from core.cli.commands.login import cmd_login

    with patch("core.cli.commands.login._login_providers") as fake:
        cmd_login("providers")
        fake.assert_called_once_with()

        fake.reset_mock()
        cmd_login("provider")  # singular alias
        fake.assert_called_once_with()


# ---------------------------------------------------------------------------
# Contract 2 — every variant rendered
# ---------------------------------------------------------------------------


def test_login_providers_lists_every_variant(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_providers
    from core.llm.registry import PROVIDER_VARIANTS

    _login_providers()
    out = capsys.readouterr().out

    for variant_id, spec in PROVIDER_VARIANTS.items():
        assert variant_id in out, f"variant {variant_id!r} missing from /login providers"
        assert spec.default_base_url in out, (
            f"base_url for {variant_id!r} missing — operators need it to "
            "verify they are hitting the right endpoint"
        )


# ---------------------------------------------------------------------------
# Contract 3 — multi-member equivalence classes surface, singletons skipped
# ---------------------------------------------------------------------------


def test_login_providers_renders_equivalence_classes(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_providers

    _login_providers()
    out = capsys.readouterr().out

    # Each multi-member class must surface
    assert "openai-codex" in out and "openai" in out
    assert "glm-coding" in out and "glm" in out

    # Equivalence map header must be present
    assert "Equivalence map" in out


def test_login_providers_dedupes_equivalent_class_entries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both ``openai`` and ``openai-codex`` map to the same member list
    ``[openai-codex, openai]``. The view renders the class once, keyed by
    the first entry-point — rendering it twice would be visual noise."""
    from core.cli.commands.login import _login_providers

    _login_providers()
    out = capsys.readouterr().out

    # The "→" arrow joins the entry-point to its member list. Count the
    # arrows after the "Equivalence map" header.
    _, _, after = out.partition("Equivalence map")
    # Each multi-member class adds one arrow line; we expect 2 classes
    # (openai + glm) post-dedup. A regression that re-renders the same
    # list under sibling keys would show 4 arrows.
    arrow_lines = [ln for ln in after.splitlines() if "→" in ln]
    assert len(arrow_lines) == 2, (
        f"expected 2 equivalence classes after dedup, got {len(arrow_lines)}: {arrow_lines!r}"
    )


# ---------------------------------------------------------------------------
# Contract 4 — /login help discovers the subcommand
# ---------------------------------------------------------------------------


def test_login_help_mentions_providers(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_help

    _login_help()
    out = capsys.readouterr().out
    assert "/login providers" in out
