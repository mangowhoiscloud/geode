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
    (r"from core\.ui\b", "core.cli.ui"),
    (r"import core\.ui\b", "core.cli.ui"),
    (r"from core\.auth\b", "core.gateway.auth"),
    (r"import core\.auth\b", "core.gateway.auth"),
    (r"from core\.extensibility\b", "core.skills"),
    (r"import core\.extensibility\b", "core.skills"),
    (r"from core\.cli\.agentic_loop\b", "core.agent.agentic_loop"),
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

# Bridge proxy files are exempt (they ARE the re-export layer)
EXEMPT_FILES = {
    "core/nodes/__init__.py",
    "core/fixtures/__init__.py",
    "core/ui/__init__.py",
    "core/auth/__init__.py",
    "core/auth/cooldown.py",
    "core/auth/profiles.py",
    "core/auth/rotation.py",
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
