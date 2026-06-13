"""PR-OBS-LOGGING-CONFIG — config centralization guards.

(1) env↔TOML parity: every non-secret Settings field is reachable via
config.toml (the cascade's promise). (2) value validation: malformed values
are rejected at boot, not silently passed to a provider that 400s mid-call.
"""

from __future__ import annotations

import pytest
from core.config import _TOML_ENV_ONLY_FIELDS, _TOML_TO_SETTINGS
from core.config._settings import Settings
from pydantic import ValidationError


def test_toml_settings_map_covers_every_non_secret_field() -> None:
    """No Settings field may be env-only-by-accident — config.toml must be a
    complete surface. Secrets are the sole intentional exception."""
    fields = set(Settings.model_fields)
    mapped = set(_TOML_TO_SETTINGS.values())
    missing = sorted(f for f in fields if f not in mapped and f not in _TOML_ENV_ONLY_FIELDS)
    assert missing == [], f"Settings fields unreachable via config.toml: {missing}"


def test_toml_map_has_no_stale_or_duplicate_entries() -> None:
    fields = set(Settings.model_fields)
    values = list(_TOML_TO_SETTINGS.values())
    stale = sorted(v for v in values if v not in fields)
    assert stale == [], f"_TOML_TO_SETTINGS points at removed fields: {stale}"
    assert len(values) == len(set(values)), "duplicate field targets in _TOML_TO_SETTINGS"


def test_env_only_fields_are_actually_secrets() -> None:
    """Guard the allowlist itself — only credential keys may be env-only."""
    assert all("api_key" in f for f in _TOML_ENV_ONLY_FIELDS)


@pytest.mark.parametrize("temp", [-0.1, 2.1, 3.0])
def test_temperature_out_of_range_rejected(temp: float) -> None:
    # temperature_* carry native ``Field(ge=0.0, le=2.0)`` constraints; this
    # locks that range in so a future field edit can't silently drop it.
    with pytest.raises(ValidationError):
        Settings(temperature_agent_loop=temp)


@pytest.mark.parametrize(
    "field", ["llm_read_timeout", "scheduler_interval_s", "gateway_poll_interval_s"]
)
def test_non_positive_duration_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="duration must be > 0 seconds"):
        Settings(**{field: 0.0})


def test_effort_enum_rejected() -> None:
    with pytest.raises(ValidationError, match="agentic_effort must be one of"):
        Settings(agentic_effort="turbo")


def test_effort_validator_accepts_full_picker_union() -> None:
    """The validator MUST accept every value the picker can persist to
    ``[agentic] effort`` — else selecting e.g. gpt-5.5 + ``none`` (OpenAI) or a
    GLM model + ``enabled`` writes a config that bricks the next ``Settings()``
    load. Drift invariant: ``AGENTIC_EFFORTS`` == the picker's provider union."""
    from core.cli.effort_picker import (
        _ANTHROPIC_ADAPTIVE_EFFORTS,
        _GLM_HYBRID_EFFORTS,
        _OPENAI_REASONING_EFFORTS,
    )
    from core.config._settings import AGENTIC_EFFORTS

    picker_union = (
        set(_ANTHROPIC_ADAPTIVE_EFFORTS) | set(_OPENAI_REASONING_EFFORTS) | set(_GLM_HYBRID_EFFORTS)
    )
    assert set(AGENTIC_EFFORTS) == picker_union, (
        "agentic_effort validator drifted from the picker — every persistable "
        f"effort must be accepted. validator={sorted(AGENTIC_EFFORTS)} "
        f"picker={sorted(picker_union)}"
    )
    for effort in picker_union:
        assert Settings(agentic_effort=effort).agentic_effort == effort


def test_valid_values_accepted() -> None:
    s = Settings(temperature_agent_loop=0.7, llm_read_timeout=120.0, agentic_effort="max")
    assert s.temperature_agent_loop == 0.7
    assert s.agentic_effort == "max"
