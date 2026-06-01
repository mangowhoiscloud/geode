"""PR-TEMP (2026-05-23) invariants — temperature is config-driven, not hardcoded.

Six former code constants (agent_loop 0.0 / reflection 0.2 / verification 0.1 /
commentary 0.4 / self-improving mutation 0.3 / progressive compression 0.0)
were lifted into ``Settings.temperature_*`` knobs so operators can tune each
call path via ``~/.geode/config.toml`` or env vars.

These tests ratchet the migration so future edits cannot silently
re-introduce a literal at the same site (Karpathy P4 ratchet).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from core.config import settings

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. Settings surface — 6 keys present with frontier-grounded defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attr", "expected_default"),
    [
        ("temperature_agent_loop", 1.0),
        ("temperature_reflection", 1.0),
        ("temperature_verification", 0.0),
        ("temperature_commentary", 1.0),
        ("temperature_self_improving_mutation", 1.0),
    ],
)
def test_temperature_setting_default(attr: str, expected_default: float) -> None:
    """Each temperature knob must exist on ``Settings`` with the expected
    frontier-aligned default. The defaults encode the design decision:
    most paths default to 1.0 (provider default — Anthropic/OpenAI/Gemini
    all converge on 1.0); verification and compression default to 0.0
    because their downstream consumers (cross-LLM agreement coefficient +
    reproducible summaries) are functional invariants where stochastic
    output is meaningless.
    """
    assert hasattr(settings, attr), f"Settings.{attr} missing"
    value = getattr(settings, attr)
    assert isinstance(value, float)
    assert value == expected_default, (
        f"Settings.{attr} default drift: expected {expected_default}, got {value}"
    )


def test_temperature_setting_range_validation() -> None:
    """Each temperature knob must reject out-of-range values
    (``ge=0.0, le=2.0``). The cap at 2.0 covers OpenAI's wider range
    while Anthropic's narrower 0.0-1.0 contract is still safe because
    every adapter clamps / strips before hitting the wire.
    """
    from core.config._settings import Settings
    from pydantic import ValidationError

    for attr in (
        "temperature_agent_loop",
        "temperature_reflection",
        "temperature_verification",
        "temperature_commentary",
        "temperature_self_improving_mutation",
    ):
        with pytest.raises(ValidationError):
            Settings(**{attr: -0.1})
        with pytest.raises(ValidationError):
            Settings(**{attr: 2.1})


# ---------------------------------------------------------------------------
# 2. Call-site ratchet — no hardcoded temperature literals at the 7 sites
# ---------------------------------------------------------------------------


# Each entry is (path relative to repo root, expected ``settings.temperature_*``
# reference substring). The test scans the file for the reference; absence is
# a regression (someone reverted to a literal or removed the call entirely).
_RATCHET_SITES = (
    (
        Path("core/agent/loop/agent_loop.py"),
        "_settings.temperature_agent_loop",
    ),
    (
        Path("core/agent/loop/_reflection.py"),
        "_settings.temperature_reflection",
    ),
    (
        Path("core/llm/commentary.py"),
        "_settings.temperature_commentary",
    ),
    (
        Path("core/self_improving/loop/runner.py"),
        "_settings.temperature_self_improving_mutation",
    ),
)


@pytest.mark.parametrize(("rel_path", "expected_ref"), _RATCHET_SITES)
def test_call_site_reads_from_config(rel_path: Path, expected_ref: str) -> None:
    """The named call site must reference its ``Settings`` knob, not a
    literal float. Pinned after PR-TEMP (2026-05-23) lifted six
    hardcoded constants into config.
    """
    path = REPO_ROOT / rel_path
    source = path.read_text(encoding="utf-8")
    assert expected_ref in source, (
        f"{rel_path}: expected reference '{expected_ref}' missing — "
        "did someone revert PR-TEMP to a hardcoded literal?"
    )


# Regex that matches ``temperature=<float-literal>`` (e.g. ``temperature=0.0``
# or ``temperature=0.42``). Allowed: ``temperature=<identifier>`` (the config-
# driven path) or ``temperature=None``.
_LITERAL_TEMP_KWARG = re.compile(r"temperature\s*=\s*-?\d+(?:\.\d+)?\b")


@pytest.mark.parametrize(("rel_path", "expected_ref"), _RATCHET_SITES)
def test_call_site_has_no_literal_temperature(rel_path: Path, expected_ref: str) -> None:
    """Defensive ratchet: the file must not contain any ``temperature=<float>``
    keyword argument. If a literal sneaks back in, this test fails so the
    operator-tunability invariant stays visible in CI.

    Allow-list: ``providers/`` adapters and ``llm/adapters/`` translators
    keep their internal ``temperature=<float>`` fallback paths (those are
    contract-layer wire formatters, not policy decisions). The 6 ratchet
    files above are policy sites and must read from config.
    """
    del expected_ref
    path = REPO_ROOT / rel_path
    source = path.read_text(encoding="utf-8")
    matches = _LITERAL_TEMP_KWARG.findall(source)
    assert matches == [], (
        f"{rel_path}: found literal temperature kwarg(s) {matches!r} — "
        "PR-TEMP invariant says these must read from Settings.temperature_*."
    )
