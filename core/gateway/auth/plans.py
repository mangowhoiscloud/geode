"""Plan — first-class subscription/credential entity.

Pre-v0.50.0 GEODE collapsed three concepts into a single (provider, key)
tuple: PAYG API keys, time-boxed subscriptions (GLM Coding Plan, ChatGPT
Plus), and OAuth borrowed from external CLIs (Codex). This made it
impossible to express "this key targets the Coding Plan endpoint with an
80-call/5h quota". Plan adds the missing axis.

Each Plan binds:
  - a provider variant (openai, openai-codex, glm, glm-coding, ...)
  - an endpoint base URL (override of ProviderSpec.default_base_url)
  - an auth method (bearer / x-api-key / oauth_external)
  - optional quota metadata (window + max calls + per-model weights)
  - optional subscription tier + upgrade URL for UX

AuthProfile.plan_id references a Plan; the Plan's provider becomes the
authoritative provider for routing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class PlanKind(Enum):
    """How the user obtained this credential."""

    PAYG = "payg"  # pay-as-you-go API key (default for env-var seeded keys)
    SUBSCRIPTION = "subscription"  # flat-fee plan with quota (GLM Coding, ChatGPT Plus)
    OAUTH_BORROWED = "oauth_borrowed"  # token sourced from an external CLI (Codex CLI)
    CLOUD_PROVIDER = "cloud_provider"  # AWS Bedrock / GCP Vertex etc.


@dataclass
class Quota:
    """Sliding-window quota metadata for a Plan.

    Used to display "used N/M, resets in T" and to drive Phase 6 quota
    awareness (sub-pacing). model_weights captures z.ai's "GLM-5.1
    counts as 3× during peak hours" pattern.
    """

    window_s: int  # sliding window length, e.g. 18000 for 5h
    max_calls: int  # soft cap within the window
    model_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class Plan:
    """A single subscription / credential bundle."""

    id: str  # user-facing label, e.g. "glm-coding-lite", "openai-payg"
    provider: str  # ProviderSpec.id — must match PROVIDER_VARIANTS
    kind: PlanKind
    display_name: str  # e.g. "GLM Coding Lite"
    base_url: str  # endpoint (may override ProviderSpec.default_base_url)
    auth_type: str = "bearer"
    quota: Quota | None = None
    subscription_tier: str | None = None  # "Lite", "Pro", "Max", "ChatGPT Plus"
    upgrade_url: str | None = None  # surfaced in error hints when quota hits


@dataclass
class PlanUsage:
    """Runtime usage tracker — populated by Phase 6 quota awareness.

    Carried as a sibling to Plan rather than mutating Plan so Plans
    remain immutable configuration.
    """

    plan_id: str
    calls_in_window: int = 0
    weighted_calls: float = 0.0
    next_reset_at: float = 0.0
    last_call_at: float = 0.0

    def is_quota_exhausted(self, plan: Plan) -> bool:
        if plan.quota is None:
            return False
        return self.weighted_calls >= plan.quota.max_calls

    def remaining_in_window(self, plan: Plan) -> int:
        if plan.quota is None:
            return -1  # unlimited / unknown
        return max(0, plan.quota.max_calls - int(self.weighted_calls))

    def seconds_until_reset(self) -> int:
        return max(0, int(self.next_reset_at - time.time()))


# ---------------------------------------------------------------------------
# Built-in plan templates
# ---------------------------------------------------------------------------

# These let the CLI offer "you said 'GLM Coding Lite' — here are the values
# we'll pre-fill" without forcing the user to know the endpoint or quota.

GLM_CODING_TIERS: dict[str, Plan] = {
    "lite": Plan(
        id="glm-coding-lite",
        provider="glm-coding",
        kind=PlanKind.SUBSCRIPTION,
        display_name="GLM Coding Lite",
        base_url="https://api.z.ai/api/coding/paas/v4",
        subscription_tier="Lite",
        upgrade_url="https://z.ai/subscribe",
        quota=Quota(
            window_s=18_000,
            max_calls=80,
            model_weights={"glm-5.1": 3.0, "glm-5-turbo": 3.0, "glm-4.7": 1.0},
        ),
    ),
    "pro": Plan(
        id="glm-coding-pro",
        provider="glm-coding",
        kind=PlanKind.SUBSCRIPTION,
        display_name="GLM Coding Pro",
        base_url="https://api.z.ai/api/coding/paas/v4",
        subscription_tier="Pro",
        upgrade_url="https://z.ai/subscribe",
        quota=Quota(
            window_s=18_000,
            max_calls=240,
            model_weights={"glm-5.1": 3.0, "glm-5-turbo": 3.0, "glm-4.7": 1.0},
        ),
    ),
    "max": Plan(
        id="glm-coding-max",
        provider="glm-coding",
        kind=PlanKind.SUBSCRIPTION,
        display_name="GLM Coding Max",
        base_url="https://api.z.ai/api/coding/paas/v4",
        subscription_tier="Max",
        upgrade_url="https://z.ai/subscribe",
        quota=Quota(
            window_s=18_000,
            max_calls=600,
            model_weights={"glm-5.1": 3.0, "glm-5-turbo": 3.0, "glm-4.7": 1.0},
        ),
    ),
}


def default_plan_for_payg(provider: str, key: str) -> Plan:
    """Build a default PAYG Plan from a bare API key + provider.

    Used by .env auto-migration so legacy users keep working without
    explicit `/login add` calls.
    """
    from core.llm.registry import get_provider_spec

    spec = get_provider_spec(provider)
    base_url = spec.default_base_url if spec else ""
    display = spec.display_name if spec else provider
    return Plan(
        id=f"{provider}-payg",
        provider=provider,
        kind=PlanKind.PAYG,
        display_name=f"{display} (PAYG)",
        base_url=base_url,
        auth_type=spec.auth_type if spec else "bearer",
    )
