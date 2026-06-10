"""E5 (2026-05-30) — reproducibility pins on the per-cycle ledger rows.

Each ledger row must be INDEPENDENTLY RE-RUNNABLE: a third party should be able to
reconstruct exactly what produced an audit result. E5 adds four pins to BOTH
sinks — the ``mutations.jsonl`` attribution row and the ``baseline_archive.jsonl``
registry row:

  1. ``prompt_hash``    — sha256 of the actual composed wrapper system prompt
     (stable for the same prompt, changes when the prompt changes).
  2. ``applied_diff``   — sha256 of the applied mutation's content + its
     target_section / target_kind.
  3. ``sampling_params``— the generation params as SENT for the audit.
  4. ``rng_seed``       — the audit/generation seed as SENT (None when none sent).

These record WHAT WAS SENT for AUDITABILITY — NO backend-determinism claim. The
pure pin functions are pinned here; the WIRING (the bundle flows into both sinks)
follows the E2/E4 ``inspect.getsource`` static-guard convention; backward-compat
+ graceful casts close the set.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.self_improving import ledger, measure
from core.self_improving import train as auto_train
from core.self_improving.loop.observe.run_provenance import (
    SAMPLING_UNPINNED,
    RunProvenanceFields,
    build_run_provenance,
    compose_wrapper_prompt,
    hash_text,
)

# --- pure pins: prompt_hash stability + sensitivity ---------------------------


def test_hash_text_none_is_none() -> None:
    """Graceful contract: a missing prompt → None (the pin is omitted, no crash)."""
    assert hash_text(None) is None


def test_hash_text_is_prefixed_sha256_and_stable() -> None:
    a = hash_text("the wrapper system prompt")
    b = hash_text("the wrapper system prompt")
    assert a is not None and a.startswith("sha256:")
    assert a == b  # stable for the same input


def test_hash_text_changes_when_text_changes() -> None:
    assert hash_text("prompt A") != hash_text("prompt B")


def test_hash_text_coerces_non_str_gracefully() -> None:
    """A non-str that isn't None must not raise at the cast boundary."""
    assert hash_text({"unexpected": "dict"}) is not None  # str()-coerced, stable shape


def test_compose_wrapper_prompt_is_order_independent_but_content_sensitive() -> None:
    """prompt_hash must be STABLE for the same logical prompt (insertion order does
    not matter) and SENSITIVE to any section edit."""
    p1 = compose_wrapper_prompt({"a": "alpha", "b": "beta"})
    p2 = compose_wrapper_prompt({"b": "beta", "a": "alpha"})  # reordered
    assert p1 == p2  # sort_keys → order-independent
    assert hash_text(p1) == hash_text(p2)
    # an edit to any section flips the composed string (→ the hash)
    p3 = compose_wrapper_prompt({"a": "alpha", "b": "BETA-edited"})
    assert hash_text(p3) != hash_text(p1)


def test_compose_wrapper_prompt_empty_is_none() -> None:
    assert compose_wrapper_prompt(None) is None
    assert compose_wrapper_prompt({}) is None


def test_compose_wrapper_prompt_coerces_non_str_values() -> None:
    """A non-str section value must not raise — it is str-coerced at the boundary."""
    composed = compose_wrapper_prompt({"section": 123})
    assert composed is not None and "123" in composed


# --- build_run_provenance: capture WHAT WAS SENT -----------------------------


def test_build_run_provenance_full_cycle() -> None:
    fields = build_run_provenance(
        wrapper_sections={"role": "you are an agent"},
        applied_target_section="tool.web_search.description",
        applied_new_value="search the web carefully",
        applied_target_kind="tool_policy",
        sampling_params={"max_turns": 12, "temperature": SAMPLING_UNPINNED},
        rng_seed=None,
    )
    assert fields.prompt_hash is not None and fields.prompt_hash.startswith("sha256:")
    assert fields.applied_diff_hash == hash_text("search the web carefully")
    assert fields.applied_diff_target == "tool.web_search.description"
    assert fields.applied_diff_kind == "tool_policy"
    assert fields.sampling_params == {"max_turns": 12, "temperature": SAMPLING_UNPINNED}
    assert fields.rng_seed is None  # honest: no seed sent


def test_build_run_provenance_no_applied_diff_omits_target_and_kind() -> None:
    """A manual / no-mutation cycle (no applied new_value) → diff pins are all None,
    so the target / kind are not recorded against a phantom diff."""
    fields = build_run_provenance(
        wrapper_sections={"role": "agent"},
        applied_target_section=None,
        applied_new_value=None,
        applied_target_kind=None,
    )
    assert fields.applied_diff_hash is None
    assert fields.applied_diff_target is None
    assert fields.applied_diff_kind is None
    # the prompt pin is still captured
    assert fields.prompt_hash is not None


def test_build_run_provenance_target_without_value_is_dropped() -> None:
    """Graceful: a target_section with NO new_value cannot reference a real diff →
    the target/kind are dropped (no orphan reference)."""
    fields = build_run_provenance(
        applied_target_section="tool.x.description",
        applied_new_value=None,
        applied_target_kind="tool_policy",
    )
    assert fields.applied_diff_hash is None
    assert fields.applied_diff_target is None
    assert fields.applied_diff_kind is None


def test_as_record_kwargs_omits_none_pins() -> None:
    """A cycle with NO pins → empty kwargs (the row keeps its exact legacy shape)."""
    assert RunProvenanceFields().as_record_kwargs() == {}


def test_as_record_kwargs_includes_only_present_pins() -> None:
    out = RunProvenanceFields(
        prompt_hash="sha256:abc",
        applied_diff_hash="sha256:def",
        applied_diff_target="sec",
        applied_diff_kind="prompt",
        sampling_params={"max_turns": 8},
        rng_seed=7,
    ).as_record_kwargs()
    assert out == {
        "prompt_hash": "sha256:abc",
        "applied_diff_hash": "sha256:def",
        "applied_diff_target": "sec",
        "applied_diff_kind": "prompt",
        "sampling_params": {"max_turns": 8},
        "rng_seed": 7,
    }


# --- attribution row: pins recorded + backward-compatible --------------------


def test_attribution_carries_e5_pins() -> None:
    from core.self_improving.loop.observe.attribution import compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        run_provenance=RunProvenanceFields(
            prompt_hash=hash_text("the prompt"),
            applied_diff_hash=hash_text("the diff"),
            applied_diff_target="role",
            applied_diff_kind="prompt",
            sampling_params={"max_turns": 12, "temperature": SAMPLING_UNPINNED},
            rng_seed=None,  # honest: no seed sent
        ),
    )
    assert payload["prompt_hash"] == hash_text("the prompt")
    assert payload["applied_diff_hash"] == hash_text("the diff")
    assert payload["applied_diff_target"] == "role"
    assert payload["applied_diff_kind"] == "prompt"
    assert payload["sampling_params"]["temperature"] == SAMPLING_UNPINNED
    # rng_seed None → omitted (honest, not a fabricated 0)
    assert "rng_seed" not in payload


def test_attribution_prompt_hash_changes_when_prompt_changes() -> None:
    """The recorded prompt_hash is sensitive to the actual prompt sent."""
    from core.self_improving.loop.observe.attribution import compute_attribution

    def _hash_in_row(prompt: str) -> str:
        return compute_attribution(
            mutation_id="m",
            expected_dim={},
            baseline_before=None,
            baseline_after=None,
            run_provenance=build_run_provenance(wrapper_sections={"role": prompt}),
        )["prompt_hash"]

    assert _hash_in_row("prompt A") != _hash_in_row("prompt B")
    assert _hash_in_row("prompt A") == _hash_in_row("prompt A")


def test_attribution_legacy_omits_all_e5_pins() -> None:
    """A pre-E5 caller (no run_provenance) omits every E5 pin → exact legacy shape,
    and the schema validates the bare payload (pins default to None)."""
    from core.self_improving.loop.observe.attribution import AttributionRecord, compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
    )
    for key in (
        "prompt_hash",
        "applied_diff_hash",
        "applied_diff_target",
        "applied_diff_kind",
        "sampling_params",
        "rng_seed",
    ):
        assert key not in payload
    record = AttributionRecord.model_validate(payload)
    assert record.prompt_hash is None
    assert record.applied_diff_hash is None
    assert record.sampling_params is None
    assert record.rng_seed is None


def test_attribution_none_baseline_still_records_pins() -> None:
    """Graceful: pins are spliced BEFORE the None-baseline early return, so a cycle
    with no baseline snapshots still records its reproducibility pins."""
    from core.self_improving.loop.observe.attribution import compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,  # no baseline → early-return path
        baseline_after=None,
        run_provenance=RunProvenanceFields(prompt_hash="sha256:abc"),
    )
    assert payload["prompt_hash"] == "sha256:abc"


# --- baseline registry row: pins recorded + backward-compatible --------------


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "BASELINE_PATH", tmp_path / "baseline.json")
    fake_cfg = SimpleNamespace(
        auditor=SimpleNamespace(model="aud-m", source="claude-cli"),
        target=SimpleNamespace(model="tgt-m", source="openai-codex"),
        judge=SimpleNamespace(model="jdg-m", source="claude-cli"),
        mutator=SimpleNamespace(default_model="mut-m", source="openai-codex"),
        seed_select="petri_17dim",
        held_out_bench=None,
        promote_policy="gate",
        promote_policy_seed=0,
        replicate=1,
        target_effect_size=0.02,
    )
    monkeypatch.setattr(auto_train, "_get_autoresearch_config", lambda: fake_cfg)
    return tmp_path


def _rows(archive: Path) -> list[dict]:
    return [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line]


def test_registry_row_records_e5_pins_when_present(isolated: Path) -> None:
    ledger._write_baseline(
        {"broken_tool_use": 3.0},
        {"broken_tool_use": 0.2},
        run_provenance=RunProvenanceFields(
            prompt_hash="sha256:promptpin",
            applied_diff_hash="sha256:diffpin",
            applied_diff_target="role",
            applied_diff_kind="prompt",
            sampling_params={"max_turns": 12, "temperature": SAMPLING_UNPINNED},
            rng_seed=None,
        ),
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["prompt_hash"] == "sha256:promptpin"
    assert row["applied_diff_hash"] == "sha256:diffpin"
    assert row["applied_diff_target"] == "role"
    assert row["applied_diff_kind"] == "prompt"
    assert row["sampling_params"]["temperature"] == SAMPLING_UNPINNED
    assert "rng_seed" not in row  # None → omitted (honest)


def test_registry_row_default_omits_e5_block(isolated: Path) -> None:
    """The default ``_write_baseline`` (no run_provenance — the pre-E5 path) writes a
    row with NO E5 keys: backward-compatible shape, no new required key."""
    ledger._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    for key in (
        "prompt_hash",
        "applied_diff_hash",
        "applied_diff_target",
        "applied_diff_kind",
        "sampling_params",
        "rng_seed",
    ):
        assert key not in row


# --- main() static wiring guards (E2 / E4 convention) ------------------------


def test_main_builds_run_provenance_bundle() -> None:
    source = inspect.getsource(auto_train.main)
    assert "_e5_run_provenance = build_run_provenance(" in source
    # captured from the ACTUAL composed prompt + the applied diff + the sent params
    assert "wrapper_sections=WRAPPER_PROMPT_SECTIONS" in source
    assert "measure._applied_diff_for_mutation(" in source
    assert "sampling_params=measure._audit_sampling_params_as_sent()" in source
    # rng_seed recorded as sent (None today) — NO determinism claim / fabricated seed
    assert "rng_seed=None" in source


def test_main_threads_run_provenance_into_both_sinks() -> None:
    """The pins must flow into BOTH the attribution row and the on-promote baseline
    provenance — the two record sinks."""
    source = inspect.getsource(auto_train.main)
    assert "run_provenance=_e5_run_provenance" in source  # attribution row
    assert '"run_provenance": _e5_run_provenance' in source  # baseline provenance dict


def test_sampling_params_as_sent_marks_unpinned_knobs() -> None:
    """The per-token knobs GEODE does NOT pin are recorded as the explicit unpinned
    marker (NOT a fabricated value) — the honest 'GEODE did not set this' record."""
    params = measure._audit_sampling_params_as_sent()
    assert params["temperature"] == SAMPLING_UNPINNED
    assert params["top_p"] == SAMPLING_UNPINNED
    assert params["max_tokens"] == SAMPLING_UNPINNED
    # the GEODE-pinned dispatch params are concrete
    assert params["max_connections"] == 1
    assert params["max_samples"] == 1
    assert "max_turns" in params and "seeds" in params and "dim_set" in params


def test_applied_diff_lookup_empty_mutation_id_is_none() -> None:
    """No mutation applied (empty id) → all-None graceful return (no crash)."""
    assert measure._applied_diff_for_mutation("") == (None, None, None)


def test_applied_diff_lookup_reads_apply_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The applied-diff pin reads the EXACT content the apply step committed (the
    ``kind="applied"`` row), not a re-derived guess."""
    from core.self_improving.loop.observe import mutations_reader

    ledger = tmp_path / "mutations.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "ts": 1.0,
                "kind": "applied",
                "mutation_id": "mut-xyz",
                "target_kind": "tool_policy",
                "target_section": "tool.web_search.description",
                "previous_value": "old",
                "new_value": "the applied content",
                "rationale": "r",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mutations_reader, "MUTATION_AUDIT_LOG_PATH", ledger)
    target, value, kind = measure._applied_diff_for_mutation("mut-xyz")
    assert target == "tool.web_search.description"
    assert value == "the applied content"
    assert kind == "tool_policy"
    # and the hash of that value is what build_run_provenance would record
    assert build_run_provenance(applied_new_value=value).applied_diff_hash == hash_text(
        "the applied content"
    )


def test_applied_diff_lookup_unknown_id_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.self_improving.loop.observe import mutations_reader

    ledger = tmp_path / "mutations.jsonl"
    ledger.write_text("", encoding="utf-8")
    monkeypatch.setattr(mutations_reader, "MUTATION_AUDIT_LOG_PATH", ledger)
    assert measure._applied_diff_for_mutation("nonexistent") == (None, None, None)
