"""LLM Router — provider-aware dispatching for all LLM calls.

Replaces the monolithic client.py. Routes to the correct provider SDK

Data types (ToolCallRecord, ToolUseResult) and the live token_tracker
re-exports are kept here as the package's public surface.

This package was split from a single 1,046-line ``router.py`` into focused
sub-modules. The public surface is preserved via re-exports below; production
code keeps importing from ``core.llm.router`` and tests can target leaf
modules (``core.llm.router.calls``, ``.tracing``) when monkeypatching
internals that one call function uses to dispatch to another.
"""

from __future__ import annotations

# PR-CLEANUP-D1 (2026-06-10) — the v0.88.0 backward-compat surface
# (LLM*Error lazy re-exports, ``_resolve_provider`` monkeypatch alias,
# provider_dispatch/anthropic-client/fallback-constant re-exports) is
# deleted: its own comment recorded zero importers since 2026-05-08,
# twelve-plus releases past the Compat 1-release grace. What remains
# below is the LIVE public surface (verified by import grep).
from core.llm.token_tracker import MODEL_PRICING as MODEL_PRICING
from core.llm.token_tracker import LLMUsage as LLMUsage
from core.llm.token_tracker import LLMUsageAccumulator as LLMUsageAccumulator
from core.llm.token_tracker import calculate_cost as calculate_cost
from core.llm.token_tracker import get_usage_accumulator as get_usage_accumulator
from core.llm.token_tracker import reset_usage_accumulator as reset_usage_accumulator

# Local sub-module re-exports
from ._hooks import (
    _fire_hook as _fire_hook,
)
from ._hooks import (
    clear_router_hooks as clear_router_hooks,
)
from ._hooks import (
    set_router_hooks as set_router_hooks,
)
from .calls import (
    _route_provider as _route_provider,
)
from .calls import (
    call_llm as call_llm,
)
from .calls import (
    call_with_failover as call_with_failover,
)
from .models import (
    ToolCallRecord as ToolCallRecord,
)
from .models import (
    ToolUseResult as ToolUseResult,
)
