"""doctor slack — Slack Gateway diagnostic checks.

Verifiable both via CLI (`geode doctor slack`) and natural language
("슬랙 연결 상태 확인해", "check slack connection").
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

from core.config.env_io import mask_key

log = logging.getLogger(__name__)

# Required Slack Bot Token scopes for full functionality
REQUIRED_SCOPES = ["app_mentions:read", "chat:write", "channels:history", "channels:read"]
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
                "app_mentions:read",
                "channels:history",
                "channels:read",
                "chat:write",
                "reactions:write",
                "users:read",
            ]
        }
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": ["app_mention", "message.channels"],
        },
        "org_deploy_enabled": False,
        "socket_mode_enabled": True,
        "token_rotation_enabled": False,
    },
}


def _resolve_env_or_dotenv(name: str) -> tuple[str, str]:
    """Resolve *name* from os.environ, else the global ~/.geode/.env.

    Returns ``(value, source)`` where source is ``env`` / ``dotenv`` /
    empty. The doctor previously checked os.environ only and reported a
    perfectly valid dotenv-stored token as "not set" (2026-07-15).
    """
    val = os.environ.get(name, "")
    if val:
        return val, "env"
    try:
        from dotenv import dotenv_values

        from core.paths import GLOBAL_ENV_FILE

        if GLOBAL_ENV_FILE.exists():
            dotenv_val = dotenv_values(str(GLOBAL_ENV_FILE)).get(name) or ""
            if dotenv_val:
                return dotenv_val, "dotenv"
    except Exception:
        log.debug("dotenv fallback read failed for %s", name, exc_info=True)
    return "", ""


def _check_env() -> list[dict[str, Any]]:
    """Check Slack credentials (os.environ, then ~/.geode/.env)."""
    results: list[dict[str, Any]] = []

    token, token_src = _resolve_env_or_dotenv("SLACK_BOT_TOKEN")
    if token:
        results.append(
            {"name": "SLACK_BOT_TOKEN", "ok": True, "detail": f"{mask_key(token)} ({token_src})"}
        )
    else:
        results.append(
            {
                "name": "SLACK_BOT_TOKEN",
                "ok": False,
                "detail": "not set",
                "hint": "Add to ~/.geode/.env: SLACK_BOT_TOKEN=xoxb-...",
            }
        )

    app_token, app_token_src = _resolve_env_or_dotenv("SLACK_APP_TOKEN")
    if app_token:
        results.append(
            {
                "name": "SLACK_APP_TOKEN",
                "ok": True,
                "detail": f"{mask_key(app_token)} ({app_token_src})",
            }
        )
    else:
        results.append(
            {
                "name": "SLACK_APP_TOKEN",
                "ok": False,
                "detail": "not set (inbound is using the polling fallback)",
                "hint": (
                    "Enable Socket Mode, create an app-level token with connections:write, "
                    "then add SLACK_APP_TOKEN=xapp-... to ~/.geode/.env"
                ),
            }
        )

    team_id, team_src = _resolve_env_or_dotenv("SLACK_TEAM_ID")
    if team_id:
        results.append({"name": "SLACK_TEAM_ID", "ok": True, "detail": f"{team_id} ({team_src})"})
    else:
        # Informational only — the direct Web API transport never reads it
        # (it was a requirement of the removed MCP server).
        results.append(
            {
                "name": "SLACK_TEAM_ID",
                "ok": True,
                "detail": "not set (unused by the direct transport)",
            }
        )

    return results


def _check_token_validity() -> dict[str, Any]:
    """Validate Slack Bot Token via the same transport the daemon uses."""
    import asyncio

    from core.messaging.slack_transport import SlackTransport

    transport = SlackTransport()
    if not transport.configured:
        return {"ok": False, "detail": "no token to validate"}
    try:
        data = asyncio.run(transport.auth_test())
        return {
            "ok": True,
            "detail": f"workspace={data.get('team', '?')}, bot={data.get('user', '?')}",
            "bot_user_id": data.get("user_id", ""),
            "team": data.get("team", ""),
            "team_id": data.get("team_id", ""),
        }
    except Exception as exc:
        return {"ok": False, "detail": f"auth.test failed: {exc}"}


def _check_scopes() -> dict[str, Any]:
    """Check bot token scopes via auth.test + headers."""
    token, _src = _resolve_env_or_dotenv("SLACK_BOT_TOKEN")
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


def _check_socket_mode() -> dict[str, Any]:
    """Validate the app token by issuing a redacted temporary socket URL."""
    import asyncio

    from core.messaging.slack_transport import open_socket_mode_url

    app_token, _source = _resolve_env_or_dotenv("SLACK_APP_TOKEN")
    if not app_token:
        return {
            "ok": False,
            "detail": "polling fallback (no SLACK_APP_TOKEN)",
            "hint": "Add an xapp- token with connections:write, then restart geode serve",
        }
    try:
        asyncio.run(open_socket_mode_url(app_token))
        return {
            "ok": True,
            "detail": "app token accepted; temporary WebSocket URL issued (ticket redacted)",
        }
    except Exception as exc:
        return {"ok": False, "detail": f"apps.connections.open failed: {exc}"}


def _check_bindings() -> list[dict[str, Any]]:
    """Check gateway bindings through the daemon's own merged config loader.

    PR-SLACK-TRANSPORT: the daemon merges the user-level
    ``~/.geode/config.toml`` (authoritative) with the project overlay —
    the doctor must diagnose the SAME view, with sources named. The old
    check read only the project file and called a working global-only
    deployment "config.toml not found".
    """
    from core.wiring.adapters import _load_gateway_config

    results: list[dict[str, Any]] = []
    try:
        merged, sources = _load_gateway_config()
    except Exception as exc:
        results.append({"name": "gateway config", "ok": False, "detail": str(exc)})
        return results

    if not sources:
        results.append(
            {
                "name": "gateway config",
                "ok": False,
                "detail": "no [gateway] section in ~/.geode/config.toml or ./.geode/config.toml",
                "hint": "Add [gateway] + [[gateway.bindings.rules]] to ~/.geode/config.toml",
            }
        )
        return results

    results.append({"name": "gateway config", "ok": True, "detail": "; ".join(sources)})

    rules = merged.get("gateway", {}).get("bindings", {}).get("rules", [])
    slack_rules = [r for r in rules if r.get("channel") == "slack"]

    if not slack_rules:
        results.append(
            {
                "name": "slack binding",
                "ok": False,
                "detail": "no slack binding in merged gateway config",
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

    return results


def _check_binding_access(auth_team_id: str = "") -> list[dict[str, Any]]:
    """Verify that the bot is a member of every bound Slack channel."""
    import asyncio

    from core.messaging.slack_transport import SlackTransport
    from core.wiring.adapters import _load_gateway_config

    transport = SlackTransport()
    if not transport.configured:
        return []
    try:
        merged, _sources = _load_gateway_config()
    except Exception:
        return []
    rules = merged.get("gateway", {}).get("bindings", {}).get("rules", [])
    channel_ids = [
        str(rule.get("channel_id", ""))
        for rule in rules
        if rule.get("channel") == "slack" and rule.get("channel_id")
    ]
    if not channel_ids:
        return []

    configured_team_id, _team_src = _resolve_env_or_dotenv("SLACK_TEAM_ID")
    team_id = auth_team_id or configured_team_id

    async def _probe() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for channel_id in channel_ids:
            try:
                channel = await transport.channel_info(channel_id)
                is_member = channel.get("is_member") is True
                name = str(channel.get("name", channel_id))
                link = f"https://app.slack.com/client/{team_id}/{channel_id}" if team_id else ""
                detail = f"#{name}, bot_member={is_member}"
                if link:
                    detail += f", {link}"
                results.append(
                    {
                        "name": f"binding_access:{channel_id}",
                        "ok": is_member,
                        "detail": detail,
                        "hint": "Run /invite @geode in this channel" if not is_member else "",
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "name": f"binding_access:{channel_id}",
                        "ok": False,
                        "detail": str(exc),
                        "hint": "Verify the channel ID and run /invite @geode in the channel",
                    }
                )
        return results

    return asyncio.run(_probe())


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


def _check_transport() -> dict[str, Any]:
    """Probe the direct Web API transport (PR-SLACK-TRANSPORT).

    Replaces the old ``pgrep server-slack`` process check — Slack no
    longer runs through an MCP subprocess, so the health question is
    "can THIS machine call chat.postMessage's API family", answered by a
    live ``auth.test`` through the same transport the daemon uses.
    """
    import asyncio

    from core.messaging.slack_transport import SlackTransport

    transport = SlackTransport()
    if not transport.configured:
        return {"ok": False, "detail": "transport unconfigured (no SLACK_BOT_TOKEN)"}
    try:
        data = asyncio.run(transport.auth_test())
        return {
            "ok": True,
            "detail": (
                f"direct Web API OK (workspace={data.get('team', '?')}, "
                f"bot={data.get('user', '?')})"
            ),
        }
    except Exception as exc:
        return {"ok": False, "detail": f"transport auth.test failed: {exc}"}


def _check_socket() -> dict[str, Any]:
    """Check if IPC socket exists (serve is accepting connections)."""
    from core.paths import CLI_SOCKET_PATH

    sock_path = CLI_SOCKET_PATH
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

    # 3. Socket Mode app token
    socket_mode_result = _check_socket_mode()
    report["checks"].append({"name": "socket_mode", **socket_mode_result})
    if not socket_mode_result["ok"]:
        report["ok"] = False

    # 4. Scopes
    scope_result = _check_scopes()
    report["checks"].append({"name": "bot_scopes", **scope_result})
    if not scope_result["ok"]:
        report["ok"] = False
    if scope_result.get("warnings"):
        report["warnings"].extend(scope_result["warnings"])

    # 5. Bindings + live bot membership
    for item in _check_bindings():
        report["checks"].append(item)
        if not item["ok"]:
            report["ok"] = False
    for item in _check_binding_access(str(token_result.get("team_id", ""))):
        report["checks"].append(item)
        if not item["ok"]:
            report["ok"] = False

    # 6. Serve process
    serve_result = _check_serve()
    report["checks"].append({"name": "geode_serve", **serve_result})
    if not serve_result["ok"]:
        report["ok"] = False

    # 7. Direct Web API transport
    transport_result = _check_transport()
    report["checks"].append({"name": "slack_transport", **transport_result})
    if not transport_result["ok"]:
        report["ok"] = False

    # 8. IPC socket
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
