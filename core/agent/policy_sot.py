"""Policy SoT loading — the ONE strict/graceful JSON loader.

PR-LOOP-PRUNE (2026-06-13): seven policy modules (heuristics, style
guide, tool, reflection, decomposition, agent contracts, tool
descriptions) each carried a textually identical ``_strict_load`` /
``_graceful_load`` pair around their own validator+coercer — ~420 lines
of copy. One loader now owns the asymmetry contract:

* **strict** (audit-subprocess path, env-var-pinned SoT): any failure is
  a ``RuntimeError`` — spending audit quota on the wrong policy must
  fail fast.
* **graceful** (daily-run path, repo/operator SoT): unreadable or
  schema-invalid files WARN and return ``None`` — an everyday ``geode``
  call must not hard-fail on a corrupted self-improving-loop artifact.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.self_improving.loop.mutate.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

__all__ = ["load_policy_sot"]


def load_policy_sot(
    *,
    env_var: str,
    operator_local: Path,
    in_repo: Path,
    label: str,
    validate_strict: Callable[[Any, Path], None],
    validate_graceful: Callable[[Any, Path], None],
    coerce: Callable[[Any], Any],
) -> Any | None:
    """Resolve + load one policy SoT; returns the coerced policy or None."""
    selection = resolve_sot(env_var=env_var, operator_local=operator_local, in_repo=in_repo)
    if selection is None:
        return None
    path = selection.path
    if selection.strict:
        if not path.is_file():
            raise RuntimeError(f"{env_var}={path} file not found")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{env_var}={path} load failed: {exc}") from exc
        validate_strict(data, path)
        return coerce(data)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("%s SoT at %s is unreadable; ignoring", label, path)
        return None
    try:
        validate_graceful(data, path)
    except RuntimeError as exc:
        log.warning("%s SoT at %s schema invalid: %s; ignoring", label, path, exc)
        return None
    return coerce(data)
