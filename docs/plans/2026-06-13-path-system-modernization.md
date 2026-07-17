# Path-System Modernization — frontier convergence + debt/slop sweep

> [!NOTE]
> Historical path-convergence sprint. Its SoT/status language is frozen; use
> current code and storage contracts for behavior. Architecture residuals roll
> up to STORE-001/002 and DI-003 in the
> [architecture roadmap](../architecture/extensibility-roadmap.md).
>
> **작성**: 2026-06-13
> **목적**: GEODE의 경로 정책(`core/paths.py` SoT + 가드 + 소비자)에 쌓인 기술부채·slop을 **전수** 정돈하고, 프론티어 에이전트 CLI의 수렴 패턴(`{APP}_HOME` override)에 맞춰 현대화한다.
> **검증**: ruff/format/mypy/lint-imports/pytest(가드 포함) + Codex MCP(gpt-5.5) review.
> **Historical SoT**: 이 문서. 당시 drift 시 코드/문서를 함께 갱신했다.
> **근거 감사**: 3-차원 Explore 감사(legacy/migration · paths.py 조직·slop · 리터럴 우회·가드) + frontier 수렴 조사(2026-06-13).

---

## 0. 문제 진술 + frontier grounding

GEODE 경로 정책은 *이미 성숙*하다: 중앙 SoT(`core/paths.py`), path-literal 가드(`tests/core/test_path_literal_guard.py` + `# paths-literal-ok`), `GEODE_STATE_ROOT` env override, layout migrator v4(부팅 시 idempotent), Claude Code parity의 project-ID 인코딩. **삭제 가능한 legacy는 0건**(전부 active grace/fallback). 따라서 이 작업은 *legacy 삭제*가 아니라 **수렴 갭 + 명명/조직 slop + 가드 사각**의 정돈이다.

### frontier 수렴 (5 시스템, 코드 근거)

| 시스템 | home/config 기본 | env override | XDG | project-ID 인코딩 | 근거 |
|---|---|---|---|---|---|
| Codex (Rust) | `~/.codex` | **`CODEX_HOME`** | No | (단일 프로젝트) | `codex-rs/utils/home-dir/src/lib.rs` |
| Hermes (Node) | `~/.hermes` | **`HERMES_HOME`** | No | (단일) | `ui-tui/src/lib/history.ts` |
| OpenClaw (Node) | `~/.openclaw` | **`OPENCLAW_HOME`** | partial(test) | path-based | `src/infra/home-dir.ts` |
| Paperclip (Node) | `~/.paperclip` | **`PAPERCLIP_HOME`** | No | slug | `packages/shared/src/home-paths.ts` |
| Crumb (Node) | `~/.crumb` | **`CRUMB_HOME(S)`** | No | path-based | `packages/studio/src/server/paths.ts` |
| **GEODE** | `~/.geode` | **없음**(paths.py:223 하드코딩) | No | `/`→`-` (Claude Code parity) | `core/paths.py:223,534-546` |

**수렴 결론**:
- **(a) home-dir env override = 강한 합의** — 전 시스템 `{APP}_HOME`. GEODE만 미보유. **채택**.
- **(b) XDG = 미채택** — 프론티어 0/5가 라이브러리 기반 XDG(`platformdirs`/`directories`/`xdg`) 미사용, hand-rolled `~/.app`이 사실상 표준. **GEODE도 스킵**(Linux distro 패키징 수요 생길 때 재검토).
- **(c) project-ID 인코딩 = 이미 정렬** — GEODE의 `/`→`-`가 Claude Code parity. **무변경**.

---

## 1. 발견 카탈로그 (감사 결과)

| ID | 항목 | 근거(file:line) | 등급 | Phase |
|----|------|----------------|------|-------|
| F1 | `GEODE_HOME` env override 부재 | `core/paths.py:223` | 수렴-핵심 | 1 |
| F2 | `ipc_client`가 `GEODE_HOME` env를 *serve cwd* 의미로 선점(충돌) | `core/cli/ipc_client.py:67` | 수렴-핵심 | 1 |
| F3 | env 값 `.expanduser()` 누락(`GEODE_STATE_ROOT`, 신규 `GEODE_HOME`) — `~` 미전개 잠재버그 | `core/paths.py:61` | LOW(버그) | 1 |
| F4 | `GLOBAL_POLICIES_DIR` + 15 `GLOBAL_*_POLICY_PATH`가 `GLOBAL_`(user-tier) 명명인데 `STATE_ROOT`(in-repo) 해석 = tier 오명명 | `core/paths.py:286,296-323` | HIGH slop | 2 |
| F5 | dead 상수: `PROJECT_SCHEDULER_LOCK`(write-only, 0 reader) | `core/paths.py:489` | MED | 3 |
| F6 | intermediate-only 상수(외부 소비 0): `SEED_POOLS_DIR`, `GLOBAL_SEARCH_DIR` | `core/paths.py:71,445` | LOW | 3 |
| F7 | test-only 상수(프로덕션 소비 0): `PROJECT_RULES_DIR`, `PROJECT_REPORTS_DIR` | `core/paths.py:484,486` | LOW(검증요) | 3 |
| F8 | 실 우회(SoT 미경유): `plugins/petri_audit/audit_mode.py:59`(`.geode/audit-mode.toml`), `scripts/retrofit_manifest.py:29`(`~/.geode/petri/logs`) | — | MED | 3 |
| F9 | 가드 사각: `core/`만 스캔(plugins/scripts 누락) | `tests/core/test_path_literal_guard.py` | MED | 4 |
| F10 | 가드 사각: `.expanduser()` 문자열형 / `os.path.expanduser` 미탐 | 동 | MED | 4 |
| F11 | vendor-path(`~/.claude` `~/.codex` `~/.geode_history` `~/.local/bin` `~/.cache`) tier 미분류 — 의도적이나 비카탈로그 | `core/llm/adapters/*oauth*.py` 등 | LOW(문서) | 4 |
| F12 | 모듈 docstring "two-tier" — 실제 3-tier(STATE_ROOT 누락) | `core/paths.py:1-14` | LOW | 4 |
| F13 | 741줄 god-module(user-global 257줄) — 분할 후보 | `core/paths.py` 전체 | HIGH effort | 5(선택) |
| F14 | (엄밀 누락 점검 발견) `GEODE_AUTH_TOML`·`GEODE_PROJECT_DIR` expanduser 누락 — `~` 미전개 | `core/auth/auth_toml.py:59`, `core/cli/ipc_client.py:71` | LOW(버그) | 4 |
| — | vendor 카탈로그 `~/.hermes` 할루시네이션 제거(실 construction 0, env_io 주석뿐), `.codex/.claude/.local/.cache` 4개만 코드-검증 | — | (rigor) | 4 |

---

## 2. 단계별 실행 계획

### Phase 1 — `GEODE_HOME` 수렴 + expanduser + ipc 개명 (F1·F2·F3) — **P0**

**Socratic**: Q1 존재? No(env override 없음). Q2 안 하면? 테스트/CI/대체 home 격리 불가 + 프론티어 5/5와 불일치 + `ipc_client`와 `paths.py`가 같은 env명을 다른 의미로 읽어 충돌 잠재. Q3 측정? 신규 가드 테스트(env→GEODE_HOME 해석) + 기존 layout/ensure-dirs 테스트 회귀 0. Q4 최소? env-read 1줄 + ipc 개명 1곳. Q5 3+ 프론티어? Yes(5/5).

구현:
1. `core/paths.py:223` →
   ```python
   GEODE_HOME = Path(os.environ.get("GEODE_HOME") or (Path.home() / ".geode")).expanduser()
   ```
   파생 `GLOBAL_*` 전부 자동 수혜(단일 지점). docstring에 "frontier `{APP}_HOME` parity" 1줄.
2. `core/paths.py:61` `GEODE_STATE_ROOT`에 `.expanduser()` 추가(일관성+`~` 버그).
3. `core/cli/ipc_client.py:67` env `GEODE_HOME`(serve cwd 의미) → **`GEODE_PROJECT_DIR`**로 개명. live env/.env/docs 어디에도 미설정 → 마이그레이션 비용 0. 주석으로 의미 명시(serve 작업 디렉토리 = `.geode/config.toml` 보유 프로젝트 루트).

가드/테스트:
- `tests/core/test_paths_env_override.py`(신규): `monkeypatch.setenv("GEODE_HOME", tmp)` 후 `importlib.reload(core.paths)` → `GEODE_HOME == tmp`, 파생 `GLOBAL_PETRI_TOML` 등도 tmp 하위. `~` 전개 케이스. `GEODE_STATE_ROOT` 동일.
- ipc: `GEODE_PROJECT_DIR` 해석 테스트(기존 ipc 테스트 있으면 개명 반영).

### Phase 2 — policy-path tier 정명명 (F4) — **P1 (HIGH slop)**

`GLOBAL_POLICIES_DIR`(286) 및 그 하위 15 `GLOBAL_*_POLICY_PATH`(296-323)는 PR-RATCHET-1로 in-repo `state/autoresearch/policies/`로 이전됐으나 명명이 `GLOBAL_`(=`~/.geode` user-tier)로 남음. 실제 tier(STATE_ROOT)와 불일치 → 독자 오인.

**Socratic Q4(최소)**: cleanup PR이라 최소-변경 제약 면제([[feedback_cleanup_no_minimal_change]]). 단 rename은 importer 전수 갱신 필요 → 1-release 호환 alias 없이 같은 PR에서 callers 이행([[Compat 규칙]]).

구현:
- `GLOBAL_POLICIES_DIR` → `STATE_POLICIES_DIR`(또는 `AUTORESEARCH_POLICIES_DIR` — `AUTORESEARCH_STATE_DIR` 자식이므로 후자가 더 정확). **선택: `AUTORESEARCH_POLICIES_DIR`**.
- 15 `GLOBAL_*_POLICY_PATH` → `AUTORESEARCH_*_POLICY_PATH`(tool/decomposition/retrieval/reflection/tool_descriptions/hyperparam/skill_catalog/style_guide/provider_routing/cache_policy/heuristics/in_context_slots/agent_contracts/few_shot_pool/wrapper_sections).
- `grep -rn "GLOBAL_.*_POLICY_PATH\|GLOBAL_POLICIES_DIR"` 전수 → core/plugins/scripts/tests 모든 importer 개명.
- **주의**: `OPERATOR_LOCAL_*_POLICY_PATH`(329-386, `~/.geode/autoresearch/handoff/` 해석)는 *진짜 operator-tier*라 무변경. GLOBAL→AUTORESEARCH(=STATE) vs OPERATOR_LOCAL(=user) 대비가 오히려 3-layer 의미를 선명하게.

가드: drift 방지 위해 tier-naming invariant 테스트(상수명 prefix ↔ 해석 root 일치) 고려(과하면 생략).

### Phase 3 — dead/우회 정돈 (F5·F6·F7·F8) — **P2**

1. `PROJECT_SCHEDULER_LOCK`(489) 삭제(0 reader 검증됨). 만약 future 락 용도면 wire, 아니면 제거.
2. `SEED_POOLS_DIR`(71)·`GLOBAL_SEARCH_DIR`(445) — 외부 소비 0인 intermediate. 자식(`CYCLE_INPUT_POOL`/`HELD_OUT_BENCH_POOL`, `GLOBAL_SEARCH_DB`)에 인라인하거나, 가독성상 유지가 나으면 *명시적 주석*으로 의도 보존. **결정: 자식이 2+개면 base 유지(가독성), 1개면 인라인.** SEED_POOLS_DIR=자식2 유지, GLOBAL_SEARCH_DIR=자식1 → 인라인 검토.
3. `PROJECT_RULES_DIR`·`PROJECT_REPORTS_DIR`(484,486) — 프로덕션 0 소비 주장. **구현 전 재검증**(getattr/문자열 간접 포함). 정말 0이면 `ensure_directories`가 만드는지 확인 후 제거 or 유지근거 주석. (init bootstrap이 만들면 유지.)
4. F8 우회:
   - `plugins/petri_audit/audit_mode.py:59`: `Path(".geode")/"audit-mode.toml"` → `core.paths`에 `PROJECT_AUDIT_MODE_TOML` 상수 신설 후 import. (plugin이라 core import 가능한지 layer 확인 — lint-imports 통과 필요.)
   - `scripts/retrofit_manifest.py:29`: `Path("~/.geode/petri/logs").expanduser()` → `from core.paths import PETRI_LOGS_DIR`.

### Phase 4 — 가드 강화 + docstring + vendor 카탈로그 (F9·F10·F11·F12) — **P3**

1. **가드 스코프 확장**(F9): `test_path_literal_guard.py`가 `core/`만 스캔 → `plugins/` 추가(scripts/는 별도 정책 — 운영 스크립트라 home-path 허용 폭이 다름; 최소 `~/.geode` 하드코딩만 잡도록). plugins allowlist 별도.
2. **expanduser 형 탐지**(F10): regex에 `["']~/\.geode` 문자열형 + `os.path.expanduser\(["']~/\.geode` 추가. 단 env-override resolver(`Path(override).expanduser()`)는 정당 → 변수형은 제외(현행 유지), *리터럴* `~/.geode`만 추가 탐지.
3. **vendor allowlist tier**(F11): `_VENDOR_HOME_ALLOWLIST = {".claude", ".codex", ".geode_history", ".local", ".cache", ".hermes"}` 명시 + 주석. 이들은 의도적 비-`.geode` home path(3rd-party 규약/XDG). 가드가 이 형들을 *오탐 안 하도록* 문서화. (현 가드는 `.geode` 전용이라 이미 미탐 — 카탈로그/주석만.)
4. **docstring 3-tier 정정**(F12): `core/paths.py:1-14` "two-tier" → "three-tier(repo-state STATE_ROOT / user-global `~/.geode` / project-local `{ws}/.geode`)". project 예시 상수 보강.

### Phase 5 — god-module 분할 (F13) — **선택, HIGH effort, 별도 PR**

741줄 → `core/paths/` 패키지(`__init__.py`가 전량 re-export → `from core.paths import X` import 면 불변):
- `core/paths/state.py` — STATE_ROOT + autoresearch + seed-gen + pointer R/W
- `core/paths/policies.py` — AUTORESEARCH_*/OPERATOR_LOCAL_* policy paths
- `core/paths/project.py` — PROJECT_* + encode_project_id + getters + compat(`_OLD_*`)
- `core/paths/__init__.py` — GEODE_HOME/global + re-export + `ensure_directories`

**판단**: import 안정(re-export)이라 안전하나 대형 mechanical change + lint-imports 계약 영향. **Phase 1-4 머지·안정화 후 별도 PR로 재평가.** 효과(가독성) 대비 위험이 낮지 않으면 *defer*. 이 문서에 보류 사유 명기.

---

## 3. 검증

각 Phase: ruff check/format(core+tests+plugins+scripts) · `mypy core/ plugins/ scripts/`(CI parity — CLAUDE.md 게이트표엔 scripts/ 누락, ci.yml:101이 실범위) · `lint-imports` · `pytest`(path 가드 + ensure-dirs + layout migrator + ipc + 영향 테스트) · `geode version` smoke · Codex MCP(gpt-5.5) per-PR review.

## 4. Out-of-scope (보류 + 사유)

- **XDG 마이그레이션**: 프론티어 0/5 미채택. 수요 없음. 스킵.
- **vendor-path(`~/.claude`/`~/.codex`) 중앙화**: vendor-소유 규약(`CLAUDE_CONFIG_DIR`/`CODEX_HOME` 자체 override 보유). core/paths.py로 끌어오면 vendor 변경에 결합. 카탈로그(F11)만, 이동 X.
- **legacy 상수 삭제**(`LEGACY_*`/`_OLD_*`/lazy migration): 전부 active grace. 삭제 조건 체크리스트는 legacy 감사에 기록 — 본 작업 범위 밖.
- **operator-local override layer 통합**: ADR-013 3-layer 설계의 일부. 무변경.

## 5. Status

| Phase | 상태 |
|---|---|
| 1 — GEODE_HOME 수렴 + expanduser + ipc 개명 | **DONE** (4 가드 테스트, `tests/core/test_paths_env_override.py`) |
| 2 — policy-path tier 정명명 (16상수 GLOBAL_→AUTORESEARCH_, 227건) | **DONE** |
| 3 — dead/우회 정돈 | **DONE** (PROJECT_SCHEDULER_LOCK 삭제·GLOBAL_SEARCH_DIR 인라인·retrofit core 경유; audit_mode=plugin SoT 유지) |
| 4 — 가드 강화 + docstring + vendor 카탈로그 | **DONE** |
| 5 — god-module 분할(선택) | DEFERRED(재평가) |
