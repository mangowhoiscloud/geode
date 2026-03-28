---
name: job-hunter
description: AI/ML Engineer 채용 공고 탐색 + 매칭 분석. "채용", "job", "공고", "포지션", "이직", "recruit", "hiring", "취업", "구직" 키워드로 트리거.
tools: web_search, web_fetch, memory_save
risk: safe
---

# Job Hunter

AI/ML Engineer 포지션을 자동 탐색하고 프로필 매칭도를 분석합니다.

## 사용자 프로필

- **역할**: AI/ML Engineer (에이전틱 시스템 전문)
- **핵심 스택**: Python, LangGraph, MCP, Claude API, OpenAI API, LLM Orchestration
- **강점**: 자율 에이전트 E2E 설계, 하네스 아키텍처 (GEODE/REODE), 프론티어 모델 실전 운용
- **경력**: 前 Rakuten Symphony, 독립 개발자, YouTube @mango_fr 운영
- **선호**: 리모트 우선, AI/에이전트 팀, 시리즈 B+ 스타트업 또는 빅테크 AI Lab
- **지역**: 한국 기반, 글로벌 리모트 가능

## 검색 전략

### 키워드 조합 (우선순위순)
1. `"AI Engineer" OR "ML Engineer" + "agentic" OR "LLM" + remote`
2. `"LangGraph" OR "MCP" OR "Claude" + engineer + hiring`
3. `AI 엔지니어 채용 에이전트 LLM`
4. `"AI infrastructure" OR "ML platform" + engineer`

### 검색 소스
- LinkedIn Jobs (web_search)
- 원티드/로켓펀치 (한국)
- Y Combinator Work at a Startup
- Anthropic/OpenAI/Google DeepMind careers
- RemoteOK, WeWorkRemotely

## 매칭 분석

각 공고에 대해 5-axis 매칭:

| 축 | 기준 |
|---|---|
| **스택 적합도** | Python, LLM, 에이전트 관련 요구사항 일치 |
| **역할 수준** | Senior/Staff 레벨 매칭 |
| **리모트 가능** | 완전 리모트 / 하이브리드 / 오피스 |
| **성장 잠재력** | 팀 규모, 투자 단계, 기술 비전 |
| **처우** | 공개된 연봉 범위, 스톡옵션 |

## 보고서 형식

```markdown
## 채용 탐색 보고서 — YYYY-MM-DD

### Top 매칭 (적합도 80%+)
| 회사 | 포지션 | 스택 | 리모트 | 처우 | 링크 |
|------|--------|------|--------|------|------|

### 관심 후보 (적합도 60-80%)
| 회사 | 포지션 | 비고 | 링크 |

### 시장 인사이트
- AI Engineer 수요 동향
- 연봉 밴드 변화
- 주목할 회사/팀
```

## 스케줄 연동

```
/schedule create "every monday at 10:00" action="이번 주 AI/ML Engineer 채용 공고 탐색해"
```

## 지침

- 7일 이내 게시된 공고만 포함
- 명확한 JD가 없는 공고는 제외
- 매칭도가 높은 순으로 정렬
- 지원 URL 직접 링크 포함
- 완료 후 memory_save로 인사이트 기록
