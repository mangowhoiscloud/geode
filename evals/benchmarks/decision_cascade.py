"""Opt-in live cascade (M8 arm C) for the matched final-verdict diagnostic.

Arm C changes only who decides a final verdict. Jev judges each frozen verification
state first. Its decision stands only when the typed response is admitted and its
maximum label probability ``q`` reaches the frozen threshold ``tau``. Otherwise the same
state is dispatched once more, as a separately observed ``turn_verification`` call, to
the Astra matched verifier, whose decision then stands. An inadmissible Astra answer
remains a failed judgment. A Jev transport error is never escalated: like every provider
error in this diagnostic it invalidates the trial.

Nothing here is enabled by default. The engine value ``cascade`` must be requested
explicitly with the ``tau`` frozen from the selection split on the pre-registered grid.
A selection freeze without an admissible tau (``null``) never starts arm C. ``q`` only
routes a decision and is recorded; it is not authorization, calibration evidence, or a
Jev success when Astra decided.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from evals.benchmarks.decision_handoff_runtime import JEV_MODEL, MODEL, _VerificationComparison

CASCADE_ENGINE = "cascade"
# 05-preregistration §5 grid (selection split only), as canonical decimal strings.
CASCADE_TAU_GRID: tuple[str, ...] = (
    "0.50",
    "0.55",
    "0.60",
    "0.65",
    "0.70",
    "0.75",
    "0.80",
    "0.85",
    "0.90",
    "0.95",
    "0.975",
    "0.99",
    "1.00",
)
FALLBACK_OF = "cascade_fallback_of"
_INVALID_RESPONSE = "invalid-verifier-response"


def cascade_tau(value: object) -> str:
    """Return the canonical frozen tau string, or reject it before any dispatch."""
    if not isinstance(value, str) or value not in CASCADE_TAU_GRID:
        raise ValueError("arm C requires a frozen tau from the pre-registered grid")
    return value


def cascade_tau_from_selection(value: object) -> str:
    """Map a selection-freeze tau (a grid float) to its canonical string.

    ``None`` means the selection split admitted no tau, so arm C is not run.
    """
    if value is None:
        raise ValueError("selection admitted no tau; arm C is not run")
    if type(value) not in (int, float):
        raise ValueError("selection tau must be a grid number")
    for grid_value in CASCADE_TAU_GRID:
        if value == float(grid_value):
            return grid_value
    raise ValueError("selection tau is off the pre-registered grid")


def choice_q(native_answer: object) -> float:
    """Return the maximum label probability of an admitted Jev Choice answer."""
    probabilities = (
        native_answer.get("probabilities") if isinstance(native_answer, Mapping) else None
    )
    if not isinstance(probabilities, Mapping) or not probabilities:
        raise ValueError("admitted Jev choice has no label probabilities")
    values = list(probabilities.values())
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
        for value in values
    ):
        raise ValueError("Jev choice probability is outside [0, 1]")
    return float(max(values))


def require_cascade_contract(engine: object, primitive: object, tau: object) -> str | None:
    """Admit arm C only with its frozen tau and the Choice verdict; others carry no tau."""
    if (engine == CASCADE_ENGINE) != (tau is not None):
        raise ValueError("arm C requires exactly its frozen tau")
    if engine != CASCADE_ENGINE:
        return None
    if primitive != "choice":
        raise ValueError("arm C is pre-registered for the Choice verdict only")
    return cascade_tau(tau)


def primary_route(receipt: Mapping[str, Any], tau: str) -> dict[str, Any]:
    """Routing block for a Jev primary judgment; rejected output always escalates.

    ``q`` is the contract V1 receipt field (maximum label probability) written by
    ``decide_answer``; the Harbor checker recomputes it from the raw answer. It must
    agree with the admitted native answer, so routing never trusts a second copy.
    """
    q: float | None = None
    if receipt.get("accepted") is True:
        q = receipt.get("q")
        if type(q) is not float or q != choice_q(receipt.get("native_answer")):
            raise ValueError("admitted Jev choice lacks its contract V1 q")
    return {"stage": "primary", "tau": tau, "q": q, "admitted": q is not None and q >= float(tau)}


def decision_receipts(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Judgments whose projection reached the root; escalated primaries are excluded."""
    return [
        row
        for row in receipts
        if not (
            isinstance(row.get("cascade"), dict)
            and row["cascade"].get("stage") == "primary"
            and row["cascade"].get("admitted") is not True
        )
    ]


class CascadeVerification(_VerificationComparison):
    """Jev-first final judgment with at most one observed Astra escalation per state.

    Both stages append to one ordered receipt inventory. Each escalation is a new
    logical ``turn_verification`` call through the same middleware registry, so the
    dispatch receipt, attempt ledger and usage record it like any other judge call.
    Routing failures fail closed: the root receives an invalid verifier response and
    ``failures`` invalidates the trial.
    """

    def __init__(
        self,
        primary: Any,
        fallback: Any,
        receipt: Any,
        request: str,
        system: str,
        intervention: Mapping[str, Any] | None = None,
        *,
        tau: str,
        registry: Any,
    ) -> None:
        if (
            primary.receipts is not fallback.receipts
            or (primary.provider, primary.source) != ("typesafe", "payg")
            or (fallback.provider, fallback.source) != ("openai", "subscription")
            or getattr(receipt, "verification_engine", None) != CASCADE_ENGINE
        ):
            raise ValueError("arm C requires a Jev primary and Astra fallback sharing receipts")
        super().__init__(primary, receipt, request, system, intervention)
        self.fallback = fallback
        self.tau = cascade_tau(tau)
        self.registry = registry
        self.stages: dict[str, str] = {}
        self._primaries: dict[str, Any] = {}
        self._escalating: set[str] = set()

    def decision_receipts(self) -> list[dict[str, Any]]:
        return decision_receipts(self.adapter.receipts)

    def metrics(self) -> dict[str, Any]:
        routes = [row.get("cascade") or {} for row in self.adapter.receipts]
        return {
            "cascade": {
                "jev_primaries": sum(route.get("stage") == "primary" for route in routes),
                "jev_admitted": sum(route.get("admitted") is True for route in routes),
                "astra_fallbacks": sum(route.get("stage") == "fallback" for route in routes),
                "routing_failures": len(self.failures),
            }
        }

    async def llm_request(self, call: Any) -> Any:
        if call.purpose != "turn_verification":
            return await super().llm_request(call)
        call_id = call.correlation.get("llm_call_id")
        primary_id = call.request.metadata.get(FALLBACK_OF)
        if not isinstance(call_id, str) or not call_id or call_id in self.stages:
            raise ValueError("cascade judgment requires a fresh logical call identity")
        if primary_id is not None and primary_id not in self._escalating:
            raise ValueError("cascade fallback has no escalated primary judgment")
        transformed = await super().llm_request(call)
        if primary_id is None:
            # Keep the untransformed judge call; an escalation re-enters the full chain.
            self._primaries[call_id] = call
            stage, adapter, model, effort = "jev", self.adapter, JEV_MODEL, "none"
        else:
            stage, adapter, model, effort = "llm", self.fallback, MODEL, "xhigh"
        self.stages[call_id] = stage
        return replace(
            transformed,
            adapter=adapter,
            request=replace(transformed.request, model=model, effort=effort),
        )

    async def llm_execution(self, call: Any, next_call: Any) -> Any:
        if call.purpose != "turn_verification":
            return await super().llm_execution(call, next_call)
        call_id = call.correlation.get("llm_call_id")
        if self.stages.get(call_id) != "jev":
            return await next_call(call)
        receipts = self.adapter.receipts
        before = len(receipts)
        result = await next_call(call)
        # A recovered transport attempt re-enters here; keep the call until one completes.
        # Nothing below may raise: after next_call the registry would hand the unadmitted
        # Jev result to the root, so every routing fault returns an invalid response.
        original = self._primaries.pop(call_id, None)
        if (
            original is None
            or len(receipts) != before + 1
            or receipts[-1].get("llm_call_id") != call_id
        ):
            return self._fail(result, call_id, "primary_receipt_missing")
        try:
            route = primary_route(receipts[-1], self.tau)
        except ValueError:
            return self._fail(result, call_id, "primary_probability_invalid")
        receipts[-1]["cascade"] = route
        if route["admitted"]:
            return result
        correlation = {
            key: value
            for key, value in original.correlation.items()
            if key not in {"llm_call_id", "llm_attempt_id"}
        }
        fallback_id = f"llm-{correlation.get('step_id') or 'cascade'}-{uuid.uuid4().hex[:8]}"
        request = replace(
            original.request, metadata={**original.request.metadata, FALLBACK_OF: call_id}
        )
        self._escalating.add(call_id)
        try:
            fallback = await self.registry.call_llm(
                original.adapter,
                request,
                correlation={**correlation, "llm_call_id": fallback_id},
                purpose="turn_verification",
            )
        except Exception as error:
            # The registry would otherwise return the unadmitted Jev result; fail closed.
            return self._fail(result, call_id, "fallback_" + type(error).__name__)
        finally:
            self._escalating.discard(call_id)
        if (
            len(receipts) != before + 2
            or receipts[-1].get("llm_call_id") != fallback_id
            or self.stages.get(fallback_id) != "llm"
        ):
            return self._fail(result, call_id, "fallback_receipt_missing")
        receipts[-1]["cascade"] = {"stage": "fallback", "tau": self.tau, "primary_call_id": call_id}
        return fallback

    def _fail(self, result: Any, call_id: str, reason: str) -> Any:
        self.failures.append({"primary_call_id": call_id, "reason": reason})
        return replace(result, text=_INVALID_RESPONSE)


def cascade_stage_summary(
    judge_ids: list[str],
    inputs: Mapping[str, Mapping[str, Any]],
    judgments: Mapping[str, Mapping[str, Any]],
    observed: Mapping[str, Mapping[str, Any]],
    tau: str,
) -> dict[str, int]:
    """Check the judgment-to-call mapping of one arm C trial from private receipts.

    Every judge call is either a Jev primary or the single Astra escalation that
    immediately follows a primary which was rejected or fell below tau, on the same
    frozen state. Routes come from the observed attempts; ``q`` is recomputed from the
    native answer that the caller has already reconstructed from the raw response.
    """
    tau = cascade_tau(tau)
    routes = {JEV_MODEL: "jev", MODEL: "llm"}
    summary = {
        "judge_calls": len(judge_ids),
        "jev_primaries": 0,
        "jev_admitted": 0,
        "astra_fallbacks": 0,
        "unanswered_calls": 0,
    }
    pending: str | None = None
    for call_id in judge_ids:
        route = routes.get(str(observed[call_id].get("model")))
        judgment = judgments.get(call_id)
        if route is None or (judgment is not None and judgment.get("engine") != route):
            raise ValueError("cascade judgment engine differs from its observed route")
        if judgment is None:
            summary["unanswered_calls"] += 1
        if pending is not None:
            primary, current = inputs[pending], inputs[call_id]
            prefix = primary.get("receipt_prefix_length")
            if (
                route != "llm"
                or type(prefix) is not int
                or current.get("receipt_prefix_length") != prefix + 1
                or current.get("state_sha256") != primary.get("state_sha256")
                or current.get("candidate_call_id") != primary.get("candidate_call_id")
                or (
                    judgment is not None
                    and judgment.get("cascade")
                    != {"stage": "fallback", "tau": tau, "primary_call_id": pending}
                )
            ):
                raise ValueError("cascade escalation is not the adjacent same-state Astra call")
            summary["astra_fallbacks"] += 1
            pending = None
            continue
        if route != "jev":
            raise ValueError("an Astra cascade judgment requires an escalated Jev primary")
        summary["jev_primaries"] += 1
        if judgment is None:
            continue  # A Jev transport failure is never escalated; the trial is invalid.
        expected = primary_route(judgment, tau)
        if judgment.get("cascade") != expected:
            raise ValueError("cascade primary routing receipt mismatch")
        if expected["admitted"]:
            summary["jev_admitted"] += 1
        else:
            pending = call_id
    if pending is not None:
        raise ValueError("cascade primary below tau was not escalated")
    return summary
