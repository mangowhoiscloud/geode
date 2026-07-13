# 리서치 노트북 모드 — 설계 플랜 (구현 보류)

> 상태: **PLAN ONLY** (2026-07-14). 이 문서는 설계 기록이며 구현 착수 전
> 운영자 승인이 필요하다. frontier 코딩 하네스들의 research/REPL 모드
> 관찰에서 도출한 채택 후보를 GEODE 맥락으로 번역한 것.

## 동기

GEODE의 정체성은 리서치·분석·자동화를 수행하는 범용 자율 실행
에이전트다. 그런데 리서치 실행의 산출물은 현재 최종 텍스트 응답과
transcript JSONL뿐이다. 중간 실험(코드 실행, 데이터 로드, 시각화)은
휘발되고, 세션이 끝나면 "무엇을 시도해서 무엇이 나왔는지"의 재현
가능한 기록이 남지 않는다.

노트북 모드는 리서치 세션의 실행 궤적을 Jupyter 노트북(.ipynb)으로
집계하고, 종료 시 결정론적으로 report.md를 합성한다. 노트북은 재현
가능한 실험 기록, 리포트는 사람이 읽는 결론 요약.

## 설계 스케치

### 저장 구조

```
~/.geode/projects/{id}/research/<run-id>/
  notebook.ipynb    # 코드 셀 + 출력 (append-only writer)
  report.md         # 종료 시 합성 (초안은 중간 저장 가능)
  metadata.json     # run id, 모드, 셀 수, 성공 런 수, 완료 시각
```

run-id는 정렬 가능한 `YYYYMMDD-HHMMSS-<rand>` 형식. 세션 체크포인트
id와 별도로 유지(프로세스 경계 id와 리서치 런 id의 분리).

### 구성 요소 4개

1. **영속 Python 커널** — 세션 수명과 일치하는 단일 커널 서브프로세스.
   변수·import·로드된 데이터가 tool call 사이에 유지된다(노트북 셀
   시맨틱). 종료 경로 전부(finally)에서 커널 dispose 보장.
   기존 python 실행 도구가 per-call 서브프로세스라면 kernel-owner
   키로 승격하는 방식.
2. **노트북 writer** — 실행마다 실제 Jupyter 셀(markdown + code +
   stream/display 출력) append. 단일 쓰기 큐 + `atomic_write` 패턴
   (기존 `core/memory/atomic_write.py` 재사용). 쓰기 직후 재읽기
   검증으로 파일 손상을 즉시 표면화.
3. **report 합성** — 종료 시(정상/예외 모두) 노트북 셀 + 목표 상태에서
   결정론적으로 report.md 생성. 모델이 `complete_research` 도구로
   최종 리포트를 명시 확정하는 경로와, 미확정 종료 시 초안 합성 경로
   둘 다.
4. **fail-loud 도구 allowlist** — 리서치 모드는 제한 도구셋(python,
   read, web_search, 읽기전용 bash)만 노출. 핵심은 등록 시점 필터가
   아니라 **레지스트리 조립 완료 후의 단언**: 세션 생성 직후 활성 도구
   목록을 allowlist와 대조해 누수가 있으면 기동 자체를 실패시킨다.
   (기존 `ToolExecutor.denied_tools` denylist와 대칭 — exec-hardening
   v0.99.240 참조.)

### GEODE 기존 부품과의 접합

| 필요 | 기존 부품 | 상태 |
|------|----------|------|
| 세션 수명 관리 | AgenticLoop + SessionCheckpoint | 재사용 |
| 원자적 파일 쓰기 | core/memory/atomic_write.py | 재사용 |
| 도구 제한 | ToolExecutor.denied_tools (denylist) | allowlist 단언 신규 |
| 영속 커널 | 없음 (python 실행은 per-call) | 신규 |
| ipynb writer | 없음 | 신규 |
| report 합성 | 없음 | 신규 |

## Socratic Gate

| # | 질문 | 답 |
|---|------|-----|
| Q1 | 이미 존재하나? | 없음. GAP 조사(2026-07-14)에서 core/plugins/scripts 전부 ipynb/kernel 무관 확인 |
| Q2 | 안 하면 뭐가 깨지나? | 리서치 실행의 중간 실험이 휘발 — 재현·검증 불가. 현재도 동작은 하므로 "깨짐"보다 "품질 상한" |
| Q3 | 효과 측정은? | 노트북 재실행 성공률, 리포트-노트북 셀 참조 정합, 리서치 태스크 회귀셋 |
| Q4 | 최소 구현은? | 커널 없이 시작: 기존 per-call python 실행 결과를 노트북에 append하는 writer + 종료 시 report 합성. 영속 커널은 2단계 |
| Q5 | frontier 3+ 수렴? | 부분적 — research/REPL 모드는 1~2개 하네스, notebook 산출물 관례는 데이터과학 도구 전반. 수렴 약함 → 보류 판단의 근거 |

Q5 수렴이 약하고 Q2가 "품질 상한" 수준이라 **지금은 구현하지 않는다**.
단, 4번 구성 요소(fail-loud allowlist 단언)는 노트북 모드와 무관하게
독립 채택 가치가 있어 별도 사이클에서 소형 PR로 분리 가능.

## 단계 계획 (승인 시)

1. **Phase A — writer만**: per-call python 결과를 ipynb로 append +
   종료 시 report.md 합성. 커널 없음. 게이트: 노트북 유효성(nbformat
   검증) 테스트.
2. **Phase B — 영속 커널**: kernel-owner 키 + finally dispose + resume
   시 노트북 요약 재주입(truncated replay context).
3. **Phase C — 도구 게이팅**: 리서치 모드 allowlist + 조립 후 단언.
4. **Phase D — CLI 표면**: `geode research "<question>"` 진입점 +
   `--resume <run-id>`.

## 리스크

- 커널 서브프로세스 누수 — 종료 경로 전수(finally) + owner-key dispose로
  방어. bootstrap_builtins 서브프로세스 규칙 준수.
- 노트북 파일 손상 — 쓰기 큐 직렬화 + 원자적 rename + 재읽기 검증.
- 도구 allowlist 드리프트 — 조립 후 단언이 기동을 실패시키므로 조용한
  드리프트는 구조적으로 불가능.
