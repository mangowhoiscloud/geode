# 핸드오프 — observability / hook taxonomy 작업

작성 2026-07-30. 이 문서 하나로 다음 세션이 이어받을 수 있게 쓴다.
읽는 순서는 §1 현재 상태 → §2 지금 해야 할 것 → §3 배경이다. §4~§6은 필요할 때 참조한다.

---

## 1. 현재 상태

### 1.1 브랜치

| ref | SHA | 비고 |
|---|---|---|
| `origin/main` | `cabff1adb` | **v1.0.8** 릴리스 반영됨. Pages 배포 success |
| `origin/develop` | `d0eb411ed` | main과 내용 동일 (아래 1행 제외) |
| `feature/hook-taxonomy-fold` | `af9015655` | **PR #2832 미머지**. CI 11/11 green |

`main`과 `develop`의 유일한 차이는 `docs/progress.md` 1행이다. main에만 있고 develop에 없는데,
`progress.md`는 main에서 유지되는 추적 문서이고 CLAUDE.md CANNOT이 feature/develop에서의 수정을
금지하므로 **gitflow가 예상하는 드리프트다. 고치려 들지 말 것.**

### 1.2 PR

| # | 상태 | 방향 | 내용 |
|---|---|---|---|
| 2828 | MERGED | feature → develop | K3형 trajectory 투영, `call_id` 관통, run 경계 복원 |
| 2829 | MERGED | feature → develop | `scripts/preflight.sh` (CI 게이트 15개 로컬 패리티) |
| 2830 | MERGED | release → develop | v1.0.8 스탬프 + CHANGELOG 승격 |
| 2831 | MERGED | develop → main | v1.0.8 통과 머지 (merge commit) |
| **2832** | **OPEN** | feature → develop | **action family 27→13, 계약 통합, schema version** |

### 1.3 worktree

```
.claude/worktrees/hook-taxonomy-fold          ← 이번 작업. PR #2832
.claude/worktrees/portfolio-bilingual-surface ← 무관, 손대지 않음
.claude/worktrees/slack-socket-mode           ← 무관
.claude/worktrees/stateflow-followup-handoff  ← 무관
```

### 1.4 머신 상태 (이 세션에서 바꾼 것)

- `pre-commit install` 완료. `core.hooksPath`가 기본값과 같은 값으로 설정돼 있어 설치를 막고
  있었고, 해제 후 설치했다. 되돌리려면 `uv run pre-commit uninstall`.
- `~/workspace/hermes-agent`와 `~/workspace/codex`를 `git fetch`했다. 체크아웃 자체는
  옛 커밋(각각 11,024 / 769 커밋 뒤)에 있으므로 **읽을 때 반드시 `git show origin/main:<path>`를
  쓸 것.** 작업 트리를 읽으면 두 달 전 설계를 현재로 오인한다.
- `uv sync --extra audit` 실행. 이것 없이는 `tests/plugins/seed_generation/` 4건이
  `ModuleNotFoundError: inspect_ai`로 실패한다 (코드 결함 아님).

---

## 2. 지금 해야 할 것

### 2.1 PR #2832 머지 (준비 완료)

CI 11/11 green, Codex 감사 반영 완료. gitflow의 게이트를 그대로 쓴다.

```bash
test "$(gh pr checks 2832 | grep -cE 'fail|pending')" -eq 0 && gh pr merge 2832 --squash
```

머지 후 정리:

```bash
git worktree remove .claude/worktrees/hook-taxonomy-fold --force
git branch -D feature/hook-taxonomy-fold
git push origin --delete feature/hook-taxonomy-fold
git fetch origin --prune && git branch -f develop origin/develop
```

`[Unreleased]`에 항목이 쌓여 있으므로 **main 반영은 릴리스를 거쳐야 한다** (§4.2).

### 2.2 다음 작업 후보 — 측정된 순서

**A. payload 계약 나머지 38종** (PR #2832 §6이 남긴 것)

현재 18/56이다. 수기 4종 + pydantic `details_cls` 14종의 합집합이고, 나머지 38종은 계약이 없다.
family 단위 공통 필수키는 **실데이터에서 성립하지 않는다** — `mcp`의 `server_name`과 `cognitive`의
5개를 빼면 family 안에서 100% 등장하는 키가 없다. 이벤트별로 `details_cls`를 추가하는 방향이라야
한다.

**B. 구독자 0 / payload 구성 게이팅** (A 이후)

`_validate_payload`는 계약이 없으면 즉시 반환한다. 현재 52/56이 그 경로라 무비용이지만 **A가 이
비용을 만든다.** A 착지 후 dispatch 지연을 재고 판단한다. Hermes의 `has_hook()`은 그대로 옮겨지지
않는데 `HookPersistenceSink`가 항상 등록돼(`core/wiring/bootstrap.py:158`) 구독자 수가 0이 되지
않기 때문이다. 게이팅 대상은 구독자가 아니라 비싼 payload 구성이어야 한다.

**C. GEODE의 turn 키 발급**

trajectory 투영에 `turn_id` 필드가 있으나 GEODE는 항상 빈 값이다. Codex는 raw item 기준 65.8%,
Hermes는 `turn_id`+`api_request_id`를 분리해 갖는다. `run_id`는 **실행 경계이지 턴이 아니므로**
대체할 수 없다 (한 실행 안에 여러 턴). 발급 지점은 agent loop의 턴 시작이고 쓰기 층을 건드린다.

**D. `messages` 툴 호출 누락 36건 원인 규명**

`transcript` ↔ `sessions.db:messages` 교집합 7,061 세션 중 36건(0.51%)에서 툴 호출 수가 다르고,
방향은 대부분 `messages`가 적다. `docs/trajectory-redesign.md` §6.3에 기록돼 있다. `messages`를
정본으로 삼는 어떤 설계든 이것이 선결 과제다.

**E. `evidence/` 보존 정책**

341MB에 정책이 없어 무한 증가한다. transcript는 30일 + 5MB 절단, `hook_events`는 retention class
3종이 있는데 evidence만 없다.

### 2.3 하지 말 것

- **`mirror_transcript` 기본값 뒤집기** — 52/56이 `True`지만 transcript 1,009,468행 중 HookEvent
  이름과 일치하는 행이 12행(0.0012%)이다. 측정된 비용이 없다. 다시 열 조건은 hook 영속화가 실제
  활성화되어 transcript 행이 유의미해질 때다.
- **`HookEvent` 이벤트 가지치기** — 56종 전부에 프로덕션 발화지가 있다 (참조 0회 0종).
- **`HookEvent` enum 값 변경** — `hook_events` 행과 `LEGACY_EVENT_VALUES` 8쌍이 값에 결속돼 있어
  3세대 alias가 쌓인다. `action`만 바꾸는 현재 방식이 alias를 한 층으로 끝낸다.
- **`messages`를 이력 정본으로 승격** — `save_messages`가 `(session_id, seq)` UPSERT 뒤 현재 목록
  밖의 seq를 DELETE하는 **거울**이다. 호출부도 "JSON above remains authoritative"라고 적고 실패를
  WARN으로 삼킨다.

---

## 3. 배경 — 이 작업이 왜 이 모양인가

### 3.1 transcript와 trajectory는 다른 물건이다

**transcript**는 writer 호출 하나에 행 하나가 대응하는 append-only 로그다. 한 `session_id`의
파일에 **재실행이 누적**되고, `seq`는 `SessionTranscript` 인스턴스마다 1에서 재시작한다
(측정 시점 14,970 파일 중 189개 감소, 357개 중복 — 라이브 디렉터리라 총수는 계속 는다).

**trajectory**는 policy가 조건화하고 생성한 순서를 재구성한 것이다. 실행 분할과 호출-결과 결속이
없으면 성립하지 않는다.

비대칭이 크다. transcript에는 모델이 본 적 없는 것이 있고(`task_preflight` 185,700행 = 전체의
18.4%), 모델이 본 것이 빠져 있다(thinking 기록 없음, 툴 결과 `summary` 평균 5자).

RL 의미의 trajectory는 여기에 토큰별 log prob과 scalar reward를 더 요구한다. GEODE는 둘 다 없어
**rollout이 아니라 감사 추적**이다.

### 3.2 정렬 기준 — Hermes와 Codex

| | 이벤트/hook | family·도메인 | 근거 |
|---|---:|---:|---|
| Hermes | **23** | 6 (문서 계열) | `hermes_cli/plugins.py` `VALID_HOOKS` |
| Codex | metric 50 + event 14 | ~12 | `metrics/names.rs`, `events/session_telemetry.rs` |
| GEODE (이전) | 56 | 27 (싱글턴 16) | `action` 첫 세그먼트 |
| GEODE (#2832) | 56 | **13** (싱글턴 0) | 동상 |

**Hermes가 갖고 GEODE가 빠뜨린 것**: payload마다 스키마 버전 주입(#2832가 채움),
`has_hook()` 게이팅(§2.2 B), `session_id → task_id → turn_id → api_request_id → tool_call_id`
상관 ID 계층(§2.2 C가 일부).

**GEODE가 더 나은 것**: dispatch 초크포인트의 payload 계약 검증(`_validate_payload`). Hermes는
hook **이름**만 검증하고 payload 형태는 검증하지 않는다. 이건 유지할 것.

**Codex에서 참고할 것**: 세 평면(trajectory·운영로그·export)이 `thread_id`만 공유하고 서로
침범하지 않는다. `token_count`가 rollout 줄의 21.1%로 exporter 없이 비용·쿼터를 복원한다.
`turn_context`·`world_state`로 턴마다 설정을 스냅샷한다 — GEODE에 대응물이 없다.

**Codex에서 따르지 말 것**: `otel.metrics_exporter` 기본값이 `statsig`라 설정 없이 지표가 나간다
(이 머신에서 9.9일간 574건). 운영 로그 `logs_2.sqlite`는 257MB에 9.9일치, 78.6%가 TRACE다.

---

## 4. 작업 방법 — 이 저장소에서 반드시 지킬 것

### 4.1 게이트

```bash
scripts/preflight.sh          # CI가 도는 게이트 15개 전부
scripts/preflight.sh --fast   # 테스트·site 빌드 제외
```

**`--fast`의 green을 CI green으로 읽지 말 것.** 이 세션에서 그렇게 했다가 PR이 `--fast`가
건너뛴 게이트에서 떨어졌다. 스크립트가 이제 노란색으로 무엇이 안 돌았는지 이름을 적는다.

문서화된 체크리스트 5개는 CI가 강제하는 17개의 일부이고 3개는 **범위가 더 좁았다**
(`mypy core/` 대 CI `mypy core/ plugins/ scripts/`). 그래서 체크리스트가 아니라 스크립트다.

### 4.2 릴리스

`[Unreleased]`에 내용이 있으면 develop → main을 바로 올릴 수 없다 (CANNOT: main에 내용 있는
`[Unreleased]` 금지). 순서는 이렇다.

1. `develop`에서 `release/vX.Y.Z` 컷
2. 버전 스탬프 **5곳** — `pyproject.toml`, `CLAUDE.md`, `README.md`, `README.ko.md`, CHANGELOG 헤더
3. `## [Unreleased]` → `## [X.Y.Z] - <날짜>` 승격 + 빈 `[Unreleased]` 신규 삽입
4. 파생 재생성 — `cd site && npm run sync-stats`, `uv run python scripts/check_llms_version.py --fix`,
   `uv run python scripts/architecture_baseline.py --update`
5. `release/*` → develop PR (squash) → develop → main PR (**merge commit**)

### 4.3 밟기 쉬운 지뢰

| 증상 | 원인 | 조치 |
|---|---|---|
| CI Test가 `knowledge graph source changed: <file>` | `context_graph.json`의 13개 노드 중 하나를 건드림 | 해당 노드 `contentSha256` 재계산 |
| Pages Build가 `Verify committed public-doc generators` | `llms-full.txt`가 스테일 | `sync-stats` 만으로는 안 됨. `npm run build && npm run export-md` 후 커밋 |
| CI Test가 `test_committed_consumers_match_current_snapshot` | 파일 추가·삭제로 카운트 변경 | `scripts/architecture_baseline.py --update` |
| 로컬 pytest 4건 실패 (`inspect_ai`) | 선택적 의존성 미설치 | `uv sync --extra audit` |
| worktree 안에서 `git stash pop` | 다른 세션의 stash를 꺼내 충돌 | **하지 말 것.** 이 세션에서 38개 stash 스택을 건드릴 뻔했다 |

### 4.4 스크립트로 파일을 고칠 때

이 세션에서 두 번 사고가 났다. `src.index("\n\n", ...)`로 helper를 삽입했더니 **테스트 함수
한가운데와 여러 줄 import 사이**에 들어갔다. 다음을 지킬 것.

- 삽입 위치는 `ast.parse`로 구한다 (`max(n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))`).
- 쓰기 전에 `ast.parse(new_src)`로 문법을 검증한다.
- 치환 건수를 `assert`로 확인한다. 결과 길이가 원본의 90% 미만이면 쓰지 않는다.

---

## 5. 이 세션에서 틀렸던 것 — 같은 실수 반복 방지

전부 **측정값은 맞았는데 해석이 틀린** 경우다. 지어낸 사실은 없었다.

| 틀린 진술 | 실제 | 원인 |
|---|---|---|
| "hook은 다른 네임스페이스" (0.06%) | `session_key` 9개 중 8개 일치 = **89%** | 분모를 transcript 14,515로 잡음 |
| "`runs`는 분리된 레인" (0.13%) | `session_key` 21개 중 19개 = **90%** | 동일 |
| "GEODE는 call id가 없다" | transcript에만 없음. `messages`는 99.3% 결속 | 한 저장소만 보고 일반화 |
| "두 소스가 같은 사건 집합" | 표본 300/300 일치였으나 전수 7,061 중 **36건 불일치** | 표본으로 일반화 |
| "Hermes는 소스가 없다" (2회) | `~/workspace/hermes-agent`에 존재 | `which` 부재를 소스 부재로 오독 + zsh glob 실패를 "없음"으로 읽음 |
| "hook 어휘가 파편화" | enum 56값 전부 고유. v1→v2 전환이 07-15에 완료 | 두 스키마 버전 공존을 파편화로 오독 |
| "Hermes ~15 hook" | `VALID_HOOKS` **23개** | 코드가 아닌 문서를 셈 |
| "`action_family()`로 27→13" | 프로덕션 소비자 0개. 선언만 존재 | 배선 확인 없이 완료 선언 |

**지킬 것 세 가지.** 비율을 말할 때 분모를 같이 출력한다. 표본을 뽑으면 요약 전에 그 표본이
무엇인지 찍는다. 새 API를 추가하면 **호출자가 있는지 grep으로 확인**한 뒤 완료라고 말한다.

마지막 두 건은 Codex 교차 검증이 잡았다. `codex exec`로 DEDUP/SLOP/GAP 감사를 돌리는 것이
이 저장소에서 실제로 값을 낸다.

---

## 6. 관련 문서

| 문서 | 내용 |
|---|---|
| `docs/plans/2026-07-30-hook-taxonomy-fold.md` | PR #2832의 GAP Audit·Socratic Gate·접기 설계·Codex 감사 반영 |
| `docs/trajectory-redesign.md` | trajectory 규격, `messages`가 거울인 근거, 36건 불일치 |
| `docs/observability-survey.md` | GEODE 14개 모듈 전수 + Codex/Hermes/OpenClaw 비교 |
| `docs/observability-alignment.md` | 로컬 소스 원문 기준 정렬안 A~E |
| `core/observability/trajectory.py` | K3형 투영. `python -m core.observability.trajectory <session\|--merge N>` |
| `scripts/preflight.sh` | CI 게이트 15개 로컬 실행 |
| `.claude/skills/geode-gitflow/SKILL.md` | Step 0(pre-commit 설치)·Step 1(preflight) 갱신됨 |
