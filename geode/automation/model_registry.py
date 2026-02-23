"""Model Registry — version control for pipeline model configurations.

Tracks model versions with hashes, promotion stages, and rollback support.
File-based JSON persistence follows RunLog JSONL patterns.

Architecture-v6 §4.5: Automation Layer — Model Registry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from geode.orchestration.hooks import HookSystem

log = logging.getLogger(__name__)

# Semantic version pattern: v{major}.{minor} or v{major}.{minor}.{patch}
# Also allows plain identifiers like "model-2024-01"
VERSION_ID_PATTERN = re.compile(
    r"^v?\d+\.\d+(\.\d+)?(-[a-zA-Z0-9._-]+)?$|^[a-zA-Z0-9][a-zA-Z0-9._-]*$"
)


class PromotionStage(Enum):
    """Model promotion lifecycle stages."""

    DEV = "dev"
    STAGING = "staging"
    CANARY = "canary"
    PROD = "prod"
    DEPRECATED = "deprecated"


VALID_TRANSITIONS: dict[PromotionStage, list[PromotionStage]] = {
    PromotionStage.DEV: [PromotionStage.STAGING],
    PromotionStage.STAGING: [PromotionStage.CANARY, PromotionStage.DEV],
    PromotionStage.CANARY: [PromotionStage.PROD, PromotionStage.STAGING],
    PromotionStage.PROD: [PromotionStage.DEPRECATED],
    PromotionStage.DEPRECATED: [],
}


def _compute_hash(data: str) -> str:
    """Compute SHA-256 hash of a string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


@dataclass
class ModelVersion:
    """A single model version record."""

    version_id: str
    parent: str | None = None
    prompt_hash: str = ""
    rubric_hash: str = ""
    config_hash: str = ""
    configs: dict[str, Any] = field(default_factory=dict)
    stage: PromotionStage = PromotionStage.DEV
    metrics: dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    promoted_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "parent": self.parent,
            "prompt_hash": self.prompt_hash,
            "rubric_hash": self.rubric_hash,
            "config_hash": self.config_hash,
            "configs": self.configs,
            "stage": self.stage.value,
            "metrics": self.metrics,
            "created_at": self.created_at,
            "promoted_at": self.promoted_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ModelVersion:
        return cls(
            version_id=d["version_id"],
            parent=d.get("parent"),
            prompt_hash=d.get("prompt_hash", ""),
            rubric_hash=d.get("rubric_hash", ""),
            config_hash=d.get("config_hash", ""),
            configs=d.get("configs", {}),
            stage=PromotionStage(d.get("stage", "dev")),
            metrics=d.get("metrics", {}),
            created_at=d.get("created_at", 0.0),
            promoted_at=d.get("promoted_at"),
        )


class _RegistryStats:
    """Internal instrumentation counters."""

    __slots__ = ("registered", "promoted", "rolled_back", "persisted")

    def __init__(self) -> None:
        self.registered: int = 0
        self.promoted: int = 0
        self.rolled_back: int = 0
        self.persisted: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "registered": self.registered,
            "promoted": self.promoted,
            "rolled_back": self.rolled_back,
            "persisted": self.persisted,
        }


class ModelRegistry:
    """Versioned model registry with promotion stages and rollback.

    Usage:
        registry = ModelRegistry(storage_dir=Path("/tmp/models"))
        version = registry.register("v1.0", configs={"temperature": 0.3})
        registry.promote("v1.0", PromotionStage.STAGING)
        prod = registry.get_production()
    """

    def __init__(
        self, storage_dir: Path | None = None, hooks: HookSystem | None = None,
    ) -> None:
        self._versions: dict[str, ModelVersion] = {}
        self._storage_dir = storage_dir
        self._hooks = hooks
        self._lock = threading.Lock()
        self._stats = _RegistryStats()
        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    @property
    def stats(self) -> _RegistryStats:
        return self._stats

    def register(
        self,
        version_id: str,
        *,
        parent: str | None = None,
        configs: dict[str, Any] | None = None,
        prompt_text: str = "",
        rubric_text: str = "",
        metrics: dict[str, float] | None = None,
    ) -> ModelVersion:
        """Register a new model version.

        Args:
            version_id: Version identifier (e.g. "v1.0", "v2.1.3-beta",
                "model-2024-01"). Must match VERSION_ID_PATTERN.
        """
        if not VERSION_ID_PATTERN.match(version_id):
            raise ValueError(
                f"Invalid version_id '{version_id}': "
                f"must match semver (v1.0, v2.1.3) or identifier pattern"
            )
        if version_id in self._versions:
            raise ValueError(f"Version '{version_id}' already registered")

        configs = configs or {}
        version = ModelVersion(
            version_id=version_id,
            parent=parent,
            prompt_hash=_compute_hash(prompt_text) if prompt_text else "",
            rubric_hash=_compute_hash(rubric_text) if rubric_text else "",
            config_hash=_compute_hash(json.dumps(configs, sort_keys=True)),
            configs=configs,
            metrics=metrics or {},
        )
        with self._lock:
            self._versions[version_id] = version
            self._stats.registered += 1
            self._persist()
        log.info("Registered model version: %s", version_id)
        return version

    def promote(
        self,
        version_id: str,
        target_stage: PromotionStage,
        *,
        validation_fn: Callable[[ModelVersion], bool] | None = None,
    ) -> ModelVersion:
        """Promote a model version to a new stage."""
        with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise KeyError(f"Version '{version_id}' not found")

            valid = VALID_TRANSITIONS.get(version.stage, [])
            if target_stage not in valid:
                raise ValueError(
                    f"Invalid transition: {version.stage.value} → {target_stage.value}. "
                    f"Valid: {[s.value for s in valid]}"
                )

            # Optional validation gate (e.g., metric thresholds)
            if validation_fn is not None and not validation_fn(version):
                raise ValueError(
                    f"Validation gate failed for {version_id}: "
                    f"cannot promote to {target_stage.value}"
                )

            old_stage = version.stage
            version.stage = target_stage
            version.promoted_at = time.time()
            self._stats.promoted += 1
            self._persist()
        log.info("Promoted %s: %s → %s", version_id, old_stage.value, target_stage.value)

        if self._hooks:
            from geode.orchestration.hooks import HookEvent

            self._hooks.trigger(HookEvent.MODEL_PROMOTED, {
                "version_id": version_id,
                "stage": target_stage.value,
            })

        return version

    # Forward-only promotion path (for rollback)
    _PROMOTION_PATH = [
        PromotionStage.DEV,
        PromotionStage.STAGING,
        PromotionStage.CANARY,
        PromotionStage.PROD,
    ]

    def rollback(self, version_id: str) -> ModelVersion:
        """Rollback a version to its previous stage (one step back)."""
        with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise KeyError(f"Version '{version_id}' not found")

            current = version.stage
            try:
                idx = self._PROMOTION_PATH.index(current)
            except ValueError as exc:
                msg = f"Cannot rollback from {current.value} — not in promotion path"
                raise ValueError(msg) from exc

            if idx == 0:
                raise ValueError(f"Cannot rollback from {current.value} — no previous stage")

            previous = self._PROMOTION_PATH[idx - 1]

            version.stage = previous
            version.promoted_at = time.time()
            self._stats.rolled_back += 1
            self._persist()
        log.info("Rolled back %s: %s → %s", version_id, current.value, previous.value)
        return version

    def get_production(self) -> ModelVersion | None:
        """Get the current production model version (most recently promoted to PROD)."""
        with self._lock:
            prod_versions = [
                v for v in self._versions.values() if v.stage == PromotionStage.PROD
            ]
        if not prod_versions:
            return None
        return max(prod_versions, key=lambda v: v.promoted_at or 0.0)

    def get_version(self, version_id: str) -> ModelVersion | None:
        """Get a specific version by ID."""
        with self._lock:
            return self._versions.get(version_id)

    def list_versions(self, stage: PromotionStage | None = None) -> list[ModelVersion]:
        """List all versions, optionally filtered by stage."""
        with self._lock:
            versions = list(self._versions.values())
        if stage is not None:
            versions = [v for v in versions if v.stage == stage]
        return sorted(versions, key=lambda v: v.created_at)

    def _persist(self) -> None:
        """Write registry to disk if storage_dir is configured."""
        if not self._storage_dir:
            return
        self._stats.persisted += 1
        data = [v.to_dict() for v in self._versions.values()]
        registry_file = self._storage_dir / "registry.json"
        tmp = registry_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(registry_file))

    def _load_from_disk(self) -> None:
        """Load registry from disk."""
        if not self._storage_dir:
            return
        registry_file = self._storage_dir / "registry.json"
        if not registry_file.exists():
            return
        try:
            data = json.loads(registry_file.read_text(encoding="utf-8"))
            for d in data:
                self._versions[d["version_id"]] = ModelVersion.from_dict(d)
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("Failed to load model registry: %s", e)
