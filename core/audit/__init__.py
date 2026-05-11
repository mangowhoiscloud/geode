"""Audit-side bookkeeping for inspect_petri runs.

Bridges inspect_ai's per-eval ``.eval`` archive (single-eval scope,
``EvalStats.role_usage`` / ``model_usage`` in the header) and GEODE's
cross-session ``~/.geode/usage/`` JSONL ledger. inspect_ai's native
``AnthropicAPI`` / ``OpenAIAPI`` bypass GEODE's TokenTracker so judge
and auditor cost is otherwise invisible to ``geode history``.
"""

from __future__ import annotations

from core.audit.eval_to_jsonl import extract_to_usage_store
from core.audit.manifest import (
    DEFAULT_MANIFEST_PATH,
    append_manifest,
    has_archive,
    read_manifest,
)

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "append_manifest",
    "extract_to_usage_store",
    "has_archive",
    "read_manifest",
]
