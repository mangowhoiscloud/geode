"""Per-cycle reproducibility pins for the self-improving loop ledger (E5, 2026-05-30).

E1-E4 made each ledger row's *outcome* statistically honest (fitness scale,
held-out ruler, control-arm tag, variance decomposition). E5 makes each row
INDEPENDENTLY RE-RUNNABLE: it records the four inputs a third party needs to
reconstruct exactly what produced an audit result, so a row is not just a number
but a recipe.

Per-role model/lane/source is already recorded
(:mod:`core.self_improving.loop.observe.role_provenance`); E3 records the
``promote_policy`` (+ its RNG seed); E4 records replicate / power. E5 adds the
remaining pins to BOTH per-cycle sinks — the ``mutations.jsonl`` attribution row
and the ``baseline_archive.jsonl`` registry row — additively (``None`` / absent
when unavailable, never a new REQUIRED key that breaks an existing reader):

1. ``prompt_hash`` — sha256 of the ACTUAL composed wrapper/scaffold system prompt
   the audit target ran under (the mutation-applied ``WRAPPER_PROMPT_SECTIONS``,
   canonically serialised then hashed). Pins "which prompt produced this row".
2. ``applied_diff`` — the scaffold mutation actually APPLIED this cycle, captured
   as a reproducible reference: ``sha256`` of the applied content + the
   ``target_section`` + ``target_kind`` it edited (NOT just a free-text rationale).
3. ``sampling_params`` — the generation params as SENT for the audit. GEODE's audit
   dispatch is a subprocess that controls only a subset (``max_turns`` / ``seeds`` /
   ``dim_set`` / ``source`` / ``max_connections`` / ``max_samples``); the per-token
   sampling knobs (``temperature`` / ``top_p`` / ``max_tokens``) are NOT pinned by
   GEODE and fall to the inspect_ai + provider defaults, so they are recorded as
   ``None`` with an explicit ``"_unpinned"`` marker rather than a fabricated value.
4. ``rng_seed`` — the audit/generation seed as SENT (distinct from E3's
   ``promote_policy_seed``, which seeds only the promote coin-flip). GEODE currently
   sends NO ``--seed`` to the audit subprocess, so the honest record is ``None``
   (no seed sent), not a fabricated number.

DETERMINISM CAVEAT (CLAUDE.md "doc-before-behaviour" + [[feedback_ctx7_before_backend_assumption]]):
these pins are for AUDITABILITY — they record WHAT WAS SENT — and make NO claim
that any backend replays deterministically from them. A ctx7 lookup of inspect_ai
(2026-05-30, ``/ukgovernmentbeis/inspect_ai``) confirmed ``GenerateConfig`` ACCEPTS
``seed`` / ``temperature`` / ``top_p`` (SDK contract) but did NOT document that any
backend — least of all GEODE's claude-cli / codex-cli OAuth subscription providers
— HONORS ``seed`` for bit-identical reproducible replay. The contract is therefore
``unverified — live test required``: no determinism flag is set to ``True`` here,
and ``rng_seed`` is recorded as the value actually sent (``None`` today) so a future
reader is never misled into assuming a replay is bit-stable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Stable marker for a sampling knob GEODE does not pin (left to the inspect_ai +
# provider default). Recorded as a value (not absence) so a reader can tell
# "GEODE did not set this" apart from "this knob does not exist".
SAMPLING_UNPINNED = "_unpinned"


def hash_text(text: str | None) -> str | None:
    """Return the ``sha256:<hex>`` of ``text``, or ``None`` when ``text`` is ``None``.

    Graceful contract — a missing prompt / diff must not crash the ledger write,
    it simply yields ``None`` and the pin is omitted from the row. A non-``str``
    that is not ``None`` is coerced via :func:`str` so an unexpected upstream type
    (e.g. an accidental dict) still hashes a stable representation rather than
    raising at the cast boundary.
    """
    if text is None:
        return None
    raw = text if isinstance(text, str) else str(text)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compose_wrapper_prompt(sections: Mapping[str, Any] | None) -> str | None:
    """Canonically serialise the wrapper system-prompt section dict for hashing.

    The audit target runs under the mutation-applied ``WRAPPER_PROMPT_SECTIONS``
    (a ``{section_key: text}`` dict). To make :func:`hash_text` STABLE for the same
    logical prompt and SENSITIVE to any edit, the dict is serialised with
    ``sort_keys=True`` (insertion-order independent) and the exact section text
    preserved (so an edit to any section flips the hash).

    Returns ``None`` for ``None`` / empty input (no prompt to hash → the pin is
    omitted, legacy shape preserved). Non-``str`` section VALUES are coerced via
    :func:`str` at the boundary so a malformed section can't raise here.
    """
    if not sections:
        return None
    normalised = {
        str(key): (value if isinstance(value, str) else str(value))
        for key, value in sections.items()
    }
    return json.dumps(normalised, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class RunProvenanceFields:
    """The E5 reproducibility pins persisted on a record row (attribution / registry).

    One bundle so the record-writer signatures take a SINGLE E5 argument (keeping
    ``write_attribution`` / ``_append_baseline_registry_row`` under the ``max-args``
    ratchet, mirroring E4's :class:`PowerRecordFields`). Every field is
    ``None``-omitting at the writer: a cycle with no pin available (legacy caller,
    no mutation applied, no prompt composed) passes ``None`` for that field and the
    writer omits the key — so the row shape is unchanged for existing readers.

    Fields
    ------
    prompt_hash
        ``sha256:<hex>`` of the canonically-serialised wrapper system prompt the
        target ran under (see :func:`compose_wrapper_prompt` → :func:`hash_text`).
    applied_diff_hash
        ``sha256:<hex>`` of the applied mutation's content (``new_value``). A
        reproducible reference to the exact scaffold change, paired with
        ``applied_diff_target`` / ``applied_diff_kind`` so a reader knows WHERE it
        applied without joining the apply row.
    applied_diff_target
        The ``target_section`` the mutation edited (dotted notation).
    applied_diff_kind
        The ``target_kind`` (``prompt`` / ``tool_policy`` / ...) the mutation edited.
    sampling_params
        The generation params as SENT for the audit (the dict actually used). The
        per-token knobs GEODE does not pin are recorded as :data:`SAMPLING_UNPINNED`.
    rng_seed
        The audit/generation seed as SENT — ``None`` when GEODE sent no ``--seed``
        (the honest record, distinct from E3's ``promote_policy_seed``).
    """

    prompt_hash: str | None = None
    applied_diff_hash: str | None = None
    applied_diff_target: str | None = None
    applied_diff_kind: str | None = None
    sampling_params: dict[str, Any] | None = None
    rng_seed: int | None = None

    def as_record_kwargs(self) -> dict[str, Any]:
        """Render only the present (non-``None``) pins as record kwargs.

        Used by the attribution writer + the baseline registry writer to splice the
        pins into the row. An empty dict (every field ``None``) means the row keeps
        its exact legacy shape — additive, never a new required key.
        """
        out: dict[str, Any] = {}
        if self.prompt_hash is not None:
            out["prompt_hash"] = self.prompt_hash
        if self.applied_diff_hash is not None:
            out["applied_diff_hash"] = self.applied_diff_hash
        if self.applied_diff_target is not None:
            out["applied_diff_target"] = self.applied_diff_target
        if self.applied_diff_kind is not None:
            out["applied_diff_kind"] = self.applied_diff_kind
        if self.sampling_params is not None:
            out["sampling_params"] = dict(self.sampling_params)
        if self.rng_seed is not None:
            out["rng_seed"] = int(self.rng_seed)
        return out


def build_run_provenance(
    *,
    wrapper_sections: Mapping[str, Any] | None = None,
    applied_target_section: str | None = None,
    applied_new_value: str | None = None,
    applied_target_kind: str | None = None,
    sampling_params: Mapping[str, Any] | None = None,
    rng_seed: int | None = None,
) -> RunProvenanceFields:
    """Assemble the E5 reproducibility pins from the values ACTUALLY sent for a cycle.

    Captures the pins at the point of truth (the audit dispatch site), so each pin
    reflects what was sent, not a re-derived guess:

    - ``prompt_hash`` from the composed wrapper sections (the dumped override file's
      content) — ``None`` when no sections were composed.
    - ``applied_diff_hash`` from the applied mutation's ``new_value`` — ``None`` when
      no mutation was applied this cycle (manual / no-mutation cycle).
    - ``sampling_params`` from the dict of params the dispatch actually sent —
      ``None`` when not supplied.
    - ``rng_seed`` recorded verbatim — ``None`` when no seed was sent (the honest
      record; GEODE's audit dispatch sends none today).

    Every cast is ``None``-tolerant so a partial cycle (e.g. a manual audit with no
    applied diff) still produces a valid bundle with only the available pins.
    """
    return RunProvenanceFields(
        prompt_hash=hash_text(compose_wrapper_prompt(wrapper_sections)),
        applied_diff_hash=hash_text(applied_new_value),
        applied_diff_target=(
            str(applied_target_section)
            if applied_target_section is not None and applied_new_value is not None
            else None
        ),
        applied_diff_kind=(
            str(applied_target_kind)
            if applied_target_kind is not None and applied_new_value is not None
            else None
        ),
        sampling_params=dict(sampling_params) if sampling_params is not None else None,
        rng_seed=int(rng_seed) if rng_seed is not None else None,
    )


__all__ = [
    "SAMPLING_UNPINNED",
    "RunProvenanceFields",
    "build_run_provenance",
    "compose_wrapper_prompt",
    "hash_text",
]
