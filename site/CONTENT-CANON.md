# GEODE Docs Content Canon

> 공식 문서(`site/`) 전 페이지가 따르는 콘텐츠 헌법.
> 페이지를 새로 쓰거나 재생성할 때 이 문서를 먼저 읽는다.
> 디자인 토큰은 `DESIGN.md`, 라우팅·문체 세칙은 `site/CLAUDE.md`가 SoT.
> 기계 검증: `scripts/check_docs_canon.py` (pages.yml CI 게이트).

## 1. 제품 정의

GEODE는 **범용 자율 실행 에이전트**다. 리서치, 분석, 자동화, 스케줄 작업을
CLI와 메신저(Slack, Discord, Telegram)에서 수행한다. 자기개선 루프는 이 본체
위의 시그니처 차별점이다.

서술 순서 규칙: 본체(무엇을 해주는가) 먼저, 시그니처(어떻게 스스로 나아지는가) 다음.
랜딩과 Overview는 이 순서를 따른다.

## 2. 자기개선 루프 캐논 (ML이 아니다)

루프의 정확한 정체: **비모수적(non-parametric) 자기개선.** 모델 가중치와
파라미터를 일절 갱신하지 않는다. 갱신 대상은 모델을 감싼 스캐폴드, 곧
시스템 프롬프트 섹션(`WRAPPER_PROMPT_SECTIONS`)과 7개 behaviour kinds다.
메커니즘은 경사하강이 아니라 선택(selection)이다:

```
변이(mutate) → 적대적 안전 감사(Petri, 22-dim judge) → fitness 스칼라
→ margin 게이트 → 승격 또는 되돌림 (옵티마이저 = git champion chain)
```

근거 코드: `core/self_improving/train.py`(루프 드라이버),
`measure.py` / `fitness.py` / `gate.py` / `ledger.py`(장비),
`core/self_improving/loop/{mutate,observe,inject}`(Mode B 런타임).

| 구분 | 공식 어휘 | 금지 어휘 |
|------|----------|----------|
| 메커니즘 | 변이, 선택, 진화적 탐색, evolutionary search | 학습, training, learning loop, ML 루프 |
| 측정 | 감사(audit), fitness, margin 게이트 | reward, reward model |
| 반영 | 승격(promote), 되돌림(revert), champion chain | weight update, gradient, fine-tuning |
| 계열 | self-evolving agents (DGM, GEPA 등) | RL, reinforcement learning, DPO |

`train.py` 파일명은 Karpathy autoresearch의 3-파일 관습
(`prepare` / `train` / `program.md`)을 빌린 것으로, training이 일어나지 않는다.
이 파일을 언급하는 모든 페이지는 이 사실을 한 문장으로 동반 표기한다.

frontier 기법 인용은 "inspired by" 강등 + "no policy/parameter update" 명시
(EXAONE fake-citation 사건 이후 규칙).

예외 표기: 계보·비교 맥락에서 금지 어휘가 불가피하면 해당 줄에 `canon-ok`
마커를 남긴다(스캐너가 그 줄을 건너뜀). 렌더되는 `<pre>` 다이어그램처럼
마커를 줄에 못 넣는 곳은 스캐너의 `FILE_WAIVERS` 레지스트리에 파일 단위,
label 단위로 등록한다(짧게 유지).

## 3. 아키텍처 캐논

**5-Layer Stack** (S-5, v0.99.163에서 공식화. 4-layer 서술은 전부 stale):

```
SELF-IMPROVING  train.py + measure/fitness/gate/ledger + loop/{mutate,observe,inject}
AGENT           AgenticLoop(while tool_use), SubAgentManager, CLIPoller, Gateway
HARNESS         SessionLane, LaneQueue, PolicyChain, TaskGraph, HookSystem
RUNTIME         ToolRegistry, MCP Registry, Skills, Memory(5-Tier), Reports
MODEL           ClaudeAdapter, OpenAIAdapter, GLMAdapter (3-provider routing)
```

엔트리 포인트는 둘: `geode`(Typer CLI) + `geode-mcp`(1급 MCP 서버,
`core/mcp_server.py`). 문서가 CLI만 언급하면 불완전하다.

## 4. 근거 규칙 (코드와의 일치)

- 모든 기능 서술은 코드 경로 인용 필수. **파일 경로까지만, 라인 번호 금지**
  (라인 번호는 드리프트 원천).
- S-1~S-5 구조 스프린트로 모듈 경로가 대거 이동했다(`core/utils/` 소멸,
  `cmd_*.py` → `commands/`, `loop/runner` → `loop/mutate/`). 기존 문서의
  경로 인용은 신뢰하지 말고 현재 트리에서 재확인한다.
- vanity metric 금지: tool/hook/module/test/LOC/release 카운트를 본문에 쓰지
  않는다. 기능적 임계값(round cap, token guard, lane limit)은 허용.
- 외부 SDK·서드파티 주장은 ctx7 검증 후 인용.
- `sot.ts`, `changelog.ts`, `public/llms.txt`는 `sync-stats.mjs` 생성물.
  수동 편집 금지.

## 5. 문체

톤의 한 줄 정의: **엔지니어링 톤이되, 간결하고 우아하게.** 사실이 문장을
끌고 가고, 문장은 사실보다 길지 않다.

- KR 본문: TossPayments 개발자 문서체. 합니다체, "왜" 먼저, 번역투 회피.
- EN 본문: 번역이 아니라 별도 작성. `<Bi ko={} en={}>` 양쪽 모두 손수.
- 간결: 한 문장 하나의 주장. 군더더기 수식어("매우", "사실상", "기본적으로",
  "단순히")와 동어반복 도입부("이 페이지에서는 ~를 알아봅니다")를 지운다.
  접속사 남용 대신 문장을 끊는다.
- 우아: 리듬을 만든다. 짧은 단정 뒤에 한 호흡 긴 설명, 그리고 코드.
  명사 나열식 번역투("~에 대한 ~의 ~") 대신 동사로 말한다. 핵심 단정은
  문단 첫 문장에 둔다.
- 엔지니어링 톤: 마케팅 형용사("강력한", "혁신적인", "완벽한") 금지.
  과장 대신 수치·경로·조건. 실패와 한계를 본문 위쪽에서 말하는 것이 우아함이다.
- 대시(—, –) 자제, 마침표·쉼표로 대체. 이모지 금지. 카드 그리드 내비 금지,
  dense table/list 사용.
- 페이지 해부 표준: 1문장 정의 → 동작 방식(표/다이어그램) → 코드 예시 →
  실패 모드와 복구 → 설정 레퍼런스 링크. quickstart는 성공 기준 체크리스트와
  "증상, 원인, 해법" 실패 모드 표를 포함한다.
- 검수 게이트: 모든 배치 PR 전에 문체 검수 패스를 한 번 돈다. 점검 항목은
  위 네 줄(간결·우아·엔지니어링 톤·해부 표준) + 금지어 스캐너.

## 6. 시각화 스펙 (3단, Hermes 배분 규율)

| 단계 | 도구 | 한도 | 용도 |
|------|------|------|------|
| 기본 | ASCII 다이어그램 (코드 블록, Fira Code) | 제한 없음 | 레이어, 데이터 플로우, 트리. llms-full.txt에 생존 |
| 플로우 | Mermaid, 빌드타임 SVG 사전 렌더 (`site/diagrams/*.mmd`가 SoT) | 사이트 전체 5~8개 | 상태 전이, 루프 사이클, 라우팅 |
| 시그니처 | 손수 SVG (DESIGN.md 토큰, 모노 폰트) | 3~5개 | 5-layer 스택, two-loops 등 대표 그림 |

- Mermaid themeVariables는 DESIGN.md 팔레트에 고정. 클라이언트 사이드
  mermaid.js 로딩 금지(정적 export).
- `@xyflow/react`는 docs 신규 사용 금지. 스크린샷은 실물 UI 증거가 필요할
  때만.

## 7. IA 타깃 (재생성 기준)

- 9섹션 골격 유지. **08b Verification 섹션 삭제**(G1-G4 가드레일, BiasBuster,
  cross-LLM, cause-decision-tree는 v0.99.154에서 코드 삭제됨).
  observability 페이지만 05 Operate로 이동.
- 신규 페이지: geode-mcp 가이드, llms.txt 컨벤션, baseline epoch(be-NNN).
- 신규 CLI 표면 반영: `geode seeds assemble`, `geode hub build`,
  `geode config explain`, `/recall`.
- config 계열 페이지(07)는 config unification(C-3/C-4) 머지 후 재생성한다.
