"""Compact observation and trajectory contracts for computer-use.

This module intentionally stays data-shaped. The computer harness already owns
desktop actions; transcripts already own durable history. These helpers only
standardise the small metadata rows needed to replay and evaluate GUI actions
without copying screenshot base64 into logs.
"""

from __future__ import annotations

import base64
import hashlib
import time
from typing import Any, Literal, TypedDict

ErrorKind = Literal[
    "unknown_action",
    "sandbox_config",
    "sandbox_unreachable",
    "no_display",
    "execution_error",
]


class ScreenObservation(TypedDict, total=False):
    schema_version: int
    observation_id: str
    screenshot_sha256: str
    target_width: int
    target_height: int
    screen_width: int
    screen_height: int
    env: str
    driver: str
    surface: str
    action: str
    cursor: dict[str, int]
    grounding: dict[str, Any]
    timestamp: float


class ComputerActionEvent(TypedDict, total=False):
    schema_version: int
    index: int
    action: str
    params: dict[str, Any]
    status: Literal["ok", "error"]
    error: str
    error_kind: ErrorKind
    recovery: dict[str, Any]
    observation: ScreenObservation


def screenshot_digest(screenshot_b64: str) -> str:
    """Return a stable digest for a screenshot without persisting the image."""
    try:
        raw = base64.b64decode(screenshot_b64, validate=True)
    except Exception:
        raw = screenshot_b64.encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def build_screen_observation(
    screenshot_b64: str,
    *,
    action: str,
    target_size: tuple[int, int],
    screen_size: tuple[int, int] = (0, 0),
    env: str,
    driver: str = "pyautogui",
    cursor: tuple[int, int] | None = None,
    grounding: dict[str, Any] | None = None,
) -> ScreenObservation:
    digest = screenshot_digest(screenshot_b64)
    observation: ScreenObservation = {
        "schema_version": 1,
        "observation_id": f"screen:{digest[:16]}",
        "screenshot_sha256": digest,
        "target_width": target_size[0],
        "target_height": target_size[1],
        "env": env,
        "driver": driver,
        "surface": "desktop",
        "action": action,
        "timestamp": time.time(),
    }
    if screen_size[0] > 0 and screen_size[1] > 0:
        observation["screen_width"] = screen_size[0]
        observation["screen_height"] = screen_size[1]
    if cursor is not None:
        observation["cursor"] = {"x": cursor[0], "y": cursor[1]}
    if grounding is not None:
        observation["grounding"] = grounding
    return observation


def classify_computer_error(error: str) -> ErrorKind:
    lower = error.lower()
    if "unknown computer-use action" in lower:
        return "unknown_action"
    if "sandbox_url is empty" in lower or "sandbox url is empty" in lower:
        return "sandbox_config"
    if "sandbox unreachable" in lower:
        return "sandbox_unreachable"
    if "no display" in lower or "cannot connect to display" in lower:
        return "no_display"
    return "execution_error"


def recovery_hint(error_kind: ErrorKind) -> dict[str, Any]:
    """Bounded GUI recovery hint; this does not execute recovery."""
    if error_kind == "unknown_action":
        return {
            "policy": "replan",
            "retryable": False,
            "reason": "provider emitted an action outside the harness vocabulary",
        }
    if error_kind in {"sandbox_config", "sandbox_unreachable", "no_display"}:
        return {
            "policy": "escalate",
            "retryable": False,
            "reason": "desktop execution environment is unavailable",
        }
    return {
        "policy": "observe_then_replan",
        "retryable": True,
        "reason": "action failed after dispatch; collect a fresh screenshot before retrying",
    }


def enrich_computer_result(
    result: dict[str, Any],
    *,
    action: str,
    target_size: tuple[int, int],
    screen_size: tuple[int, int] = (0, 0),
    env: str,
    cursor: tuple[int, int] | None = None,
    grounding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach compact observation/error metadata to a harness result."""
    enriched = dict(result)
    screenshot = enriched.get("screenshot")
    if isinstance(screenshot, str) and screenshot and "observation" not in enriched:
        raw_driver = enriched.get("driver")
        driver = raw_driver if isinstance(raw_driver, str) else "pyautogui"
        enriched["observation"] = build_screen_observation(
            screenshot,
            action=action,
            target_size=target_size,
            screen_size=screen_size,
            env=env,
            driver=driver,
            cursor=cursor,
            grounding=grounding,
        )
    error = enriched.get("error")
    if isinstance(error, str) and error:
        kind = classify_computer_error(error)
        enriched.setdefault("error_kind", kind)
        enriched.setdefault("recovery", recovery_hint(kind))
    return enriched


_SENSITIVE_PARAM_KEYS = {"text", "password", "secret", "token", "api_key"}


def redact_action_params(value: Any) -> Any:
    """Redact typed text/secrets from trajectory rows while preserving shape."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_PARAM_KEYS and item:
                out[key] = f"<redacted:length={len(str(item))}>"
            else:
                out[key] = redact_action_params(item)
        return out
    if isinstance(value, list):
        return [redact_action_params(item) for item in value]
    return value


def build_action_event(
    *,
    index: int,
    action: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> ComputerActionEvent:
    event: ComputerActionEvent = {
        "schema_version": 1,
        "index": index,
        "action": action,
        "params": redact_action_params(params),
        "status": "error" if result.get("error") else "ok",
    }
    if isinstance(result.get("error"), str):
        event["error"] = str(result["error"])
    if isinstance(result.get("error_kind"), str):
        event["error_kind"] = result["error_kind"]
    if isinstance(result.get("recovery"), dict):
        event["recovery"] = result["recovery"]
    if isinstance(result.get("observation"), dict):
        event["observation"] = result["observation"]
    return event


def _event_points(event: ComputerActionEvent) -> list[tuple[int, int]]:
    params = event.get("params") or {}
    action = event.get("action", "")
    points: list[tuple[int, int]] = []
    if action in {"click", "double_click", "move", "scroll"}:
        points.append((int(params.get("x", 0) or 0), int(params.get("y", 0) or 0)))
    if action == "drag":
        points.extend(
            [
                (int(params.get("start_x", 0) or 0), int(params.get("start_y", 0) or 0)),
                (int(params.get("end_x", 0) or 0), int(params.get("end_y", 0) or 0)),
            ]
        )
    return points


def trajectory_metrics(
    events: list[ComputerActionEvent],
    *,
    target_size: tuple[int, int],
    final_has_screenshot: bool,
) -> dict[str, Any]:
    error_events = [event for event in events if event.get("status") == "error"]
    unknown_actions = [
        event.get("action", "")
        for event in error_events
        if event.get("error_kind") == "unknown_action"
    ]
    out_of_bounds = 0
    for event in events:
        for x, y in _event_points(event):
            if x < 0 or y < 0 or x >= target_size[0] or y >= target_size[1]:
                out_of_bounds += 1
    return {
        "schema_version": 1,
        "total_actions": len(events),
        "successful_actions": len(events) - len(error_events),
        "failed_actions": len(error_events),
        "observed_actions": sum(1 for event in events if event.get("observation")),
        "final_has_screenshot": final_has_screenshot,
        "unknown_actions": unknown_actions,
        "out_of_bounds_points": out_of_bounds,
    }


def evaluate_trajectory(
    events: list[ComputerActionEvent],
    *,
    target_size: tuple[int, int],
    final_has_screenshot: bool,
) -> dict[str, Any]:
    """Score a GUI trajectory for bounded, provider-neutral reliability.

    This is not a task-success oracle. It evaluates whether the agent left an
    auditable, recoverable GUI trace: observations present, coordinates sane,
    errors classified, and the final screen state available for verification.
    """
    metrics = trajectory_metrics(
        events,
        target_size=target_size,
        final_has_screenshot=final_has_screenshot,
    )
    failures = int(metrics["failed_actions"])
    out_of_bounds = int(metrics["out_of_bounds_points"])
    total = int(metrics["total_actions"])
    observed = int(metrics["observed_actions"])
    score = 1.0
    if total == 0:
        score -= 0.35
    if failures:
        score -= min(0.45, failures * 0.15)
    if out_of_bounds:
        score -= min(0.25, out_of_bounds * 0.1)
    if total and observed == 0:
        score -= 0.2
    if not final_has_screenshot:
        score -= 0.15
    score = max(0.0, round(score, 3))
    if score >= 0.85:
        verdict = "strong"
    elif score >= 0.65:
        verdict = "usable"
    elif score >= 0.4:
        verdict = "weak"
    else:
        verdict = "failed"
    return {
        "schema_version": 1,
        "score": score,
        "verdict": verdict,
        "metrics": metrics,
        "recommendations": _trajectory_recommendations(metrics),
    }


def _trajectory_recommendations(metrics: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    if metrics["total_actions"] == 0:
        recs.append("Collect an initial screen observation before planning GUI actions.")
    if metrics["failed_actions"]:
        recs.append("Re-observe after the failed action and avoid repeating unchanged inputs.")
    if metrics["out_of_bounds_points"]:
        recs.append("Remap or re-ground coordinates before dispatching more pointer actions.")
    if not metrics["final_has_screenshot"]:
        recs.append("Capture a final screenshot so the next model turn can verify state.")
    if metrics["total_actions"] and not metrics["observed_actions"]:
        recs.append("Attach compact screen observations to trajectory rows.")
    return recs
