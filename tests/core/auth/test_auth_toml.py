"""Phase 4 — auth.toml persistence + .env migration tests."""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
from core.auth.auth_toml import (
    auth_file_transaction,
    auth_toml_path,
    load_auth_toml,
    save_auth_toml,
)
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.auth.rotation import ProfileRotator
from core.llm.strategies.plan_registry import (
    PlanRegistry,
    get_plan_registry,
    reset_plan_registry,
)
from core.llm.strategies.plans import GLM_CODING_TIERS, Quota


def _fresh_path() -> Path:
    fd, name = tempfile.mkstemp(suffix=".toml")
    os.close(fd)
    p = Path(name)
    p.unlink()  # save_auth_toml will recreate
    return p


def _reset_state() -> None:
    from core.wiring import container as _infra

    _infra._profile_store = None
    _infra._profile_rotator = None
    reset_plan_registry()


class TestRoundtrsubject:
    @pytest.mark.parametrize(
        "quota", [None, Quota(window_s=18_000, max_calls=80, model_weights={"glm-5.1": 3.0})]
    )
    def test_save_then_load_preserves_plan(self, quota: Quota | None) -> None:
        _reset_state()
        from core.wiring.container import ensure_profile_store

        store = ensure_profile_store()
        registry = get_plan_registry()
        plan = replace(GLM_CODING_TIERS["lite"], quota=quota)
        registry.add(plan)
        store.add(
            AuthProfile(
                name="glm-coding-lite:user",
                provider="glm-coding",
                credential_type=CredentialType.API_KEY,
                key="zai-test-key",
                plan_id=plan.id,
            )
        )
        registry.set_routing("glm-5.1", [plan.id])

        path = _fresh_path()
        save_auth_toml(path=path)
        assert path.exists()
        text = path.read_text()
        assert "glm-coding-lite" in text
        assert "zai-test-key" in text
        assert ("[plans.quota]" in text) is (quota is not None)
        if quota is not None:
            assert "max_calls = 80" in text

        # Reload into a fresh state
        path.chmod(0o644)
        _reset_state()
        load_auth_toml(path=path)
        assert path.stat().st_mode & 0o777 == 0o600
        registry2 = get_plan_registry()
        assert registry2.get("glm-coding-lite") == plan
        assert registry2.get_routing("glm-5.1") == ["glm-coding-lite"]
        store2 = ensure_profile_store()
        prof = next((p for p in store2.list_all() if p.name == "glm-coding-lite:user"), None)
        assert prof is not None
        assert prof.key == "zai-test-key"
        path.unlink()

    def test_managed_profiles_are_not_persisted(self) -> None:
        _reset_state()
        from core.wiring.container import ensure_profile_store

        store = ensure_profile_store()
        store.add(
            AuthProfile(
                name="openai-codex:codex-cli",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key="oauth-token-borrowed",
                managed_by="codex-cli",
            )
        )
        path = _fresh_path()
        save_auth_toml(path=path)
        text = path.read_text()
        assert "oauth-token-borrowed" not in text
        path.unlink()


class TestEnvironmentKeys:
    def test_first_use_keeps_environment_keys_in_their_own_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.config import settings
        from core.wiring.container import ensure_profile_store

        _reset_state()
        monkeypatch.setattr(settings, "openai_api_key", "sk-proj-environment-only")
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-...")  # placeholder

        store = ensure_profile_store()

        assert not auth_toml_path().exists()
        profile = store.get("openai:default")
        assert profile is not None and profile.metadata["origin"] == "environment"
        assert not store.list_by_provider("anthropic")
        save_auth_toml()
        assert "sk-proj-environment-only" not in auth_toml_path().read_text()


class TestEnvOverride:
    def test_geode_auth_toml_env_var_redirects_path(self) -> None:
        custom = _fresh_path()
        old = os.environ.get("GEODE_AUTH_TOML")
        try:
            os.environ["GEODE_AUTH_TOML"] = str(custom)
            assert auth_toml_path() == custom
        finally:
            if old is None:
                os.environ.pop("GEODE_AUTH_TOML", None)
            else:
                os.environ["GEODE_AUTH_TOML"] = old


def _user_profile(name: str, *, key: str = "synthetic-key") -> AuthProfile:
    return AuthProfile(name, "glm-coding", CredentialType.API_KEY, key=key, plan_id="one")


def _auth_state() -> tuple[PlanRegistry, ProfileStore]:
    registry, store = PlanRegistry(), ProfileStore()
    registry.add(replace(GLM_CODING_TIERS["lite"], id="one"))
    store.add(_user_profile("first"))
    store.add(_user_profile("second"))
    return registry, store


@pytest.mark.parametrize("ordered", [False, True])
def test_auth_preferences_reach_fresh_rotator(tmp_path: Path, ordered: bool) -> None:
    registry, store = _auth_state()
    if ordered:
        store.set_auth_order("glm-coding", ["second", "first"])
    else:
        store.set_active("second")
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=store, path=path)
    restored_registry, restored_store = PlanRegistry(), ProfileStore()
    assert load_auth_toml(registry=restored_registry, store=restored_store, path=path)
    assert ProfileRotator(restored_store).resolve("glm-coding").name == "second"
    assert restored_store.get_auth_order("glm-coding") == (["second", "first"] if ordered else [])


def test_reload_removes_only_file_owned_credentials_and_routes(tmp_path: Path) -> None:
    registry, writer = _auth_state()
    registry.set_routing("glm-5.3", ["one"])
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=writer, path=path)
    live_registry, live = PlanRegistry(), ProfileStore()
    managed = AuthProfile(
        "managed",
        "openai-codex",
        CredentialType.OAUTH,
        key="synthetic-managed",
        managed_by="codex-cli",
    )
    environment = AuthProfile("environment", "openai", CredentialType.API_KEY, key="synthetic-env")
    live.add(managed)
    live.add(environment)
    assert load_auth_toml(registry=live_registry, store=live, path=path)
    selected = ProfileRotator(live).resolve("glm-coding")
    assert selected is not None
    path.write_text("")
    assert load_auth_toml(registry=live_registry, store=live, path=path)
    assert live.get("first") is None and live.get("second") is None
    assert live_registry.get("one") is None
    assert live_registry.get_routing("glm-5.3") == []
    assert live.get("managed") is managed and live.get("environment") is environment
    assert selected.key == "synthetic-key"  # An in-flight borrowed reference stays usable.
    assert ProfileRotator(live).resolve("glm-coding") is None


@pytest.mark.parametrize(
    "invalid_tail",
    [
        '[[profiles]]\nname="bad"\nprovider="glm-coding"\ncredential_type="unknown"\nkey="synthetic-secret-do-not-log"\n',
        '[[profiles]]\nname="first"\nprovider="glm-coding"\nkey="duplicate"\n',
    ],
)
def test_invalid_reload_publishes_nothing(tmp_path: Path, caplog, invalid_tail: str) -> None:
    registry, store = _auth_state()
    store.set_auth_order("glm-coding", ["second", "first"])
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=store, path=path)
    before = {p.name: p for p in store.list_all()}
    before_plan = registry.get("one")
    path.write_text(path.read_text() + "\n" + invalid_tail)
    assert not load_auth_toml(registry=registry, store=store, path=path)
    assert {p.name: p for p in store.list_all()} == before
    assert all(store.get(name) is profile for name, profile in before.items())
    assert registry.get("one") is before_plan
    assert store.get_auth_order("glm-coding") == ["second", "first"]
    assert "synthetic-secret-do-not-log" not in caplog.text


def test_reload_preserves_unchanged_runtime_health_and_replaces_rotated_key(tmp_path: Path) -> None:
    registry, writer = _auth_state()
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=writer, path=path)
    live = ProfileStore()
    live.add(AuthProfile("environment", "openai", CredentialType.API_KEY, key="synthetic-env"))
    assert load_auth_toml(registry=PlanRegistry(), store=live, path=path)
    old = live.get("first")
    old.error_count, old.cooldown_until = 2, 98765432100.0
    assert load_auth_toml(registry=PlanRegistry(), store=live, path=path)
    assert live.get("first") is old and old.error_count == 2
    writer.add(_user_profile("first", key="synthetic-rotated"))
    save_auth_toml(registry=registry, store=writer, path=path)
    assert load_auth_toml(registry=PlanRegistry(), store=live, path=path)
    assert live.get("first") is not old
    assert old.key == "synthetic-key"
    assert live.get("first").key == "synthetic-rotated"
    assert live.get("first").error_count == 0


def test_file_preferences_reach_plan_bound_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.llm.strategies import plan_registry
    from core.wiring import container

    registry, writer = _auth_state()
    writer.set_auth_order("glm-coding", ["second", "first"])
    registry.set_routing("glm-5.3", ["one"])
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=writer, path=path)
    live_registry, live = PlanRegistry(), ProfileStore()
    assert load_auth_toml(registry=live_registry, store=live, path=path)
    monkeypatch.setattr(plan_registry, "_plan_registry", live_registry)
    monkeypatch.setattr(container, "_profile_store", live)
    monkeypatch.setattr(container, "_profile_rotator", ProfileRotator(live))
    from core.llm.routing import resolve_routing

    target = resolve_routing("glm-5.3")
    assert target is not None and target.profile.name == "second"
    live.set_active("first")
    assert ProfileRotator(live).resolve("glm-coding").name == "first"


def test_missing_file_keeps_state_but_legacy_file_clears_owned_preferences(tmp_path: Path) -> None:
    registry, store = _auth_state()
    store.set_auth_order("glm-coding", ["second", "first"])
    managed = AuthProfile(
        "managed",
        "openai-codex",
        CredentialType.OAUTH,
        key="synthetic-managed",
        managed_by="codex-cli",
    )
    store.add(managed)
    store.set_active(managed.name)
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=store, path=path)
    legacy = path.read_text().split("[pinned_active]")[0]
    path.unlink()
    assert not load_auth_toml(registry=registry, store=store, path=path)
    assert store.get_auth_order("glm-coding") == ["second", "first"]
    path.write_text(legacy)
    assert load_auth_toml(registry=registry, store=store, path=path)
    assert store.get_auth_order("glm-coding") == []
    assert store.get_pinned_active("glm-coding") is None
    assert store.get_pinned_active("openai-codex") is managed


def test_deleted_file_entry_does_not_delete_another_owners_replacement(tmp_path: Path) -> None:
    registry, store = _auth_state()
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=store, path=path)
    replacement = _user_profile("first", key="external-replacement")
    replacement.managed_by = "external"
    store.add(replacement)
    unrelated = replace(GLM_CODING_TIERS["lite"], id="one", display_name="External")
    registry.add(unrelated)
    path.write_text("")
    assert load_auth_toml(registry=registry, store=store, path=path)
    assert store.get("first") is replacement
    assert registry.get("one") is unrelated
    assert store.get("second") is None


def test_auth_write_failure_preserves_file_and_does_not_claim_runtime_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.memory import atomic_write

    registry, store = _auth_state()
    path = tmp_path / "auth.toml"
    path.write_text("# original\n")

    def fail_replace(*args):
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(atomic_write.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic filesystem failure"):
        save_auth_toml(registry=registry, store=store, path=path)
    assert path.read_text() == "# original\n"
    assert load_auth_toml(registry=registry, store=store, path=path)
    assert store.get("first") is not None  # Failed write never claimed it.
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "bad_section",
    [
        '[pinned_active]\n"glm-coding"="missing"',
        '[auth_order]\n"glm-coding"=["first", "first"]',
        '[[plans]]\nid="one"\nprovider="glm-coding"',
    ],
)
def test_invalid_selection_or_duplicate_plan_keeps_all_live_state(
    tmp_path: Path, bad_section: str
) -> None:
    registry, store = _auth_state()
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=store, path=path)
    profiles, plans = store.list_all(), registry.list_all()
    path.write_text(path.read_text() + "\n" + bad_section + "\n")
    assert not load_auth_toml(registry=registry, store=store, path=path)
    assert store.list_all() == profiles and registry.list_all() == plans


def test_saving_another_auth_file_transfers_only_persisted_ownership(tmp_path: Path) -> None:
    registry, store = _auth_state()
    store.set_auth_order("glm-coding", ["second", "first"])
    registry.set_routing("glm-5.3", ["one"])
    first, second = tmp_path / "first.toml", tmp_path / "second.toml"
    save_auth_toml(registry=registry, store=store, path=first)
    save_auth_toml(registry=registry, store=store, path=second)
    first.write_text("")
    assert load_auth_toml(registry=registry, store=store, path=first)
    assert store.get("first") is not None and registry.get("one") is not None
    assert store.get_auth_order("glm-coding") == ["second", "first"]
    assert registry.get_routing("glm-5.3") == ["one"]
    second.write_text("")
    assert load_auth_toml(registry=registry, store=store, path=second)
    assert len(store) == 0 and not registry.list_all() and not registry.all_routing()


def test_environment_fallback_is_not_claimed_by_auth_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings
    from core.wiring.container import build_auth

    path = tmp_path / "auth.toml"
    path.write_text("")
    monkeypatch.setenv("GEODE_AUTH_TOML", str(path))
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-env")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "zai_api_key", "")
    _reset_state()
    store, rotator, _ = build_auth()
    environment = rotator.resolve("openai")
    assert environment is not None
    registry = get_plan_registry()
    save_auth_toml(registry=registry, store=store, path=path)
    assert "synthetic-env" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_auth_toml(registry=registry, store=store, path=path)
    assert rotator.resolve("openai") is environment


@pytest.mark.parametrize("external_provider", ["openai", "glm-coding"])
def test_file_bindings_validate_effective_external_plan_before_publication(
    tmp_path: Path,
    external_provider: str,
) -> None:
    writer_registry, writer = _auth_state()
    writer.set_auth_order("glm-coding", ["second", "first"])
    writer_registry.set_routing("glm-5.3", ["one"])
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=writer_registry, store=writer, path=path)
    registry, store = PlanRegistry(), ProfileStore()
    external = replace(GLM_CODING_TIERS["lite"], id="one", provider=external_provider)
    registry.add(external)
    loaded = load_auth_toml(registry=registry, store=store, path=path)
    assert registry.get("one") is external
    if external_provider == "openai":
        assert not loaded
        assert not store.list_all() and not registry.all_routing()
        assert store.auth_preferences() == ({}, {})
    else:
        assert loaded
        assert store.get("first").provider == registry.get("one").provider
        assert store.get_auth_order("glm-coding") == ["second", "first"]


def test_non_string_profile_endpoint_rejects_whole_candidate(tmp_path: Path) -> None:
    registry, store = _auth_state()
    path = tmp_path / "auth.toml"
    save_auth_toml(registry=registry, store=store, path=path)
    first, second = store.get("first"), store.get("second")
    path.write_text(path.read_text() + "base_url_override=123\n")
    assert not load_auth_toml(registry=registry, store=store, path=path)
    assert store.get("first") is first and store.get("second") is second


def test_transaction_adopts_other_writers_before_changing_the_file(tmp_path: Path) -> None:
    """A stale in-memory copy cannot revive a removed profile or restore a rotated key."""
    path = tmp_path / "auth.toml"
    registry, store = _auth_state()
    save_auth_toml(registry=registry, store=store, path=path)
    stale_registry, stale = PlanRegistry(), ProfileStore()
    assert load_auth_toml(registry=stale_registry, store=stale, path=path)
    other_registry, other = PlanRegistry(), ProfileStore()
    assert load_auth_toml(registry=other_registry, store=other, path=path)
    other.remove("second")
    other.add(_user_profile("first", key="rotated-key"))
    save_auth_toml(registry=other_registry, store=other, path=path)

    with auth_file_transaction(registry=stale_registry, store=stale, path=path) as (_, profiles):
        profiles.set_active("first")

    restored_registry, restored = PlanRegistry(), ProfileStore()
    assert load_auth_toml(registry=restored_registry, store=restored, path=path)
    assert restored.get("second") is None
    assert restored.get("first").key == "rotated-key"
    assert restored.get_pinned_active("glm-coding").name == "first"
    assert stale.get("second") is None  # The writer publishes what it saved.
    assert stale.get("first").key == "rotated-key"


def test_transaction_write_failure_leaves_file_and_live_state_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.memory import atomic_write

    path = tmp_path / "auth.toml"
    registry, store = _auth_state()
    save_auth_toml(registry=registry, store=store, path=path)
    before = path.read_bytes()

    def fail_replace(*args: object) -> None:
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(atomic_write.os, "replace", fail_replace)
    with (
        pytest.raises(OSError, match="synthetic filesystem failure"),
        auth_file_transaction(registry=registry, store=store, path=path) as (_, profiles),
    ):
        profiles.add(_user_profile("third"))
    assert path.read_bytes() == before
    assert store.get("third") is None


def test_transaction_rejects_invalid_file_without_running_the_change(tmp_path: Path) -> None:
    path = tmp_path / "auth.toml"
    path.write_text('[[profiles]]\nname="bad"\n')
    before = path.read_bytes()
    registry, store = _auth_state()
    with (
        pytest.raises(ValueError, match="is invalid"),
        auth_file_transaction(registry=registry, store=store, path=path),
    ):
        pytest.fail("a change must not run against an unreadable file")
    assert path.read_bytes() == before


def test_load_does_not_rewrite_the_file_when_the_token_tier_differs(tmp_path: Path) -> None:
    """Reading hydrates the stores only; token writers record the tier."""
    import base64
    import json

    from core.auth.oauth_login import _GEODE_OPENAI_PLAN_ID
    from core.llm.strategies.plans import Plan, PlanKind

    claims = {"https://api.openai.com/auth": {"chatgpt_plan_type": "pro"}}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    registry, store = PlanRegistry(), ProfileStore()
    registry.add(
        Plan(
            id=_GEODE_OPENAI_PLAN_ID,
            provider="openai-codex",
            kind=PlanKind.OAUTH_BORROWED,
            display_name="GEODE OAuth",
            base_url="https://chatgpt.com/backend-api/codex",
            subscription_tier="plus",
        )
    )
    store.add(
        AuthProfile(
            name=f"{_GEODE_OPENAI_PLAN_ID}:user",
            provider="openai-codex",
            credential_type=CredentialType.OAUTH,
            key=f"e30.{payload}.sig",
            plan_id=_GEODE_OPENAI_PLAN_ID,
        )
    )
    path = auth_toml_path()
    save_auth_toml(registry=registry, store=store, path=path)
    before = path.read_bytes()
    _reset_state()

    assert load_auth_toml()

    assert path.read_bytes() == before
    assert get_plan_registry().get(_GEODE_OPENAI_PLAN_ID).subscription_tier == "plus"


def test_unreadable_credential_value_is_rejected_before_writing(tmp_path: Path) -> None:
    """A stray terminal control sequence cannot produce a file that later loads reject."""
    path = tmp_path / "auth.toml"
    registry, store = _auth_state()
    save_auth_toml(registry=registry, store=store, path=path)
    before = path.read_bytes()

    with (
        pytest.raises(ValueError, match="unreadable auth file"),
        auth_file_transaction(registry=registry, store=store, path=path) as (_, profiles),
    ):
        profiles.add(_user_profile("pasted", key="synthetic\x1b[201~"))

    assert path.read_bytes() == before
    assert store.get("pasted") is None
