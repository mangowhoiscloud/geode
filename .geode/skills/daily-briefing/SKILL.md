---
name: daily-briefing
description: 매일 아침 뉴스/트렌드/일정 자동 요약 브리핑. "브리핑", "briefing", "오늘 뉴스", "아침 요약", "daily", "모닝" 키워드로 트리거.
tools: web_search, web_fetch, memory_save, schedule_job
risk: safe
---

# Daily Briefing

매일 자동으로 AI/기술 트렌드, 채용 시장, 관심 분야 뉴스를 요약합니다.

## 브리핑 섹션

### 1. AI/ML 트렌드
- Hugging Face trending models/papers
- Anthropic, OpenAI, Google 주요 발표
- 에이전틱 AI / MCP / LangGraph 관련 뉴스

### 2. 채용 시장
- AI/ML Engineer 포지션 동향
- 한국 + 글로벌 (리모트) 채용 공고
- 연봉/처우 트렌드

### 3. 관심 분야
- YouTube 크리에이터/개발자 커뮤니티 동향
- 오픈소스 에이전트 프레임워크 업데이트

## 브리핑 형식

```markdown
## Daily Briefing — YYYY-MM-DD

### AI/ML
- [헤드라인] — 요약 (출처)

### 채용
- [회사/포지션] — 핵심 조건 (출처)

### 관심
- [주제] — 요약 (출처)

---
생성: GEODE auto-briefing
```

## 스케줄 연동

```
/schedule create "daily at 9:00" action="오늘의 AI/채용/기술 브리핑 생성해"
```

스케줄 잡으로 등록하면 매일 아침 isolated 세션에서 자동 실행됩니다.

## 지침

- 각 섹션 3-5개 항목으로 간결하게
- 24시간 이내 뉴스만 포함
- 한국어 요약, 원문 링크 첨부
- 완료 후 memory_save로 프로젝트 메모리에 기록
