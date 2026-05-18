"""4-path × N-component auth coverage matrix.

Defines the canonical matrix the GEODE seed-pipeline sprint must keep
green: every component (seed-pipeline, petri_audit, autoresearch,
GEODE main) must be reachable via every supported auth path
(``anthropic.claude-cli``, ``anthropic.api_key``,
``openai.openai-codex``, ``openai.api_key``).

The matrix is the **single source of truth** for which (component,
family, source) cells the system claims to support. Tests in
``tests/integration/test_auth_path_coverage.py`` walk every cell and
verify the routing is actually wired.

Why a separate module: the matrix is queried by both tests and the
operator-facing ``auth_status_table()`` formatter, so it needs to
live somewhere both can import without circulars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "AUTH_COVERAGE_MATRIX",
    "TEST_SETUP_PROFILE",
    "AuthCell",
    "Component",
    "Path",
    "auth_status_table",
]


Component = Literal["seed_pipeline", "petri_audit", "autoresearch", "geode_main"]
Family = Literal["anthropic", "openai"]
Source = Literal["claude-cli", "openai-codex", "api_key"]


@dataclass(frozen=True)
class Path:
    """One auth path — (family, source) pair."""

    family: Family
    source: Source

    def __str__(self) -> str:
        return f"{self.family}.{self.source}"


@dataclass(frozen=True)
class AuthCell:
    """One cell in the coverage matrix — (component, path) tuple."""

    component: Component
    path: Path
    supported: bool
    notes: str = ""


_PATHS: tuple[Path, ...] = (
    Path("anthropic", "claude-cli"),
    Path("anthropic", "api_key"),
    Path("openai", "openai-codex"),
    Path("openai", "api_key"),
)


_COMPONENTS: tuple[Component, ...] = (
    "seed_pipeline",
    "petri_audit",
    "autoresearch",
    "geode_main",
)


def _build_matrix() -> tuple[AuthCell, ...]:
    """Build the canonical 4×4 cell list.

    All 16 cells currently expected to be supported — the seed-pipeline
    sprint settled on a uniform 4-path matrix. A cell is set
    ``supported=False`` only when the component has a documented
    structural reason it cannot reach the path (e.g., a future
    embeddings-only component that has no Anthropic surface).
    """
    cells: list[AuthCell] = []
    for component in _COMPONENTS:
        for path in _PATHS:
            cells.append(
                AuthCell(
                    component=component,
                    path=path,
                    supported=True,
                    notes="",
                )
            )
    return tuple(cells)


AUTH_COVERAGE_MATRIX: tuple[AuthCell, ...] = _build_matrix()


# Profile used by the 2026-05-18 test setup the user specified. Pinned
# here so the integration test that exercises "all 4 components in
# their target test paths" stays self-documenting.
TEST_SETUP_PROFILE: dict[Component, Path] = {
    "seed_pipeline": Path("openai", "openai-codex"),  # gpt-5.5 subscription
    "petri_audit": Path("anthropic", "claude-cli"),
    "autoresearch": Path("openai", "openai-codex"),  # gpt-5.5 subscription
    "geode_main": Path("openai", "openai-codex"),  # gpt-5.5 subscription
}


def auth_status_table(probe_resolved_path: dict[Component, Path] | None = None) -> str:
    """Render the matrix as a plain-text table for operator inspection.

    ``probe_resolved_path``, if given, overlays the actual resolved
    binding per component (typically from a live ``pick_bindings()`` /
    settings probe) so the operator can see canonical-vs-actual. When
    omitted, only the canonical support flags are printed.
    """
    lines = ["seed-pipeline auth coverage matrix (4 path × 4 component)"]
    lines.append("")
    header = f"  {'component':<15}  {'anth.cli':<9} {'anth.api':<9} {'oai.cdx':<9} {'oai.api':<9}"
    lines.append(header)
    lines.append("  " + "─" * (len(header) - 2))
    by_component: dict[Component, dict[str, bool]] = {}
    for cell in AUTH_COVERAGE_MATRIX:
        by_component.setdefault(cell.component, {})[str(cell.path)] = cell.supported
    for component in _COMPONENTS:
        row = f"  {component:<15}"
        for path in _PATHS:
            supported = by_component[component][str(path)]
            mark = "OK " if supported else " - "
            row += f" {mark:<9}"
        lines.append(row)
    if probe_resolved_path:
        lines.append("")
        lines.append("  resolved (live):")
        for component, path in probe_resolved_path.items():
            lines.append(f"    {component:<15} → {path}")
    return "\n".join(lines)
