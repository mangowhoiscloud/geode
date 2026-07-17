# `./state` 분리 — tracked SoT (in-repo) vs runtime (~/.geode)

> [!NOTE]
> Historical path/storage migration plan. The pending table and implementation
> language below are a frozen 2026-06-14 snapshot, not current execution
> status. Re-audit current code and storage contracts; architecture residuals
> roll up to STORE-001/002 in the
> [architecture roadmap](../architecture/extensibility-roadmap.md).
>
> **작성**: 2026-06-14
> **운영자 결정**: ① tracked SoT는 in-repo로, runtime은 ② **`~/.geode/`(레포 밖)**으로. repo-루트 `state/` 소멸.
> **배경**: CSP-7(2026-05-22)이 `~/.geode/self-improving-loop/` + `~/.geode/seed-generation/`를 repo-루트 `state/`로 끌어왔는데, 그때 tracked SoT(버전관리 必)와 runtime(머신-로컬)을 한 묶음으로 옮긴 게 혼선의 근원. 이 PR이 둘을 다른 집으로 분리.

## 0. 왜 runtime을 ~/.geode로 (in-repo gitignored가 아니라)
- worktree/clone마다 `<wt>/state/` 별도 → run 분산·worktree 삭제 시 유실 (CSP-7 포터블 이점은 약함 — 코드가 mkdir로 자동 생성). ~/.geode는 한 곳 영속.
- 작업트리 청결, gitignore-but-present footgun(PR-G5b `mutations.jsonl` 사건 클래스) 소멸, `~/.geode` 유저데이터 컨벤션 일치.
- runtime은 재생성 가능한 실행 트레이스(빌드 산출물 범주) → 레포에 둘 이유 없음.

## 1. 핵심 사실 (GAP 감사)
- 하드코딩 "state/..." 문자열은 전부 **docstring/주석**. 실제 코드는 `core.paths` 상수 import → **상수 이름 유지 + 값 repoint = importer 투명**(40+ 파일 무변경).
- 예외: 경로 **값**을 단언하는 테스트(`test_runner_repo_root_invariant`·`test_ratchet_policies_in_repo`·`test_state_pointer`·`test_reproducibility_pins` 등)는 새 위치로 갱신 필요.
- `.gitignore`: `state/*` ignore + `state/autoresearch/{mutations,baseline_archive,policies}` force-track + seed_generation bundle 예외 — 전면 재작업.
- 2-tier policy: in-repo 기본(`AUTORESEARCH_POLICIES_DIR`) + `~/.geode` 오퍼레이터 override(`GLOBAL_AUTORESEARCH_HANDOFF_DIR` 하위 `OPERATOR_LOCAL_*`). override 레이어는 그대로(이미 ~/.geode).

## 2. 상수 split (core/paths.py — 이름 유지, 값 repoint)

**신규 2 루트:**
- `SELF_IMPROVING_SOT_DIR = _REPO_ROOT / "core" / "self_improving" / "state"` — in-repo tracked.
- `RUNTIME_ROOT = Path(os.environ["GEODE_STATE_ROOT"] or (GEODE_HOME / "self-improving"))` — ~/.geode runtime. (GEODE_STATE_ROOT override 유지; 기본값이 repo→~/.geode로 바뀜.)

| 상수 | 현 위치 | 새 위치 | 종류 |
|---|---|---|---|
| `AUTORESEARCH_STATE_DIR` | STATE_ROOT/autoresearch | **SELF_IMPROVING_SOT_DIR** | tracked |
| `AUTORESEARCH_POLICIES_DIR` | .../autoresearch/policies | SELF_IMPROVING_SOT_DIR/policies | tracked |
| `MUTATION_AUDIT_LOG_PATH` | .../mutations.jsonl | SELF_IMPROVING_SOT_DIR/mutations.jsonl | tracked |
| `BASELINE_ARCHIVE_PATH` | .../baseline_archive.jsonl | SELF_IMPROVING_SOT_DIR/baseline_archive.jsonl | tracked |
| baseline_epochs.json 상수 | .../baseline_epochs.json | SELF_IMPROVING_SOT_DIR/baseline_epochs.json | tracked |
| `SEED_POOLS_DIR`(+cycle-input/held-out) | _REPO_ROOT/state/seed-pools | SELF_IMPROVING_SOT_DIR/seed_pools | tracked |
| `STATE_ROOT` | repo/state | **RUNTIME_ROOT** (~/.geode/self-improving) | runtime |
| `STATE_SEED_GENERATION_DIR` | STATE_ROOT/seed_generation | RUNTIME_ROOT/seed_generation | runtime |
| `AUTORESEARCH_HANDOFF_DIR` | autoresearch/handoff | RUNTIME_ROOT/handoff | runtime |
| `STATE_LATEST_POINTER_PATH` | handoff/latest_pointer.json | RUNTIME_ROOT/handoff/latest_pointer.json | runtime |
| campaign-progress.log 상수 | autoresearch/ | RUNTIME_ROOT/ | runtime |

(전 *_PATH 정책 상수는 AUTORESEARCH_POLICIES_DIR 파생이라 자동 따라감.)

**⚠ 핵심 발견 — `STATE_DIR`가 tracked/runtime ad-hoc join 혼용**: 코드가 `STATE_DIR / "<file>"`로 직접 조립하는데, 일부는 tracked·일부는 runtime. `AUTORESEARCH_STATE_DIR`를 tracked SoT로 repoint하면 **runtime 파일이 tracked dir로 잘못 감** → 6파일 재분류 필수:
| ad-hoc join | 파일:라인 | tracked? | 조치 |
|---|---|---|---|
| `STATE_DIR/"campaign-progress.log"` | watch_campaign.py:32, campaign.py:125 | runtime | → RUNTIME_ROOT |
| `STATE_DIR/"baseline.json"` | campaign.py:123, ledger.py:51 | runtime(latest) | → RUNTIME_ROOT |
| `STATE_DIR/"run.log"` | train.py:422 | runtime | → RUNTIME_ROOT |
| `STATE_DIR/"results.{tsv,jsonl}"` | ledger.py | runtime | → RUNTIME_ROOT |
| `STATE_DIR/"wrapper-override.json"` | measure.py:338 | runtime | → RUNTIME_ROOT |
| `STATE_DIR/"prepare-report.txt"` | prepare.py:56 | runtime | → RUNTIME_ROOT |
| `STATE_DIR/"mutations.jsonl"·"baseline_archive.jsonl"·"policies"` | watch_campaign·campaign | tracked | SoT (자동) |
실제 git-tracked 집합(검증): `mutations.jsonl·baseline_archive.jsonl·baseline_epochs.json·policies/hyperparam.json`. `baseline.json`(latest)은 미추적(runtime) vs `baseline_archive.jsonl`(promoted)은 추적 — latest/promoted SoT 구분([[feedback_latest_vs_promoted_sot]]).

## 3. 데이터 이동 (git mv — 히스토리 보존)
```
git mv state/autoresearch/mutations.jsonl        core/self_improving/state/
git mv state/autoresearch/baseline_archive.jsonl core/self_improving/state/
git mv state/autoresearch/baseline_epochs.json   core/self_improving/state/
git mv state/autoresearch/policies              core/self_improving/state/policies
git mv state/seed-pools                         core/self_improving/state/seed_pools
# runtime(handoff/·seed_generation/)은 gitignored였으니 git mv 없음 — 새 코드가 ~/.geode에 생성.
# repo-루트 state/ 디렉토리 + state/README.md 제거(내용은 SoT README로 이전).
```

## 4. 기타
- `.gitignore`: `state/*` 블록 + force-track 예외 제거(이제 tracked는 core/ 아래 자연 추적, runtime은 ~/.geode 레포 밖). seed_generation bundle 예외도 제거.
- 경로-단언 테스트 + `tests/fixtures/self_improving_hub/` 미러를 새 위치로.
- docstring/주석의 "state/autoresearch/..." 표기 갱신(cosmetic).
- `core/paths.py` 상단 SoT README 내용 흡수 + GEODE_STATE_ROOT 의미(=runtime root) 갱신.
- **running daemon**: 경로 변경은 리빌드 후 적용(이번 세션 리빌드 생략). git mv된 tracked는 머지 후 새 위치, 구 데몬(구 코드)은 구 경로 참조 — 캠페인 미실행 중이라 저위험. 머지 후 리빌드 시 정합.

## 5. Status
| 항목 | 상태 |
|---|---|
| paths.py 2-루트 split + 상수 repoint | PENDING |
| git mv tracked 데이터 | PENDING |
| .gitignore 재작업 | PENDING |
| 경로-단언 테스트 + fixtures 갱신 | PENDING |
| docstring/README 갱신 | PENDING |
| 게이트 + Codex | PENDING |
