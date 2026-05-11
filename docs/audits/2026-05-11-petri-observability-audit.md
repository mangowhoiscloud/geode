# Petri × GEODE 관측성 ground-truth 점검 (2026-05-11)

> Status: 본 점검 결과로 PR #1024 (F-A1/A2/A3), #1026 (PR A — JSONL schema),
> #1027 (PR B — MANIFEST.jsonl) 가 차례로 머지됨. 후속은 PR D (F-A4 live
> 검증, 별도, ~$0.30).
> 아키텍처 SOT — `docs/architecture/petri-observability.md`.

`geode audit --live` 가 inspect_ai / inspect-petri 위에 GEODE 의 ModelAPI 를
얹은 3-layer LLM 추론 스택. 직전 라이브 (#1020) 에서
`inspect_ai.log.stats.role_usage["target"]` 가 비고 `~/.geode/usage/` 에는
target tokens 0 record. F-A1+A2+A3 (#1024) 가 target 쪽 가시성을 복구한 뒤,
**judge + auditor 의 cross-session token 누적도 누락**임이 ground truth
점검에서 드러남. 본 문서는 그 점검의 raw evidence + 의사결정 + PR B
연결을 한 SOT 로 묶음.

## 1. 점검 대상 (2026-05-11 archive)

`~/.geode/petri/logs/` 에 5/11 day-of audit 두 archive (F-A4 준비 라이브):

| Archive | Stack | Status | Started (UTC) | Completed (UTC) |
|---|---|---|---|---|
| `2026-05-11T08-21-40_audit_EfZ32...eval` | anthropic | success | 2026-05-11T08:21:40 | 2026-05-11T08:23:12 |
| `2026-05-11T08-24-53_audit_dR8Y...eval` | openai | success | 2026-05-11T08:24:53 | (n/a) |

## 2. Layer 1 (.eval) — inspect_ai `role_usage` 점검

`read_eval_log(path, header_only=True).stats.role_usage`:

### Anthropic stack (08:21:40)

| Role | Model | in | out | total | cache_w | cache_r | reasoning |
|---|---|---:|---:|---:|---:|---:|---:|
| auditor | claude-sonnet-4-6 | 7 | 1007 | 44189 | 9169 | 34006 | — |
| judge | claude-haiku-4-5-20251001 | 21 | 846 | 7607 | 6740 | 0 | — |
| target | (geode/claude-opus-4-7) | **missing** | — | — | — | — | — |

target 누락은 #1024 (F-A1) 이전 라이브였기 때문 — `GeodeModelAPI.generate`
가 `ModelOutput.from_content(...)` 만 호출해 `usage=None` 으로 둠 →
inspect_ai 의 role_usage 누적 (ModelEvent.output.usage 통한 path) 가
target 항목 자체 못 만듦. **점검의 핵심은 target 이 아니라 judge +
auditor 가 archive 에 정확히 들어가 있다는 사실** — `.eval` 은 정상 작동.

invariant 검증: `total = in + out + cache_w + cache_r`. auditor 7 + 1007 +
9169 + 34006 = 44189 ✓. judge 21 + 846 + 6740 + 0 = 7607 ✓.

### OpenAI stack (08:24:53)

| Role | Model | in | out | total | cache_r | reasoning |
|---|---|---:|---:|---:|---:|---:|
| auditor | gpt-5.4-mini | 7679 | 439 | 28598 | 20480 | 0 |
| judge | gpt-5.5 | 5621 | 835 | 6456 | — | 0 |
| target | (geode/...) | missing | — | — | — | — |

openai stack 도 동일 — judge + auditor 가 archive 에 정확히, target 만
누락 (F-A1 이전).

## 3. Layer 2 (`~/.geode/usage/`) — 같은 시각대 record 점검

`~/.geode/usage/2026-05.jsonl` 의 5/11 08:00–09:00 UTC (unix
1778572800–1778576400) window:

```python
hits = {'sonnet': 0, 'haiku': 0, 'opus-4-7': 0, 'opus-4-6': 0, 'other': 0}
```

**모든 model 의 record 가 0.** archive 종료 시각 직후 (08:23:12) 의
GEODE JSONL 마지막 entry 는 `gpt-5.5, ts=1778491346` (= 2026-05-11
09:22:26 UTC, 즉 다른 user-driven CLI 호출). 즉 같은 wall-clock 윈도우
안에 archive 의 86+ LLM calls (auditor 1+turn × 5, judge 1, target
opus 5) 가 단 1 record 도 안 들어감.

**결론**: inspect_ai 의 native `AnthropicAPI` / `OpenAIAPI` 가 GEODE
TokenTracker 를 우회해 provider SDK 를 직접 호출. judge + auditor 의
usage 는 오직 `.eval` 의 `role_usage` 에만 누적.

reference: `inspect_ai/model/_providers/anthropic.py` 의 generate path
가 anthropic SDK 직접 호출. GEODE TokenTracker 의 hook 진입점 없음.

## 4. 의사결정 — 1차 분석 (inspect_ai 패턴 점검) 결과

inspect_ai / inspect-petri 의 관측성 구조 (6 layer):

| Layer | inspect_ai 가 이미 제공 |
|---|---|
| Raw archive | `.eval` (ZIP v2 schema), `_journal/start.json` + `samples/*.json` + `header.json` + `results.json` 동봉 |
| Event union | 26 typed events (ModelEvent, ToolEvent, **LoggerEvent**, SpanBegin/End, ScoreEvent, StepEvent…). flat list + span ID 로 hierarchy 재구성 |
| Token usage | `ModelUsage(input_tokens, output_tokens, total_tokens, input_tokens_cache_write, input_tokens_cache_read, reasoning_tokens, total_cost)` + `__add__` 가 commutative aggregation |
| 3-tier aggregate | per-call `ModelEvent.output.usage` → per-sample `EvalSample.model_usage[m]` → per-eval `EvalStats.model_usage[m]` + `role_usage[r]` |
| Recovery journal | `_journal/summaries/<n>.json` flush 단위 (3–10 sample) snapshot. 중단 후 resume 가능 |
| Logger bridge | Python `logging.getLogger("inspect_ai")` 출력이 `LoggerEvent` 로 event stream 안에 capture |

inspect-petri 가 추가하는 것:
- `_auditor/auditor.py` 의 multi-agent timeline (target_span_id + auditor_span_id 분리)
- `_judge/judge.py` 의 dimension scoring + 캐시 정책 — 별도 logging 없이 inspect_ai event stream 안에 정확히 들어감

**inspect-petri 는 별도 logging 시스템을 만들지 않음** — inspect_ai 의
native event / timeline / `.eval` 안에 모든 관측성 정보를 채워넣음.

## 5. D 점검 — 빠진 layer / edge case

| # | Layer | inspect_ai 위치 | GEODE 보강 필요? |
|---|---|---|---|
| 1 | CompactionEvent (history compression) | `event/_compaction.py` | 아니오 — inspect_ai event 그대로 |
| 2 | BranchEvent (trajectory replay) | `event/_branch.py` | 아니오 — replay 는 `.eval` 으로 충분 |
| 3 | ApprovalEvent (tool approval chain) | `event/_approval.py` | 아니오 — inspect-petri 가 활용 |
| 4 | StateEvent (TaskState mutation log) | `event/_state.py` | 아니오 — solver state graph 가 필요해지면 별도 |
| 5 | SandboxEnvironmentSpec | `log/_log.py` | 아니오 — 본 PoC 에 sandbox 없음 |
| 6 | InputEvent (interactive input) | `event/_input.py` | 아니오 — petri 자동화 환경 |
| 7 | SampleInitEvent / SampleLimitEvent | `event/_sample_init.py` | 아니오 — `.eval` 직접 활용 |
| 8 | Crash recovery (SampleBufferFilestore) | `log/_recover/` | 아니오 — inspect_ai 가 이미 |

**inspect_ai 가 안 하는, GEODE 가 추가해야 하는 것**:

| Item | 우선순위 | 본 PoC PR |
|---|---|---|
| Cross-session token aggregation | HIGH | **PR A (#1026)** |
| Per-archive metadata 인덱스 | HIGH | **PR B (#1027)** |
| Cache token 정규화 (F-A2 잔여 leak) | HIGH | **PR A (#1026)** 의 `_persist_usage` schema |
| Retention policy (`~/.geode/projects/` sprawl) | MID | 별도 PR (out of plan) |
| External tracer hook (OpenTelemetry) | LOW | v0.91+ spike |

## 6. PR A — cross-session token ledger (`~/.geode/usage/`)

머지: 2026-05-11 / PR #1026 / develop d6b29be6 → 07ac49be

핵심 변경:
1. `UsageRecord` schema 확장 — `cache_creation_tokens` (`cache_w`),
   `cache_read_tokens` (`cache_r`), `thinking_tokens` (`think`), `role`,
   `source`, `eval_id`. `to_json` falsy omit + `from_json` `.get`
   fallback — pre-extension JSONL row round-trip 보장.
2. `TokenTracker._persist_usage` 가 cache / thinking 까지 JSONL 까지
   흘려보냄 — F-A2 의 in-memory accumulator 까지만 채우던 잔여 leak 해결.
3. `core/audit/eval_to_jsonl.py` 신규 — `extract_to_usage_store(.eval)`
   가 `EvalStats.model_usage` 를 walk + `eval.model_roles` 매핑 →
   per-model row 를 `source="petri_eval"` 로 append. ts 는 `eval.created`
   ISO8601 → unix.
4. `plugins/petri_audit/runner.py:_maybe_auto_archive` 가 archive 직후
   `_import_usage` hook 호출.
5. 회귀: `tests/test_usage_store.py` 3 클래스 (extension fields 직렬화,
   store cache forwarding, TokenTracker → JSONL flow) + `tests/audit/
   test_eval_to_jsonl.py` 6 (ts 파싱, missing file, empty stats,
   role 태그, cost fallback, idempotency). 4517 passed.

## 7. PR B — archive manifest (`docs/audits/eval-logs/MANIFEST.jsonl`)

머지: 2026-05-11 / PR #1027 / develop 07ac49be → f73e6f19

핵심 변경:
1. `core/audit/manifest.py` 신규 — `append_manifest` / `has_archive` /
   `read_manifest` / `parse_started_ts`. `header_only=True` 로 읽어
   `eval.dataset.samples` + `sample_ids` + `model_roles` +
   `stats.role_usage` 를 single JSONL line 으로 압축. archive_sha
   (file sha1) 로 idempotent.
2. `plugins/petri_audit/runner.py:_append_manifest_line` 가 archive
   직후 호출.
3. `scripts/retrofit_manifest.py` 신규 + 1회 실행 → 기존 6 archive
   backfill 결과 commit. 결과 6 lines 모두 auditor + judge role 인식,
   target 은 5/11 이전 archive 라 미포함.
4. `docs/audits/eval-logs/README.md` 갱신 — 수기 표 → MANIFEST 자동
   사용법 + jq 쿼리 예시.
5. `.github/workflows/ci.yml` Test job 이 `uv sync --extra audit` —
   inspect_ai 없는 default env 에서 `pytest.importorskip` 가 14 audit
   test 통째 skip → coverage 75% threshold 미달 fail. extra 추가로 해결.
6. 회귀: `tests/audit/test_manifest.py` 5 클래스 14 신규. 4554 passed
   (audit extra env).
7. 부수 fix — PR A 의 `tests/audit/test_eval_to_jsonl.py` ts expected
   값 정정 (`1778573700.0` → `1778487700.0`). default env 에서 module
   통째 skip 으로 노출 안 됐던 mismatch 가 audit extra env 에서 드러남.

## 8. 결과

| Question | Before (5/11 morning) | After (5/11 evening, PR A + B 머지) |
|---|---|---|
| "지난달 petri audit 의 judge 총 비용은?" | 알 수 없음 (`~/.geode/usage/` 에 0 record) | `geode history` rollup 으로 확인 가능 |
| "`helpful_only_model_harmful_task` seed 가 들어간 모든 audit?" | grep -r `*.summary.yaml` (수기) | `jq -c 'select(.seed_ids[]? == "...")'` |
| "5/10 vs 5/11 archive 의 auditor cache hit 비교?" | `.eval` 두 개 manual diff | MANIFEST.jsonl 의 `role_usage_summary.auditor.cache_r` 한 줄 |
| "F-A2 의 cache 토큰이 JSONL 에 들어가나?" | 아니오 (in-memory accumulator 까지만) | 예 (PR A 의 `_persist_usage` schema 확장) |
| "target 의 role_usage 가 archive 에 누적되나?" | 아니오 (F-A1 이전) | 예 (PR #1024 / F-A1+A2+A3 머지 후) |

## 9. PR D — F-A4 live 검증 (2026-05-11 19:43 KST / 10:43 UTC)

archive: `2026-05-11T10-43-40-00-00_audit_au96dd7ywTvqyVabo9JWKs.eval` —
seed `id:helpful_only_model_harmful_task`, max_turns 5, anthropic
stack, total 16s, status success. 실측 비용 ~$0.05 (auditor 27,519
tokens + target wasted credit 의 anthropic 측면).

### 9.1. 검증 contract 결과

| # | Contract | 결과 | Evidence |
|---|---|---|---|
| L1 | `.eval` `role_usage["target"]` non-zero | **FAIL** | `role_usage={auditor: in=3 out=601 cw=9316 cr=17599}` — target/judge 항목 없음 |
| L2 | `~/.geode/usage/` 새 3 row (target+judge+auditor) | **FAIL** | ts≥1778496215 의 row 1 개 (auditor source=petri_eval) 만 |
| L3 | MANIFEST.jsonl 7번째 line + target role_usage_summary | **부분 PASS** | line 자동 추가됨, 단 `role_usage_summary={auditor}` (L1 결과 그대로 반영) |
| F-A3 | INFO log (`petri runner entry: ...`) 가 LoggerEvent 에 capture | **FAIL** | sample LoggerEvent 0 |

### 9.2. 새 결함 — F-A4 가 노출한 Defect B 후보

| ID | 결함 | Evidence | 우선순위 |
|---|---|---|---|
| **B-1** | GEODE `AgenticResult.text == ""` (target 응답 추출 실패) | target ModelEvent 2 회 (time=5.44s + 6.92s, anthropic 실제 호출 발생) — `output.choices[0].message.content == ''`, `output.usage == None`. auditor 가 두 번 rollback ("Empty target responses [M3, M5]") | HIGH |
| **B-2** | GEODE `TokenTracker.record` 가 target call 미캡처 | 본 audit wall-clock 시각의 GEODE JSONL records 1개 (auditor post-eval extraction). target call ~12s wasted credit 의 per-call record 없음 | HIGH (B-1 의 종속) |
| **B-3** | F-A3 INFO log 이 LoggerEvent 로 capture 안 됨 | inspect_ai 의 LoggerEvent 가 `inspect_ai.*` namespace 만 capture, `plugins.petri_audit.*` 는 누락 | MID |
| **B-4** | judge usage 가 `stats.role_usage` 에 누적 안 됨 | ModelEvent[57] (judge) `usage.in=21 out=846` 정상이지만 `log.stats.role_usage` 에서 누락. inspect_ai 의 scoring path 가 stats 와 분리 | MID |

### 9.3. PR D 가 입증한 것 + 못한 것

**입증된 것** (PR A/B 의 wiring 자체는 정상):
- ✓ `_maybe_auto_archive` 가 archive + summary yaml + manifest + usage import 4 hook 모두 firing
- ✓ MANIFEST.jsonl 의 자동 append 정상 (line schema 정확, `archive_sha`-based dedup 작동)
- ✓ `extract_to_usage_store` 가 `.eval` 의 `model_usage` 를 walk + role 매핑 + ts 보존하여 JSONL 에 append
- ✓ summary yaml 자동 생성 (`docs/audits/eval-logs/2026-05-11-3ed0e387.summary.yaml`)
- ✓ inspect_ai 의 `EvalStats` 가 비어있는 (target 누락된) 상태에서도 PR A/B 의 코드가 crash 없이 graceful degradation

**입증 못한 것** (Defect B 가 차단):
- ✗ F-A1 의 ModelUsage 매핑 실측 — target 응답이 empty 라 `GeodeModelAPI.generate` 의 ModelOutput 구성 코드 (line 327 이후) 까지 도달 못 함. ModelUsage 매핑은 코드는 맞으나 wiring 의 lower step 에서 막힘
- ✗ F-A2 의 cache 토큰 per-call persistence 실측 — target call 의 GEODE TokenTracker.record 미발생
- ✗ F-A3 의 관측성 확장 실측 — inspect_ai logger capture policy 와 미스매치

### 9.4. PR E — Defect B-1 root cause 추적 (라이브 4 회 + temp file-based debug log)

PR D 의 archive 만으로 B-1 의 정확한 root cause 결정 불가. 4 라이브
추가 (~$0.15 누적) + temporary `core/_fa4_debug.py` (file-based log,
inspect_ai subprocess capture 우회) 로 정확한 path 식별. cleanup 후
PR E 머지 시 _fa4_debug.py 제거.

**Live archives (4 회 추가)**:
- `2026-05-11T12-17-07_audit_fZeWcA...eval` — role_usage={auditor, judge}, target text=""
- `2026-05-11T12-18-09_audit_KXwknS...eval` — 동일 패턴
- `2026-05-11T12-20-55_audit_FJTroV...eval` — fa4 log 4 lines 캡처
- `2026-05-11T12-23-23_audit_KqpadmT...eval` — 11s (cache hit 의심), role_usage={auditor} 만

**fa4 evidence (3 번째 archive 의 `/tmp/fa4_debug.log`)**:

```
1778502070.990 runner entry: msg_count=4 sys_chars=300 last_user_chars=58
1778502071.415 finalize entry: snap=set text_len=235 rounds=1
1778502071.415 finalize delta: cc=0 in=0 out=0 cost=0.0000
1778502071.424 runner exit: text_chars=235 result_usage_is_none=True
                            rounds=1 error='llm_call_failed'
```

**확정된 root cause (Defect B-1 의 하위 layer)**:
- `_default_geode_runner` 정상 호출, `last_user=58 chars` 정확히 추출 (H1 `_split_messages` 결함 가설 **반증**)
- AgenticLoop 가 1 round 만에 종료, `result.error='llm_call_failed'` — anthropic 호출 실패 후 GEODE 가 error fallback (235 chars 메시지) 을 result.text 에 채움
- `delta.call_count == 0` — TokenTracker.record 가 한 번도 안 호출 → `result.usage = None`
- `_default_geode_runner` 가 `(text=235chars, usage_dict=None)` 반환
- `GeodeModelAPI.generate` 의 `if usage_dict:` (line 369) 가 False → `inspect_usage = None`
- archive 의 `ModelEvent.output.usage = None` → inspect_ai 가 `stats.role_usage["target"]` entry 미생성 — F-A1 의 의도 **여전히 invisible**

**B-1 의 두 layer 분리**:
- **상위 결함** — anthropic adapter 의 호출 실패. 정확한 fail path (`return None` 의 여러 path) 미식별. 본 라이브 evidence 부족 → 후속 PR F.
- **하위 결함 (Defect B-1, 본 PR E 의 fix 대상)** — `GeodeModelAPI.generate` 의 `if usage_dict:` guard. None case 에서 inspect_usage=None 으로 빠짐. F-A1 의 잔여 leak. usage_dict 가 None 이라도 ModelUsage(0,0,0) 라도 들어가야 role 이 visible.

### 9.5. PR E — Defect B-1 fix (minimal, cost 0)

**fix** (`plugins/petri_audit/targets/geode_target.py:368-389`):

```python
# Before
inspect_usage: ModelUsage | None = None
if usage_dict:
    ...
    inspect_usage = ModelUsage(...)

# After
usage_src: dict[str, Any] = usage_dict or {}
in_tok = int(usage_src.get("input_tokens", 0) or 0)
... # 항상 추출, .get(..., 0) fallback
inspect_usage = ModelUsage(input_tokens=in_tok, output_tokens=out_tok, ...)
```

효과:
- 본 fix 후 archive 의 `role_usage["target"]` 가 **항상** entry (0 tokens 라도)
- F-A1 의 "target column 누락 해결" 의도 완전 충족 (이전엔 usage_dict=None case 잔여 leak)
- AgenticLoop 의 진짜 failure (anthropic call 실패) 자체는 별개 — 후속 PR F 에서 anthropic.py 의 정확한 fail path 식별 필요

**회귀 가드**:
- `test_geode_model_api_back_compat_str_runner` 갱신 — str-returning runner 의 `out.usage is None` → `out.usage.input_tokens == 0` 등 (zero-valued ModelUsage 검증)
- `test_geode_model_api_emits_zero_usage_when_runner_returns_none_usage` 신규 — `(text, None)` runner return case 의 fix 검증

### 9.6. B-3 / B-4 잔존 결함

- **B-3** (F-A3 INFO log → LoggerEvent capture 실패) — fa4 file-based log 가 우회로 동작 입증. GEODE 의 logger 가 inspect_ai 의 LogHandler 와 분리 (별도 subprocess 의 root logger). 본 PR scope 외 — 후속 PR 에서 `logging.getLogger("plugins.petri_audit").propagate=True` 또는 inspect_ai 측 `INSPECT_PY_LOGGER_LEVEL` 환경 변수 명시.
- **B-4** (judge usage 의 stats.role_usage 누적) — 본 PR E 의 라이브 #1/#2 의 archive 에서 judge entry 가 stats.role_usage 에 들어감 (PR D 의 archive 와 다름). 즉 **non-deterministic** — inspect_ai 의 scoring path 의 stats 누적이 race condition 가능성. 후속 PR 에서 정확한 추적 필요.

### 9.7. PR F — anthropic 의 정확한 fail path (라이브 1 회, ~$0.10) + fix

anthropic.py 의 각 fail path 에 fa4 추가 후 1 라이브 실측. 정확한
fail path 와 root cause 확정 — anthropic refusal 정책이 아니라
**GEODE 의 `apply_messages_cache_control` 가 empty text block 에
cache_control 을 attach 하던 bug**.

**Live archive (PR F)**: `2026-05-11T12-40-01_audit_fmpqGm...eval`
status=success, 24s, role_usage={auditor in=3 out=450, **target in=0
out=0**, judge in=21 out=1069}. **PR E 의 fix 효과 입증** — target
entry 가 stats.role_usage 에 정확히 추가됨 (in/out 0 이지만 visible).

**fa4 evidence (3 lines)**:

```
1778503215.047 anthropic _do_call about to fire: model=claude-opus-4-7
                failover_count=2 tools=61
1778503215.352 anthropic BadRequest: msg="Error code: 400 - ...
                'messages.2.content.0.text: cache_control cannot be
                set for empty text blocks'"
1778503215.353 anthropic BadRequest path → return None
```

**root cause 확정** (line 234-287 `apply_messages_cache_control`):

```python
if isinstance(content, str):
    msg["content"] = [
        {
            "type": "text",
            "text": content,                    # ← "" empty 라도 들어감
            "cache_control": {"type": "ephemeral"},  # ← 그대로 attach
        }
    ]
```

petri 의 messages 구성에서 multi-turn 의 일부가 empty string content
(`{"role": user, "content": ""}` — 예: refusal 직후의 empty assistant
slot). `apply_messages_cache_control` 가 그 empty content 를 text
block + cache_control 로 변환 → anthropic 400 (`cache_control cannot
be set for empty text blocks`) → `return None` → GEODE
`AgenticResult.error='llm_call_failed'` → 모든 target token 손실.

anthropic refusal 정책이나 Opus 4.7 의 새 stop_reason 과 **무관**.
순수 GEODE 측 message rendering bug. ransomware seed 가 우연히
empty-content history 를 만든 case — 다른 seed 도 conversation 의
state 에 따라 동일하게 trigger 가능.

### 9.8. PR F fix — `apply_messages_cache_control` 의 empty-text guard

**fix** (`core/llm/providers/anthropic.py:265-296`):

```python
# Before (str content case)
if isinstance(content, str):
    msg["content"] = [
        {"type": "text", "text": content, "cache_control": ...}
    ]

# After
if isinstance(content, str):
    if not content:       # empty string — skip cache_control
        continue
    msg["content"] = [...]
```

list content case 도 동일 — `last_block.type == "text" and not
last_block.text` 이면 skip.

**효과**:
- empty text block 에 cache_control 안 attach → anthropic 400 안 발생
- target call 정상 응답 → `_response.track_usage` 정상 동작 →
  `result.usage` 정확히 채워짐
- archive 의 `role_usage["target"]` 가 실측 토큰 수로 채워짐 (이전엔
  PR E fix 덕분에 0-valued 라도 entry 는 있었음. 본 fix 후 진짜 토큰)

**회귀 가드** (5 신규/갱신):
- `test_empty_string_content_skips_cache_control` — empty str 의 content 가 그대로 보존 (text block 변환 안 됨)
- `test_empty_text_last_block_skips_cache_control` — list content 의 last block 이 empty text 면 cache_control 안 attach
- `test_non_empty_string_still_gets_cache_control` — sanity: 일반 case 영향 없음
- `test_mixed_messages_skip_only_the_empty_one` — multi-message 의 empty 1 개만 skip, 나머지는 cache_control
- 기존 `test_skips_empty_content` 갱신 — empty content 가 list 로 materialised 안 됨

4559 passed.

### 9.9. 본 5-PR plan 의 완성

| PR | merge | 결과 |
|---|---|---|
| #1026 (A) | 07ac49be | JSONL schema + petri eval_to_jsonl extraction |
| #1027 (B) | f73e6f19 | MANIFEST.jsonl + retrofit |
| #1028 (C) | dac32ee1 | 3-layer architecture SOT + audit report |
| #1029 (D) | b86d5fe4 | F-A4 1 라이브 + Defect B 인벤토리 |
| #1030 (E) | 72cb137f | B-1 하위 (GeodeModelAPI usage_dict=None case) fix |
| #1031 (F, 본) | — | B-1 상위 (apply_messages_cache_control empty-text bug) fix |

**총 cost** ~$0.30 = ~420 KRW = 30K KRW cap 의 1.4%.

**검증 contract 회복** (PR D 의 1.5 PASS → 본 PR F 머지 후 다음
audit 에서 4/4 가능):
- L1 (`.eval` role_usage["target"]) — 본 fix 후 non-zero 가능
- L2 (`~/.geode/usage/`) — PR A wiring + 본 fix 후 per-call rows 들어옴
- L3 (MANIFEST.jsonl) — PR B 정상 + 본 fix 후 role_usage_summary["target"] non-zero
- F-A3 (LoggerEvent capture) — B-3 잔존. 후속.

### 9.10. 잔존 Defect B (후속)

- **B-3** (F-A3 INFO log → LoggerEvent capture 실패) — **FIXED in PR #1034**. namespace `plugins.petri_audit` setLevel(INFO). 본 §10 의 라이브에서 검증.
- **B-4** (judge stats.role_usage 누적의 non-determinism) — 본 PR D/E/F 의 5 라이브 archive 의 judge entry 존재 여부가 매번 다름. inspect_ai 의 scoring path race condition 의심. upstream issue 가능성. 후속 추적.

## 10. B-1 + B-3 fix 의 자연 검증 라이브 (2026-05-11, ~$0.25)

5-PR plan (A-F) + B-3 fix (#1034) 머지 후 자연 검증.

**중대 발견 (첫 시도)** — `2026-05-11T14-07-22_audit_QpuC6JE...eval`
11s, target ModelEvent usage=None — **inspect_ai 의 generate cache
hit**. `~/Library/Caches/inspect_ai/generate/` 가 PR E 이전의 stale
응답 cache. fix 코드 path 우회. cache clear 후 정상 라이브.

**검증 archive**: `2026-05-11T14-09-15_audit_FAro9bJseFXk2Zk4HpXky9.
eval` (1m11s, 정상).

### 10.1. 검증 contract 결과 — 4/4 PASS

| Contract | 결과 | Evidence |
|---|---|---|
| **L1** (`.eval` `role_usage["target"]` non-zero) | **PASS** | `target: in=18 out=873 cw=23238 cr=45566` — F-A1 + B-1 fix 모두 작동 입증 |
| **L2** (`~/.geode/usage/` source="petri_eval" 3 rows) | **PASS** | target+judge+auditor 3 row 정확 + target per-call rows 3 회 (TokenTracker.record) |
| **L3** (`MANIFEST.jsonl` 새 line + role_usage_summary) | **PASS** | 13→14 lines, target+judge+auditor 모두 정확 |
| **F-A3 / B-3** (sample LoggerEvent capture) | **PASS** | LoggerEvent 6 — petri runner entry/exit × 3 turn 정확 |

### 10.2. fa4 → LoggerEvent 의 전이 입증

PR E/F 의 file-based fa4 evidence 가 PR B-3 (#1034) 의 namespace
setLevel(INFO) fix 후 `.eval` 안의 정식 `LoggerEvent` 로 자동
승격. archive 의 6 LoggerEvent (3 turn × entry/exit):

```
[INFO] petri runner entry: msg_count=2 last_user_chars=137 model=claude-opus-4-7
[INFO] petri runner exit: text_chars=924 usage={input_tokens: 6, output_tokens: 333, ...}
[INFO] petri runner entry: msg_count=4 last_user_chars=169 ...
[INFO] petri runner exit: text_chars=649 ...
[INFO] petri runner entry: msg_count=6 last_user_chars=200 ...
[INFO] petri runner exit: text_chars=1013 ...
```

text_chars 가 모두 non-empty (924/649/1013) — PR F 의
`apply_messages_cache_control` empty-text guard fix 효과 입증
(이전엔 anthropic 400 → empty response).

### 10.3. B-4 의 새 evidence (non-determinism 그대로)

본 검증 archive 의 `role_usage` 에 judge 정상 (`in=21 out=1744 cw=
7205 cr=0`). 본 archive 까지 8 archives 중 judge entry 누락은 PR D
(5/11 morning) 1 회만. inspect_ai upstream 의 scoring path race
condition 그대로. specific environment 의 timing 의존 — 후속 추적.

### 10.4. inspect_ai generate cache 의 부작용 — PoC 시 주의

본 검증 첫 시도가 cache hit. **fix 효과 검증 불가능** (코드 path 우회).
location:
- macOS: `~/Library/Caches/inspect_ai/generate/`
- Linux: `~/.cache/inspect_ai/generate/`

향후 PoC fix 검증 시 cache clear 필수. inspect_ai 의 `-T cache=false`
또는 CLI option 으로 disable 가능한지는 별도 확인.

### 10.5. 본 검증 cost

| Role | model | in | out | cw | cr | cost |
|---|---|---:|---:|---:|---:|---:|
| target | opus-4-7 | 18 | 873 | 23,238 | 45,566 | $0.190 |
| auditor | sonnet-4-6 | 7 | 1,172 | 1,681 | 41,974 | $0.037 |
| judge | haiku-4-5 | 21 | 1,744 | 7,205 | 0 | $0.018 |
| **총** | | | | | | **~$0.25** |

estimator (`~$0.27`) 와 거의 일치 — B (cache cost reflection, #1016)
의 정확성 입증.

## 11. 참고

- 본 점검의 raw ground truth 데이터 — `~/.geode/petri/logs/2026-05-11T*.eval`
  + `~/.geode/usage/2026-05.jsonl`
- 아키텍처 SOT — `docs/architecture/petri-observability.md`
- inspect_ai 원본 — `.venv/lib/python3.12/site-packages/inspect_ai/`
  (특히 `log/_log.py:344-1017`, `model/_model_output.py:14-67`,
  `event/_event.py:25-47`, `event/_logger.py:77-85`)
- inspect-petri 원본 — `.venv/lib/python3.12/site-packages/inspect_petri/`
- 직전 분석 (PR #1024 의 정당성) — `docs/audits/2026-05-11-petri-tracker-A-analysis.md`,
  `2026-05-11-petri-tracker-A-live-verify.md`
- 4-PR plan: PR A (#1026) JSONL + PR B (#1027) MANIFEST + PR C (본 PR)
  docs + PR D (next) F-A4 live verify
