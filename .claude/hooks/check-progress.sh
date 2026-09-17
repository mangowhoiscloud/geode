#!/usr/bin/env bash
# Stop hook: advisory progress and GitFlow reminders, never merge authority.
set -euo pipefail

TODAY=$(date +%Y-%m-%d)
PROGRESS_FILE="docs/progress.md"
MESSAGES=()

if COMMITS_TODAY=$(git rev-list --count --since="$TODAY 00:00:00" HEAD 2>/dev/null); then
  if [ "$COMMITS_TODAY" -gt 0 ]; then
    if [ ! -f "$PROGRESS_FILE" ] || ! grep -q "$TODAY" "$PROGRESS_FILE"; then
      MESSAGES+=("[progress] 오늘 ${COMMITS_TODAY}건 커밋이 있지만 docs/progress.md에 ${TODAY} 날짜가 없습니다. 세션 종료 전 갱신 여부를 검토해주세요.")
    fi
  fi
else
  MESSAGES+=("[progress] 커밋 조회 실패로 갱신 필요 여부를 확인하지 못했습니다.")
fi

if git fetch origin --quiet 2>/dev/null; then
  if AHEAD=$(git rev-list --count origin/main..origin/develop 2>/dev/null); then
    if [ "$AHEAD" -gt 0 ]; then
      MESSAGES+=("[gitflow] develop이 main보다 ${AHEAD}커밋 앞서 있습니다. 커밋 수는 병합 근거가 아닙니다. 콘텐츠 차이, 현재 CI, 작업 권한을 확인한 뒤 승격 여부를 검토해주세요.")
    fi
  else
    MESSAGES+=("[gitflow] 브랜치 조회 실패로 main/develop 격차를 확인하지 못했습니다.")
  fi
else
  MESSAGES+=("[gitflow] 원격 조회 실패로 최신 main/develop 격차를 확인하지 못했습니다.")
fi

# JSON escaping belongs to the standard encoder, not shell substitutions.
if [ ${#MESSAGES[@]} -eq 0 ]; then
  printf '{"continue": true}\n'
else
  printf '%s\n' "${MESSAGES[@]}" | python3 -c \
    'import json, sys; print(json.dumps({"continue": True, "message": sys.stdin.read().rstrip()}, ensure_ascii=False))'
fi
