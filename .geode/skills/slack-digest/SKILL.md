---
name: slack-digest
description: Slack 채널 대화 요약 — 놓친 메시지 정리. "슬랙", "slack", "놓친 메시지", "채널 요약", "digest" 키워드로 트리거.
tools: web_search, memory_save
risk: safe
---

# Slack Digest

geode serve Gateway로 수신된 Slack 채널 대화를 요약합니다.

## 요약 범위

- 최근 24시간 (또는 사용자 지정 기간)
- config.toml에 등록된 바인딩 채널 대상

## 요약 형식

```markdown
## Slack Digest — YYYY-MM-DD

### #채널명
- **주요 논의**: 핵심 주제 1-2문장
- **결정 사항**: 합의된 내용 (있으면)
- **액션 아이템**: 후속 작업 (있으면)
- **멘션**: @mango 관련 메시지 (있으면)

### #다른채널
...
```

## 지침

- 잡담/인사는 제외, 실질적 내용만
- 멘션(@mango)은 별도 하이라이트
- 결정 사항과 액션 아이템 우선 추출
- 한국어 요약
