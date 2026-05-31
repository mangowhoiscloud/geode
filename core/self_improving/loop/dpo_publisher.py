"""DPO publisher adapters — ADR-012 M4.2.

Transforms M4.1's canonical preference pack (one row per ``(prompt,
chosen, rejected)`` tuple) into per-provider DPO training formats.
Three targets in scope:

* ``trl`` — HuggingFace TRL ``DPOTrainer``. Row schema is the simplest
  of the three (``{prompt, chosen, rejected}``) and is the de-facto
  standard for open-weight DPO training across the ecosystem.
* ``openai`` — OpenAI preference fine-tuning. Uses the messages-style
  schema with ``input.messages`` + ``preferred_output`` +
  ``non_preferred_output``. Field names follow the OpenAI fine-tuning
  guide. Each ``prompt`` becomes one user message; ``chosen`` and
  ``rejected`` become assistant-role completions.
* ``bedrock`` — Amazon Bedrock fine-tuning. The exact schema varies by
  base model family; we emit a passthrough that the operator can
  post-process per model. Documented as ``raw`` so callers aren't
  misled into thinking we know every Bedrock model's flavor.

**Scope** — adapters are *pure transforms*. No network calls, no SDK
imports, no API keys read. The publisher writes a JSONL file the
operator hands off to the provider's upload tool (``openai files
create``, ``aws s3 cp``, ``hf datasets push``). M4.3 will add PII
redaction + ratchet gates; M4.4 the in-context wiring path.

**Idempotency** — :func:`publish_pack` overwrites the destination
file each invocation. The canonical pack (M4.1) is the durable
source-of-truth; the published artefact is a *derived view* whose
identity is the (pack content, target) pair. Re-running over the
same pack produces a byte-equal output.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

__all__ = [
    "SUPPORTED_TARGETS",
    "Target",
    "publish_pack",
    "to_bedrock_format",
    "to_openai_format",
    "to_trl_format",
]

Target = Literal["trl", "openai", "bedrock"]
SUPPORTED_TARGETS: tuple[Target, ...] = ("trl", "openai", "bedrock")


def to_trl_format(row: dict[str, Any]) -> dict[str, Any]:
    """HuggingFace TRL ``DPOTrainer`` row — minimal canonical triple."""
    return {
        "prompt": row["prompt"],
        "chosen": row["chosen"],
        "rejected": row["rejected"],
    }


def to_openai_format(row: dict[str, Any]) -> dict[str, Any]:
    """OpenAI preference fine-tuning row — messages-style schema.

    ``input.messages`` carries the user turn; ``preferred_output`` and
    ``non_preferred_output`` are assistant-role completions. Schema
    matches the OpenAI fine-tuning guide (``input`` + ``preferred_output``
    + ``non_preferred_output``). If OpenAI's exact field names drift,
    callers should override at the adapter boundary rather than mutate
    canonical pack rows.
    """
    return {
        "input": {
            "messages": [{"role": "user", "content": row["prompt"]}],
        },
        "preferred_output": [{"role": "assistant", "content": row["chosen"]}],
        "non_preferred_output": [{"role": "assistant", "content": row["rejected"]}],
    }


def to_bedrock_format(row: dict[str, Any]) -> dict[str, Any]:
    """Amazon Bedrock fine-tuning row — generic passthrough.

    Bedrock's preference-tuning schema varies by base model family
    (Anthropic-on-Bedrock differs from Llama-on-Bedrock). Rather than
    bake one assumption into the publisher, we emit a stable triple
    (``prompt``/``chosen``/``rejected``) plus the per-row metadata
    (signature, fitness scores) so an operator-side script can adapt
    to the specific model with full audit context.
    """
    return {
        "prompt": row["prompt"],
        "chosen": row["chosen"],
        "rejected": row["rejected"],
        "signature": row.get("signature", ""),
        "fitness_chosen": row.get("fitness_chosen"),
        "fitness_rejected": row.get("fitness_rejected"),
        "fitness_delta": row.get("fitness_delta"),
    }


_ADAPTERS: dict[Target, Any] = {
    "trl": to_trl_format,
    "openai": to_openai_format,
    "bedrock": to_bedrock_format,
}


def _iter_pack_rows(pack_path: Path) -> list[dict[str, Any]]:
    """Read the canonical pack JSONL → list of row dicts.

    Malformed JSON lines silently dropped (per-line graceful — a stray
    bad row shouldn't block the rest of the pack from publishing).
    Rows missing the required ``prompt``/``chosen``/``rejected`` triple
    are also skipped — the publisher can only emit what the canonical
    pack has labelled.
    """
    if not pack_path.is_file():
        return []
    try:
        text = pack_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("dpo_publisher: failed to read pack %s: %s", pack_path, exc)
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if not all(isinstance(row.get(k), str) for k in ("prompt", "chosen", "rejected")):
            continue
        rows.append(row)
    return rows


def publish_pack(
    *,
    target: Target,
    pack_path: Path,
    out_path: Path,
) -> int:
    """Transform every row in ``pack_path`` via the ``target`` adapter, write to ``out_path``.

    Args:
        target: One of :data:`SUPPORTED_TARGETS`. Selects the adapter.
        pack_path: Canonical pack JSONL (M4.1 output).
        out_path: Destination JSONL. The file is OVERWRITTEN — re-run
            with the same pack produces a byte-equal output.

    Returns:
        Number of rows written.

    Raises:
        ValueError: ``target`` is not in :data:`SUPPORTED_TARGETS`.
    """
    if target not in _ADAPTERS:
        raise ValueError(f"unsupported target {target!r}; expected one of {SUPPORTED_TARGETS}")
    adapter = _ADAPTERS[target]
    rows = _iter_pack_rows(pack_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            transformed = adapter(row)
            fh.write(json.dumps(transformed, ensure_ascii=False) + "\n")
            written += 1
    return written
