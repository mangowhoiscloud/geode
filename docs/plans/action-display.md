# action-display

## 목적
GEODE의 도구 실행 표시를 개선. tool-type 그루핑, 병렬 서브에이전트 카운터, 턴 끝 요약.
Tier1(결정론적, LLM 호출 0, 토큰 비용 0)만 구현.

## 소크라틱 게이트
- Q1: 현재 개별 나열만. 그루핑/카운터 없음.
- Q2: 8건+ 도구 호출 시 wall-of-text. 유저가 "뭘 했는지 모르겠다" 피드백.
- Q3: 표시 줄 수 감소 + 유저 가독성 향상으로 측정.
- Q4: OperationLogger에 그루핑 로직 추가 (최소 변경).
- Q5: Claude Code(Read 5 files 그루핑), Codex(/ps 3줄 롤링) 동일 패턴.

## 변경 3건

### 1. Tool-type 그루핑 (6건 이상)
5건 이하: 현행 개별 표시 유지.
6건 이상: 동일 타입 도구를 그룹 헤더로 접기.
```
web_search (3)
  ⎿ 12 results
memory_search (1)
  ⎿ 2 matches
```

### 2. 병렬 서브에이전트 카운터
완료 순 표시 + 상태 카운터.
```
▸ 5 sub-agents dispatched
  ⎿ ✓ S1 thread-safety (2.1s)
  ⎿ ⠙ S3 dry-resource...
✓ 5 sub-agents completed (4.2s)
```

### 3. 턴 끝 컴팩트 요약
```
──── 3 rounds · 8 tools · 4.2s · $0.012 ────
```

## 수정 파일
- core/cli/ui/agentic_ui.py — OperationLogger 그루핑 + 턴 요약
- core/agent/sub_agent.py — 완료 순 콜백 (이미 announce 메커니즘 있음)
- core/agent/agentic_loop.py — 턴 끝 요약 render 호출
