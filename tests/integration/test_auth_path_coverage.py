"""Integration test — 4-path × 4-component auth coverage matrix.

Walks every (component, family, source) cell in
``plugins.seed_pipeline.auth_coverage.AUTH_COVERAGE_MATRIX`` and
verifies the routing surface is actually wired:

- **seed_pipeline** — `pick_bindings()` with a user override forces the
  cell's source; the resolved `RoleBinding` must reflect it.
- **petri_audit** — the manifest's `[petri.source.<family>].allowed`
  list contains the cell's source.
- **autoresearch** — `train.py`'s SEED_SELECT + USE_OAUTH knobs can
  reach both subscription (`USE_OAUTH=True`) and PAYG (`USE_OAUTH=False`)
  variants of each family.
- **geode_main** — the credential resolver in `core.config.settings`
  has the env field for the cell's family + source.

Also exercises the **TEST_SETUP_PROFILE** the user pinned on
2026-05-18 (seed_pipeline + autoresearch + geode_main → openai.openai-codex,
petri_audit → anthropic.claude-cli).
"""

from __future__ import annotations

import pytest
from plugins.seed_pipeline.auth_coverage import (
    AUTH_COVERAGE_MATRIX,
    TEST_SETUP_PROFILE,
    AuthCell,
    auth_status_table,
)

# ---------------------------------------------------------------------------
# Matrix structural invariants
# ---------------------------------------------------------------------------


def test_matrix_has_16_cells() -> None:
    """4 components × 4 paths = 16 cells."""
    assert len(AUTH_COVERAGE_MATRIX) == 16


def test_matrix_covers_all_four_paths_per_component() -> None:
    """Every component must have one cell per supported path."""
    expected_paths = {
        ("anthropic", "claude-cli"),
        ("anthropic", "api_key"),
        ("openai", "openai-codex"),
        ("openai", "api_key"),
    }
    by_component: dict[str, set[tuple[str, str]]] = {}
    for cell in AUTH_COVERAGE_MATRIX:
        by_component.setdefault(cell.component, set()).add((cell.path.family, cell.path.source))
    assert set(by_component) == {
        "seed_pipeline",
        "petri_audit",
        "autoresearch",
        "geode_main",
    }
    for component, paths in by_component.items():
        assert paths == expected_paths, f"{component} missing paths: {expected_paths - paths}"


def test_all_cells_currently_supported() -> None:
    """Sprint baseline — every cell should be `supported=True`."""
    unsupported = [c for c in AUTH_COVERAGE_MATRIX if not c.supported]
    assert unsupported == [], f"unexpected unsupported cells: {unsupported}"


# ---------------------------------------------------------------------------
# Per-component wiring checks
# ---------------------------------------------------------------------------


def _cells_for(component: str) -> list[AuthCell]:
    return [c for c in AUTH_COVERAGE_MATRIX if c.component == component]


@pytest.mark.parametrize("cell", _cells_for("seed_pipeline"))
def test_seed_pipeline_routes_to_cell(cell: AuthCell) -> None:
    """`pick_bindings()` honours a user override pinning the cell's source.

    Constructs a minimal in-memory manifest + override and verifies the
    resolved RoleBinding for the cell's family lands on the requested
    source.
    """
    from plugins.seed_pipeline.manifest import (
        JudgePanelSpec,
        SeedPipelineManifest,
        SeedRoleSpec,
        VoterSpec,
    )
    from plugins.seed_pipeline.picker import pick_bindings

    # Pick a model whose family matches the cell.
    model = "claude-sonnet-4-6" if cell.path.family == "anthropic" else "gpt-5.5"
    role_name = "generator"
    manifest = SeedPipelineManifest(
        enabled_roles=[role_name],
        roles={role_name: SeedRoleSpec(default_model=model, allowed_models=[model])},
        judge_panel=JudgePanelSpec(
            voters=[
                VoterSpec(model="claude-sonnet-4-6", family="anthropic", source="api_key"),
                VoterSpec(model="gpt-5.5", family="openai", source="api_key"),
            ],
            required_diversity_families=2,
        ),
    )
    overrides = {role_name: {"source": cell.path.source}}
    result = pick_bindings(
        manifest=manifest,
        overrides=overrides,
        auto_probe=False,
        enforce_diversity=False,
    )
    binding = result.bindings[role_name]
    assert binding.family == cell.path.family
    assert binding.source == cell.path.source


@pytest.mark.parametrize("cell", _cells_for("petri_audit"))
def test_petri_manifest_supports_cell(cell: AuthCell) -> None:
    """Petri's `[petri.source.<family>].allowed` lists the cell source."""
    from plugins.petri_audit.manifest import load_manifest as load_petri_manifest

    petri = load_petri_manifest()
    source_spec = petri.get_source(cell.path.family)
    assert cell.path.source in source_spec.allowed, (
        f"petri manifest [petri.source.{cell.path.family}].allowed missing "
        f"{cell.path.source!r}; got {source_spec.allowed}"
    )


@pytest.mark.parametrize("cell", _cells_for("autoresearch"))
def test_autoresearch_can_target_cell(cell: AuthCell) -> None:
    """`autoresearch/train.py`'s flags can drive each cell's family.

    Subscription paths (`claude-cli` / `openai-codex`) ride the
    `USE_OAUTH=True` branch; `api_key` rides the explicit env-var
    branch. The test just confirms the constants + flag plumbing
    exist; live OAuth probing is out of scope here.
    """
    from autoresearch import train

    assert hasattr(train, "USE_OAUTH")
    assert hasattr(train, "TARGET_MODEL")
    # Subscription path needs OAuth; PAYG needs an env key field.
    if cell.path.source in {"claude-cli", "openai-codex"}:
        # The flag must be a bool the agent can set/clear.
        assert isinstance(train.USE_OAUTH, bool)
    else:
        from core.config import _settings as settings_module

        env_var = f"{cell.path.family}_api_key"
        assert (
            hasattr(settings_module.Settings.model_fields[env_var], "alias")
            or hasattr(settings_module, env_var)
            or env_var in settings_module.Settings.model_fields
        )


@pytest.mark.parametrize("cell", _cells_for("geode_main"))
def test_geode_main_has_credential_field_for_cell(cell: AuthCell) -> None:
    """`core.config.settings` exposes the credential field per family."""
    from core.config import settings

    if cell.path.source == "api_key":
        attr = f"{cell.path.family}_api_key"
        assert hasattr(settings, attr), f"settings missing {attr}"
    elif cell.path.source == "claude-cli":
        from plugins.petri_audit.claude_code_provider import is_claude_oauth_available

        assert callable(is_claude_oauth_available)
    elif cell.path.source == "openai-codex":
        from plugins.petri_audit.codex_provider import is_codex_oauth_available

        assert callable(is_codex_oauth_available)


# ---------------------------------------------------------------------------
# Test-setup profile (2026-05-18 pinned)
# ---------------------------------------------------------------------------


def test_test_setup_profile_has_all_four_components() -> None:
    assert set(TEST_SETUP_PROFILE) == {
        "seed_pipeline",
        "petri_audit",
        "autoresearch",
        "geode_main",
    }


def test_test_setup_profile_targets() -> None:
    """The 2026-05-18 user directive pinned the profile."""
    assert str(TEST_SETUP_PROFILE["seed_pipeline"]) == "openai.openai-codex"
    assert str(TEST_SETUP_PROFILE["petri_audit"]) == "anthropic.claude-cli"
    assert str(TEST_SETUP_PROFILE["autoresearch"]) == "openai.openai-codex"
    assert str(TEST_SETUP_PROFILE["geode_main"]) == "openai.openai-codex"


def test_test_setup_profile_cells_are_supported() -> None:
    """Every cell in the test profile must be marked supported in the matrix."""
    for component, path in TEST_SETUP_PROFILE.items():
        cell = next(
            (c for c in AUTH_COVERAGE_MATRIX if c.component == component and c.path == path),
            None,
        )
        assert cell is not None, f"profile cell ({component}, {path}) not in matrix"
        assert cell.supported, f"profile cell ({component}, {path}) marked unsupported"


# ---------------------------------------------------------------------------
# auth_status_table renderer
# ---------------------------------------------------------------------------


def test_auth_status_table_renders_all_four_components() -> None:
    out = auth_status_table()
    for component in ("seed_pipeline", "petri_audit", "autoresearch", "geode_main"):
        assert component in out
    # Each row must show 4 path columns
    assert "anth.cli" in out
    assert "oai.cdx" in out


def test_auth_status_table_overlays_resolved_paths() -> None:
    out = auth_status_table(probe_resolved_path=TEST_SETUP_PROFILE)
    assert "resolved (live):" in out
    assert "openai.openai-codex" in out
    assert "anthropic.claude-cli" in out
