#!/bin/bash
# Hook: Stop — progress.md 갱신 + develop→main 격차 리마인드
# (1) 오늘 커밋이 있는데 progress.md 미갱신이면 리마인드
# (2) develop이 main보다 앞서 있으면 머지 리마인드
# Ref: https://rooftopsnow.tistory.com/329 §5.2

set -euo pipefail

TODAY=$(date +%Y-%m-%d)
PROGRESS_FILE="docs/progress.md"
MESSAGES=()

# --- Check 1: progress.md 갱신 여부 ---
COMMITS_TODAY=$(git log --since="$TODAY 00:00:00" --oneline 2>/dev/null \
  | wc -l | tr -d ' ')

if [ "$COMMITS_TODAY" -gt 0 ]; then
  if [ ! -f "$PROGRESS_FILE" ] || ! grep -q "$TODAY" "$PROGRESS_FILE"; then
    MESSAGES+=("[progress] 오늘 ${COMMITS_TODAY}건 커밋이 있지만 docs/progress.md에 ${TODAY} 날짜가 없습니다. 세션 종료 전 갱신해주세요.")
  fi
fi

# --- Check 2: develop→main 격차 감지 ---
git fetch origin --quiet 2>/dev/null || true
AHEAD=$(git rev-list --count origin/main..origin/develop 2>/dev/null \
  || echo "0")

if [ "$AHEAD" -gt 0 ]; then
  MESSAGES+=("[gitflow] develop이 main보다 ${AHEAD}커밋 앞서 있습니다. develop → main PR + merge를 진행하세요.")
fi

# --- Output ---
if [ ${#MESSAGES[@]} -eq 0 ]; then
  echo '{"continue": true}'
else
  MSG=$(printf '%s ' "${MESSAGES[@]}")
  # JSON 특수문자 이스케이프
  MSG=$(echo "$MSG" | sed 's/"/\\"/g')
  cat <<EOF
{
  "continue": true,
  "message": "${MSG}"
}
EOF
fi
