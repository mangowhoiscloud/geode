---
name: long-task-watcher
visibility: public
triggers: monitor, tail, progress, background, long task, watch, 진행 상황, 백그라운드, 모니터링
description: Reliable progress watching for long-running background commands (training runs, live audits, batch jobs, CI) without losing output to stdout buffering. Prefer post-completion cat-and-grep over tail -F.
---

# Long-Task Watcher

Patterns for tracking a long-running background command and surfacing its
events without the classic `tail -F | grep` buffering trap: matching lines can
sit in a 4KB stdout block buffer and never emit within the watch window, so a
watcher waits forever on output that is already on disk.

## Pattern selection

| Situation | Pattern | Why |
|-----------|---------|-----|
| Task finishes within minutes | Wait for completion, then `cat <logfile> \| grep -E "<filter>"` | No inotify/buffering dependency; no lost lines. Default choice. |
| Long task, frequent progress lines | `stdbuf -oL tail -F <logfile> \| stdbuf -oL grep --line-buffered "<filter>"` | Forces line-buffering at every pipe stage (macOS: needs coreutils). |
| External state (CI, deploy, queue) | Polling loop: `while true; do <one-shot status call>; sleep 30; done` | The external status API is the truth; tailing local output adds nothing. |
| Task should stop the watch when it dies | Add `kill -0 $PID 2>/dev/null \|\| break` to the polling loop | Breaks immediately on process exit instead of waiting for a timeout. |

## Rules

- Redirect long-run stdout/stderr to a file from the start (`... > run.log 2>&1`); never rely on scrollback.
- After the task exits, one `cat`-and-`grep` pass over the log is more reliable than any live tail.
- Watch loops need a hard timeout; a watcher without one outlives dead tasks.
- Archive logs to a stable location (`.audit/` convention) before summarizing, so the evidence survives the session.
