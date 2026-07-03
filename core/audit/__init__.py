"""Audit-side bookkeeping for inspect_petri runs.

Bridges inspect_ai's per-eval ``.eval`` archive (single-eval scope,
``EvalStats.role_usage`` / ``model_usage`` in the header) and GEODE's
cross-session ``~/.geode/usage/`` JSONL ledger. inspect_ai's native
``AnthropicAPI`` / ``OpenAIAPI`` bypass GEODE's TokenTracker so judge
and auditor cost is otherwise invisible to ``geode history``.
"""

from __future__ import annotations

from core.audit.diagnostics import DEFAULT_DIAGNOSTICS_DIR, diag, diagnostics_path
from core.audit.eval_to_jsonl import extract_to_usage_store
from core.audit.judge_agreement import (
    compute_report,
    extract_pairs,
    krippendorff_alpha,
    weighted_cohens_kappa,
)
from core.audit.manifest import (
    DEFAULT_MANIFEST_PATH,
    append_manifest,
    has_archive,
    read_manifest,
)

__all__ = [
    "DEFAULT_DIAGNOSTICS_DIR",
    "DEFAULT_MANIFEST_PATH",
    "append_manifest",
    "compute_report",
    "diag",
    "diagnostics_path",
    "extract_pairs",
    "extract_to_usage_store",
    "has_archive",
    "krippendorff_alpha",
    "read_manifest",
    "weighted_cohens_kappa",
]
