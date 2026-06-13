# Computer-Use Enhancement — 3-provider human-level GUI control + opt-in sandbox

> **작성**: 2026-06-14
> **목적**: GEODE의 computer-use를 현 browser-use 이상으로 — 사람-레벨 마우스/스크롤/입력을 3사(Anthropic·OpenAI·Zhipu)에서, 호스트 기본 실행 + Docker+Xvfb 샌드박스 옵인으로 보강.
> **운영자 결정**: ① 3사 전부 ② GUI 실행 = **호스트 기본 + 샌드박스 옵인** ③ 사람-레벨 조작 필수 ④ MD 계획 먼저.
> **근거**: provider 리서치(2026-06-14) + codex/claude-code 샌드박스 1차 분석 + GEODE GAP 감사. 모든 외부 capability는 구현 전 `ctx7` 재확인(`[[feedback_ctx7_before_backend_assumption]]`).

---

## 0. GAP 감사 (검증됨 — 무엇이 이미 있나)

| 요소 | 현황 | 근거 |
|---|---|---|
| `ComputerUseHarness` (host pyautogui) | **있음** — screenshot/click(좌/우/중/더블/트리플)/type/key(조합키 매핑)/scroll(상하좌우)/move/drag/wait/cursor_position. 좌표 스케일링(LLM↔screen), base64 JPEG, FAILSAFE. | `core/tools/computer_use.py` |
| 사람-레벨 조작 | **있음** (위 액션 = 마우스 포인터+스크롤+입력) | 동상 |
| Anthropic 배선 | **있음** — `_COMPUTER_USE_TOOL`(`computer_20251124`) API 주입, `is_computer_use_enabled()` 게이트, handler | `core/llm/providers/anthropic.py:717-720,725,819-820`, `core/config/_settings.py` `computer_use_enabled` |
| `zoom` 액션 | **없음** — `computer_20251124`의 신규 액션 미구현 | harness 액션셋에 `screenshot/click/double_click/type/key/scroll/move/drag/wait`만(`grep "def "` 검증) |
| OpenAI computer-use | **없음** — `openai.py`에 `computer`/`ComputerUse` 참조 0개(grep 검증). GA `{type:computer}` 미배선 | `openai.py` grep 0 hits |
| Zhipu computer-use | **없음** — `glm.py`에 `computer` 참조 0개(grep 검증) | `glm.py` grep 0 hits |
| `ComputerUseCapable` 프로토콜 | **없음** — Anthropic 전용. (cf. `WebSearchCapable` 패턴) | `core/llm/adapters/base.py` |
| 실행 격리(샌드박스) | **없음** — pyautogui 로컬 호스트 직접 | — |
| run_bash 커맨드 샌드박스 | **없음** | — |

**핵심**: 보강 = ① 3사 배선 + 프로토콜 ② zoom ③ 호스트/샌드박스 실행 추상화 ④ run_bash 커맨드 샌드박스(codex 수렴).

> **구현 중 발견 (중대)**: 사람-레벨 조작 harness는 존재하나 **production에서 computer-use가 완전히 죽어 있었음**. ① 툴 주입이 레거시 `ClaudeAgenticAdapter.agentic_call`에만 있었는데 PR-MAINPATH-67(2026-05-24)이 그 분기를 삭제 → production AgenticLoop(`LLMAdapter.acomplete` → `anthropic_oauth/payg` → `_anthropic_common.build_create_kwargs/stream_kwargs`)은 모델에게 `computer` 툴을 **한 번도 제시한 적 없음**. ② 설령 제시됐어도 핸들러가 `action`을 positional+kwargs 중복 전달 → 첫 호출에서 TypeError. → tool-search-defer가 겪은 "docstring-vs-live-path" 동류 결함. **Phase A를 production 경로 부활로 재정의**(아래).

---

## 1. 프로바이더 capability — ctx7 검증 결과 (2026-06-14)

| | Anthropic | OpenAI | Zhipu |
|---|---|---|---|
| 툴 | `computer_20251124` (beta) | **GA: `{type:"computer"}`** / preview: `computer_use_preview` | ComputerRL/AutoGLM(오픈) + GLM-5V grounding |
| 모델 | Opus 4.8/4.7/4.6, Sonnet 4.6 | **GA `gpt-5.5`** (preview=`computer-use-preview`) | AutoGLM-OS-9B·Phone·GLM-5V-Turbo |
| 액션 전달 | tool_use.input.action (단일) | **GA=batched `actions[]` 배열** / preview=단일 `action` | bbox grounding |
| 툴 파라미터 | `display_width_px`·`display_height_px`·`display_number`(X11) | `display_width`·`display_height`·environment(mac/linux/windows/ubuntu/browser) | — |
| 안전 | beta header(아래 ⚠) | safety check 적용(computer tool) | self-host |

> **ctx7 출처**: Anthropic=`/anthropics/anthropic-sdk-python` `beta_tool_computer_use_20251124_param.py`(3필드: display_width_px/height_px/display_number) + `anthropic_beta_param.py`(beta enum). OpenAI=`/websites/developers_openai_api` `guides/tools-computer-use`(GA `{type:"computer"}` on gpt-5.5, batched actions[]).

> ⚠ **검증 안 됨(ctx7 ambiguous → live test 게이트)**:
> - **Anthropic beta 헤더**: **두 축을 분리해야 함** — 툴 SCHEMA(`computer_20251124`, Nov 2025, 최신 액션셋)와 feature-gate HEADER(`computer-use-2025-01-24`, Anthropic이 고정 유지)는 별개 버전 축. ctx7 enum은 2026-06까지 최신(`server-side-fallback-2026-06-01` 등 포함)인데도 computer-use 문자열은 `2024-10-22`/`2025-01-24` 둘뿐 — `computer-use-2026-*` 없음. 즉 `2025-01-24`는 stale이 아니라 **현행 유일 게이트**. 남은 건 header↔schema 페어링이 직접 예제로는 미노출(강하게 추론) → live-test 최종확인. 현재 GEODE는 **헤더 없이** 주입 중이라 이 정정이 strict ≥.
> - **`zoom` 액션 / `enable_zoom` 필드**: SDK TypedDict에 **없음**(3필드뿐). 기존 플랜의 `enable_zoom: true`는 폐기. zoom 액션은 모델 tool_use 어휘라 SDK로 확인 불가 → live-test 게이트 후속으로 분리(Phase B 축소).
> - **OSWorld 점수**: 외부 리서치 기반, 코드/ctx7 근거 아님 → 본문서에서 인용 보류.

**의도적 비차용**: OpenAI hosted browser(API 미노출, self-host), Zhipu 폰(안드로이드 — 데스크탑 범위 밖).

---

## 2. 샌드박스 — codex/claude-code 수렴의 진실 (1차 소스 분석)

- **codex**: 커맨드 실행을 seatbelt(macOS `/usr/bin/sandbox-exec`+`.sbpl`) / bubblewrap+seccomp(Linux) / Restricted Token(Windows)로 격리. `AskForApproval` + network OFF 기본. crate: `landlock 0.4.4`, `seccompiler 0.5.0`, vendored bwrap. (`codex-rs/sandboxing/`)
- **claude-code(역엔지니어 ref)**: OS 격리 primitive 소스 부재 — 권한 모델(PermissionMode + `Bash(pattern)` allow/deny)만.
- **결정적**: **둘 다 GUI computer-use를 커맨드 샌드박스 밖**에 둠 — codex=외부 MCP 플러그인, claude-code=Chrome 확장. OS 커맨드 샌드박스는 **디스플레이 미제공** → GUI는 실제 호스트 or 가상 디스플레이 컨테이너.

→ **수렴 해석(운영자 결정 반영)**:
- (a) **GUI 실행** = 호스트 기본(사람-레벨, 현행) + Docker+Xvfb 샌드박스 옵인.
- (b) **run_bash 커맨드 실행** = codex 패턴(seatbelt/bwrap) 별도 하드닝 — 이게 "codex 샌드박스 수렴"의 실제 적용 지점.

---

## 3. 단계별 실행

### Phase A — production 경로 부활 + `ComputerUseCapable` 프로토콜 (P0) ✅ DONE (v0.99.208)
- **핸들러 버그 수정**: `core/cli/tool_handlers/single_tool.py` `handle_computer`가 `action`을 `pop`(기존 `get` → positional+kwargs 중복 TypeError). 회귀 가드 `test_computer_use.py::TestHandlerActionForwarding`.
- **production 주입 부활**: `core/llm/adapters/_anthropic_common.py`에 `_maybe_inject_computer_use(kwargs)` — `build_create_kwargs`/`build_stream_kwargs` 양쪽에서 `is_computer_use_enabled()`일 때 `computer_20251124` 툴 + `computer-use-2025-01-24` beta 헤더 주입(merge, no-clobber). `req.tools` 비어도 주입, 이미 있으면 idempotent, type-carrying이라 defer 면제. dim은 harness `TARGET_*` 단일 SoT.
- **`ComputerUseCapable` 프로토콜**: `core/llm/adapters/base.py`(WebSearchCapable 미러, source-adapter 레벨). 라이브 어댑터 `AnthropicOAuthAdapter`/`AnthropicPaygAdapter`가 `supports_computer_use=True` + `computer_tool_param()`(주입 payload와 동일 — drift 가드 테스트로 핀).
- 가드: `tests/core/llm/adapters/test_computer_use_live_path.py`(주입/비주입/idempotent/merge/defer-exempt/protocol/dim-unify) + 핸들러 회귀.
- **이월(다음 PR)**: harness `_execute_sync`의 OpenAI batched `actions[]` 일반화 + 좌표 규약 분기는 Phase C와 함께(OpenAI 어휘가 실제 들어오는 시점).

### Phase B — Anthropic beta 헤더 정정 (P1, 축소 — zoom 분리)
- **현재 결함**: computer 툴이 `anthropic-beta` 헤더 없이 주입됨(context-mgmt 모델만 헤더 설정). computer-use는 beta 툴(`types/beta/BetaToolComputerUse...`)이라 헤더가 필요할 가능성 높음.
- 조치: computer 툴 주입 시 `computer-use-2025-01-24`(ctx7 enum의 최신 documented 문자열)를 `extra_h["anthropic-beta"]`에 append. 무헤더 대비 strict ≥(인식 안 되는 beta는 무시됨), 근거=ctx7 enum. tool-version(`_20251124`) vs beta-version(`_2025-01-24`) 불일치는 `unverified — live test required` docstring 명기.
- **zoom 액션 + 1:1 좌표는 분리**(ctx7 미확인) → Phase B' live-test 게이트 후속(§6 보류로 이동).
- 가드: computer 주입 시 beta 헤더에 computer-use 문자열 존재.

### Phase C — OpenAI GA 배선 (P1, ctx7 확정)
- `core/llm/providers/openai.py`: Responses API **`{type:"computer"}`** 주입(GA `gpt-5.5` 게이트, preview `computer_use_preview` 회피), `ComputerUseCapable` 구현. `display_width/height` + environment.
- **GA batched `actions[]`**: computer_call이 액션 배열을 담음 → 핸들러가 배열 순회 실행(마지막 screenshot 반환). 액션 매핑(click/double_click/drag/scroll/move/type/keypress/wait/screenshot → harness).
- safety check 흐름(computer tool 대상) 반영.
- ctx7 출처(developers_openai_api guides/tools-computer-use) docstring 인용. backend 실제 수용은 live-test 게이트.
- 가드: openai computer tool 주입(GA type) + batched actions 순회 + 모델 게이트.

### Phase D — Zhipu 배선 (P2, self-host)
- GLM-5V-Turbo grounding(bbox normalized ×1000) → harness 좌표 변환(de-normalize by display W/H). AutoGLM-OS는 self-host harness(범위: 데스크탑만, 폰 제외).
- ctx7/z.ai docs 확인; self-host라 live 검증은 운영자 환경 의존 → `unverified` 게이트.
- 가드: bbox→픽셀 변환 단위 테스트.

### Phase E — 실행환경 추상화: 호스트 기본 + Docker+Xvfb 옵인 (P1)
- `GEODE_COMPUTER_USE_ENV` (`host`(기본) | `sandbox`) config. `host`=현 pyautogui 직접. `sandbox`=Docker+Xvfb(:99)+window manager 컨테이너에서 pyautogui, optional x11vnc/Xpra 관측.
- harness가 env에 따라 디스플레이 타깃 분기(host display vs `:99`). 컨테이너 spec(Dockerfile)+기동 헬퍼.
- 패키지: 호스트=pyautogui(현행). 샌드박스=Docker + Xvfb + (fluxbox/x11vnc). 무거우니 옵인 + lazy.
- 가드: env 분기 단위 테스트(컨테이너 미기동 시 host fallback). 실제 컨테이너 E2E는 운영자 환경(live).

### Phase F — run_bash 커맨드 샌드박스 (codex 수렴, P2)
- `run_bash` 실행을 OS 샌드박스로 감싸기: macOS=`sandbox-exec`+`.sb`(deny default, cwd+/tmp writable, network off), Linux=`bwrap`(있으면)+seccomp. 패키지: macOS=OS 바이너리(crate 불필요), Linux=`pyseccomp`/`bwrap` 바이너리.
- `GEODE_BASH_SANDBOX` (`off`(기본, 호환) | `on`) — 옵인, codex `AskForApproval` 정렬.
- ctx7 불필요(OS 기제), 단 macOS seatbelt 프로필은 codex `.sbpl`(`seatbelt_base_policy.sbpl`) 참조.
- 가드: 샌드박스 래퍼가 cwd 밖 쓰기/네트워크 차단(단위), 호스트 fallback.

---

## 4. 배선 검증 (Anti-Disconnection)
- 각 provider adapter의 computer-tool 주입점이 `agentic_call`에서 실제 호출되는지(anthropic는 있음, openai/glm 신규) — writer-reader parity.
- `computer_use_enabled` + `GEODE_COMPUTER_USE_ENV` + provider별 게이트가 모두 읽히는지(conditional read parity).
- harness 액션 매핑이 3사 provider-action을 전부 커버(미매핑 시 honest error, silent skip 금지).

## 5. 검증
- 각 Phase: ruff/format/mypy(scripts 포함)/lint-imports/pytest + Codex(gpt-5.5). 단위(액션매핑·좌표변환·env분기) + provider 주입 가드.
- 외부 backend 수용(OpenAI computer 타입, Anthropic zoom, Zhipu grounding)은 ctx7 → ambiguous면 `unverified — live test required` 게이트(`[[feedback_ctx7_before_backend_assumption]]`).
- 라이브 E2E(실제 GUI 제어·컨테이너)는 운영자 환경 — `-m live` 무단 실행 금지.

## 6. Out-of-scope (보류)
- **Phase B' — Anthropic `zoom` 액션 + Opus 1:1 좌표**: ctx7(SDK)로 `zoom` 액션·`enable_zoom` 미확인 → live-test로 모델이 zoom을 실제 emit하는지 확인 후 별도 PR.
- Zhipu 폰(AutoGLM-Phone 안드로이드) — 데스크탑 범위 밖.
- OpenAI hosted browser(Operator/ChatGPT Agent) — API 미노출, self-host computer로 대체.
- 컨테이너 이미지 배포/CI — 옵인 인프라, 수요 확인 후.

## 7. 리스크
- pyautogui 호스트 모드 = 운영자 실 데스크탑 제어(격리 0) — DANGEROUS 권한 + HITL 게이트 유지(현행 `computer`는 DANGEROUS_TOOLS).
- 좌표 스케일 provider 분기 = 클릭 오차 주요 원인 — provider별 단위 테스트 필수.
- 외부 backend capability 가정 = ctx7 미검증 시 live-test 게이트 강제.

## 8. Status
| Phase | 상태 |
|---|---|
| A — production 경로 부활 + ComputerUseCapable 프로토콜 | ✅ DONE (v0.99.208) |
| C — OpenAI GA {type:computer} 배선 (+harness batched actions[]) | PENDING |
| E — 호스트 기본 + Docker+Xvfb 샌드박스 옵인 | PENDING |
| F — run_bash 커맨드 샌드박스(codex 수렴) | PENDING |
| D — Zhipu GLM-5V grounding 배선 (self-host) | PENDING |
| B' — Anthropic zoom + 1:1 좌표 (live-test 게이트) | DEFERRED |
