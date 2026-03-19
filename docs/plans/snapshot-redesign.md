# Snapshot 재설계 — 범용 작업 컨텍스트 보존

> Date: 2026-03-18 | Status: **Phase 1 구현 완료** (Transcript + AgenticLoop 통합)
> 선행: snapshot 리서치, REODE SessionTranscript, Karpathy P4-P6, OpenClaw RunLog

## 1. 현재 문제

### 1.1. Snapshot이 게임 IP 전용

현재 `SnapshotManager`는 `GeodeState`(파이프라인 상태)만 캡처한다. 이는 게임 IP 분석에만 유용하고, GEODE의 실제 워크플로우에서 의미가 없다:

| GEODE 실제 작업 | Snapshot이 캡처하는가? |
|:--|:--|
| "AI 에이전트 시장 조사해줘" → 리서치 보고서 | X (pipeline 안 탐) |
| "내 프로필 시그널 분석해줘" → 시그널 리포트 | X (pipeline 안 탐) |
| "Anthropic 지원서 써줘" → 커버레터 | X (pipeline 안 탐) |
| "Berserk 분석해줘" → IP 분석 | O (PIPELINE_END에서 캡처) |

### 1.2. 캡처 범위가 좁음

| 캡처됨 | 안 캡처됨 |
|:---:|:---:|
| 분석 결과 (tier, score) | **사용자 입력** |
| 평가 축 점수 | **LLM 응답 원문** |
| 검증 결과 | **도구 호출 + 결과** |
| prompt/rubric hash | **비용 데이터** |
| | **생성된 산출물 (보고서, 지원서)** |

### 1.3. 사용자 접근 불가

- CLI 명령 없음 (`/snapshots list` 같은 게 없다)
- AgenticLoop 도구 없음 (에이전트가 과거 스냅샷 참조 불가)
- Journal(C2)과 분리되어 있어 실행 이력과 매핑 안 됨

## 2. 재정의: 3-Tier 보존 체계

기존 SnapshotManager를 폐기하지 않고, **3단계 보존 체계**로 확장한다.

```
Tier 1: SessionTranscript (JSONL 이벤트 스트림)
  ← 모든 세션의 모든 이벤트를 append-only 기록
  ← REODE 패턴 채택

Tier 2: Journal (C2, 이미 구현)
  ← 세션 종료 시 핵심 결과 침전 (runs.jsonl, learned.md)

Tier 3: Snapshot (기존, 파이프라인 전용)
  ← 도메인 파이프라인 상태 캡처 (유지, 확장 안 함)
```

### 각 Tier의 역할

| Tier | 질문 | 보존 대상 | 수명 | 형식 |
|:--:|:--|:--|:--|:--|
| 1 | "이 세션에서 정확히 무슨 일이 있었는가?" | 대화 전문, 도구 호출/결과, 비용 | 30일 auto-cleanup | JSONL |
| 2 | "프로젝트에서 지금까지 무엇을 했는가?" | 실행 요약, 학습 패턴, 에러 | 영구 (pruning) | JSONL + MD |
| 3 | "이 분석의 정확한 상태는?" | 파이프라인 GeodeState | 30 recent + weekly | JSON |

**핵심 통찰**: Tier 1(Transcript)이 추가되면, "왜 이 결과가 나왔는가?"를 추적할 수 있다. 현재는 Tier 2(뭘 했는가)와 Tier 3(결과가 뭔가)만 있어 중간 과정이 소실된다.

## 3. SessionTranscript 설계 (Tier 1)

### 3.1. 이벤트 스키마

```jsonl
{"ts":1710000000,"event":"session_start","model":"claude-opus-4-6","session_id":"s-abc123"}
{"ts":1710000001,"event":"user_message","text":"내 프로필 시그널 분석해줘"}
{"ts":1710000005,"event":"tool_call","tool":"web_fetch","input":{"url":"https://youtube.com/..."}}
{"ts":1710000008,"event":"tool_result","tool":"web_fetch","status":"ok","summary":"channel data..."}
{"ts":1710000012,"event":"assistant_message","text":"YouTube 채널 분석 결과입니다..."}
{"ts":1710000015,"event":"vault_save","path":"vault/profile/signal-report-2026-03-18.md","category":"profile"}
{"ts":1710000016,"event":"cost","model":"claude-opus-4-6","input_tokens":1200,"output_tokens":350,"cost_usd":0.015}
{"ts":1710000020,"event":"session_end","duration_s":20,"total_cost":0.015,"rounds":3}
```

### 3.2. 이벤트 타입

| 이벤트 | 캡처 시점 | 데이터 |
|:--|:--|:--|
| `session_start` | REPL/AgenticLoop 시작 | model, provider, session_id |
| `session_end` | 세션 종료 | duration_s, total_cost, rounds |
| `user_message` | 사용자 입력 수신 | text (최대 500자) |
| `assistant_message` | LLM 응답 | text (최대 500자) |
| `tool_call` | 도구 호출 직전 | tool name, input (최대 300자) |
| `tool_result` | 도구 실행 완료 | tool name, status, summary (최대 300자) |
| `vault_save` | Vault에 산출물 저장 | path, category |
| `cost` | LLM 호출 비용 | model, tokens, cost_usd |
| `error` | 에러 발생 | error_type, message |
| `subagent_start` | 서브에이전트 시작 | task_id, task_type |
| `subagent_complete` | 서브에이전트 완료 | task_id, status, summary |

### 3.3. 저장 위치

```
.geode/journal/transcripts/
├── s-abc123.jsonl          # 세션별 1개 파일
├── s-def456.jsonl
└── index.json              # 세션 인덱스 (session_id, started_at, event_count, summary)
```

**왜 journal/ 아래인가?** Transcript는 C2(Journal)의 상세 버전이다. Journal은 요약(runs.jsonl), Transcript는 원본.

### 3.4. 텍스트 절단 정책 (Karpathy P6 Context Budget)

| 필드 | 최대 길이 | 이유 |
|:--|:--|:--|
| user_message.text | 500자 | 사용자 의도는 짧음 |
| assistant_message.text | 500자 | 전문은 Vault에 저장됨 |
| tool_call.input | 300자 | 도구 입력은 짧음 |
| tool_result.summary | 300자 | 전체 결과는 session checkpoint에 |

### 3.5. 정리 정책

- **30일 auto-cleanup**: 30일 지난 .jsonl 파일 삭제 (REODE 패턴)
- **index.json 유지**: 삭제된 세션도 인덱스에 메타데이터 보존 (요약만)
- **크기 제한**: 개별 파일 최대 5MB (초과 시 tail 보존)

## 4. 구현 계획

### Phase 1: SessionTranscript 모듈

| # | 작업 | 파일 |
|---|------|------|
| 1 | `SessionTranscript` 클래스 | `core/cli/transcript.py` (신규) |
| 2 | AgenticLoop 통합 | `core/cli/agentic_loop.py` 수정 — 매 라운드 이벤트 기록 |
| 3 | Vault 연동 | `core/memory/vault.py` 수정 — save() 시 transcript 이벤트 |
| 4 | Journal 인덱싱 | `core/memory/project_journal.py` 수정 — transcript 인덱스 관리 |
| 5 | `geode init` 확장 | `core/cli/__init__.py` — `journal/transcripts/` 디렉토리 |

### Phase 2: CLI 노출

| # | 작업 | 파일 |
|---|------|------|
| 6 | `/transcript` 커맨드 | `core/cli/commands.py` — 세션 목록, 특정 세션 조회 |
| 7 | `/snapshot` 커맨드 | `core/cli/commands.py` — 기존 SnapshotManager CLI 노출 |

## 5. 기존 SnapshotManager 유지 전략

SnapshotManager(Tier 3)는 **게임 IP 도메인 파이프라인 전용**으로 유지한다. 범용 작업에는 Transcript(Tier 1) + Journal(Tier 2)이 대체한다.

| 컴포넌트 | 역할 | 변경 |
|----------|------|------|
| SnapshotManager | 파이프라인 GeodeState 캡처 | 변경 없음 (유지) |
| SessionTranscript | 세션 이벤트 스트림 (신규) | REODE 패턴 구현 |
| ProjectJournal | 프로젝트 수준 요약 (기존) | transcript 인덱싱 추가 |
| SessionCheckpoint | 세션 재개용 (기존) | 변경 없음 |

## 6. 프론티어 매핑

| 프론티어 | 패턴 | 적용 |
|---------|------|------|
| REODE | SessionTranscript JSONL | Tier 1 그대로 채택 |
| Karpathy P4 | Ratchet (best-so-far) | Journal learned.md tier tracking |
| Karpathy P6 | Context Budget (L1-L3) | 텍스트 절단 정책 (500/300자) |
| OpenClaw | RunLog JSONL + pruning | Transcript 30일 + 5MB 정리 |
| LangGraph | SqliteSaver per-node | Tier 3 SnapshotManager (유지) |
