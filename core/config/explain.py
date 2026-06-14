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

Dotenv-layer order (2026-06-15, Hermes-aligned): the GLOBAL
``~/.geode/.env`` is the authoritative secret store and beats the project
``.env`` — a project file only fills keys global lacks, never shadows a
global key. pydantic-settings merges ``env_file=(".env", global)`` with
the LATER (global) file winning, and the serve daemon's bootstrap
promotion follows the same order (both loaders flip together, so the
per-process inversion hazard H5 stays fixed). Secrets differ from config:
config.toml keeps project>global. Behavior(model-pick) keys never survive
into the daemon's os.environ (hazard H2,
``core.config.env_io.BEHAVIOR_ENV_KEYS``).
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


def _global_toml_path() -> Path:
    env_toml = os.environ.get("GEODE_CONFIG_TOML", "").strip()
    return Path(env_toml).expanduser() if env_toml else GLOBAL_CONFIG_PATH


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

    # Dotenv layer — env_file=(project, global) with later-file-wins, so the
    # GLOBAL file beats project (2026-06-15 Hermes-aligned secret precedence);
    # report both files separately so a duplicate key is visible. An empty
    # value (KEY=) coalesces to None so it never registers as a winning layer,
    # matching the loaders' "empty never clobbers" contract.
    global_env = dotenv_values(GLOBAL_ENV_FILE) if GLOBAL_ENV_FILE.exists() else {}
    project_env = dotenv_values(PROJECT_ENV_FILE) if PROJECT_ENV_FILE.exists() else {}
    candidates.append(
        LayerValue("global .env", str(GLOBAL_ENV_FILE), global_env.get(env_var) or None)
    )
    candidates.append(
        LayerValue(
            "project .env", str(PROJECT_ENV_FILE.resolve()), project_env.get(env_var) or None
        )
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
        # H9 (C-4): GEODE_CONFIG_TOML redirects the global file for the main
        # loader too — report the path actually read.
        LayerValue("global config.toml", str(_global_toml_path()), _toml_value(_global_toml_path()))
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
    if winner is None or winner.layer not in ("os.environ", "project .env", "global .env"):
        return None
    masked_toml = [entry for entry in report.masked_layers if entry.layer.endswith("config.toml")]
    if not masked_toml:
        return None
    return (
        f"{report.env_var} ({winner.layer}) = {winner.value!r} is masking "
        f"{masked_toml[0].layer} = {masked_toml[0].value!r} — "
        "run `geode config explain model`"
    )
