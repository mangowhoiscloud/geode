---
name: long-task-watcher
description: Reliable progress monitoring for long-running background tasks (live audits, training, multi-step CI). Covers Monitor + tail buffering pitfalls, polling vs streaming patterns, post-mortem cat/grep, and the Petri × GEODE eval log discovery flow. Triggered by "monitor", "tail -F", "progress", "background", "live audit", "stdbuf", "buffering" keywords.
user-invocable: false
---

# Long-Task Watcher

Use this skill when you need to track progress of a long-running background command — `geode audit --live`, multi-sample evals, slow CI watches, training jobs — and surface its events back into the conversation. The Monitor tool is the right primitive, but its usual `tail -F | grep` pattern has a sharp corner that bit us during Petri × GEODE's N7' / N8 live runs.

## The N7' / N8 incident (don't repeat this)

| 단계 | 동작 | 결과 |
|------|------|------|
| `Bash run_in_background: true` 로 `geode audit --live` 실행 | task id `br6pe219i`, output file 에 stdout 누적 | OK |
| 그 직후 `Monitor` 시작 — `tail -F file \| grep -E "samples \[0-9\]+/12\|✓\|error\|..." \| head -200` | task 가 ~3 분 만에 anthropic credit 부족으로 종료 | OK |
| 매칭 라인 5개 (BadRequestError, credit balance, Task interrupted, Log:) 가 file 에 존재 | tail -F 가 시작 시점의 마지막 10 라인을 emit + 새 라인을 inotify 로 watch | event 0건 |
| **60분 후 Monitor timeout** | task 는 이미 종료된 상태 → tail -F 가 영원히 wait | event 0건 stuck |

원인 — `tail -F` 가 pipe 에 출력될 때의 **stdout buffering**. macOS BSD `tail` 은 line-buffered 이지만 background task 의 stdout flush 타이밍, file inotify 트리거, Monitor 의 capture 타이밍이 어긋나면 매칭 라인이 buffer 안에 갇혀 시간 내 emit 되지 않음. 본 case 에서 5개 매칭 라인의 총 byte 수가 ~250B 라 stdout 의 4KB block-buffer 한도를 못 채우는 상황도 의심.

상세 분석: `docs/audits/2026-05-11-petri-2b-7-n7-prime-n8-n4.md` 의 N7' Monitor 타임아웃 섹션.

## 안정 패턴 — 상황별 선택

| 상황 | 추천 패턴 | 이유 |
|------|-----------|------|
| **task 가 빠르게 끝남 (~수분)** | `Bash run_in_background` 받은 완료 알림 후 `cat output | grep ...` | tail -F 의 inotify 의존 없음. 가장 단순. 분실 라인 없음 |
| **task 가 길게 진행, 진행 라인 자주 emit** | `Monitor` + `stdbuf -oL tail -F file \| stdbuf -oL grep --line-buffered "..."` | stdbuf 가 모든 단계의 stdout 을 line-buffered 로 강제. macOS 에서는 `brew install coreutils` 후 사용 가능 |
| **CI / poll 형 외부 endpoint** | `Monitor` + bash `while-true` polling loop (sleep 30s) + `gh pr checks --json` 같은 한 번 호출 | tail 안 씀. 외부 상태가 곧 진실. 본 PoC 의 PR CI 모니터링이 이 패턴 |
| **task 의 PID 가 사라지면 종료** | polling loop 에 `kill -0 $PID 2>/dev/null \|\| break` 추가 | 종료 시 자동 break — Monitor timeout 안 기다림 |
| **inspect_ai 의 ``Log: <path>.eval`` 라인** | task 종료 후 자동 archive — 본 PoC 는 `_extract_eval_log_path` + `_maybe_auto_archive` 로 처리 | 사용자 명시 호출 불필요 |

### 권장 default — "task 종료 후 cat-and-grep"

```bash
# 1) background task 시작
Bash(command="...your long command...", run_in_background=true)
# → background task id 받음

# 2) 종료 알림 받음 (자동)
# → 그 후 cat 한 번
Bash(command="cat /private/tmp/.../tasks/<task_id>.output | grep -E '<filter>'")
```

이 패턴은:
- ★ 분실 라인 없음 (file 전체 grep)
- ★ buffering 이슈 무관 (file 이 이미 stable)
- ★ Monitor timeout 위험 없음 (Monitor 안 씀)
- ★ 가장 단순

단점: **진행 중 가시성 없음**. task 가 30분 이상 걸리면 사용자가 답답할 수 있음. 그 경우 streaming 패턴 추가.

### Streaming — `stdbuf -oL` 의무

macOS BSD tail + grep + head pipeline:

```bash
# ❌ 위험 — buffering 이슈로 stuck 가능
tail -F file 2>/dev/null | grep -E --line-buffered "..." | head -200

# ✅ 안전 — 모든 단계 line-buffered
stdbuf -oL tail -F file 2>/dev/null | stdbuf -oL grep -E "..." | head -200
```

`stdbuf` 는 macOS 기본에 없음. `brew install coreutils` 필요. 또는 `gtail --line-buffered` (gnu tail).

## Petri × GEODE 의 audit live monitoring 권장

`geode audit --live` 가 끝나면 inspect_ai 가 stdout 마지막 줄에 `Log: logs/<...>.eval` emit. 본 PoC 는 #1010 PR 부터 `run_audit` 의 live 분기에서 자동으로:

1. `_extract_eval_log_path(stdout, stderr)` — `Log: <path>` 정규식 매칭
2. `archive_eval(<path>)` — raw → `~/.geode/petri/logs/`, summary YAML → `docs/audits/eval-logs/`
3. 결과를 `AuditReport.archived_raw` / `archived_summary` 에 보존

따라서 사용자/Claude 는 **task 끝난 후 `report.archived_summary` 만 읽으면** 모든 sample 의 dim score / timing / seed_id 가 yaml 로 손에 들어옴. 별도 monitor pattern 불필요.

진행 가시성이 필요한 경우 (1 sample 당 ~30 초 × 여러 sample), 본 skill 의 streaming 패턴 사용.

## 짧은 체크리스트

- [ ] task 가 짧게 끝나면 (수 분) Monitor 안 쓰기 — Bash 종료 알림 + cat
- [ ] streaming 이 필요하면 `stdbuf -oL tail -F` (macOS 는 brew coreutils 필요)
- [ ] polling endpoint 에는 `while-true + sleep + gh|curl` (tail 의존 없음)
- [ ] grep filter 가 silence 일 때 stuck 안 되도록 `head -N` 이나 종료 조건 명시
- [ ] file mtime 검증으로 task 가 진짜 진행 중인지 확인 (`stat -f mtime`)

## Reference
- 사례: `docs/audits/2026-05-11-petri-2b-7-n7-prime-n8-n4.md` § N7' Monitor 타임아웃
- 자동 archive: `plugins/petri_audit/runner.py` `_extract_eval_log_path` / `_maybe_auto_archive`
- inspect_ai eval log 형식: `logs/<ISO-timestamp>_audit_<id>.eval` 끝에 `Log: <path>` line emit
