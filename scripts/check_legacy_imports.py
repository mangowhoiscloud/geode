#!/usr/bin/env python3
"""CI ratchet: reject new imports using legacy bridge paths.

Checks only files changed since base-ref (default: origin/develop).
Exits non-zero if any legacy import is found in changed files.
Usage:
    python scripts/check_legacy_imports.py
    python scripts/check_legacy_imports.py --base-ref origin/main
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts.git_command import GitExecutableNotFoundError, run_git

LEGACY_PATTERNS: list[tuple[str, str]] = [
    (r"from core\.nodes\b", "external package nodes"),
    (r"import core\.nodes\b", "external package nodes"),
    (r"from core\.fixtures\b", "external package fixtures"),
    (r"import core\.fixtures\b", "external package fixtures"),
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
    (r"from core\.runtime_wiring\b", "core.wiring"),
    (r"import core\.runtime_wiring\b", "core.wiring"),
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
    (r"from core\.infrastructure\.ports\.notification_port\b", "core.mcp.notification_port"),
    (r"from core\.infrastructure\.ports\.calendar_port\b", "core.mcp.calendar_port"),
]


def main() -> int:
    base = "origin/develop"
    if "--base-ref" in sys.argv:
        idx = sys.argv.index("--base-ref")
        if idx + 1 < len(sys.argv):
            base = sys.argv[idx + 1]

    try:
        result = run_git(
            ["diff", "--name-only", "--diff-filter=ACMR", base, "HEAD"],
        )
    except GitExecutableNotFoundError:
        raise SystemExit("git executable not found") from None
    changed = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]

    violations: list[str] = []
    for filepath in changed:
        try:
            content = Path(filepath).read_text(encoding="utf-8")
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
