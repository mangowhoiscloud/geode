"""Compatibility facade for the stable Crucible preparation entrypoint."""

from .admission.prepare import (
    PREPARE_PROVENANCE_SCHEMA,
    PREPARE_REPORT_SCHEMA,
    SPEC_SCHEMA,
    evaluator_hash_at,
    load_pack,
    prepare_campaign,
)

__all__ = [
    "PREPARE_PROVENANCE_SCHEMA",
    "PREPARE_REPORT_SCHEMA",
    "SPEC_SCHEMA",
    "evaluator_hash_at",
    "load_pack",
    "prepare_campaign",
]
