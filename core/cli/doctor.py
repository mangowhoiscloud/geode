"""doctor slack — Slack Gateway diagnostic checks.

Verifiable both via CLI (`geode doctor slack`) and natural language
("슬랙 연결 상태 확인해", "check slack connection").
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Required Slack Bot Token scopes for full functionality
REQUIRED_SCOPES = ["chat:write", "channels:history", "channels:read"]
OPTIONAL_SCOPES = ["reactions:write"]

# Slack App Manifest — current GEODE event schema
SLACK_APP_MANIFEST: dict[str, Any] = {
    "display_information": {
        "name": "GEODE",
        "description": "Autonomous execution agent — research, analysis, automation",
        "background_color": "#1e293b",
    },
    "features": {"bot_user": {"display_name": "GEODE", "always_online": True}},
    "oauth_config": {
        "scopes": {
            "bot": [
                "channels:history",
                "channels:read",
                "chat:write",
                "reactions:write",
                "users:read",
            ]
        }
    },
    "settings": {
        "org_deploy_enabled": False,
        "socket_mode_enabled": False,
        "token_rotation_enabled": False,
    },
}


def _check_env() -> list[dict[str, Any]]:
    """Check Slack environment variables."""
    results: list[dict[str, Any]] = []

    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if token:
        masked = token[:10] + "..." + token[-4:] if len(token) > 14 else "***"
        results.append({"name": "SLACK_BOT_TOKEN", "ok": True, "detail": masked})
    else:
        results.append(
            {
                "name": "SLACK_BOT_TOKEN",
                "ok": False,
                "detail": "not set",
                "hint": "Add to ~/.geode/.env: SLACK_BOT_TOKEN=xoxb-...",
            }
        )

    team_id = os.environ.get("SLACK_TEAM_ID", "")
    if team_id:
        results.append({"name": "SLACK_TEAM_ID", "ok": True, "detail": team_id})
    else:
        results.append(
            {
                "name": "SLACK_TEAM_ID",
                "ok": False,
                "detail": "not set",
                "hint": "Add to ~/.geode/.env: SLACK_TEAM_ID=T...",
            }
        )

    return results


def _check_token_validity() -> dict[str, Any]:
    """Validate Slack Bot Token via auth.test API."""
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "detail": "no token to validate"}

    try:
        import httpx

        resp = httpx.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        data = resp.json()
        if data.get("ok"):
            return {
                "ok": True,
                "detail": f"workspace={data.get('team', '?')}, bot={data.get('user', '?')}",
                "bot_user_id": data.get("user_id", ""),
                "team": data.get("team", ""),
            }
        return {"ok": False, "detail": f"auth.test failed: {data.get('error', '?')}"}
    except Exception as exc:
        return {"ok": False, "detail": f"API call failed: {exc}"}


def _check_scopes() -> dict[str, Any]:
    """Check bot token scopes via auth.test + headers."""
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "detail": "no token", "missing": REQUIRED_SCOPES}

    try:
        import httpx

        resp = httpx.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        # Slack returns scopes in x-oauth-scopes header
        scope_header = resp.headers.get("x-oauth-scopes", "")
        granted = {s.strip() for s in scope_header.split(",") if s.strip()}

        missing_required = [s for s in REQUIRED_SCOPES if s not in granted]
        missing_optional = [s for s in OPTIONAL_SCOPES if s not in granted]

        if missing_required:
            return {
                "ok": False,
                "detail": f"missing required: {', '.join(missing_required)}",
                "granted": sorted(granted),
                "missing": missing_required,
            }
        warnings = []
        if missing_optional:
            warnings = [f"optional missing: {', '.join(missing_optional)} (reactions disabled)"]
        return {
            "ok": True,
            "detail": f"{len(granted)} scopes granted",
            "granted": sorted(granted),
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "detail": f"scope check failed: {exc}"}


def _check_bindings() -> list[dict[str, Any]]:
    """Check config.toml gateway bindings."""
    results: list[dict[str, Any]] = []
    config_path = Path(".geode/config.toml")

    if not config_path.exists():
        results.append(
            {
                "name": "config.toml",
                "ok": False,
                "detail": "not found",
                "hint": "cp .geode/config.toml.example .geode/config.toml",
            }
        )
        return results

    results.append({"name": "config.toml", "ok": True, "detail": str(config_path)})

    try:
        import tomllib

        with open(config_path, "rb") as f:
            config = tomllib.load(f)

        rules = config.get("gateway", {}).get("bindings", {}).get("rules", [])
        slack_rules = [r for r in rules if r.get("channel") == "slack"]

        if not slack_rules:
            results.append(
                {
                    "name": "slack binding",
                    "ok": False,
                    "detail": "no slack binding in config.toml",
                    "hint": "Add [[gateway.bindings.rules]] with channel='slack' and channel_id",
                }
            )
        else:
            for rule in slack_rules:
                ch_id = rule.get("channel_id", "")
                mention = rule.get("require_mention", False)
                results.append(
                    {
                        "name": f"binding:{ch_id}",
                        "ok": bool(ch_id and ch_id != "C0XXXXXXXXX"),
                        "detail": f"channel_id={ch_id}, require_mention={mention}",
                        "hint": "Replace C0XXXXXXXXX with actual channel ID"
                        if ch_id == "C0XXXXXXXXX"
                        else "",
                    }
                )
    except Exception as exc:
        results.append({"name": "config.toml parse", "ok": False, "detail": str(exc)})

    return results


def _check_serve() -> dict[str, Any]:
    """Check if geode serve is running."""
    try:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-f", "geode serve"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]
        if pids:
            return {"ok": True, "detail": f"PID {pids[0]}", "pid": int(pids[0])}
        return {
            "ok": False,
            "detail": "not running",
            "hint": "Run: geode serve (or geode will auto-start it)",
        }
    except Exception:
        return {"ok": False, "detail": "pgrep check failed"}


def _check_mcp_slack() -> dict[str, Any]:
    """Check if Slack MCP server process is running."""
    try:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-f", "server-slack"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]
        if pids:
            return {"ok": True, "detail": f"MCP server-slack PID {pids[0]}"}
        return {
            "ok": False,
            "detail": "Slack MCP server not running",
            "hint": "geode serve starts it automatically",
        }
    except Exception:
        return {"ok": False, "detail": "process check failed"}


def _check_socket() -> dict[str, Any]:
    """Check if IPC socket exists (serve is accepting connections)."""
    sock_path = Path.home() / ".geode" / "cli.sock"
    if sock_path.exists():
        return {"ok": True, "detail": str(sock_path)}
    return {"ok": False, "detail": "cli.sock not found", "hint": "geode serve creates this"}


def run_doctor_slack() -> dict[str, Any]:
    """Run all Slack diagnostic checks. Returns structured result."""
    report: dict[str, Any] = {"checks": [], "ok": True, "warnings": []}

    # 1. Environment
    for item in _check_env():
        report["checks"].append(item)
        if not item["ok"]:
            report["ok"] = False

    # 2. Token validity
    token_result = _check_token_validity()
    report["checks"].append({"name": "token_validity", **token_result})
    if not token_result["ok"]:
        report["ok"] = False

    # 3. Scopes
    scope_result = _check_scopes()
    report["checks"].append({"name": "bot_scopes", **scope_result})
    if not scope_result["ok"]:
        report["ok"] = False
    if scope_result.get("warnings"):
        report["warnings"].extend(scope_result["warnings"])

    # 4. Bindings
    for item in _check_bindings():
        report["checks"].append(item)
        if not item["ok"]:
            report["ok"] = False

    # 5. Serve process
    serve_result = _check_serve()
    report["checks"].append({"name": "geode_serve", **serve_result})
    if not serve_result["ok"]:
        report["ok"] = False

    # 6. MCP Slack server
    mcp_result = _check_mcp_slack()
    report["checks"].append({"name": "mcp_slack", **mcp_result})
    if not mcp_result["ok"]:
        report["ok"] = False

    # 7. IPC socket
    sock_result = _check_socket()
    report["checks"].append({"name": "ipc_socket", **sock_result})
    if not sock_result["ok"]:
        report["ok"] = False

    report["status"] = "OPERATIONAL" if report["ok"] else "DEGRADED"
    if report["warnings"]:
        report["status"] += f" ({len(report['warnings'])} warning)"

    return report


def format_doctor_report(report: dict[str, Any]) -> str:
    """Format diagnostic report for CLI/Slack display."""
    lines = ["Slack Gateway Diagnostics", "-" * 30]

    for check in report["checks"]:
        icon = "PASS" if check.get("ok") else "FAIL"
        name = check.get("name", "?")
        detail = check.get("detail", "")
        lines.append(f"  {icon}  {name}: {detail}")
        hint = check.get("hint", "")
        if hint:
            lines.append(f"       -> {hint}")

    for w in report.get("warnings", []):
        lines.append(f"  WARN  {w}")

    lines.append("")
    lines.append(f"Status: {report['status']}")
    return "\n".join(lines)


def get_manifest_url() -> str:
    """Return Slack app creation URL with pre-filled manifest."""
    encoded = json.dumps(SLACK_APP_MANIFEST, separators=(",", ":"))
    from urllib.parse import quote

    return f"https://api.slack.com/apps?new_app=1&manifest_json={quote(encoded)}"
