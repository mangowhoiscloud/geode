"""PR-ROLE-PROVENANCE (2026-05-30) — source→lane mapping + role provenance.

The shared SoT for per-role {model, source, lane} recorded in both
``baseline_archive.jsonl`` (on promote) and ``mutations.jsonl`` (every cycle).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.config.credential_source import CredentialSource
from core.self_improving_loop.role_provenance import (
    ROLES,
    build_role_provenance,
    collect_role_provenance,
    role_display_id,
    source_to_lane,
)


@pytest.mark.parametrize(
    ("source", "lane"),
    [
        ("api_key", "PAYG"),
        ("openai-codex", "Subscription"),
        ("claude-cli", "CLI"),
        ("auto", "Auto"),
        (CredentialSource.API_KEY, "PAYG"),  # enum form
        (CredentialSource.CLAUDE_CLI, "CLI"),
        ("totally-unknown", "Unknown"),
        (None, "Unknown"),
    ],
)
def test_source_to_lane(source: object, lane: str) -> None:
    assert source_to_lane(source) == lane  # type: ignore[arg-type]


def test_role_display_id() -> None:
    assert role_display_id("gpt-5.5", "Subscription") == "GEODE/gpt-5.5/Subscription"
    assert role_display_id(None, "PAYG") == "GEODE/?/PAYG"


def test_build_role_provenance_derives_lane_from_source() -> None:
    prov = build_role_provenance(
        {
            "auditor": ("claude-opus-4-8", "api_key"),
            "target": ("gpt-5.5", "openai-codex"),
            "judge": ("claude-opus-4-8", "claude-cli"),
            "mutator": ("gpt-5.5", "openai-codex"),
        }
    )
    assert prov["auditor"] == {"model": "claude-opus-4-8", "source": "api_key", "lane": "PAYG"}
    assert prov["target"]["lane"] == "Subscription"
    assert prov["judge"]["lane"] == "CLI"
    assert set(prov) == set(ROLES)


def test_build_role_provenance_handles_none_model() -> None:
    """mutator default_model can be None (inherits Settings.model) — recorded
    as empty string, never crashes."""
    prov = build_role_provenance({"mutator": (None, "auto")})
    assert prov["mutator"] == {"model": "", "source": "auto", "lane": "Auto"}


def test_collect_role_provenance_from_config() -> None:
    cfg = SimpleNamespace(
        auditor=SimpleNamespace(model="A", source="api_key"),
        target=SimpleNamespace(model="T", source="openai-codex"),
        judge=SimpleNamespace(model="J", source="claude-cli"),
        mutator=SimpleNamespace(default_model="M", source="openai-codex"),
    )
    prov = collect_role_provenance(cfg)
    assert set(prov) == set(ROLES)
    assert prov["auditor"]["lane"] == "PAYG"
    assert prov["mutator"]["model"] == "M"
