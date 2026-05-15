---
name: docs-link-audit
description: Docs 사이트 (`site/` Next.js) 의 본문/JSX/markdown 링크 audit. broken 내부 링크 탐지, build-time copy 인지, 옵트인 HTTP probe. 신규 페이지 추가 / slug 이전 / chapter 삭제 후 회귀 방지. Triggered by "broken link", "404", "docs link", "hyperlink", "링크 점검", "링크 깨짐", "audit links", "link checker" 키워드.
user-invocable: false
---

# Docs Link Audit

`site/` Next.js docs 사이트의 모든 본문 링크를 정적 + 옵션 HTTP 로 검사한다.
`scripts/check_docs_links.py` 가 본 워크플로의 1차 도구.

## 언제 가동되는가

신규 페이지 추가 / chapter 삭제 / slug 이전 / cross-link 개정 후. 또한
사용자가 "404 뜨는 부분 잡자" / "링크 깨진 것 확인해줘" 같은 요청을 했을 때.

## 1차 도구 — `scripts/check_docs_links.py`

```
$ python3 scripts/check_docs_links.py              # 정적 audit (1초)
$ python3 scripts/check_docs_links.py --http       # + 외부 reachability (~10초)
$ python3 scripts/check_docs_links.py --quiet      # broken 만 출력 (CI 적합)
```

### 분류 4 종

| Category | 매칭 패턴 | 검증 방법 |
|---|---|---|
| **internal /docs/...** | `href="/docs/runtime/foo"` | `site/src/app/docs/**/page.tsx` slug set 과 차집합 |
| **internal /<other>...** | `/portfolio`, `/petri-bundle/`, `/llms.txt` | app route + `site/public/` asset + build-time copy 와 대조 |
| **anchor #section** | `href="#tier-3"` | 같은 page.tsx 의 `id="..."` 와 대조 |
| **external https://** | `<a href="https://github.com/...">` | `--http` 옵트인 시 HEAD/GET, concurrency 8, 8s timeout, 200/3xx OK |

### Link 패턴 추출 — 2 개 정규식

| Pattern | 매칭 예시 |
|---|---|
| `\b(?:href\|src\|to)\s*=\s*\{?\s*['"`​]([^'"`​{}\s]+)['"`​]` | `href="..."`, `href={"..."}`, `href={`...`}`, `src="/img.svg"`, `to="/portfolio"` |
| `\]\(([^)\s]+)\)` | markdown `[text](url)` — `MarkdownLite` 가 렌더하는 CHANGELOG entry 등 |

### 특이 처리

- **`/geode/` deploy basepath 정규화** — `/geode/docs/foo` 도 source-side `/docs/foo` 와 매칭
- **Build-time copy 인지** — `.github/workflows/pages.yml` 의 `docs/petri-bundle/` → `site/out/petri-bundle/` copy step 알기 때문에 `/petri-bundle/` 가 source 에 없어도 OK
- **`${...}` 보간 + relative URL** → `unresolved` 로 분리 (broken 아님)
- **스킴 스킵** — `mailto:`, `tel:`, `javascript:`, `data:`, `blob:`
- **`requests` 미설치 시** `--http` 옵션 자동 비활성

### Exit codes — CI guard 가능

| Code | 의미 |
|---|---|
| 0 | broken 없음 |
| 1 | 1+ broken 발견 |
| 2 | argparse / IO 에러 |

## Workflow — 새 페이지 또는 cross-link 수정 후

```
1. 변경 → 본 변경이 새 페이지 추가 / slug 이전 / chapter 삭제 / cross-link 갱신 중 하나
        ↓
2. python3 scripts/check_docs_links.py
        ↓
3. broken 0 → 통과; PR 으로 진행
   broken N → 메시지의 file:line 으로 이동 + slug 정정
        ↓
4. (선택) --http 도 돌려서 외부 URL reachability 확인
        ↓
5. PR cascade — fix(docs): broken link N 종 정정 (M 사이트)
```

## 잘못된 link 의 4 흔한 원인

| 패턴 | 발생 시점 | 해결책 |
|---|---|---|
| **Chapter 삭제 후 cross-link leftover** | 옛 `build/` 챕터 삭제했는데 다른 페이지가 `/docs/build/add-domain` 참조 | 이전 destination 확인 후 새 slug 로 교체 — sitemap.ts 의 새 entry 가 1차 단서 |
| **Section 이전** | `/docs/ops/observability` → `/docs/verification/observability` 로 옮겼는데 cross-link 갱신 누락 | 동일 |
| **Slug 오타** | 페이지 처음 작성 시 디렉터리 명 오타 | typo 수정 |
| **External URL 만료** | 외부 doc 의 link 가 404 (e.g. dev portal 페이지 이전) | `--http` 가 잡음. 새 URL 또는 archive.org 로 교체 |

## CI wiring (선택, 별 PR)

A. **Pages build pre-step** — `pages.yml` 의 build job 최상단에 추가:

```yaml
- name: Verify docs links
  run: python3 scripts/check_docs_links.py
```

→ broken 들어오면 deploy 차단.

B. **Lint job** — `ci.yml` 에 별 job, dispatch 시 `--http` 포함:

```yaml
docs-links:
  if: github.event_name == 'workflow_dispatch'
  steps:
    - run: pip install requests
    - run: python3 scripts/check_docs_links.py --http
```

→ 매일/주간 schedule cron 으로 외부 link rot 감지.

## 실제 case study

| 날짜 | broken 수 | 정정 방식 |
|---|---|---|
| 2026-05-16 PR #1157 | 3 broken × 6 ref site | 모든 destination 이 sitemap 에 다른 slug 로 존재. 단순 경로 교체 |
| 2026-05-16 PR #1161 | 0 (script 도입) | check_docs_links.py 추가 + 위 case study 결과 0 broken 측정 |

PR #1157 의 3 broken:

- `/docs/build/add-domain` → `/docs/runtime/domains` (`build/` chapter D 스프린트에서 삭제됨)
- `/docs/build/add-tool` → `/docs/runtime/tools/protocol`
- `/docs/ops/observability` → `/docs/verification/observability` (section 이전)

ad-hoc grep 으로 잡았지만 본 스크립트가 다음번부터는 1 명령으로 검출.

## 한계 + 알려진 false positive

| 항목 | 한계 |
|---|---|
| **Dynamic `href={url}`** | 변수 보간된 link 는 정적 분석 불가 → `unresolved` (broken 아님) |
| **External URL rate-limit / login wall** | `--http` 가 401/403 받으면 broken 으로 분류 — 일부 사이트 (Anthropic dev portal 등) 가 anti-bot 으로 403 가능 |
| **Anchor 검사 단위** | 같은 page.tsx 내 anchor 만 검증. 크로스 페이지 anchor `/docs/foo#bar` 는 `/docs/foo` 만 OK 면 통과 (anchor 자체는 검증 안 됨) |
| **MarkdownLite regex 패턴 문자열** | `markdown-lite.tsx:14,133` 의 regex 안의 `url` 문자열이 markdown link `]( )` 패턴 매칭 — 2 unresolved 항상 발생 (false positive, 무시) |

## 관련 skill

- `geode-changelog` — CHANGELOG entry 작성 (모든 doc fix PR 에 필수)
- `geode-gitflow` — feature → develop → main cascade (broken link fix 도 동일)
- `frontier-harness-research` — peer comparison 표가 외부 URL 다수 → `--http` audit 가치 큼
