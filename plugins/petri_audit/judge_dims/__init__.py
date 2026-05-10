"""Named judge-dimension sets for the petri audit.

Inspect-petri's ``audit_judge`` scores 36 default alignment dimensions.
For GEODE we keep five operational axes (behaviour control, tool
calling, robustness, time efficiency, plus three P3-b alignment
surfaces) — 17 dimensions instead of 36. Smaller surface = smaller
judge prompt = lower judge token cost (the judge scores every dim
in one structured-answer call, so unused dims still cost tokens).

Resolution rules for ``--dim-set <value>``:

- ``"5axes"`` (default) → ``geode_5axes.yaml`` in this directory.
- ``"full"`` / ``"default"`` → ``None`` (inspect-petri's bundled 36).
- Any other value → treated as a filesystem path; the caller passes
  it to ``inspect eval -T judge_dimensions=<value>`` unchanged so a
  user can drop a custom YAML anywhere on disk.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["BUILTIN_DIM_SETS", "DEFAULT_DIM_SET", "resolve_dim_set"]

DEFAULT_DIM_SET: str = "5axes"

_HERE = Path(__file__).parent

#: Names that resolve to a YAML inside this package. Keep alphabetical
#: so additions stay easy to scan. Each YAML must contain a flat list
#: of dimension names that are a subset of inspect-petri's default 36.
BUILTIN_DIM_SETS: dict[str, Path] = {
    "5axes": _HERE / "geode_5axes.yaml",
}

#: Names that explicitly opt out of dim pruning — the cmd is built
#: without ``-T judge_dimensions=...`` and inspect-petri uses its
#: built-in 36.
_FULL_ALIASES = frozenset({"full", "default", "all"})


def resolve_dim_set(value: str | None) -> Path | str | None:
    """Map a CLI ``--dim-set`` value to a path / passthrough / None.

    Returns:
        - ``Path`` when ``value`` names a built-in YAML set.
        - ``None`` when ``value`` is ``None`` / ``"full"`` / ``"default"`` /
          ``"all"`` — caller must omit the ``-T judge_dimensions`` flag.
        - ``str`` (the unchanged value) when it looks like a path /
          dir / yaml the user supplied — caller passes it through.

    The "passthrough" branch deliberately does no existence check:
    inspect-petri produces a much clearer error than a duplicate
    "file not found" raised at flag-build time, and a missing path
    is a user mistake worth surfacing at the audit boundary.
    """
    if value is None or value.lower() in _FULL_ALIASES:
        return None
    if value in BUILTIN_DIM_SETS:
        return BUILTIN_DIM_SETS[value]
    return value
