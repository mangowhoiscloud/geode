"""C.8 (2026-05-25) — silent fallback STRICT mode parity invariants (PR-28).

Memory ``project_autoresearch_fragmentation_audit.md`` F5 — silent fallback
은 ``evolve/scaffold_search/train.py:838-873`` 의 ``_STRICT=1`` 강제 + ``sot_resolution.
resolve_sot`` 의 strict flag 분기로 이미 해소 (ADR-012 S0a/S0b). 본 file
은 그 fix 의 **drift invariant pin** — 12 kind 의 STRICT env naming 이
지속적으로 sot_resolution 의 derivation (``<X>_OVERRIDE → <X>_STRICT``)
과 일치하는지 fail-fast.

drift 사례 (예방):
- train.py 가 ``GEODE_TOOL_POLICY_OVERRIDE`` set 하는데 STRICT 누락 → audit 의
  silent fallback 복귀
- sot_resolution 가 다른 STRICT suffix (예: ``_FAIL_FAST``) 로 rename →
  train.py 와 desync

12 kind 의 invariant:
- 모든 GEODE_<X>_OVERRIDE env 가 set 됐을 때 STRICT 도 함께 set
- STRICT suffix 가 sot_resolution 의 _OVERRIDE → _STRICT derivation 과
  일치
"""

from __future__ import annotations

import inspect
import re

# 12 kind enumerated in evolve/scaffold_search/train.py — must stay in sync
# with that file's env-emit block.
#
# Override pattern is intentionally RHS-agnostic: matches
# ``env["GEODE_<X>_OVERRIDE"] = …`` *regardless* of what is on the right
# (str(Path), helper call, local variable). A future kind that swaps
# ``GLOBAL_<X>_PATH`` for a different path expression must still pair
# with STRICT — drift detection should not be subverted by a cosmetic
# RHS rename.
_TRAIN_PY_STRICT_ENV_PATTERN = re.compile(r'env\["GEODE_([A-Z_]+)_STRICT"\]\s*=\s*"1"')
_TRAIN_PY_OVERRIDE_ENV_PATTERN = re.compile(r'env\["GEODE_([A-Z_]+)_OVERRIDE"\]\s*=')

# Overrides that are NOT mutation-surface SoTs (do not flow through
# resolve_sot). These have their own consumers and strict-mode contracts.
#
# - ``WRAPPER``: ``GEODE_WRAPPER_OVERRIDE`` is consumed by
#   ``core/agent/system_prompt.WRAPPER_OVERRIDE_HOOK_READY`` to override
#   the wrapper system prompt during the audit subprocess. It is gated
#   by the hook-ready flag in train.py:791-794, which is the strict-
#   equivalent (audit raises if the hook is unwired) — no separate
#   STRICT env is needed because there is no graceful fall-through.
_NON_MUTATION_SURFACE_OVERRIDES: frozenset[str] = frozenset({"WRAPPER"})


def _read_train_py_env_block() -> str:
    # S-5 (2026-06-11) — the audit env block moved to measure.py.
    from evolve.scaffold_search import measure

    return inspect.getsource(measure)


def test_train_py_overrides_paired_with_strict() -> None:
    """Every ``GEODE_<X>_OVERRIDE`` env set in train.py must be paired
    with a ``GEODE_<X>_STRICT=1`` set on the same kind."""
    source = _read_train_py_env_block()
    overrides = set(_TRAIN_PY_OVERRIDE_ENV_PATTERN.findall(source))
    stricts = set(_TRAIN_PY_STRICT_ENV_PATTERN.findall(source))
    mutation_surface_overrides = overrides - _NON_MUTATION_SURFACE_OVERRIDES
    missing_strict = mutation_surface_overrides - stricts
    assert not missing_strict, (
        f"Override-without-STRICT drift: {missing_strict} — audit subprocess "
        "would silent-fallback. Add GEODE_<X>_STRICT=1 alongside the override, "
        "or document the override as non-mutation-surface in "
        "_NON_MUTATION_SURFACE_OVERRIDES."
    )


def test_override_pattern_catches_non_global_path_rhs() -> None:
    """Regression — pairing invariant must not be subverted by a future
    kind that uses a different RHS shape (helper call, Path(...) literal,
    local variable). Synthetic source with an override using a non-
    ``GLOBAL_<X>_PATH`` RHS must still register as an override."""
    synthetic = 'env["GEODE_FUTURE_KIND_OVERRIDE"] = some_helper(path)\n'
    matches = set(_TRAIN_PY_OVERRIDE_ENV_PATTERN.findall(synthetic))
    assert "FUTURE_KIND" in matches, (
        "Override pattern is too narrow — a future kind with a non-"
        "GLOBAL_<X>_PATH RHS would evade pairing detection while "
        "the >=12 strict count floor keeps passing."
    )


def test_train_py_strict_count_at_least_12_kinds() -> None:
    """ADR-012 S0a/S0b — 12 kind 의 STRICT 강제. drift 시 count 감소."""
    source = _read_train_py_env_block()
    strict_kinds = set(_TRAIN_PY_STRICT_ENV_PATTERN.findall(source))
    assert len(strict_kinds) >= 12, (
        f"Expected >=12 STRICT kinds (ADR-012 S0a/S0b), found {len(strict_kinds)}: "
        f"{sorted(strict_kinds)}"
    )


def test_sot_resolution_strict_derivation_pattern() -> None:
    """중립 source selector 가 ``<X>_OVERRIDE → <X>_STRICT`` 패턴을
    유지 — train.py 의 env naming 과 일치."""
    from core.config import policy_source

    source = inspect.getsource(policy_source)
    assert "_OVERRIDE_SUFFIX" in source
    assert "_STRICT_SUFFIX" in source
    assert "removesuffix(_OVERRIDE_SUFFIX) + _STRICT_SUFFIX" in source
