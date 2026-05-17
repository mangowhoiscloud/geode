"""PR #6 (2026-05-14) — Codex OAuth judge bridge tests.

Coverage:

- ``to_inspect_model`` auto-routes gpt-5.x to ``openai-codex/`` when a
  Codex OAuth token resolves; falls back to ``openai/`` otherwise.
- User-pinned raw ids (``openai/gpt-5.5``) bypass the rewrite.
- ``--use-oauth`` / ``--no-oauth`` overrides auto-detect.
- ``is_oauth_routed`` predicate classifies inspect_ai ids correctly.
- ``estimate_cost_usd`` zeros out the judge / auditor contribution
  when the OAuth flag is set.
- ``run_audit`` plumbs the OAuth routing into both the command line
  (the ``--model-role judge=…`` token) and the cost estimate.
- Provider registration: when ``[audit]`` extra is installed, the
  ``openai-codex`` modelapi is in inspect_ai's registry after import
  of ``plugins.petri_audit``.
"""

from __future__ import annotations

import importlib.util
from typing import Any
from unittest.mock import patch

import pytest

_AUDIT_INSTALLED = importlib.util.find_spec("inspect_ai") is not None


# ---------------------------------------------------------------------------
# to_inspect_model — auto-detect + explicit use_oauth
# ---------------------------------------------------------------------------


def test_to_inspect_model_uses_oauth_when_token_present() -> None:
    """Auto-detect: token resolves → ``openai-codex/<model>``."""
    from plugins.petri_audit.models import to_inspect_model

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=True):
        assert to_inspect_model("gpt-5.5") == "openai-codex/gpt-5.5"
        assert to_inspect_model("gpt-5.4-mini") == "openai-codex/gpt-5.4-mini"
        assert to_inspect_model("gpt-5.3-codex") == "openai-codex/gpt-5.3-codex"


def test_to_inspect_model_falls_back_to_per_token_without_token() -> None:
    """Auto-detect: no token → legacy ``openai/<model>``."""
    from plugins.petri_audit.models import to_inspect_model

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=False):
        assert to_inspect_model("gpt-5.5") == "openai/gpt-5.5"
        assert to_inspect_model("gpt-5.4-mini") == "openai/gpt-5.4-mini"


def test_to_inspect_model_use_oauth_true_forces_route() -> None:
    """``use_oauth=True`` forces re-route regardless of token presence.

    The constructor of ``OpenAICodexAPI`` will raise at call time if
    no token is actually available; the mapping itself is a pure
    string operation.
    """
    from plugins.petri_audit.models import to_inspect_model

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=False):
        assert to_inspect_model("gpt-5.5", use_oauth=True) == "openai-codex/gpt-5.5"


def test_to_inspect_model_use_oauth_false_keeps_per_token() -> None:
    """``use_oauth=False`` keeps PAYG mapping even when a token exists."""
    from plugins.petri_audit.models import to_inspect_model

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=True):
        assert to_inspect_model("gpt-5.5", use_oauth=False) == "openai/gpt-5.5"


def test_to_inspect_model_raw_openai_passthrough_bypasses_oauth() -> None:
    """User-pinned raw ``openai/gpt-5.5`` stays PAYG even with token."""
    from plugins.petri_audit.models import to_inspect_model

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=True):
        assert to_inspect_model("openai/gpt-5.5") == "openai/gpt-5.5"
        # And the explicit OAuth-routed form is honoured.
        assert to_inspect_model("openai-codex/gpt-5.5") == "openai-codex/gpt-5.5"


def test_to_inspect_model_o_series_never_oauth() -> None:
    """``o3`` / ``o4-mini`` are not on the Codex backend catalogue —
    they stay on per-token regardless of OAuth availability."""
    from plugins.petri_audit.models import to_inspect_model

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=True):
        assert to_inspect_model("o3") == "openai/o3"
        assert to_inspect_model("o4-mini") == "openai/o4-mini"


def test_to_inspect_model_claude_routes_when_oauth_available() -> None:
    """Claude mapping follows the subscription OAuth route when available."""
    from plugins.petri_audit.models import to_inspect_model

    with (
        patch("plugins.petri_audit.models._codex_oauth_available", return_value=True),
        patch("plugins.petri_audit.models._claude_oauth_available", return_value=True),
    ):
        assert (
            to_inspect_model("claude-haiku-4-5-20251001")
            == "claude-code/claude-haiku-4-5-20251001"
        )


# ---------------------------------------------------------------------------
# is_oauth_routed predicate
# ---------------------------------------------------------------------------


def test_is_oauth_routed_classifies_inspect_ids() -> None:
    from plugins.petri_audit.models import is_oauth_routed

    assert is_oauth_routed("openai-codex/gpt-5.5") is True
    assert is_oauth_routed("openai-codex/gpt-5.3-codex") is True
    assert is_oauth_routed("claude-code/claude-haiku-4-5-20251001") is True
    assert is_oauth_routed("openai/gpt-5.5") is False
    assert is_oauth_routed("anthropic/claude-haiku-4-5-20251001") is False
    assert is_oauth_routed("geode/claude-opus-4-7") is False


# ---------------------------------------------------------------------------
# estimate_cost_usd — OAuth zeroing
# ---------------------------------------------------------------------------


def test_estimate_cost_zero_for_oauth_judge() -> None:
    """``judge_oauth=True`` removes the judge contribution from the
    per-sample cost. Auditor + target costs remain."""
    from plugins.petri_audit.runner import estimate_cost_usd

    payg = estimate_cost_usd(
        judge="gpt-5.5",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
    )
    oauth = estimate_cost_usd(
        judge="gpt-5.5",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
        judge_oauth=True,
    )
    assert payg > 0
    assert oauth >= 0
    assert oauth < payg, (
        f"OAuth-routed judge must reduce the per-sample cost. payg={payg:.4f}, oauth={oauth:.4f}"
    )


def test_estimate_cost_zero_for_oauth_auditor() -> None:
    """``auditor_oauth=True`` zeros out auditor's per-turn share."""
    from plugins.petri_audit.runner import estimate_cost_usd

    payg = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="gpt-5.4-mini",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
    )
    oauth = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="gpt-5.4-mini",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
        auditor_oauth=True,
    )
    assert payg > 0
    assert oauth >= 0
    assert oauth < payg


def test_estimate_cost_both_oauth_only_target_remains() -> None:
    """When judge + auditor are both OAuth, only target cost is billed."""
    from plugins.petri_audit.runner import estimate_cost_usd

    full_oauth = estimate_cost_usd(
        judge="gpt-5.5",
        auditor="gpt-5.4-mini",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
        judge_oauth=True,
        auditor_oauth=True,
    )
    target_only = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
        judge_oauth=True,
        auditor_oauth=True,
    )
    # Both expressions zero judge + auditor; difference would only be
    # the target column, which is identical → results must match.
    assert full_oauth == pytest.approx(target_only, rel=1e-9)


# ---------------------------------------------------------------------------
# run_audit — end-to-end command + estimate plumbing
# ---------------------------------------------------------------------------


def test_run_audit_uses_oauth_when_token_present() -> None:
    """End-to-end: auto-detect lights up → judge gets ``openai-codex/``
    in the constructed command + the cost line drops below PAYG."""
    from plugins.petri_audit.runner import run_audit

    with (
        patch("plugins.petri_audit.models._codex_oauth_available", return_value=True),
        patch("plugins.petri_audit.models._claude_oauth_available", return_value=True),
    ):
        report = run_audit(
            judge="gpt-5.5",
            auditor="claude-sonnet-4-6",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=10,
            dry_run=True,
        )
    joined = " ".join(report.command)
    assert "judge=openai-codex/gpt-5.5" in joined
    assert "auditor=claude-code/claude-sonnet-4-6" in joined


def test_run_audit_no_oauth_flag_forces_per_token() -> None:
    """Explicit ``--no-oauth`` keeps PAYG even when a token resolves."""
    from plugins.petri_audit.runner import run_audit

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=True):
        report = run_audit(
            judge="gpt-5.5",
            auditor="claude-sonnet-4-6",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=10,
            dry_run=True,
            use_oauth=False,
        )
    joined = " ".join(report.command)
    assert "judge=openai/gpt-5.5" in joined
    assert "openai-codex" not in joined


def test_run_audit_falls_back_when_no_token() -> None:
    """No OAuth token + auto-detect → legacy ``openai/`` path."""
    from plugins.petri_audit.runner import run_audit

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=False):
        report = run_audit(
            judge="gpt-5.5",
            auditor="claude-sonnet-4-6",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=10,
            dry_run=True,
        )
    joined = " ".join(report.command)
    assert "judge=openai/gpt-5.5" in joined
    assert "openai-codex" not in joined


def test_run_audit_user_pinned_raw_openai_not_rewritten() -> None:
    """User pinned ``openai/gpt-5.5`` → no rewrite (raw passthrough)."""
    from plugins.petri_audit.runner import run_audit

    with patch("plugins.petri_audit.models._codex_oauth_available", return_value=True):
        report = run_audit(
            judge="openai/gpt-5.5",
            auditor="claude-sonnet-4-6",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=10,
            dry_run=True,
        )
    joined = " ".join(report.command)
    assert "judge=openai/gpt-5.5" in joined
    assert "openai-codex" not in joined


# ---------------------------------------------------------------------------
# Provider registration with inspect_ai
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_openai_codex_provider_registered_with_inspect_ai() -> None:
    """``openai-codex`` is in inspect_ai's modelapi registry after
    ``import plugins.petri_audit`` runs ``register()``."""
    from inspect_ai._util.registry import registry_find

    import plugins.petri_audit  # noqa: F401 — triggers register()

    # Find by registry tag — provider names come through ``registry_
    # unqualified_name`` and may carry a package prefix. Match on the
    # unqualified leaf.
    def _match(info: Any) -> bool:
        if info.type != "modelapi":
            return False
        leaf = info.name.split("/")[-1]
        return leaf == "openai-codex"

    matches = registry_find(_match)
    assert matches, (
        "openai-codex modelapi must be registered with inspect_ai after "
        "plugins.petri_audit is imported with [audit] extra installed."
    )


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_openai_codex_init_raises_without_token() -> None:
    """Constructing the provider with no token + no env raises the
    standard inspect_ai environment-prerequisite error so the caller
    sees the same failure shape as the per-token PAYG path."""
    import plugins.petri_audit  # noqa: F401 — register()

    # Patch the resolver to return empty token and clear OPENAI_API_KEY.
    with (
        patch("core.llm.providers.codex._resolve_codex_token", return_value=""),
        patch.dict("os.environ", {}, clear=False) as env,
    ):
        env.pop("OPENAI_API_KEY", None)
        from inspect_ai.model import get_model

        # Clear any prior cache for this id so the constructor actually
        # runs under our patch.
        from inspect_ai.model._model import _models

        _models.pop("openai-codex/gpt-5.5::None::None", None)

        with pytest.raises(Exception) as exc_info:
            get_model("openai-codex/gpt-5.5", memoize=False)
        # Error string mentions either the prerequisite or auth.
        msg = str(exc_info.value).lower()
        assert "codex" in msg or "auth" in msg or "prerequisite" in msg or "openai" in msg


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_openai_codex_constructor_sets_codex_headers() -> None:
    """When a token resolves, the provider wires ``ChatGPT-Account-ID``
    and ``originator`` into ``default_headers``. Avoid actually opening
    a TCP socket by injecting a fake token + asserting on the cached
    attributes."""
    # A minimal fake JWT — header.payload.signature. We synthesise
    # ``chatgpt_account_id`` in the payload claim so ``_extract_account_id``
    # returns a non-empty value.
    import base64
    import json

    from inspect_ai.model import get_model
    from inspect_ai.model._model import _models

    import plugins.petri_audit  # noqa: F401 — register()

    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": "fake-acc-id"}}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    fake_token = f"header.{payload_b64}.signature"

    _models.clear()
    with patch("core.llm.providers.codex._resolve_codex_token", return_value=fake_token):
        model = get_model("openai-codex/gpt-5.5", memoize=False)
    api = model.api  # OpenAICodexAPI instance
    assert api._codex_token == fake_token
    assert api._codex_headers["originator"] == "codex_cli_rs"
    assert api._codex_headers.get("ChatGPT-Account-ID") == "fake-acc-id"
    # base_url forced to the Codex endpoint.
    from core.config import CODEX_BASE_URL

    assert api.base_url == CODEX_BASE_URL


# ---------------------------------------------------------------------------
# Post-smoke fixes (2026-05-14) — observability of the live-run-only failures.
# ---------------------------------------------------------------------------


def test_entry_points_include_openai_codex_prefix() -> None:
    """inspect_ai's ``ensure_entry_points(package=<prefix>)`` matches by
    exact ``ep.name == prefix``. If the entry-point group does not list
    ``openai-codex``, the subprocess never imports ``plugins.petri_audit``
    and falls back to stock ``openai`` provider → SDK auth fails with
    ``Could not resolve authentication method``. This guards against
    regressing the pyproject.toml entry-points block.
    """
    from importlib.metadata import entry_points

    names = {ep.name for ep in entry_points(group="inspect_ai")}
    assert "openai-codex" in names, (
        "pyproject.toml [project.entry-points.inspect_ai] must include "
        "'openai-codex = plugins.petri_audit' so inspect_ai's subprocess "
        "fast-path loads our ModelAPI registration"
    )
    assert "geode" in names, (
        "pyproject.toml must also include 'geode = plugins.petri_audit' "
        "for the target=geode/<base> prefix fast-path"
    )


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_count_tokens_uses_tiktoken_not_responses_api() -> None:
    """ChatGPT Plus backend returns ``PermissionDeniedError`` on
    ``/responses/input_tokens.count``. Stock ``OpenAIAPI.count_tokens``
    hits that endpoint when ``responses_api=True``. We override
    ``count_tokens`` to do tiktoken-based local counting instead.

    This test confirms the override path is wired by feeding a known
    string and asserting tiktoken's count is returned (i.e., the method
    does NOT raise the PermissionDenied that the live audit hit).
    """
    import asyncio
    import base64
    import json as _json

    from inspect_ai.model import get_model
    from inspect_ai.model._model import _models

    import plugins.petri_audit  # noqa: F401 — register()

    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": "fake-acc-id"}}
    payload_b64 = base64.urlsafe_b64encode(_json.dumps(payload).encode()).decode().rstrip("=")
    fake_token = f"header.{payload_b64}.signature"

    _models.clear()
    with patch("core.llm.providers.codex._resolve_codex_token", return_value=fake_token):
        model = get_model("openai-codex/gpt-5.5", memoize=False)

    # tiktoken local count — must NOT make a network call to the
    # responses endpoint. "hello world" → handful of tokens.
    n = asyncio.run(model.count_tokens("hello world"))
    assert isinstance(n, int)
    assert 1 <= n <= 10, f"unexpected tiktoken count: {n}"
