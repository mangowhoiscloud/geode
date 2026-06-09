"""PR-A — `/model` role-tab (primary + reflection) invariants.

Pins the new ``AGENT_ROLES`` registry, the ``PickerResult.role``
field, the Tab key plumbing in ``_read_key``, and the
``_apply_model`` dispatcher.
"""

from __future__ import annotations

import inspect

import pytest
from core.cli.commands._state import (
    AGENT_ROLES,
    role_by_name,
)

from core.cli import effort_picker

# ---------------------------------------------------------------------------
# AGENT_ROLES registry
# ---------------------------------------------------------------------------


def test_agent_roles_includes_primary_and_reflection() -> None:
    names = {r.name for r in AGENT_ROLES}
    assert {"primary", "reflection"} <= names


def test_primary_role_writes_to_settings_model() -> None:
    primary = role_by_name("primary")
    assert primary.settings_field == "model"
    assert primary.env_var == "GEODE_MODEL"
    assert primary.toml_section == "llm"
    assert primary.toml_key == "primary_model"
    assert primary.has_effort is True


def test_reflection_role_writes_to_cognitive_reflection_model() -> None:
    reflection = role_by_name("reflection")
    assert reflection.settings_field == "cognitive_reflection_model"
    assert reflection.env_var == "GEODE_COGNITIVE_REFLECTION_MODEL"
    assert reflection.toml_section == "cognitive"
    assert reflection.toml_key == "reflection_model"
    # Reflection node has no effort axis — different LLM, different
    # contract (one-shot JSON output, no reasoning depth knob).
    assert reflection.has_effort is False


def test_role_by_name_raises_on_unknown() -> None:
    with pytest.raises(ValueError, match="unknown agent role"):
        role_by_name("not_a_role")


# ---------------------------------------------------------------------------
# PickerResult role field
# ---------------------------------------------------------------------------


def test_picker_result_defaults_role_to_primary() -> None:
    """Backward compat — callers that don't specify role get
    primary so the legacy single-axis flow keeps working."""
    r = effort_picker.PickerResult(model_id="x", effort="high")
    assert r.role == "primary"


def test_picker_result_carries_explicit_role() -> None:
    r = effort_picker.PickerResult(model_id="x", effort=None, role="reflection")
    assert r.role == "reflection"


# ---------------------------------------------------------------------------
# Tab key + role tabs in render
# ---------------------------------------------------------------------------


def test_read_key_handles_tab() -> None:
    """``\\t`` must map to ``_KEY_TAB`` so the picker can cycle roles."""
    src = inspect.getsource(effort_picker._read_key)
    assert '"\\t"' in src or "'\\t'" in src
    assert effort_picker._KEY_TAB == "TAB"


def test_render_signature_accepts_roles() -> None:
    """Pin the role-tab parameter so a future refactor that drops it
    surfaces here, not at runtime."""
    sig = inspect.signature(effort_picker._render)
    assert "roles" in sig.parameters
    assert "role_cursor" in sig.parameters
    assert "role_initials" in sig.parameters


def test_pick_model_and_effort_signature_accepts_roles() -> None:
    sig = inspect.signature(effort_picker.pick_model_and_effort)
    assert "roles" in sig.parameters
    assert "initial_role" in sig.parameters
    assert "role_initial_models" in sig.parameters


# ---------------------------------------------------------------------------
# _apply_model dispatcher
# ---------------------------------------------------------------------------


def test_apply_model_accepts_role_kwarg() -> None:
    """Pin the ``role`` kwarg on ``_apply_model`` — the picker passes
    it through from ``PickerResult.role``."""
    from core.cli.commands.model import _apply_model

    sig = inspect.signature(_apply_model)
    assert "role" in sig.parameters
    assert sig.parameters["role"].default == "primary"


def test_apply_model_dispatches_to_reflection_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reflection branch must write to
    ``settings.cognitive_reflection_model`` (not ``settings.model``)
    and to the reflection env/toml keys."""
    from core.cli.commands._state import ModelProfile
    from core.config import settings

    # Stub _check_provider_key + console + upsert_env + upsert_config_toml
    # to capture invocations without touching real .env / config.toml.
    from core.cli import commands as _pkg
    from core.cli.commands import model as _model_mod

    monkeypatch.setattr(_pkg, "_check_provider_key", lambda _p: None)
    monkeypatch.setattr(_pkg, "get_conversation_context", lambda: None)
    upsert_env_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(_pkg, "_upsert_env", lambda k, v: upsert_env_calls.append((k, v)))

    from core.utils import env_io as _env_io

    upsert_toml_calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        _env_io,
        "upsert_config_toml",
        lambda section, key, value, *, scope="project": upsert_toml_calls.append(
            (section, key, value)
        ),
    )

    # Snapshot the current reflection model so we can restore + verify.
    old_reflection = getattr(settings, "cognitive_reflection_model", "")
    target = ModelProfile(
        id="claude-haiku-4-5-20251001", provider="anthropic", label="Haiku 4.5", cost="$"
    )

    # Set a sentinel so the test exercises the change path
    object.__setattr__(settings, "cognitive_reflection_model", "claude-opus-4-7")

    _model_mod._apply_model(target, effort=None, role="reflection")

    # settings field flipped
    assert settings.cognitive_reflection_model == "claude-haiku-4-5-20251001"
    # env_io wrote the reflection env + toml keys, NOT GEODE_MODEL /
    # [llm] primary_model
    assert ("GEODE_COGNITIVE_REFLECTION_MODEL", "claude-haiku-4-5-20251001") in upsert_env_calls
    assert ("cognitive", "reflection_model", "claude-haiku-4-5-20251001") in upsert_toml_calls
    assert not any(k == "GEODE_MODEL" for k, _v in upsert_env_calls)
    assert not any(s == "llm" for s, _k, _v in upsert_toml_calls)

    # Restore
    object.__setattr__(settings, "cognitive_reflection_model", old_reflection)


def _capture_apply_io(monkeypatch: pytest.MonkeyPatch):
    """Shared stub: capture _upsert_env + upsert_config_toml(scope=…) calls."""
    from core.cli import commands as _pkg
    from core.utils import env_io as _env_io

    monkeypatch.setattr(_pkg, "_check_provider_key", lambda _p: None)
    monkeypatch.setattr(_pkg, "get_conversation_context", lambda: None)
    env_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(_pkg, "_upsert_env", lambda k, v: env_calls.append((k, v)))
    toml_calls: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        _env_io,
        "upsert_config_toml",
        lambda section, key, value, *, scope="project": toml_calls.append(
            (section, key, value, scope)
        ),
    )
    return env_calls, toml_calls


def test_apply_model_primary_project_scope_skips_global_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary + project scope persists to the project config only — never
    the global GEODE_MODEL env, the pre-fix leak that made a project switch
    stick across every workspace and shadow the project TOML on reload."""
    from core.cli.commands._state import ModelProfile
    from core.config import settings

    from core.cli.commands import model as _model_mod

    env_calls, toml_calls = _capture_apply_io(monkeypatch)
    old = settings.model
    object.__setattr__(settings, "model", "claude-opus-4-7")
    try:
        target = ModelProfile(
            id="claude-opus-4-8", provider="anthropic", label="Opus 4.8", cost="$$$"
        )
        _model_mod._apply_model(target, role="primary", scope="project")
    finally:
        object.__setattr__(settings, "model", old)

    assert not any(k == "GEODE_MODEL" for k, _v in env_calls)
    assert ("llm", "primary_model", "claude-opus-4-8", "project") in toml_calls


def test_apply_model_primary_global_scope_writes_env_and_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary + global scope writes the global config + GEODE_MODEL env so
    every project without its own override inherits the choice."""
    from core.cli.commands._state import ModelProfile
    from core.config import settings

    from core.cli.commands import model as _model_mod

    env_calls, toml_calls = _capture_apply_io(monkeypatch)
    old = settings.model
    object.__setattr__(settings, "model", "claude-opus-4-7")
    try:
        target = ModelProfile(
            id="claude-opus-4-8", provider="anthropic", label="Opus 4.8", cost="$$$"
        )
        _model_mod._apply_model(target, role="primary", scope="global")
    finally:
        object.__setattr__(settings, "model", old)

    assert ("GEODE_MODEL", "claude-opus-4-8") in env_calls
    assert ("llm", "primary_model", "claude-opus-4-8", "global") in toml_calls


def test_cmd_model_global_token_routes_to_global_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/model global <name>`` dispatches with scope='global'; a bare
    ``/model <name>`` stays project-scoped."""
    from core.cli.commands import model as _model_mod

    monkeypatch.setattr(_model_mod, "model_available", lambda _id: True)
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _model_mod,
        "_apply_model",
        lambda selected, *, role="primary", scope="project", effort=None: captured.append(
            (selected.id, scope)
        ),
    )
    _model_mod.cmd_model("global claude-opus-4-8")
    _model_mod.cmd_model("claude-opus-4-8")
    assert ("claude-opus-4-8", "global") in captured
    assert ("claude-opus-4-8", "project") in captured


def test_apply_model_primary_skips_effort_for_reflection_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``has_effort=False`` roles must never call ``_upsert_env``
    with ``GEODE_AGENTIC_EFFORT`` even when ``effort=`` is passed
    (defensive — picker passes None for non-effort roles, but the
    dispatcher must double-check)."""
    from core.cli.commands._state import ModelProfile

    from core.cli import commands as _pkg
    from core.cli.commands import model as _model_mod

    monkeypatch.setattr(_pkg, "_check_provider_key", lambda _p: None)
    monkeypatch.setattr(_pkg, "get_conversation_context", lambda: None)
    upsert_env_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(_pkg, "_upsert_env", lambda k, v: upsert_env_calls.append((k, v)))
    from core.utils import env_io as _env_io

    monkeypatch.setattr(_env_io, "upsert_config_toml", lambda *_a, **_kw: None)

    target = ModelProfile(id="claude-haiku-4-5-20251001", provider="anthropic", label="x", cost="$")
    # Pass effort even though reflection role doesn't have one
    _model_mod._apply_model(target, effort="high", role="reflection")
    assert not any(k == "GEODE_AGENTIC_EFFORT" for k, _v in upsert_env_calls)


# ---------------------------------------------------------------------------
# cmd_model arg parsing — role prefix
# ---------------------------------------------------------------------------


def test_cmd_model_parses_role_prefix() -> None:
    """``/model reflection haiku-4.5`` must route to the reflection
    role, not interpret 'reflection' as a model name."""
    from core.cli.commands.model import cmd_model

    src = inspect.getsource(cmd_model)
    # Pin the role-prefix parsing branch
    assert "first, _, rest = arg.partition" in src or "partition" in src
    assert "role_name = first" in src or "role_name=" in src


def test_cmd_model_role_def_passed_to_apply_model() -> None:
    """End-to-end grep — ``cmd_model`` must pass ``role=role_def.name``
    into ``_apply_model``, not the hardcoded 'primary' default."""
    from core.cli.commands.model import cmd_model

    src = inspect.getsource(cmd_model)
    assert "role=role_def.name" in src


# ---------------------------------------------------------------------------
# Single-role mode still works (backward compat)
# ---------------------------------------------------------------------------


def test_picker_without_roles_runs_in_single_axis_mode() -> None:
    """Pin that calling pick_model_and_effort WITHOUT ``roles`` keeps
    the legacy behaviour — older test fixtures that don't construct
    the role tab list must not break."""
    sig = inspect.signature(effort_picker.pick_model_and_effort)
    # Default = None so callers can omit
    assert sig.parameters["roles"].default is None


def test_picker_render_accepts_show_effort_flag() -> None:
    """Codex MCP #1 catch — picker must hide effort controls when the
    focused role has ``has_effort=False`` so the user can't move ←→
    expecting a no-op write. Pin the show_effort parameter."""
    sig = inspect.signature(effort_picker._render)
    assert "show_effort" in sig.parameters
    assert sig.parameters["show_effort"].default is True


def test_picker_pass_role_has_effort_dict() -> None:
    """The model.py picker entry must pass ``role_has_effort`` so the
    picker knows which roles support effort. Without this kwarg,
    show_effort defaults to True and the bug remains."""
    sig = inspect.signature(effort_picker.pick_model_and_effort)
    assert "role_has_effort" in sig.parameters

    from core.cli.commands import model as _model_mod

    src = inspect.getsource(_model_mod._interactive_model_picker)
    assert "role_has_effort=role_has_effort" in src
    src_role = inspect.getsource(_model_mod._interactive_model_picker_for_role)
    assert "role_has_effort=role_has_effort" in src_role


def test_picker_render_show_effort_false_emits_no_knob_hint() -> None:
    """Behavioural check — when show_effort=False the render writes
    the 'No effort knob for this role' hint so the user gets
    explicit feedback instead of an absent line."""
    import io
    import sys

    profiles = [
        ("claude-haiku-4-5-20251001", "anthropic", "Haiku 4.5", "$", True, None),
    ]
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        effort_picker._render(
            profiles,
            cursor=0,
            effort_per_model={"claude-haiku-4-5-20251001": None},
            initial_model="claude-haiku-4-5-20251001",
            show_effort=False,
        )
    finally:
        sys.stdout = old_stdout
    out = buf.getvalue()
    assert "No effort knob for this role" in out
    # And it does NOT render the disc + ←→ adjuster
    assert "← → to adjust" not in out
