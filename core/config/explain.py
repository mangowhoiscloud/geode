"""Config layer explainer — which layer wins, and what it masks.

C-1 of the config-unification sprint (2026-06-11). The override audit
mapped 14 hazards whose common symptom is "I changed the config but the
effective value didn't move" — a higher-precedence layer (os.environ, a
forgotten ``.env`` line, a project-toml pin) silently masks the edit and
no surface showed the winning layer (hazard H8). This module computes,
per Settings field, every layer's candidate value and the winner, using
the SAME precedence the real resolution applies:

    os.environ  >  dotenv layer  >  project config.toml  >  global
    config.toml  >  code default

Dotenv-layer honesty note: pydantic-settings merges ``env_file=(".env",
"~/.geode/.env")`` with the LATER file winning, so within the dotenv
layer the GLOBAL file beats the project file for a plain ``Settings()``
construction. (The serve daemon's bootstrap loads them in the opposite
direction — hazard H5; this explainer reports the plain-Settings order
and flags the key when both files define it.)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from core.config import _TOML_TO_SETTINGS, GLOBAL_CONFIG_PATH, PROJECT_CONFIG_PATH, _flatten_toml
from core.paths import GLOBAL_ENV_FILE

PROJECT_ENV_FILE = Path(".env")

#: Layer identifiers in precedence order (index 0 = strongest).
LAYERS: tuple[str, ...] = (
    "os.environ",
    "global .env",
    "project .env",
    "project config.toml",
    "global config.toml",
    "code default",
)


@dataclass
class LayerValue:
    layer: str
    source: str  # file path or "process env" / "Settings default"
    value: Any | None  # None = not set at this layer
    is_winner: bool = False
    is_masked: bool = False


@dataclass
class FieldReport:
    field_name: str
    env_var: str
    toml_key: str | None
    effective: Any
    layers: list[LayerValue] = field(default_factory=list)

    @property
    def winner(self) -> LayerValue | None:
        return next((entry for entry in self.layers if entry.is_winner), None)

    @property
    def masked_layers(self) -> list[LayerValue]:
        return [entry for entry in self.layers if entry.is_masked]


_FIELD_TO_TOML: dict[str, str] = {v: k for k, v in _TOML_TO_SETTINGS.items()}


def _env_var_for(field_name: str) -> str:
    return f"GEODE_{field_name.upper()}"


def explain_field(field_name: str) -> FieldReport:
    """Compute the per-layer candidates + winner for one Settings field."""
    from core.config import settings

    env_var = _env_var_for(field_name)
    toml_key = _FIELD_TO_TOML.get(field_name)

    candidates: list[LayerValue] = []

    candidates.append(LayerValue("os.environ", "process env", os.environ.get(env_var)))

    # Dotenv layer — pydantic's later-file-wins means GLOBAL beats project
    # for plain Settings(); report both files separately so a duplicate key
    # is visible.
    global_env = dotenv_values(GLOBAL_ENV_FILE) if GLOBAL_ENV_FILE.exists() else {}
    project_env = dotenv_values(PROJECT_ENV_FILE) if PROJECT_ENV_FILE.exists() else {}
    candidates.append(LayerValue("global .env", str(GLOBAL_ENV_FILE), global_env.get(env_var)))
    candidates.append(
        LayerValue("project .env", str(PROJECT_ENV_FILE.resolve()), project_env.get(env_var))
    )

    def _toml_value(path: Path) -> Any | None:
        if toml_key is None or not path.exists():
            return None
        import tomllib

        try:
            with open(path, "rb") as f:
                flat = _flatten_toml(tomllib.load(f))
        except Exception:
            return None
        return flat.get(toml_key)

    candidates.append(
        LayerValue(
            "project config.toml",
            str(PROJECT_CONFIG_PATH.resolve()),
            _toml_value(PROJECT_CONFIG_PATH),
        )
    )
    candidates.append(
        LayerValue("global config.toml", str(GLOBAL_CONFIG_PATH), _toml_value(GLOBAL_CONFIG_PATH))
    )

    default = (
        type(settings).model_fields[field_name].default
        if field_name in type(settings).model_fields
        else None
    )
    candidates.append(LayerValue("code default", "Settings default", default))

    # Winner = first set layer in precedence order.
    winner_seen = False
    for entry in candidates:
        if entry.value is None:
            continue
        if not winner_seen:
            entry.is_winner = True
            winner_seen = True
        else:
            entry.is_masked = True

    return FieldReport(
        field_name=field_name,
        env_var=env_var,
        toml_key=toml_key,
        effective=getattr(settings, field_name, None),
        layers=candidates,
    )


def model_mask_warning() -> str | None:
    """One-line warning when an env-layer model masks a toml pick (H3/H4 class).

    Returns None when nothing is masked. Consumed by ``geode about``.
    """
    report = explain_field("model")
    winner = report.winner
    if winner is None or winner.layer not in ("os.environ", "global .env", "project .env"):
        return None
    masked_toml = [entry for entry in report.masked_layers if entry.layer.endswith("config.toml")]
    if not masked_toml:
        return None
    return (
        f"{report.env_var} ({winner.layer}) = {winner.value!r} is masking "
        f"{masked_toml[0].layer} = {masked_toml[0].value!r} — "
        "run `geode config explain model`"
    )
