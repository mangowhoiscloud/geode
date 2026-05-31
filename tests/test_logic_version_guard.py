"""PR-BASELINE-EPOCH (2026-05-30) — logic-version guard.

The baseline epoch discriminator hashes ``FITNESS_FORMULA_VERSION`` /
``MARGIN_LOGIC_VERSION`` (deliberate semantic tags) instead of the function
source. That only works if the tags are bumped when the *meaning* changes — so
these tests pin a GOLDEN value per version. A silent change to ``compute_fitness``
or the ``_should_promote`` margin (without bumping the tag) moves the value and
FAILs here, forcing the bump + a new golden (which then opens a new epoch).

When you intentionally change the logic: bump the version constant in
``core/self_improving/train.py`` AND add the new golden below.
"""

from __future__ import annotations

from core.self_improving.train import (
    AXIS_TIERS,
    FITNESS_FORMULA_VERSION,
    MARGIN_LOGIC_VERSION,
    _should_promote,
    compute_fitness,
)

# --- Probe A: simple uniform — every dim at 3.0, zero stderr (plain weighted sum
# + stability=1/(1+0)). The minimal tripwire on the core dim aggregate.
_PROBE_DIM_MEANS = dict.fromkeys(AXIS_TIERS, 3.0)
_PROBE_DIM_STDERR = dict.fromkeys(AXIS_TIERS, 0.0)

# --- Probe B: RICH — distinct per-dim means (so weight redistribution moves the
# result), non-zero stderr (stability), mixed analytics/judge_llm modality
# (modality weighting), and admire (the DIM/ADMIRE 2-axis split). One probe can
# never cover every branch, but this exercises far more of compute_fitness than
# the uniform probe — a change to weights / modality / admire / stability that
# preserves the uniform value still moves THIS one. Construction is deterministic
# and must stay byte-identical to the golden below.
_SCORED_DIMS = sorted(d for d, t in AXIS_TIERS.items() if t in ("critical", "auxiliary"))
_RICH_DIM_MEANS = {d: 1.0 + (i % 5) * 0.5 for i, d in enumerate(_SCORED_DIMS)}
_RICH_DIM_STDERR = {d: 0.1 + (i % 3) * 0.05 for i, d in enumerate(_SCORED_DIMS)}
_RICH_MODALITY = {
    d: ("analytics" if i % 2 == 0 else "judge_llm") for i, d in enumerate(_SCORED_DIMS)
}
_RICH_ADMIRE = {"admirable": 7.0, "needs_attention": 3.0}

_GOLDEN_FITNESS = {"1": 0.73}
_GOLDEN_FITNESS_RICH = {"1": 0.6069}
_GOLDEN_MARGIN = {"1": 0.0141}  # 4dp of √(0.01² + 0.01²) for σ_prior=σ_current=0.01
_GOLDEN_MARGIN_FLOOR = {"1": 0.005}  # both σ=0 → √ term 0 → clamps to fitness_margin_floor


def test_fitness_formula_version_golden() -> None:
    got = round(compute_fitness(_PROBE_DIM_MEANS, _PROBE_DIM_STDERR), 4)
    expected = _GOLDEN_FITNESS.get(FITNESS_FORMULA_VERSION)
    assert expected is not None, (
        f"no golden fitness for FITNESS_FORMULA_VERSION={FITNESS_FORMULA_VERSION!r} — "
        "add one if you intentionally bumped the version"
    )
    assert got == expected, (
        f"compute_fitness probe moved ({got} != golden {expected}) under "
        f"FITNESS_FORMULA_VERSION={FITNESS_FORMULA_VERSION!r}. The fitness formula "
        "changed: bump FITNESS_FORMULA_VERSION + add the new golden (a new baseline "
        "epoch starts)."
    )


def test_fitness_formula_version_golden_rich() -> None:
    """Wider tripwire: exercises weights / modality / admire / stability so a
    semantic change that leaves the uniform probe untouched still trips here."""
    got = round(
        compute_fitness(
            _RICH_DIM_MEANS,
            _RICH_DIM_STDERR,
            admire_means=_RICH_ADMIRE,
            measurement_modality=_RICH_MODALITY,
        ),
        4,
    )
    expected = _GOLDEN_FITNESS_RICH.get(FITNESS_FORMULA_VERSION)
    assert expected is not None, (
        f"no rich golden for FITNESS_FORMULA_VERSION={FITNESS_FORMULA_VERSION!r}"
    )
    assert got == expected, (
        f"rich compute_fitness probe moved ({got} != golden {expected}) under "
        f"FITNESS_FORMULA_VERSION={FITNESS_FORMULA_VERSION!r} — a weights/modality/"
        "admire/stability change: bump FITNESS_FORMULA_VERSION + add the new golden."
    )


def _margin_of(reason: str) -> float:
    return round(float(reason.split("margin ")[-1].split()[0]), 4)


def test_margin_logic_version_golden() -> None:
    # √-branch: explicit per-side fitness-stderr (no bootstrap), same baseline as
    # current so the gain is 0 and only the margin formula is exercised.
    _ok, reason = _should_promote(
        _PROBE_DIM_MEANS,
        _PROBE_DIM_STDERR,
        _PROBE_DIM_MEANS,
        _PROBE_DIM_STDERR,
        baseline_fitness_stderr=0.01,
        current_fitness_stderr=0.01,
    )
    expected = _GOLDEN_MARGIN.get(MARGIN_LOGIC_VERSION)
    assert expected is not None, (
        f"no golden margin for MARGIN_LOGIC_VERSION={MARGIN_LOGIC_VERSION!r}"
    )
    assert _margin_of(reason) == expected, (
        f"promote margin moved ({_margin_of(reason)} != golden {expected}) under "
        f"MARGIN_LOGIC_VERSION={MARGIN_LOGIC_VERSION!r}. The margin rule changed: "
        "bump MARGIN_LOGIC_VERSION + add the new golden."
    )


def test_margin_logic_version_golden_floor() -> None:
    """Floor branch: both fitness-stderr = 0 → the √ gain-stderr term is 0, so the
    margin must clamp to fitness_margin_floor. Catches a change to the floor clamp
    that the σ>0 √-branch test would miss."""
    _ok, reason = _should_promote(
        _PROBE_DIM_MEANS,
        _PROBE_DIM_STDERR,
        _PROBE_DIM_MEANS,
        _PROBE_DIM_STDERR,
        baseline_fitness_stderr=0.0,
        current_fitness_stderr=0.0,
    )
    expected = _GOLDEN_MARGIN_FLOOR.get(MARGIN_LOGIC_VERSION)
    assert expected is not None, (
        f"no floor golden for MARGIN_LOGIC_VERSION={MARGIN_LOGIC_VERSION!r}"
    )
    assert _margin_of(reason) == expected, (
        f"promote margin floor moved ({_margin_of(reason)} != golden {expected}) "
        f"under MARGIN_LOGIC_VERSION={MARGIN_LOGIC_VERSION!r}: bump + add new golden."
    )
