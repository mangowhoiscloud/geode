"""PR-L7 (2026-05-26) — wrapper-sections fallback ↔ writer-schema drift invariants.

Pattern source: PR-MINIMAL-2 #1398 — `_FALLBACK_SYSTEM_PROMPT` ↔ `program.md`
shared-anchor invariant. Same dual-SoT shape risk applies here:

- ``core/self_improving/train.py:_WRAPPER_PROMPT_SECTIONS_FALLBACK`` — bootstrap
  default loaded when ``state/autoresearch/policies/wrapper-sections.json``
  (canonical, mutator-written runtime SoT) is absent.
- ``core/self_improving/train.py:write_wrapper_prompt_sections`` — validator the
  mutator goes through when promoting a wrapper-prompt mutation.

A future PR could:

- Change one validator constraint (e.g. add a per-section length minimum)
  without updating the fallback to satisfy it → daily fresh checkouts ship
  a fallback the writer would refuse, but the loader's read path stays
  silent.
- Edit the fallback dict and drop a section key the rest of the codebase
  relies on (e.g. seed-generation evolver assumes ``role``).

This file pins:

1. **fallback ↔ writer schema parity** — every fallback section value
   satisfies ``write_wrapper_prompt_sections``'s validator without raising.
2. **fallback shape invariant** — non-empty dict, ≥ 5 sections, every
   key + value is a non-empty string.
3. **canonical 5-section anchor** — the 5 documented intent buckets
   (``role`` / ``tool_result_handling`` / ``shell_caution`` /
   ``refusal_policy`` / ``thinking_visibility``) stay present so a
   careless rename breaks here, not silently at runtime.
4. **loader bootstrap path** — with the canonical SoT absent,
   ``load_wrapper_prompt_sections`` returns a copy of the fallback
   (defence against operator deleting the disk SoT mid-cycle).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.self_improving import train as auto_train
from core.self_improving.train import (
    _WRAPPER_PROMPT_SECTIONS_FALLBACK,
    load_wrapper_prompt_sections,
    write_wrapper_prompt_sections,
)

# The 5 documented bootstrap section anchors. These are not "required by
# every consumer" — `core/agent/system_prompt.py` only validates
# ``dict[str, str]`` and joins values, and the mutator accepts arbitrary
# new ``target_section`` strings. The anchors are a drift ratchet: a
# careless PR dropping one of these keys from the fallback dict trips
# here, forcing a conscious update of this tuple AND a sweep of any
# documentation / runbook that depends on the legacy 5-section layout.
_CANONICAL_SECTION_KEYS: tuple[str, ...] = (
    "role",
    "tool_result_handling",
    "shell_caution",
    "refusal_policy",
    "thinking_visibility",
)


def test_fallback_satisfies_writer_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback dict must round-trip through ``write_wrapper_prompt_sections``
    without raising. A future tightening of the writer's validation that
    breaks the fallback would land here first."""
    target = tmp_path / "wrapper-sections.json"
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", target)
    write_wrapper_prompt_sections(_WRAPPER_PROMPT_SECTIONS_FALLBACK)
    # Roundtrip readback to verify the writer accepted the payload.
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == _WRAPPER_PROMPT_SECTIONS_FALLBACK


def test_fallback_is_non_empty_str_dict() -> None:
    """Fallback shape: non-empty dict, every key + value is a non-empty
    string. Mirrors the writer's validation invariants so the loader
    bootstrap path is always safe."""
    assert isinstance(_WRAPPER_PROMPT_SECTIONS_FALLBACK, dict)
    assert _WRAPPER_PROMPT_SECTIONS_FALLBACK, "fallback must not be empty"
    for key, value in _WRAPPER_PROMPT_SECTIONS_FALLBACK.items():
        assert isinstance(key, str) and key, f"non-string or empty key: {key!r}"
        assert isinstance(value, str) and value.strip(), (
            f"non-string or empty value at {key!r}: {value!r}"
        )


def test_fallback_contains_canonical_section_keys() -> None:
    """The 5 canonical bootstrap anchors stay present. These are
    NOT required by every consumer (``core.agent.system_prompt``
    accepts any ``dict[str, str]``); they are documented intent
    buckets that the operator-facing docs + the fallback dict have
    grown around. Dropping or renaming one here forces a conscious
    update of ``_CANONICAL_SECTION_KEYS`` + a sweep of docs/runbooks
    that reference the legacy layout."""
    fallback_keys = set(_WRAPPER_PROMPT_SECTIONS_FALLBACK)
    missing = set(_CANONICAL_SECTION_KEYS) - fallback_keys
    assert not missing, (
        f"fallback dropped canonical section(s): {sorted(missing)}. "
        "Either restore the key(s) or update _CANONICAL_SECTION_KEYS "
        "after auditing all wrapper-section consumers."
    )


def test_load_returns_fallback_copy_when_canonical_sot_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader must return the fallback (not None / not empty) when the
    canonical disk SoT is missing. Defends the loop against operator
    accidentally deleting ``state/autoresearch/policies/wrapper-sections.json``
    mid-cycle."""
    missing = tmp_path / "definitely-not-there.json"
    assert not missing.exists()
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", missing)
    result = load_wrapper_prompt_sections()
    assert result == _WRAPPER_PROMPT_SECTIONS_FALLBACK
    # Must be a copy — loader's docstring says callers may mutate.
    assert result is not _WRAPPER_PROMPT_SECTIONS_FALLBACK


def test_load_returns_fallback_copy_when_canonical_sot_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader must return the fallback (not raise) when the canonical
    SoT exists but is malformed JSON. ``load_wrapper_prompt_sections``
    docstring guarantees the autoresearch loop never crashes on a bad
    on-disk patch."""
    bad = tmp_path / "wrapper-sections.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", bad)
    result = load_wrapper_prompt_sections()
    assert result == _WRAPPER_PROMPT_SECTIONS_FALLBACK
    # Codex MCP review catch — equality alone passes even if the loader
    # returned the module dict itself, leaving the caller free to mutate
    # the shared fallback. Pin "copy, not identity" so mutation safety
    # is enforced symmetric to the absent-SoT test above.
    assert result is not _WRAPPER_PROMPT_SECTIONS_FALLBACK
