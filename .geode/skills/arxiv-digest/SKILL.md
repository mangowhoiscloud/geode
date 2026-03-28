---
name: arxiv-digest
description: AI/에이전트 분야 최신 논문 자동 탐색 + 요약. "논문", "paper", "arxiv", "연구", "최신 연구", "학회" 키워드로 트리거.
tools: web_search, web_fetch, memory_save
risk: safe
---

# arXiv Digest

AI/ML, 에이전틱 시스템, LLM 분야의 최신 논문을 탐색하고 핵심을 요약합니다.

## 관심 분야 (우선순위순)

1. **Agentic AI** — autonomous agents, tool use, multi-agent, agent orchestration
2. **LLM Engineering** — prompting, fine-tuning, evaluation, RLHF, MoE
3. **Retrieval & RAG** — retrieval-augmented generation, knowledge grounding
4. **Code Generation** — code agents, program synthesis, SWE-bench
5. **Multimodal** — vision-language, video understanding

## 검색 전략

### 키워드 조합
- `agentic AI autonomous agent tool use 2026`
- `LLM orchestration multi-agent framework`
- `MCP model context protocol`
- `code generation agent benchmark`

### 소스
- arXiv cs.AI, cs.CL, cs.LG (web_search로 최신순)
- Hugging Face Daily Papers
- Semantic Scholar trending

## 요약 형식

```markdown
## arXiv Digest — YYYY-MM-DD

### Top Papers (최근 7일)

#### 1. [논문 제목]
- **저자**: ...
- **분야**: cs.AI / cs.CL
- **핵심**: 1-2문장 요약
- **GEODE 관련성**: 에이전트 설계에 적용 가능한 포인트
- **링크**: arxiv.org/abs/...

#### 2. ...

### 트렌드 키워드
- keyword1 (N건), keyword2 (N건)
```

## 스케줄 연동

```
/schedule create "daily at 8:00" action="오늘의 AI/에이전트 논문 다이제스트 생성해"
```

## 지침

- 7일 이내 게시된 논문만 포함
- 논문당 핵심 1-2문장 + GEODE/에이전트 관련성 1문장
- 최소 5편, 최대 10편
- 한국어 요약, 제목은 원문 유지
- 완료 후 memory_save로 인사이트 기록
