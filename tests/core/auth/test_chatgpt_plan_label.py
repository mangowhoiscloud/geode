"""PR-FIX-CHATGPT-PLAN-HALLUCINATION (2026-05-26) — chatgpt_plan_label invariants.

Pre-fix the GEODE codebase had "ChatGPT Plus" hard-coded in ~28 places
regardless of the operator's actual subscription tier. Verified
incident: operator on JWT claim ``chatgpt_plan_type='prolite'`` (the
Pro Lite tier) saw "ChatGPT Plus" surfaced in CLI / hub chip / docs /
audit reports. This file pins the dynamic-resolution behaviour so a
future drift can't re-hardcode a single tier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.auth.jwt_claims import decode_jwt_claims
from core.auth.oauth_login import (
    _plan_type_from_token,
    chatgpt_plan_label,
    resolve_local_chatgpt_plan_label,
)


class TestChatgptPlanLabel:
    """Slug → display label resolver — covers documented + future tiers."""

    @pytest.mark.parametrize(
        "slug,expected",
        [
            ("free", "ChatGPT Free"),
            ("plus", "ChatGPT Plus"),
            ("pro", "ChatGPT Pro"),
            ("prolite", "ChatGPT Pro Lite"),
            ("team", "ChatGPT Team"),
            ("business", "ChatGPT Business"),
            ("enterprise", "ChatGPT Enterprise"),
            ("edu", "ChatGPT Edu"),
        ],
    )
    def test_known_slugs(self, slug: str, expected: str) -> None:
        assert chatgpt_plan_label(slug) == expected

    def test_empty_slug_returns_generic_label(self) -> None:
        """No JWT signed in / build-time site render → generic label, never empty."""
        assert chatgpt_plan_label("") == "ChatGPT subscription"

    def test_unknown_slug_title_cases_and_prefixes(self) -> None:
        """Future-launched tier → ``ChatGPT {Title-Case}`` so display still works."""
        assert chatgpt_plan_label("future-tier-2030") == "ChatGPT Future-Tier-2030"

    def test_case_insensitive_slug_lookup(self) -> None:
        """JWT issuer occasionally serves variants — case folds at the boundary."""
        assert chatgpt_plan_label("PLUS") == "ChatGPT Plus"
        assert chatgpt_plan_label("ProLite") == "ChatGPT Pro Lite"

    def test_whitespace_slug_treated_as_empty(self) -> None:
        """Defensive — JWT claim might be whitespace-only on partial decode."""
        assert chatgpt_plan_label("   ") == "ChatGPT subscription"

    def test_none_safe(self) -> None:
        """Callers passing ``None`` (e.g. typed as ``str | None`` upstream)
        must not crash."""
        assert chatgpt_plan_label(None) == "ChatGPT subscription"


class TestPlanTypeFromToken:
    """JWT-extraction edge cases. The decode helper itself is tested via
    ``decode_jwt_claims`` (core.auth.jwt_claims); this wraps the slug-extract step."""

    def test_empty_token(self) -> None:
        assert _plan_type_from_token("") == ""

    def test_malformed_token_returns_empty(self) -> None:
        """Malformed JWT (not three dot-separated segments) returns empty
        slug — defensive so the caller's :func:`chatgpt_plan_label` falls
        through to ``"ChatGPT subscription"``."""
        assert _plan_type_from_token("not-a-real-jwt") == ""

    def test_jwt_without_openai_auth_claim(self) -> None:
        """Token decoded but missing the ``https://api.openai.com/auth``
        nested claim → empty slug."""
        # Build a minimal JWT-shaped string with a payload that has NO
        # openai.com/auth claim.
        import base64

        payload = {"sub": "user-123"}
        encoded_payload = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        fake_token = f"header.{encoded_payload}.signature"
        assert _plan_type_from_token(fake_token) == ""

    def test_jwt_with_plan_type_extracted(self) -> None:
        """Round-trip: build a JWT-shaped string with ``chatgpt_plan_type``
        in the OpenAI auth claim → extract returns the slug."""
        import base64

        payload = {
            "https://api.openai.com/auth": {
                "chatgpt_plan_type": "prolite",
            }
        }
        encoded_payload = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        fake_token = f"header.{encoded_payload}.signature"
        assert _plan_type_from_token(fake_token) == "prolite"


class TestDecodeJwtClaims:
    """JWT payload decoder — base64url padding edge cases."""

    def test_unpadded_payload(self) -> None:
        """JWT payloads omit trailing ``=`` — decoder must re-pad."""
        import base64

        payload = {"foo": "bar"}
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        # Force unpadded (rstrip already did, but assert no padding remains)
        assert "=" not in raw
        token = f"hdr.{raw}.sig"
        assert decode_jwt_claims(token) == payload

    def test_empty_token_returns_empty_dict(self) -> None:
        assert decode_jwt_claims("") == {}

    def test_single_segment_token(self) -> None:
        assert decode_jwt_claims("only-one-segment") == {}


class TestResolveLocalLabel:
    """Live resolution from disk — covers both Codex CLI auth.json and
    GEODE profile store paths. Uses monkeypatch + tmp_path to keep the
    test deterministic (operator's actual JWT remains untouched)."""

    def test_falls_back_to_generic_when_no_token_anywhere(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No codex auth file + no GEODE profile → generic label."""
        # Re-route HOME so the real ~/.codex/auth.json isn't read
        monkeypatch.setenv("HOME", str(tmp_path))
        # Hard-fail the profile store import so source-2 falls through
        import core.wiring.container

        monkeypatch.setattr(
            core.wiring.container,
            "ensure_profile_store",
            lambda: (_ for _ in ()).throw(RuntimeError("test: container disabled")),
        )
        assert resolve_local_chatgpt_plan_label() == "ChatGPT subscription"

    def test_reads_codex_cli_auth_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Synthetic codex auth.json with prolite plan → resolved label."""
        import base64

        payload = {
            "https://api.openai.com/auth": {
                "chatgpt_plan_type": "prolite",
            }
        }
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        fake_token = f"hdr.{encoded}.sig"
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        (codex_dir / "auth.json").write_text(
            json.dumps({"tokens": {"id_token": fake_token}}), encoding="utf-8"
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        assert resolve_local_chatgpt_plan_label() == "ChatGPT Pro Lite"

    def test_malformed_codex_auth_falls_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Malformed auth.json must not crash, must fall through to source-2
        (and from there to generic when container is disabled)."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        (codex_dir / "auth.json").write_text("not json at all", encoding="utf-8")
        monkeypatch.setenv("HOME", str(tmp_path))
        import core.wiring.container

        monkeypatch.setattr(
            core.wiring.container,
            "ensure_profile_store",
            lambda: (_ for _ in ()).throw(RuntimeError("test: container disabled")),
        )
        assert resolve_local_chatgpt_plan_label() == "ChatGPT subscription"
