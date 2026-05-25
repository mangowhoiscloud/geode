"""PR-L7 (2026-05-26) — wrapper-sections fallback ↔ writer-schema drift invariants.

Pattern source: PR-MINIMAL-2 #1398 — `_FALLBACK_SYSTEM_PROMPT` ↔ `program.md`
shared-anchor invariant. Same dual-SoT shape risk applies here:

- ``autoresearch/train.py:_WRAPPER_PROMPT_SECTIONS_FALLBACK`` — bootstrap
  default loaded when ``autoresearch/state/policies/wrapper-sections.json``
  (canonical, mutator-written runtime SoT) is absent.
- ``autoresearch/train.py:write_wrapper_prompt_sections`` — validator the
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
from autoresearch.train import (
    _WRAPPER_PROMPT_SECTIONS_FALLBACK,
    load_wrapper_prompt_sections,
    write_wrapper_prompt_sections,
)

from autoresearch import train as auto_train

# The 5 documented intent buckets. Renaming any of these requires updating
# this list AND auditing every consumer (core/agent/system_prompt.py
# reader, seed-generation evolver scenario_realism handoff, etc.).
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
    """Renaming or dropping any of the 5 canonical section buckets is a
    breaking change for the wrapper-prompt mutation surface — the
    seed-generation evolver and the daily ``geode`` runtime both
    consume these keys. Adding new keys is fine; removing or renaming
    requires updating ``_CANONICAL_SECTION_KEYS`` here + auditing
    every consumer in the same PR."""
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
    accidentally deleting ``autoresearch/state/policies/wrapper-sections.json``
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
