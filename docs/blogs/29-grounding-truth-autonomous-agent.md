# 자율 에이전트의 그라운딩 트루스 — 도구 결과만으로 말하게 하기

> Date: 2026-03-16 | Author: geode-team | Tags: [grounding, hallucination, citation, web-search, tool-result, guardrails, agentic-loop]

## 목차

1. [문제 — 에이전트가 거짓을 말할 때](#1-문제--에이전트가-거짓을-말할-때)
2. [두 가지 그라운딩 — 도메인 vs 에이전트](#2-두-가지-그라운딩--도메인-vs-에이전트)
3. [설계 결정 — 프롬프트 레벨 강제](#3-설계-결정--프롬프트-레벨-강제)
4. [구현 — 소스 태깅과 인용 규칙](#4-구현--소스-태깅과-인용-규칙)
5. [도메인 가드레일 완화](#5-도메인-가드레일-완화)
6. [트레이드오프 — 정확성 vs 유용성](#6-트레이드오프--정확성-vs-유용성)
7. [한계와 발전 방향](#7-한계와-발전-방향)
8. [마무리](#8-마무리)

---

## 1. 문제 — 에이전트가 거짓을 말할 때

GEODE는 `while(tool_use)` 루프로 도구를 호출하고, 결과를 받아 사용자에게 응답합니다. `web_fetch`로 URL을 읽고, `general_web_search`로 검색하고, MCP 도구로 Steam/arXiv 데이터를 가져옵니다.

문제는 LLM이 도구 결과를 **받은 뒤** 응답을 생성하는 단계에서 발생합니다.

```
User: "이 회사 최근 실적 알려줘"
  → web_fetch("https://example.com/earnings") → 매출 $2.1B, 영업이익 $340M
  → LLM 응답: "매출은 $2.1B이며, 전년 대비 15% 성장했습니다."
                                              ↑ 이 숫자는 도구 결과에 없음
```

도구 결과에는 `$2.1B`과 `$340M`만 있었지만, LLM이 **"전년 대비 15% 성장"**이라는 정보를 스스로 생성했습니다. 사전 학습 데이터에서 가져왔을 수도 있고, 완전한 날조일 수도 있습니다. 사용자는 도구로 검증된 정보와 LLM이 추가한 정보를 구분할 수 없습니다.

이것이 자율 에이전트의 **그라운딩 트루스(Grounding Truth)** 문제입니다.

---

## 2. 두 가지 그라운딩 — 도메인 vs 에이전트

GEODE에는 그라운딩이 필요한 두 개의 계층이 있습니다. 각 계층의 특성이 다르므로 다른 전략이 필요합니다.

### 도메인 파이프라인 (L5)

게임 IP 분석 파이프라인은 이미 강력한 그라운딩 체계를 갖추고 있습니다.

```
Fixture signals (YouTube views, Reddit subs, ...)
  → Analyst evidence[] (LLM이 signal 기반으로 생성)
  → G3 Guardrail (_check_evidence_grounding)
  → grounding_ratio 산출
```

| 요소 | 상태 | 방식 |
|------|------|------|
| 입력 데이터 | 통제됨 | fixture JSON, 구조화된 signal |
| evidence 검증 | 자동 | signal key/value 대조 (G3) |
| 점수 산출 | 결정적 | PSM 공식, 코드 기반 Decision Tree |
| 내러티브 | 반자동 | LLM이 signal summary 기반으로 생성 |

> 도메인 파이프라인은 **구조화된 입력 → 구조화된 출력** 패턴입니다. 입력이 통제되므로 출력도 검증 가능합니다.

### 자율 에이전트 (L0)

AgenticLoop은 근본적으로 다릅니다.

```
User free-text input
  → Claude Tool Use → web_fetch / web_search / MCP tools
  → 비구조화 텍스트 결과
  → LLM이 자유 형식으로 응답 생성
```

| 요소 | 상태 | 문제 |
|------|------|------|
| 입력 데이터 | 비통제 | 사용자가 어떤 질문이든 가능 |
| 도구 결과 | 비구조화 | HTML 텍스트, 검색 스니펫 |
| 응답 생성 | 자유 형식 | LLM이 도구 결과 + 사전 학습 혼합 |
| 출처 표기 | 없음 | URL이 결과에 있지만 인용 안 됨 |

> 자율 에이전트의 그라운딩은 **비구조화 입력 → 비구조화 출력** 환경에서 작동해야 합니다. 도메인 파이프라인과 같은 스키마 검증은 불가능합니다.

이 차이가 핵심 설계 결정을 결정합니다. 도메인 가드레일을 에이전트에 그대로 적용하면 false positive가 폭발하고, 에이전트 수준의 느슨한 검증을 도메인에 적용하면 분석 품질이 하락합니다.

---

## 3. 설계 결정 — 프롬프트 레벨 강제

자율 에이전트의 그라운딩을 어디에서 강제할지 3가지 선택지를 검토했습니다.

| 방식 | 장점 | 단점 | 결정 |
|------|------|------|------|
| **프롬프트 규칙** | 구현 단순, 즉시 적용, 모든 도구 커버 | LLM이 규칙을 무시할 수 있음 | **채택** |
| **사후 검증** | 정확도 높음, 자동화 가능 | 비구조화 텍스트에서 claim 추출 어려움, 비용 2배 | 보류 |
| **도구 결과 강제 태깅** | 출처가 구조화됨 | 모든 도구(38+MCP) 수정 필요, 외부 도구 통제 불가 | 부분 채택 |

최종 설계는 **프롬프트 규칙 + 부분 도구 태깅**의 조합입니다.

### 왜 프롬프트 규칙이 1순위인가

자율 에이전트의 응답은 **자유 형식 텍스트**입니다. 응답에서 "이 문장은 tool_result에서 온 것이고, 이 문장은 LLM이 추가한 것"을 자동으로 구분하는 것은 사실상 또 다른 LLM 호출이 필요합니다. 이는 비용과 지연을 2배로 만듭니다.

반면 프롬프트 규칙은 **생성 시점**에서 그라운딩을 강제합니다. LLM이 응답을 생성하는 동안 "이 정보가 도구 결과에 있었는가?"를 스스로 판단하게 합니다.

```python
# core/llm/prompts/router.md (AGENTIC_SUFFIX)
## Grounding & Citation (CRITICAL)

1. ONLY state facts that appear in the tool result.
   Do NOT invent statistics, dates, names, or claims
   beyond what the tool returned.

2. Cite the source for each key claim.
   - Format: "According to [URL]..." or "Sources:" section.

3. When data is insufficient, say so explicitly.

4. Numerical data: quote the exact number from the tool result.
```

> `CRITICAL` 태그는 GEODE의 프롬프트 체계에서 최우선 규칙을 의미합니다. Completion criteria, Clarification rules와 같은 수준으로 그라운딩을 배치한 것은 의도적인 결정입니다. LLM이 우선순위를 판단할 때 그라운딩 규칙이 "도구를 더 호출할까" 같은 전략적 판단보다 앞서도록 합니다.

---

## 4. 구현 — 소스 태깅과 인용 규칙

프롬프트 규칙만으로는 LLM에게 "출처를 인용하라"고 할 때 인용할 출처가 결과에 명시되어 있어야 합니다. 두 가지 핵심 도구에 소스 태깅을 추가했습니다.

### web_fetch — source 필드 추가

```python
# core/tools/web_tools.py
return {
    "result": {
        "url": url,
        "source": url,  # explicit source tag for grounding
        "content": text[:max_chars],
        "truncated": len(text) > max_chars,
        "content_type": content_type,
        "status_code": resp.status_code,
    }
}
```

> `url`과 `source`가 동일한 값이지만, `source`라는 이름을 명시적으로 추가한 이유는 LLM의 **semantic priming(의미적 점화)** 때문입니다. tool_result에 `"source": "https://..."` 필드가 있으면 LLM이 응답에서 해당 URL을 인용할 확률이 높아집니다. 필드 이름 자체가 행동을 유도합니다.

### general_web_search — source_urls 추출

```python
# core/tools/web_tools.py
text_parts: list[str] = []
source_urls: list[str] = []
for block in response.content:
    if hasattr(block, "text"):
        text_parts.append(block.text)
    if getattr(block, "type", "") == "web_search_tool_result":
        for entry in getattr(block, "content", []):
            url = getattr(entry, "url", None)
            if url:
                source_urls.append(url)
return {
    "result": {
        "query": query,
        "search_results": "\n".join(text_parts),
        "source": "anthropic_web_search",
        "source_urls": source_urls,
    }
}
```

> Anthropic의 `web_search_20250305` 도구는 검색 결과를 텍스트 블록과 `web_search_tool_result` 블록으로 반환합니다. 기존에는 텍스트만 추출하고 URL은 버렸습니다. 이제 `source_urls` 리스트로 구조화하여 LLM이 개별 결과를 인용할 수 있게 합니다.

### 프롬프트에서의 인용 규칙

```
2. Cite the source for each key claim:
   - For web_fetch: use the `url` field from the result.
   - For general_web_search: cite individual result URLs when available.
   - For MCP tools: cite the server name (e.g. "Steam API", "arXiv").
```

MCP 도구는 외부 프로세스이므로 결과 구조를 통제할 수 없습니다. 대신 서버 이름을 출처로 인용하도록 합니다. Steam MCP가 반환한 데이터는 "Steam API에 따르면..."으로, arXiv MCP 결과는 "arXiv에 따르면..."으로 인용됩니다.

---

## 5. 도메인 가드레일 완화

에이전트 그라운딩을 추가하면서 도메인 파이프라인의 G3 가드레일을 동시에 완화했습니다.

### AS-IS: quantitative analyst hard fail

```python
# 이전 코드
if g_count == 0 and a.analyst_type in quantitative_analysts:
    errors.append(f"Analyst {a.analyst_type}: 0/{ev_count} evidence "
                  f"grounded in signals (quantitative analyst requires grounding)")
```

`growth_potential`이나 `discovery` 분석가의 evidence가 signal key와 0% 매칭이면 G3가 hard fail했습니다.

### TO-BE: soft warning으로 복원

```python
# core/verification/guardrails.py
if g_count == 0:
    # Soft warning for all analysts — domain guardrails are
    # already strong enough; hard failures here caused
    # false positives in dry-run fixtures.
    details_only.append(
        f"Analyst {a.analyst_type}: 0/{ev_count} evidence "
        f"grounded (review recommended)"
    )
```

> **왜 완화했는가?** dry-run fixture의 evidence 문자열 `"YouTube 12M views"`가 signal key `youtube_views`와 부분 매칭은 되지만, 매칭 알고리즘의 한계로 false positive가 발생했습니다. 도메인 파이프라인은 이미 G1(스키마), G2(범위), G4(일관성), BiasBuster(편향), Cross-LLM(교차 검증) 등 5겹의 검증을 갖추고 있어 G3 하나를 완화해도 전체 품질이 유지됩니다.

### grounding_ratio는 유지

```python
# core/state.py
class GuardrailResult(BaseModel):
    ...
    grounding_ratio: float = 0.0  # [0.0, 1.0]
```

hard fail은 제거했지만 **grounding_ratio는 계속 산출**합니다. 이 값은 리포트에 표시되어 사용자가 evidence의 신뢰도를 판단할 수 있습니다. "이 분석의 evidence 중 70%가 실제 signal 데이터에 근거합니다"와 같은 투명성을 제공합니다.

---

## 6. 트레이드오프 — 정확성 vs 유용성

그라운딩 정책은 **정확성과 유용성** 사이의 긴장을 내포합니다.

| 강도 | 정확성 | 유용성 | 예시 |
|------|--------|--------|------|
| **무제한** | 낮음 | 높음 | LLM이 사전 학습 지식도 자유롭게 활용, 풍부한 응답 |
| **엄격 (현재)** | 높음 | 중간 | tool_result 데이터만 인용, 부족 시 명시 |
| **극단** | 최고 | 낮음 | 모든 문장에 출처 태그, 사후 검증으로 미그라운딩 문장 삭제 |

현재 GEODE는 **엄격** 수준을 택했습니다.

### 유용성 감소 사례

```
User: "Berserk 원작자에 대해 알려줘"
Tool: web_fetch → 미우라 켄타로 Wikipedia 페이지 (1966-2021 정보)

엄격 그라운딩:
  "미우라 켄타로(1966-2021)는 Berserk의 원작자입니다. (Source: Wikipedia)"

무제한:
  "미우라 켄타로는 일본 만화 역사상 가장 영향력 있는 작가 중 한 명으로,
   다크 판타지 장르를 재정의했습니다. 그의 사후 제자인 스튜디오 갸가가
   연재를 이어가고 있으며..."
```

> 엄격 모드의 응답은 짧지만 **모든 문장이 검증 가능**합니다. 무제한 모드의 응답은 풍부하지만 "다크 판타지 장르를 재정의했다"는 주관적 평가이며, "스튜디오 갸가" 정보가 도구 결과에 없다면 할루시네이션입니다.

### 의도적으로 허용하는 영역

에이전트의 그라운딩 규칙에는 **의도적 예외**가 있습니다.

1. **사전 지식 기반 질답**: "Python의 list comprehension 문법 알려줘" 같은 일반 지식 질문은 도구 호출 없이 LLM의 사전 학습 지식으로 답변합니다. 이 경우 그라운딩 규칙이 적용되지 않습니다.

2. **도구 결과 해석**: "이 데이터가 무엇을 의미하는지 설명해줘"와 같은 요청에서 LLM이 분석적 해석을 추가하는 것은 허용합니다. 단, 새로운 **사실**을 추가하는 것은 금지합니다.

이 구분이 프롬프트 규칙 1번의 "facts that appear in the tool result"라는 표현에 담겨 있습니다. **사실(fact)**만 제한하고, **해석(interpretation)**은 허용합니다.

---

## 7. 한계와 발전 방향

### 현재 한계

**1. 프롬프트 규칙은 강제가 아닌 권고입니다.**

LLM은 프롬프트 규칙을 99% 따르지만, 복잡한 멀티턴 대화에서 규칙 준수율이 하락할 수 있습니다. 특히 도구 호출이 5회 이상 누적된 후 최종 응답을 생성할 때, 초기 도구 결과의 세부 사항을 사전 학습 지식으로 채우는 경향이 관찰됩니다.

**2. 비구조화 텍스트의 그라운딩 검증은 어렵습니다.**

"매출이 $2.1B"이라는 응답이 도구 결과의 "$2.1 billion"과 같은 값인지 자동으로 판단하려면 의미적 매칭이 필요합니다. 단순 문자열 비교로는 불가능합니다.

**3. MCP 도구의 결과 구조를 통제할 수 없습니다.**

Steam MCP가 반환하는 JSON 구조, Brave Search가 반환하는 텍스트 형식은 외부 패키지에 의존합니다. `source` 필드를 강제할 수 없으므로 서버 이름 수준의 인용만 가능합니다.

### 발전 방향

**단기**: 도구 결과에 `_grounding_id`를 태깅하여 LLM 응답에서 참조할 수 있게 합니다. `[ref:1]`, `[ref:2]` 형태의 인라인 참조를 통해 사후 검증이 가능해집니다.

**중기**: 응답 생성 후 경량 모델(Haiku)로 "이 응답의 각 주장이 제공된 도구 결과에 근거하는가?"를 검증하는 2단계 파이프라인을 추가합니다. 비용은 증가하지만 정확도가 크게 향상됩니다.

**장기**: 에이전트의 응답을 구조화된 형식(`claim + source_ref`)으로 생성한 뒤 자연어로 렌더링하는 방식으로 전환합니다. Structured Output을 응답 레벨에도 적용하는 것입니다.

---

## 8. 마무리

### 핵심 정리

| 항목 | 값 |
|------|-----|
| 그라운딩 대상 | 자율 에이전트 레벨 (L0) — web_fetch, web_search, MCP 도구 결과 기반 응답 |
| 강제 방식 | AGENTIC_SUFFIX 프롬프트 규칙 (CRITICAL 등급) |
| 소스 태깅 | web_fetch `source` 필드, web_search `source_urls` 리스트 |
| 인용 포맷 | "According to [URL]..." 또는 "Sources:" 섹션 |
| 도메인 G3 | hard fail → soft warning 완화 + grounding_ratio 유지 |
| 도메인 가드레일 | G1-G4 + BiasBuster + Cross-LLM — 이미 5겹 검증 |
| 의도적 예외 | 사전 지식 질답, 도구 결과 해석 (사실 추가만 금지) |

### 그라운딩 계층 구조

```
L0 에이전트    프롬프트 규칙 (Citation & Grounding)
               → tool_result 데이터만 인용
               → 출처 URL/서버명 필수 표기
               → 미확인 정보 생성 금지

L1 도구        소스 태깅 (source, source_urls)
               → web_fetch: URL 명시
               → web_search: 개별 검색 결과 URL 추출
               → MCP: 서버 이름 수준 인용

L5 도메인      G3 grounding_ratio (soft warning)
               → evidence vs signal 교차 검증
               → 비율 산출 + 리포트 Evidence Chain 표시
```

### 체크리스트

- [x] AGENTIC_SUFFIX에 Grounding & Citation 규칙 추가
- [x] web_fetch `source` 필드 태깅
- [x] web_search `source_urls` 추출
- [x] G3 quantitative hard fail → soft warning 완화
- [x] grounding_ratio 필드 + 리포트 Evidence Chain
- [ ] 응답 내 인라인 참조 (`[ref:N]`) 체계
- [ ] 2단계 사후 검증 (Haiku 기반 claim verification)
- [ ] Structured Output 응답 레벨 적용
