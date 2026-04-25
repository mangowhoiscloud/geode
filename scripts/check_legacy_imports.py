#!/usr/bin/env python3
"""CI ratchet: reject new imports using legacy bridge paths.

Checks only files changed since base-ref (default: origin/develop).
Exits non-zero if any legacy import is found in changed files.
Bridge proxy files themselves are excluded from checking.

Usage:
    python scripts/check_legacy_imports.py
    python scripts/check_legacy_imports.py --base-ref origin/main
"""

from __future__ import annotations

import re
import subprocess
import sys

LEGACY_PATTERNS: list[tuple[str, str]] = [
    (r"from core\.nodes\b", "core.domains.game_ip.nodes"),
    (r"import core\.nodes\b", "core.domains.game_ip.nodes"),
    (r"from core\.fixtures\b", "core.domains.game_ip.fixtures"),
    (r"import core\.fixtures\b", "core.domains.game_ip.fixtures"),
    # v0.52 — directional flip: ui와 auth가 top-level로 승격되어 cli.ui /
    # gateway.auth 가 이제 legacy. 새 위치를 권장.
    (r"from core\.cli\.ui\b", "core.ui"),
    (r"import core\.cli\.ui\b", "core.ui"),
    (r"from core\.gateway\.auth\b", "core.auth"),
    (r"import core\.gateway\.auth\b", "core.auth"),
    # v0.52 phase 4 — gateway/ 폐기. pollers는 server/, channels는 channels/
    (r"from core\.gateway\.pollers\b", "core.server.{ipc_server,supervised}"),
    (r"from core\.gateway\.channel_manager\b", "core.channels.binding"),
    (r"from core\.gateway\.models\b", "core.channels.models"),
    (r"from core\.gateway\.shared_services\b", "core.server.supervised.services"),
    (r"from core\.gateway\.webhook_handler\b", "core.server.supervised.webhook_handler"),
    # v0.52 phase 1 — runtime_wiring → lifecycle, infra → container
    (r"from core\.runtime_wiring\b", "core.lifecycle"),
    (r"import core\.runtime_wiring\b", "core.lifecycle"),
    # v0.52 phase 5 — automation/ cron 부분이 scheduler/ 로 분리
    (r"from core\.automation\.scheduler\b", "core.scheduler.scheduler"),
    (r"from core\.automation\.triggers\b", "core.scheduler.triggers"),
    (r"from core\.automation\.predefined\b", "core.scheduler.predefined"),
    (r"from core\.automation\.nl_scheduler\b", "core.scheduler.nl_scheduler"),
    (r"from core\.automation\.calendar_bridge\b", "core.scheduler.calendar_bridge"),
    # v0.52 phase 7 — agent rename
    (r"from core\.agent\.agentic_loop\b", "core.agent.loop"),
    (r"from core\.agent\.safety_constants\b", "core.agent.safety"),
    (r"from core\.cli\.agentic_loop\b", "core.agent.loop"),
    (r"from core\.extensibility\b", "core.skills"),
    (r"import core\.extensibility\b", "core.skills"),
    (r"from core\.cli\.sub_agent\b", "core.agent.sub_agent"),
    (r"from core\.cli\.conversation\b", "core.agent.conversation"),
    (r"from core\.cli\.error_recovery\b", "core.agent.error_recovery"),
    (r"from core\.cli\.tool_executor\b", "core.agent.tool_executor"),
    (r"from core\.cli\.system_prompt\b", "core.agent.system_prompt"),
    (r"from core\.infrastructure\.adapters\.mcp\b", "core.mcp"),
    (r"from core\.infrastructure\.ports\.signal_port\b", "core.mcp.signal_port"),
    (r"from core\.infrastructure\.ports\.notification_port\b", "core.mcp.notification_port"),
    (r"from core\.infrastructure\.ports\.calendar_port\b", "core.mcp.calendar_port"),
]

# Bridge proxy files are exempt (they ARE the re-export layer).
# v0.52 — ui/ + auth/ 는 이제 top-level 정식 위치이므로 exempt 불필요.
EXEMPT_FILES = {
    "core/nodes/__init__.py",
    "core/fixtures/__init__.py",
    "core/extensibility/__init__.py",
    "core/extensibility/_frontmatter.py",
    "core/extensibility/agents.py",
    "core/extensibility/plugins.py",
    "core/extensibility/reports.py",
    "core/extensibility/skills.py",
    "core/cli/agentic_loop.py",
    "core/cli/sub_agent.py",
    "core/cli/conversation.py",
    "core/cli/error_recovery.py",
    "core/cli/tool_executor.py",
    "core/cli/system_prompt.py",
    "core/infrastructure/adapters/mcp/__init__.py",
    "core/infrastructure/adapters/mcp/apple_calendar_adapter.py",
    "core/infrastructure/adapters/mcp/base.py",
    "core/infrastructure/adapters/mcp/brave_adapter.py",
    "core/infrastructure/adapters/mcp/catalog.py",
    "core/infrastructure/adapters/mcp/composite_calendar.py",
    "core/infrastructure/adapters/mcp/composite_notification.py",
    "core/infrastructure/adapters/mcp/composite_signal.py",
    "core/infrastructure/adapters/mcp/discord_adapter.py",
    "core/infrastructure/adapters/mcp/google_calendar_adapter.py",
    "core/infrastructure/adapters/mcp/manager.py",
    "core/infrastructure/adapters/mcp/registry.py",
    "core/infrastructure/adapters/mcp/slack_adapter.py",
    "core/infrastructure/adapters/mcp/stdio_client.py",
    "core/infrastructure/adapters/mcp/steam_adapter.py",
    "core/infrastructure/adapters/mcp/telegram_adapter.py",
    "core/infrastructure/ports/signal_port.py",
    "core/infrastructure/ports/notification_port.py",
    "core/infrastructure/ports/calendar_port.py",
}


def main() -> int:
    base = "origin/develop"
    if "--base-ref" in sys.argv:
        idx = sys.argv.index("--base-ref")
        if idx + 1 < len(sys.argv):
            base = sys.argv[idx + 1]

    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base, "HEAD"],
        capture_output=True,
        text=True,
    )
    changed = [
        f
        for f in result.stdout.strip().split("\n")
        if f.endswith(".py") and f not in EXEMPT_FILES
    ]

    violations: list[str] = []
    for filepath in changed:
        try:
            content = open(filepath, encoding="utf-8").read()  # noqa: SIM115
        except FileNotFoundError:
            continue
        for i, line in enumerate(content.split("\n"), 1):
            for pattern, replacement in LEGACY_PATTERNS:
                if re.search(pattern, line):
                    violations.append(f"  {filepath}:{i}: use {replacement}")

    if violations:
        print(f"Legacy import violations ({len(violations)}):")
        for v in violations:
            print(v)
        return 1

    print(f"No legacy imports in {len(changed)} changed files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
