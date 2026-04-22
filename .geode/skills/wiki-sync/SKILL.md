---
name: wiki-sync
visibility: public
description: GEODE 리서치/지식을 mango-wiki (Obsidian vault)에 인제스트. Triggers: 'wiki', '위키', 'vault', 'wiki-sync', '위키 동기화', 'wiki render', '위키 렌더링'.
tools: web_search, web_fetch, memory_save
risk: safe
---

# Wiki Sync — GEODE to mango-wiki

GEODE에서 생성된 리서치, 분석 결과, 아키텍처 문서를 mango-wiki Obsidian vault에 인제스트.

## Target Vault

```
/Users/mango/workspace/mango-wiki/vault/
```

## Workflow

### 1. Source Identification

GEODE 내 인제스트 대상 소스 탐지:
- `docs/research/*.md` — 리서치 문서
- `docs/architecture/*.md` — 아키텍처 문서
- `docs/plans/_done/*.md` — 완료된 계획
- `.geode/memory/PROJECT.md` — 프로젝트 메모리

### 2. Delta Check

mango-wiki의 `.manifest.json`을 읽어 이미 인제스트된 소스를 확인.
이미 있는 소스는 스킵하거나 업데이트 판단.

### 3. Page Generation

Obsidian wiki 포맷으로 변환. 반드시 아래 구조를 따른다:

```yaml
---
title: Page Title
type: concept | reference | entity
category: topic-area
tags: [tag1, tag2, tag3]
related:
  - "[[other-page]]"
sources:
  - "source reference"
created: 2026-01-01T00:00:00Z
updated: 2026-01-01T00:00:00Z
summary: "1-2 sentence summary for tiered retrieval"
---
```

### Page Type Routing

| Source Type | Vault Location | Page Type |
|------------|---------------|-----------|
| Research paper analysis | `vault/concepts/` | concept |
| Architecture doc | `vault/projects/geode/concepts/` | concept |
| Blog post | `vault/projects/geode/references/blog/` | reference |
| Tool/library review | `vault/references/` | reference |
| Person/org profile | `vault/entities/` | entity |

### 4. Cross-Linking

- 기존 vault 페이지와 `[[wikilinks]]`로 연결
- 최소 2개 이상의 related 링크 포함
- GEODE 관련 페이지는 반드시 `[[geode-architecture]]` 또는 `[[geode-agentic-loop]]` 등 기존 GEODE 페이지와 연결

### 5. Manifest & Index Update

인제스트 후 반드시 업데이트:
1. `vault/.manifest.json` — 소스 항목 + stats 카운트
2. `vault/index.md` — 새 페이지를 적절한 섹션에 추가
3. `vault/log.md` — 인제스트 로그 한 줄 추가

### 6. Blog Post Generation (Optional)

`/wiki-sync blog` 또는 "블로그도 써줘"라고 요청하면:
- vault의 concept 페이지 기반으로 기술 블로그 포스트 작성
- `vault/projects/geode/references/blog/` 에 저장
- rooftopsnow.tistory.com 스타일: 한국어 기술 산문, 코드 블록 + 설계 의도 코멘트

## Rules

- **Compile, don't retrieve**: 원본 복사가 아닌 지식 압축
- **Merge over create**: 기존 페이지가 있으면 업데이트
- **Provenance tracking**: 모든 claim에 source attribution
- **No placeholders**: 측정된 값만 기록
