"""File-based diagnostics that survive inspect_ai subprocess boundaries.

PR E/F (2026-05-11) 의 ``core/_fa4_debug.py`` ad-hoc pattern 의
정식 인프라화. ``inspect eval`` 의 child process 는 stdout/stderr 가
parent 의 ``subprocess.run(..., capture_output=True)`` 에 잡혀
일반적인 print/stderr 출력이 외부 관찰자에게 닿지 않고, Python
``logging`` 의 root handler 역시 child 안에서 inspect_ai 가 자체
설정 (``inspect_ai/_util/logger.py:init_logger``) 으로 갈아치우는
탓에 GEODE plugin 의 INFO/DEBUG record 가 parent 의 LogHandler 까지
propagate 되지 않는다. file 기반 append-only log 가 이 두 boundary
와 무관하게 evidence 를 보존한다.

위치 — ``~/.geode/diagnostics/<YYYY-MM>.log`` (월 단위 rotation,
다른 GEODE runtime artifacts 와 같은 ``~/.geode/`` 컨벤션).
override — ``GEODE_DIAGNOSTICS_LOG=<path>`` 환경 변수.

사용 예::

    from core.audit.diagnostics import diag

    diag("petri.runner", f"entry msg_count={len(messages)}")
    diag("petri.anthropic", f"BadRequest: {str(exc)[:200]}")

분석::

    # 본 audit 의 sample 만 (unix-ts window)
    awk '$1 >= 1778500000 && $1 <= 1778510000' \\
        ~/.geode/diagnostics/2026-05.log
    # component 별
    grep ' petri.anthropic ' ~/.geode/diagnostics/2026-05.log
    # PID 별 (subprocess 추적)
    awk '{print $2}' ~/.geode/diagnostics/2026-05.log | sort | uniq -c

Failure mode — best-effort. disk full / permission denied / monthly
rotation 의 partial mkdir 등 모든 OSError 는 swallow 된다. diagnostics
가 실제 audit 를 깨트리면 안 되기 때문.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

__all__ = ["DEFAULT_DIAGNOSTICS_DIR", "diag", "diagnostics_path"]

#: GEODE convention. ``~/.geode/`` 의 다른 artifacts 와 동거.
DEFAULT_DIAGNOSTICS_DIR: Path = Path.home() / ".geode" / "diagnostics"


def diagnostics_path() -> Path:
    """Resolve the current diagnostics log path.

    Priority:
    1. ``GEODE_DIAGNOSTICS_LOG`` env var — full path override (PoC scope,
       e.g. test fixture redirecting to ``tmp_path``).
    2. ``~/.geode/diagnostics/<YYYY-MM>.log`` — month-rolled file under
       the standard GEODE convention.

    The parent directory is created on demand. Path resolution is pure
    (no I/O beyond mkdir); errors during mkdir bubble to the caller so
    a misconfigured env var fails loudly at test time. The runtime
    write path (:func:`diag`) catches them anyway.
    """
    override = os.environ.get("GEODE_DIAGNOSTICS_LOG")
    if override:
        return Path(override).expanduser()
    DEFAULT_DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    return DEFAULT_DIAGNOSTICS_DIR / f"{now.year:04d}-{now.month:02d}.log"


def diag(component: str, msg: str) -> None:
    """Append a single line to the diagnostics log.

    Line format::

        <unix_ts:%.3f> <pid> <component> <msg>\\n

    ``component`` is a short dotted namespace (``petri.runner``,
    ``petri.anthropic``, ``petri.lifecycle`` …) so grep/jq queries
    stay simple. Multi-line ``msg`` is allowed but discouraged —
    each call is one line; the caller is responsible for trimming.

    Best-effort: every ``Exception`` during write is swallowed. The
    diagnostics path exists to *help* debugging, not to fail the audit
    when the disk is full.
    """
    try:
        path = diagnostics_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f} {os.getpid()} {component} {msg}\n")
    except Exception:  # noqa: S110 — best-effort debug log
        pass
