# ADR -- Credential Rollout 시 Outer-Loop Checkpoint + Resume

> [English](self-improving-loop-resume-decision.md) | **한국어**

> **Status**: Accepted (2026-05-19)
> **Scope**: GEODE self-improving-loop (autoresearch + seed-generation). subscription credential(Claude Code OAuth, ChatGPT OAuth)이 실행 도중 quota에 도달하면, 운영자가 계정을 교체하고 이미 끝난 generation / candidate / match에 예산을 다시 쓰지 않으면서 **마지막으로 완료된 작업 단위부터 재개**할 수 있어야 합니다.

## 배경 (Context)

2026-05-19 self-improving-loop config 통합 계획은 strict subscription mode(`fallback_to_payg=false` 기본값)를 도입해, subscription 소진 시 PAYG로 조용히 넘어가는 대신 실행 가능한 안내 배너와 함께 중단하도록 했습니다. strict-abort 자체는 올바르지만 새로운 실패 모드를 만듭니다. 긴 self-improving-loop 실행(다세대 seed evolution 또는 overnight autoresearch ratchet)은 중단 시점에 진행 중이던 모든 것을 잃습니다. 사용자가 2026-05-19에 명시적으로 요청했습니다: "self-improving-loop 가 subscription 초과로 끊겨도, 계정 롤아웃해서 이어갈 수 있게 체크포인트와 같은 replay-resume 조치가 되어있는지 점검."

사용자는 결정 전 조사 순서도 지정했습니다: "ADR 들어가기 전에 관련 레퍼런스 디깅 + 원본인 co-scientist 의 패키지 구현본을 살펴서 이에 대한 고려가 되어있는지도 확인."

### 레퍼런스 조사 결과 (2026-05-19 agent 조사, 요약)

| 출처 | resume 지원? | 메커니즘 |
|---|---|---|
| co-scientist paper (arXiv:2502.18864) | 주장만 존재 (1문장: *"easy restarts in-case of any failure"*) | "persistent context memory" -- 메커니즘/스키마 미정의 |
| co-scientist reference impl (Swarms `AI-CoScientist`) | 부분적 / **stub 상태로 깨짐** (README TODO에 "Fix state saving" 명시) | agent별 JSON 파일. 릴리스된 코드에서 깨져 있음 |
| Karpathy autoresearch | 설계에 없음 -- `program.md`가 pause를 명시적으로 금지 | 사실상: accepted generation마다 git commit + `results.tsv`. resume = 같은 worktree에서 agent 재실행 |
| **LangGraph** | ✅ first-class | `Checkpointer` interface (SqliteSaver / MemorySaver / PostgresSaver), `(thread_id, checkpoint_id)` key, step 단위 granularity, `Command(resume=...)` semantics |
| **Inspect_ai** | ✅ first-class | `.eval` log 파일 + 안정적 sample ID + `inspect eval-retry`. sample ID = idempotency key, 기본 최대 10회 retry |
| **Stripe API** | ✅ 패턴 (`Idempotency-Key` header) | 논리 연산마다 client가 생성한 UUID, 서버가 결과를 24시간 이상 캐시, replay 시 `Idempotent-Replayed: true` |
| OpenAI Agents SDK | ❌ 명시적으로 기각 (issue #2172 not planned로 closed) | -- |
| AutoGen v0.4 | primitive만 제공 (`save_state` / `load_state`) | 정책은 구현자가 추가 |
| Hermes credential_pools | 429/402 시 auto-rotate | silent rotation. token overwrite + persistence 관련 **활성 버그 다수** (#11364 / #6907 / #15099). 프로세스 종료를 견디지 못함 |
| OpenClaw | 깨짐 (#26872 / #50791 / #51917 / #62442) | session JSONL은 있으나 재시작 시 in-flight sub-agent 작업이 유실됨 |
| AutoGPT | 기본 지원 없음 | 수동 log-backup workaround |
| CrewAI Flows | 플러그형 `FlowPersistence` (LanceDB) | `kickoff(restore_from_state_id=...)` -- 단, miss 시 silent fallback |

정리: **co-scientist는 논문에도 reference 구현에도 쓸 만한 설계가 없습니다**. 실제 prior art는 LangGraph(`thread_id` checkpointer) + Inspect_ai(안정적 sample ID + retry-idempotent) + Stripe(idempotency-key replay)이며, 배너 쪽에는 Codex CLI의 `forced_login_method`가 이미 채택돼 있습니다.

### GEODE 현재 상태 (감사 요약)

| Layer | Surface | Persist | Load | Resume-ready |
|---|---|---|---|---|
| C3 | `core/memory/session_checkpoint.py` `SessionCheckpoint` | ✅ atomic_write_json + SQLite | ✅ `load()` / `list_resumable()` | ✅ `/resume <session_id>` CLI |
| C2 | `core/memory/project_journal.py` ProjectJournal | ✅ fsync + append | tail/aggregate만 | ❌ audit 전용 |
| Outer | `~/.geode/self-improving-loop/sessions.jsonl` (P1a) | ✅ append | tail만 | ❌ index 전용 |
| Outer | `~/.geode/self-improving-loop/<session>/journal.jsonl` (P1c) | ✅ append | tail만 | ❌ event audit 전용 |
| Seed-pipeline | `<run_dir>/state.json` (S8 `_persist_state`) | ✅ write_text (non-atomic) | ❌ **`_load_state()` 미구현** | ❌ |
| Autoresearch | `~/.geode/self-improving/baseline.json` (P0a) | ✅ atomic | ✅ `_load_baseline()` | 부분적 (promote/run만) |
| Primitive | `core/utils/atomic_io.py` | tmp + `os.replace` + `fsync` | -- | ✅ |

**핵심 통찰**: GEODE에는 이미 `SessionCheckpoint`가 있습니다. `atomic_write_json` + SQLite + `/resume` CLI를 갖춘 production-ready C3 checkpoint+resume 계층입니다. self-improving-loop driver(seed-generation + autoresearch)는 아직 그 위에 얹혀 있지 않습니다. S8 `_persist_state` 주석은 *"S11 CLI `geode audit-seeds resume` will re-hydrate"*라고 말하지만 load 경로는 구현돼 있지 않습니다.

## 결정 (Decision)

**병렬 checkpoint 시스템을 새로 만들지 않고, self-improving-loop driver를 기존 `SessionCheckpoint` 위에 얹습니다.** frontier 패턴 3개를 그대로 차용합니다:

1. **LangGraph 스타일** -- `SessionCheckpoint`는 이미 `(session_id, ...)` key의 SQLite 기반 snapshot을 atomic write로 제공합니다. outer-loop는 안전한 경계에서 `SessionCheckpoint.save()`를 호출하고 resume 시 `SessionCheckpoint.load()`를 호출하기만 하면 됩니다.
2. **Inspect_ai 스타일** -- 모든 작업 단위(generation, candidate, match, audit)는 resume 시 idempotency key 역할을 하는 안정적 ID를 갖습니다. 이미 완료된 단위는 재호출 시 건너뛰고, 부분 완료 단위는 마지막 완료 step부터 재시도합니다.
3. **Stripe idempotency-key** -- (run_id, unit_id, agent_role)별 UUID를 LLM call metadata에 삽입합니다. 그 UUID를 key로 하는 로컬 response cache가 credential rollout 후의 중복 지출을 차단합니다.

credential-rollout 경계는 **사용자 주도**로 유지합니다(PR-β1에서 채택한 Codex `forced_login_method` 패턴). auto-rotation은 없습니다. 새 resume 메커니즘은 수동 교체의 비용을 "실행 전체 유실"에서 "최대 작업 단위 1개 유실"로 줄입니다.

### 굵기 -- LLM call 사이가 아니라 unit 사이에 checkpoint

autoresearch의 `git commit per generation` + co-scientist의 "Supervisor writes state periodically" + LangGraph의 super-step 경계를 따라, checkpoint는 unit 내부가 아니라 **unit 사이**에서 기록합니다.

| Driver | Unit 경계 | Checkpoint 기록 시점 |
|---|---|---|
| autoresearch | generation (= `train.py` 1회 호출 = audit subprocess 1회) | `_should_promote()` 결정 후, `_write_baseline()` 전 |
| seed-generation | phase (Generation → Proximity → Critic → Pilot → Ranker → Evolver → MetaReviewer) | `_run_phase()` 반환 후, 다음 `_run_phase()` 전 |
| Petri inner-loop | sample (seed × auditor × judge transcript 1개) | `inspect_ai` `.eval` log가 이미 처리 -- GEODE self-improving-loop는 `eval` 경로만 기록 |

unit 내부(예: LLM call 도중)에서는 "이 unit을 잃는다"를 비용 상한으로 받아들입니다. LLM call 내부의 checkpoint는 기각합니다(storage churn 대비 UX 가치 부족).

### Idempotency-key 형태

```
<run_id>::<driver>::<unit_kind>::<unit_id>::<agent_role>

Examples:
  2026-05-19T1530Z-a1b2c3 :: seed-generation :: phase     :: pilot      :: pilot-llm
  2026-05-19T1530Z-a1b2c3 :: seed-generation :: candidate :: c-007      :: critic
  2026-05-19T1530Z-a1b2c3 :: seed-generation :: match     :: m042       :: voter-haiku
  2026-05-19T1610Z-b4c5d6 :: autoresearch  :: audit     :: 7f3a9c2    :: judge
```

LLM call마다 `~/.geode/self-improving-loop/<session>/journal.jsonl`(P1c)에 기록합니다. resume 시 runtime이 journal에서 완료된 `<...key>` entry를 스캔해 건너뜁니다.

### Checkpoint에 담기는 credential context

```json
{
  "session_id": "2026-05-19T1530Z-a1b2c3",
  "gen_tag": "autoresearch-176d8778",
  "active_sources": {
    "anthropic": "claude-cli",
    "openai":    "openai-codex"
  },
  "completed_units": ["...idempotency-keys..."],
  "next_unit": {"driver": "seed-generation", "kind": "phase", "id": "ranker"},
  "fallback_to_payg": false
}
```

resume 시:

1. `resolve_credential_source(..., fallback_to_payg=cfg.fallback_to_payg)`로 source를 다시 해석합니다.
2. active source가 바뀌었으면(예: 다른 계정의 claude-cli → claude-cli), journal이 경계를 담도록 checkpoint에 `credential_rolled_over_at` marker와 함께 기록합니다.
3. 원래 실행에서 `false`였던 `fallback_to_payg`를 resume 호출에서 사용자가 명시적으로 `true`로 요청하면, runtime이 계속 진행하기 전에 journal에 `credential_policy_change` event를 남깁니다.

### 같은 source 안의 계정 rotation (paperclip / crumb 패턴)

PR-β1이 막은 cross-source PAYG 전환과는 별개의 차원입니다: **같은 `family.source` 안의 다중 계정**(예: 운영자가 둘 다 저장해 둔 Claude Code OAuth 계정 2개). 2026-05-19 사용자 지시 "paperclip, crumb 의 사례처럼 로컬에 기록된 계정 기록으로 롤아웃"이 가리키는 경우가 이것입니다. paperclip / crumb(`https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/main/sil/audit-reports/2026-05-18-i2-paperclip-review.md`, 외부 repo `~/workspace/crumb/` 참고)는 `claude -p` subprocess가 `~/.claude/credentials`를 자동으로 읽게 하고, 계정 선택은 symlink 교체 또는 env var로 처리합니다. 패턴은 **non-interactive subprocess + 로컬에 기록된 credential**입니다.

GEODE에는 이미 더 풍부한 in-process 등가물이 있습니다: `core/auth/profiles.py`(AuthProfile / ProfileStore / EligibilityResult), `core/auth/rotation.py`(`ProfileRotator.resolve(provider)`가 best-eligible 반환, `mark_failure` → cooldown, managed-token은 만료 120초 전 이내 자동 refresh), `core/auth/credential_breadcrumb.py`(ProfileRejectReason별 LLM-readable hint, Claude Code `createModelSwitchBreadcrumbs` parity). outer-loop는 현재 이 중 아무것도 쓰지 않습니다. `plugins/petri_audit/credential_source.py`는 process-local `suppress_credential_source(family, source)`만 수행합니다(profile 차원 없음).

**결정** (Phase ζ 확장):

1. **`ProfileRotator`를 self-improving-loop credential 경로에 배선합니다.**
   `resolve_credential_source(family, ..., fallback_to_payg)`는 source key(예: `claude-cli`)를 반환하고, 새 계층 `resolve_self_improving_loop_binding(family) → (source, profile)`이 두 번째 차원을 더합니다. autoresearch / seed-generation은 모든 LLM call에 `profile.name`을 전달해, 실패가 in-process suppress set 대신 `ProfileRotator.mark_failure(profile)`로 라우팅되게 합니다.

2. **Rotation은 운영자 주도이며, 절대 자동이 아닙니다.** strict-mode가 중단을 트리거하면(PR-β1의 `CredentialResolutionError(subscription_only=True)`), FE 배너(PR-γ1)가 같은 family에 대해 ProfileRotator에 다른 eligible profile이 있는지 확인합니다. 있으면 abort dialog가 2축 picker(다음 소절)를 표시합니다. 없으면 기존의 "profile 추가 / reset 대기 / PAYG opt-in" 옵션을 표시합니다.

3. **Rollout 경계는 journal에 기록합니다.** 새 active `(source, profile)`은 checkpoint에 담기고, `credential_rolled_over` event가 `~/.geode/self-improving-loop/<session>/journal.jsonl`(P1c)에 추가됩니다. LLM call별 idempotency key(PR-ζ4)에는 이미 `agent_role`이 포함되므로, 교체된 계정도 해당되는 경우 같은 cache entry를 그대로 재사용합니다.

### 계정 picker UX (2축, GEODE slash-command parity)

2026-05-19 사용자 지시 "자연어 뿐 아니라 UI/UX 로도 선택/입력 가능 (GEODE 슬래시 명령어 구조 참고). provider 변경은 좌우, 계정 선택은 위아래"에 따라, picker는 `core/cli/effort_picker.py`의 기존 `pick_model_and_effort` 패턴(Claude Code `ModelPicker.tsx` parity)을 미러링하는 2D interactive selector입니다:

```
┌─ Subscription quota exhausted — claude-cli (anthropic:work) ─────────┐
│                                                                       │
│  ◀ anthropic    openai     zhipuai ▶          (←/→ change provider)  │
│                                                                       │
│  Profiles for anthropic:                                              │
│    anthropic:work                              [exhausted]            │
│  ▶ anthropic:personal     OAuth · 0% used      [eligible]    ↑↓      │
│    anthropic:org-shared   OAuth · 12% used     [eligible]             │
│    anthropic:api-key      api_key · PAYG       [blocked by strict]    │
│    + Add new profile…                                                 │
│                                                                       │
│  [Enter] swap & resume     [n] add new     [w] wait for reset         │
│  [p] opt-in PAYG fallback (this run only)    [Esc] keep aborted       │
└───────────────────────────────────────────────────────────────────────┘
```

진입점(지시에 따라 둘 다 필수):

1. **Slash command**: 계정 추가/삭제용 `/login`은 이미 존재합니다(`core/cli/commands/login.py`). `/login picker`로 확장하거나 `/account` alias로 2축 picker를 바로 엽니다. 배너가 red(aborted 상태)일 때 자동 트리거됩니다.
2. **자연어**: agent loop가 "swap account", "use my other Claude account", "rollout to next profile" 같은 문구를 인식해 같은 picker를 programmatic하게 호출합니다.

구현은 `pick_model_and_effort`의 raw-tty 2축 입력 loop를 재사용합니다. 지시대로 **provider = ←→, 계정 = ↑↓**입니다. action row(`[Enter] / [n] / [w] / [p] / [Esc]`)가 정책 경계를 명시합니다. 자동 rotation은 없으며, 모든 교체는 사용자의 키 입력입니다.

## 비결정 (명시적으로 기각)

| 대안 | 기각 사유 |
|---|---|
| Hermes 스타일 auto credential rotation | silent rotation은 비용을 숨기고(`feedback_test_cost`와 모순), Hermes 자체 bug tracker(#11364, #6907, #15099)가 rotation logic의 취약함을 기록 |
| 병렬 checkpoint 시스템 신규 구축 | `SessionCheckpoint`가 이미 존재하고 production-ready. 그 위에 얹으면 atomic_write + SQLite + `/resume` CLI를 재사용 |
| LLM call 단위 checkpoint | storage churn / IO 비용이 미미한 UX 이득에 비해 과함. unit 경계로 충분 |
| CrewAI의 missing checkpoint ID silent fallback | `anti-deception-checklist` 위반. 대신 fail-loud |
| autoresearch "never pause" 정책 | 단일 사용자, 단일 credential ML 실행에는 유효하나 다중 credential self-improving loop에서는 깨짐 |
| 중단 시 generic 재실행 (checkpoint 없음) | 실행 전체 예산을 다시 소모. strict-mode subscription의 목적을 무력화 |

## 결과 (Consequences)

### 긍정

- subscription rollout이 전체 재시작이 아니라 일상적인 운영 동작이 됩니다.
- idempotency key는 SDK가 지원할 때 provider 측 response caching도 열어 줍니다.
- 기존 `SessionCheckpoint` 위에 쌓아 위험과 코드 표면을 줄입니다.
- frontier 패턴 3개는 대규모로 검증돼 있습니다(LangGraph, Inspect_ai, Stripe).

### 부정

- 통합 sprint에 `~1500 LOC`가 추가됩니다(phase ζ 행마다 PR 1개).
- idempotency-key 관리로 모든 LLM call이 약간 무거워집니다. 확인을 per-token이 아니라 unit-경계 hit로 제한해 완화합니다.
- unit 단위 granularity라서 credential 중단 시 **단일 unit의 진행 중 비용은 여전히 유실**됩니다. 이것이 수용한 상한입니다.

### 범위 밖 (연기)

- 병렬 resume용 multi-process file lock: v1에서는 single-resumer 가정으로 충분합니다.
- resume 시 hook replay: 전체 lifecycle 재방출 없이 `RESUME_STARTED` 1회만 방출합니다.
- cross-machine resume: checkpoint 파일은 경로 이식이 가능하지만 수동 복사가 필요합니다.

## 구현 계획

`docs/plans/2026-05-19-self-improving-loop-config-consolidation.md`의 Phase ζ로 관리합니다. **PR 8개**(~2100 LOC + backfill 1). 2026-05-19 paperclip/crumb 지시 이후 6개에서 확장:

- **PR-ζ1**: self-improving-loop 필드(active_sources, completed_units, next_unit, fallback_to_payg, active_profile)를 위한 `SessionCheckpoint` schema 확장. round-trip 테스트.
- **PR-ζ2**: `plugins/seed_generation/orchestrator.py:PipelineState`의 `_load_state()` 짝 구현. CLI flag `geode audit-seeds resume <run_id>`.
- **PR-ζ3**: autoresearch `_load_pending_audit()` + `core/self_improving/train.py`의 `--resume <session_id>` flag.
- **PR-ζ4**: LLM call metadata에 idempotency-key 삽입 + 로컬 response cache 조회(`~/.geode/self-improving-loop/<session>/idempotency.db`).
- **PR-ζ5**: credential-rollover 감지. resume 시 active source를 checkpoint와 비교하고 journal에 `credential_rolled_over_at` event를 방출.
- **PR-ζ5.5** (신규): `ProfileRotator`를 self-improving-loop credential 경로에 배선. `resolve_self_improving_loop_binding(family) → (source, profile)`이 profile 차원을 추가. `plugins/petri_audit/credential_source.py`는 실패를 in-process suppress set 대신 `ProfileRotator.mark_failure(profile)`로 라우팅. autoresearch + seed-generation은 LLM call metadata에 `profile.name`을 전달해 cooldown이 계정별로 추적되게 함.
- **PR-ζ5.6** (신규): 2축 계정 picker(provider ←→ × profile ↑↓), `core/cli/effort_picker.py` 미러. 진입점 2개: (a) `/login picker` slash command + red 배너 abort dialog 자동 트리거(PR-γ1 트리거 조건), (b) agent loop의 자연어 문구 인식기가 picker를 programmatic하게 호출. action row: Enter(교체+재개) / n(`claude /login` subprocess delegate로 새 profile 추가) / w(reset 대기) / p(이 실행에 한해 PAYG opt-in) / Esc(중단 유지).
- **PR-ζ6**: 문서 + resume run-book 샘플(`https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/main/sil/audit-reports/2026-05-19-resume-rollout-runbook.md`) + CHANGELOG.

## 레퍼런스

- co-scientist paper (arXiv:2502.18864): https://arxiv.org/abs/2502.18864 (§4.5 "persistent context memory" + §5 "Supervisor agent")
- co-scientist reference impl: https://github.com/The-Swarm-Corporation/AI-CoScientist (README TODO에 save-state 깨짐 명시)
- Karpathy autoresearch: https://github.com/karpathy/autoresearch (`train.py` + `program.md`)
- LangGraph Checkpoints: https://reference.langchain.com/python/langgraph/checkpoints
- Inspect_ai eval-retry: https://inspect.aisi.org.uk/reference/inspect_eval-retry.html
- Stripe idempotency: https://docs.stripe.com/api/idempotent_requests
- Codex CLI `forced_login_method`: https://developers.openai.com/codex/config-reference
- Hermes credential_pools (부정 레퍼런스): https://hermes-agent.nousresearch.com/docs/user-guide/features/credential-pools
- OpenAI Agents SDK issue #2172 (not planned로 closed): https://github.com/openai/openai-agents-python/issues/2172
- GEODE `SessionCheckpoint`: `core/memory/session_checkpoint.py`
- GEODE `atomic_io`: `core/utils/atomic_io.py`
- 선행 계획: `docs/plans/2026-05-19-self-improving-loop-config-consolidation.md`
- 선행 ADR: `docs/architecture/seed-generation-decision.md`, `docs/architecture/autoresearch-axis-decision.md`
