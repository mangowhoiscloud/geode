---
name: tech-blog-writer
description: 기술 블로그 포스트 작성 가이드. rooftopsnow.tistory.com 스타일 — 한국어 존댓말 기술 문체, 아키텍처 다이어그램, 코드 블록 + 설계의도 해설, 테이블 비교, 체크리스트 마무리. "blog", "포스팅", "블로그", "기술 글", "tech blog" 키워드로 트리거.
---

# Tech Blog Writer (Tistory Style)

## 문체 규칙

| 항목 | 규칙 |
|---|---|
| 톤 | 존댓말 기조 ("합니다", "됩니다", "입니다") |
| 관점 | 1인칭 ("이 글에서는", "설계 결정입니다") |
| 코드 설명 | `>` 인용 블록으로 설계 의도 해설 |
| 강조 | **굵은 글씨**, `인라인 코드`, > Note 박스 |
| 이모지 | 사용하지 않음 (사용자 요청 시에만) |

## 포스트 구조

```
# 제목: [기술 개념] — [부제/핵심 가치]

> Date: YYYY-MM-DD | Author: geode-team | Tags: [태그1, 태그2]

## 목차
1. 도입 (문제 정의)
2~N. 본문 섹션 (아키텍처 → 구현 → 검증)
N+1. 마무리 (핵심 정리 테이블 + 체크리스트)

---

## 1. 도입

문제 정의 1단락 → 해결 전략 1단락.
독자가 "왜 이 글을 읽어야 하는지" 명확히.

## 2~N. 본문

### 섹션 제목: "N. 개념명 + 상세 설명"

각 섹션 패턴:
1. 개념 한 줄 요약
2. 아키텍처 다이어그램 (Mermaid 또는 ASCII)
3. 핵심 코드 블록 (Python, 타입 힌트 포함)
4. > 설계 의도 해설 블록
5. 비교 테이블 (설정값, 트레이드오프 등)

## N+1. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|---|---|
| ... | ... |

### 체크리스트

- [ ] 항목 1
- [ ] 항목 2
```

## 코드 블록 규칙

1. **인터페이스/Protocol 먼저** → 구현 나중에
2. 타입 힌트 필수 포함
3. 코드 블록 직후 `>` 인용 블록으로 "왜 이렇게 설계했는지" 설명
4. 파일 경로를 코드 블록 위에 주석으로 표시: `# geode/infrastructure/ports/llm_port.py`

```python
# geode/infrastructure/ports/llm_port.py
class LLMClientPort(Protocol):
    def generate(self, system: str, user: str, **kwargs) -> str: ...
    def generate_json(self, system: str, user: str, **kwargs) -> dict: ...
```

> LLM 호출의 구체적인 구현(Claude, GPT)을 추상화하여 어댑터 교체만으로 모델을 전환할 수 있습니다.
> 이는 Hexagonal Architecture의 Port/Adapter 패턴을 따른 설계 결정입니다.

## 다이어그램 규칙

- Mermaid 우선 사용 (GitHub 렌더링 호환)
- 복잡한 흐름은 ASCII 다이어그램 병행
- 다이어그램 직후 1-2문장으로 핵심 흐름 설명
- 색상: Tailwind CSS 기반 (`fill:#3B82F6`, `fill:#10B981` 등)

## 분량 가이드

| 유형 | 분량 | 코드:설명 비율 |
|---|---|---|
| 개념 소개 | 3000-5000자 | 3:7 |
| 아키텍처 심화 | 6000-10000자 | 4:6 |
| 구현 튜토리얼 | 8000-12000자 | 6:4 |

## 한국어 기술 용어 규칙

- 영어 기술 용어는 첫 등장 시 한글 병기: "Port(포트)"
- 이후로는 영어 원어 사용: "Port"
- 고유명사(LangGraph, Anthropic, FastMCP)는 항상 영어
- 약어는 첫 등장 시 풀어쓰기: "PSI(Population Stability Index)"
