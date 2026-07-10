"""Typed boundary implemented by executable-assay adapters."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol

from plugins.crucible.contract import ExperimentContract
from plugins.crucible.evidence import EvidenceEnvelope, ResourceUsage


class AssayAdapter(Protocol):
    """Normalize one assay without adding assay cases to promotion core."""

    @property
    def schema(self) -> str: ...

    def validate_config(self, config: Mapping[str, Any]) -> None: ...

    def normalize(
        self,
        contract: ExperimentContract,
        *,
        arm: Literal["baseline", "candidate"],
        results_path: Path,
        snapshot_path: Path,
        usage: ResourceUsage,
        checks_by_pair: Mapping[tuple[str, int], Mapping[str, bool]],
    ) -> EvidenceEnvelope: ...
