# Computer-use + command 샌드박싱 — frontier 사례 리서치 (2026-06-17)

> **목적**: GEODE computer-use 샌드박스(Phase E) + run_bash 샌드박스(Phase F)의 구현 전 설계 확정. 운영자 지시("sandbox 조치는 외부 사례 리서치 더 진행부터").
> **방법**: frontier 시스템 전수(WebSearch/WebFetch + ctx7) + 로컬 1차 소스(`~/workspace/codex/codex-rs/sandboxing`, `~/workspace/claude-code-ref`) 직접 판독. 모든 주장에 출처(URL 또는 repo file:line) 병기.
> **결론(BLUF)**: ① **GUI 샌드박스의 frontier 합의 = in-container shim** — 손(pyautogui/xdotool)을 컨테이너 안에 두고 host는 구조화된 액션을 HTTP/WS로 dispatch. **"host가 `DISPLAY=:99` 설정" 모델(현 plan Phase E)은 아무도 안 쓰고, 격리 0이며, macOS에서 물리적으로 작동 안 함**(pyautogui가 macOS에서 Quartz API 사용 — `core/tools/computer_use.py:17` — Quartz는 X11 `DISPLAY`를 읽지 않으므로 `DISPLAY=:99` 무력, 추론). ② **command 샌드박스 = codex 수렴형** — macOS `sandbox-exec`+`.sbpl`(deny-default) / Linux `bwrap --unshare-net`. GEODE는 Rust 없음(Python) → OS 바이너리로 shell-out. ③ **격리 보장은 CI 검증 불가** — live Docker/OS 환경 필요, `unverified — live test required`.

---

## 1. GUI computer-use 샌드박스 (Phase E)

### 1.1 frontier 사례 (전수, 출처 병기)

| 시스템 | 격리 primitive | dispatch 모델 | agent 위치 | 출처 |
|--------|---------------|---------------|-----------|------|
| Anthropic computer-use-demo | Docker(Linux) — Xvfb+mutter+tint2+x11vnc+noVNC | host dispatch **없음**(루프 전체 컨테이너 내부) | **컨테이너 내부** | [README](https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/README.md) |
| OpenAI computer-use(CUA/GA) | **개발자 제공**(OpenAI는 환경 미호스팅) | 모델이 `actions[]` 반환 → 개발자 코드가 자기 sandbox에서 실행 후 screenshot POST. `environment`는 OS 힌트일 뿐 | 개발자 host 코드 | [OpenAI guide](https://developers.openai.com/api/docs/guides/tools-computer-use) |
| trycua/cua | Lume(Apple Virtualization) VM / Docker / cloud | **in-sandbox `cua-computer-server` shim** — host SDK가 `/cmd`(HTTP)+`/ws`로 click/type/screenshot dispatch | host agent + 컨테이너 내부 손 | [repo](https://github.com/trycua/cua), [WS API](https://cua.ai/docs/libraries/computer-server/WebSocket-API) |
| E2B Desktop | Firecracker microVM(E2B 인프라) | **in-sandbox shim**(SDK click/screenshot 등이 컨테이너 내부 실행, `pyautogui()` 메서드 노출); 관측은 별도 VNC stream | host agent + 컨테이너 내부 손 | [repo](https://github.com/e2b-dev/desktop), [docs](https://e2b.dev/docs/use-cases/computer-use) |
| HUD | per-eval Docker Ubuntu | **MCP over stdio**; VNC=관측 | agent가 MCP 도구 호출, 실행은 컨테이너 | [docs](https://docs.hud.ai/) |
| Scrapybara | cloud Ubuntu/Browser VM | host `act()` → 원격 인스턴스 | agent host, 실행 원격 | [Act SDK](https://docs.scrapybara.com/act-sdk) |
| browser-use / Skyvern | 로컬/원격 Chrome(브라우저 한정) | CDP/Playwright | host | [browser-use](https://docs.browser-use.com/examples/templates/playwright-integration) |

**교차 사실**: 풀-데스크탑 격리의 수렴 패턴 = **in-sandbox 자동화 도구(xdotool/pyautogui) + in-sandbox 액션 shim(HTTP/WS 또는 MCP) + 관측용 별도 VNC 채널**. VNC는 *보기*용이지 *액션 dispatch*용이 아니다. Anthropic 데모만 예외(루프 전체를 컨테이너에 넣어 host dispatch 자체를 회피).

### 1.2 dispatch 모델 분류 + 판정

| 모델 | 설명 | 격리 | 복잡도 | macOS host | 채택처 |
|------|------|------|--------|-----------|--------|
| (a) agent가 sandbox 내부 | 루프+GUI 한 컨테이너 | 강 | GEODE엔 높음(런타임 전체를 컨테이너에) | host-resident 설계 포기 | Anthropic demo |
| (b) host가 remote-display(VNC/RDP)로 dispatch | host가 합성 입력+framebuffer | 강 | 중(VNC client 필요, 입력 fidelity 낮음) | 가능하나 비효율 | (대개 관측용) |
| **(c) host가 in-sandbox HTTP/WS shim으로 dispatch** | 컨테이너 내 shim이 로컬 pyautogui 호출, host는 구조화 액션 POST | **강** | 중(shim+이미지 제작; 액션 vocab 1:1) | **최적**(host OS 무관, HTTP만) | **E2B·cua·HUD** |
| (d) host-display virtual(`Xvfb DISPLAY=:99`) | host에 Xvfb 띄우고 pyautogui를 `:99`로 | **없음/약**(같은 커널·fs·user) | 낮음 | **macOS 작동 불가**(Quartz가 DISPLAY 무시) | **아무도 안 씀 = 현 plan** |

### 1.3 GEODE Phase E 권고 — 모델 (c) 채택, (d) 폐기

GEODE는 host-resident 에이전트(데몬이 운영자 macOS/Linux에서 실행)이고 macOS+Linux 양쪽을 지원해야 한다. frontier 합의는 명확하다 — **모델 (c): opt-in Docker(Linux) 샌드박스 + in-container HTTP/WS shim이 기존 `ComputerUseHarness`(pyautogui)를 컨테이너 안에서 구동**.

- **현 plan의 (d)("host가 `DISPLAY=:99`")는 폐기.** 격리 0(`docs/v1.0.0-stability-contract.md:143`이 이미 host=격리 0 명시)이고 macOS에서 물리적 불가(`core/tools/computer_use.py:17` Quartz API → X11 `DISPLAY` 미사용, 추론). `core/llm/adapters/_anthropic_common.py:140-141`의 "Xvfb sandbox가 display_number 설정" 주석은 틀린 멘탈모델 — sandbox 모드의 `display_number`는 *컨테이너 내부* Xvfb 디스플레이지 host가 타깃하는 게 아니다.
- **harness 변경 최소**: 액션 vocab은 이미 provider-agnostic + pyautogui 매핑(`core/tools/computer_use.py:249-307`). Phase E는 새 harness가 아니라 **transport 분기**다:
  1. `GEODE_COMPUTER_USE_ENV = host(기본) | sandbox` config (코드에 없음 — grep 0, 미구현 확인).
  2. `host`: 현행(운영자 실제 데스크탑 직접, `DANGEROUS_TOOLS` `core/agent/safety.py:68` HITL 게이트 유지).
  3. `sandbox`: GEODE가 로컬 pyautogui를 부르지 않고 — Docker 이미지(Xvfb+경량 WM+harness 래핑한 작은 HTTP/WS 서버)를 띄우고, **host harness가 thin client**가 되어 각 `aexecute(action)`을 컨테이너 `/cmd`에 POST하고 base64 screenshot을 받는다(= cua `/cmd`+`/ws`, E2B `pyautogui()` 모델). 스크린샷 모양 불변 → Phase A의 image-block 직렬화(`_serialize_computer_result`) 그대로 동작. 관측용 noVNC는 별도 채널(선택).
- **macOS 특정**: macOS host는 `DISPLAY`로 Linux Xvfb 못 몬다(확정). (c)에서는 **host가 디스플레이를 안 만지므로**(HTTP 호출만) 무관 — pyautogui는 *Linux 컨테이너 내부*에서 자기 Xvfb를 구동. (진짜 *macOS-GUI* 격리가 필요하면 Apple Virtualization/Lume macOS VM뿐 — Docker는 macOS GUI 불가 — 이건 Phase E "Docker+Xvfb" 범위 밖.)

---

## 2. command(run_bash) 샌드박스 (Phase F)

### 2.1 codex 1차 소스 판독 (`~/workspace/codex/codex-rs`)

- **플랫폼 분기**: `get_platform_sandbox()` — macOS→Seatbelt, Linux→Seccomp, 그 외→none (`sandboxing/src/manager.rs:48-62`).
- **macOS**: `/usr/bin/sandbox-exec`(하드코딩 경로 — PATH 주입 방어) `-p <sbpl> -D<K>=<v> -- <cmd>` (`seatbelt.rs:25-29,731-740`). base 프로필 `(deny default)`(`seatbelt_base_policy.sbpl:8`), write는 `/dev/null`만 기본 + writable root 동적 주입, **network 규칙 없음=기본 차단**.
- **Linux**: 기본 **bubblewrap**(`bwrap` argv에 `--unshare-net`(`linux-sandbox/src/bwrap.rs:280,326`) + full-fs read-only 정책 `--ro-bind / /` + cwd writable `--bind` + 보호 subpath 재적용 `--ro-bind <subpath>`(동일 파일 `:355-363,447-505`)) + **seccomp-bpf**(`seccompiler`로 ptrace/io_uring/socket 류 deny, `linux-sandbox/src/landlock.rs:169-267`). Landlock(0.4.4)은 legacy fallback.
- **승인/네트워크**: `AskForApproval`(`protocol/src/protocol.rs:787-818`) + 모든 `SandboxPolicy` network 기본 off(`protocol.rs:881-929`). 실패 시 escalate-retry(`core/src/tools/orchestrator.rs`).
- **crate**: `landlock=0.4.4`, `seccompiler=0.5.0` (`codex-rs/Cargo.toml:310,355`).

### 2.2 claude-code-ref — permission 모델만, OS primitive 없음

`~/workspace/claude-code-ref`에 `seatbelt|sandbox-exec|landlock|seccomp|bwrap` grep = 0. permission 모델(`PermissionMode` + `Bash(pattern)` allow/deny, `src/config/permissions.ts:56,80-98`)뿐이고 "sandbox mode"는 에이전트 프로세스 내 패턴 분석이지 커널 경계 아님. (프로덕션 Claude Code는 별도 `srt` 바이너리가 Seatbelt/bwrap 사용 — 본 ref엔 없음. 출처: [wincent gist](https://gist.github.com/wincent/2752d8d97727577050c043e4ff9e386e).)

### 2.3 primitive 비교

| primitive | 경계 | macOS | Linux | 무게 | 출처 |
|-----------|------|-------|-------|------|------|
| Seatbelt/`sandbox-exec` | TrustedBSD MAC, `.sbpl` deny-default | O(native, 단 deprecated) | X | 경량 | codex `seatbelt.rs:29`; [deprecation HN](https://news.ycombinator.com/item?id=44283454) |
| Landlock(LSM) | unprivileged fs(+최신 net) | X | O(≥5.13) | 경량 | [kernel.org](https://docs.kernel.org/userspace-api/landlock.html) |
| seccomp-bpf | syscall 필터 | X | O | 초경량 | codex `linux-sandbox/.../landlock.rs:169-267` |
| bubblewrap | user/pid/net ns + bind-mount | X | O(userns 필요, WSL1 불가) | 경량-중 | codex `bwrap.rs:280,326,355-363` |
| gVisor | user-space 커널 | X | O | 중 | [Northflank](https://northflank.com/blog/what-is-gvisor) |
| Firecracker microVM | HW 가상화(KVM) | X(KVM=Linux host) | O | 무거움(~150ms) | [Northflank](https://northflank.com/blog/firecracker-vs-gvisor) |
| Docker/OCI | ns+cgroups(공유 커널) | O(VM 경유) | O | 중-무거움 | [Unit42](https://unit42.paloaltonetworks.com/making-containers-more-isolated-an-overview-of-sandboxed-container-technologies/) |

수렴(출처 [wincent gist](https://gist.github.com/wincent/2752d8d97727577050c043e4ff9e386e)): Codex=Seatbelt(mac)/Landlock+seccomp(linux); Claude Code srt=Seatbelt(mac)/bwrap+proxy(linux); 로컬/대화형은 VM 안 씀.

### 2.4 GEODE Phase F 권고 — codex 수렴형 shell-out

GEODE는 Python(Rust 0 — `*.rs`/`Cargo.toml` 코어에 없음) → codex의 Rust crate 사용 불가 → **OS 바이너리로 shell-out**(codex가 `/usr/bin/sandbox-exec`/`bwrap` 부르는 것과 동일 형태). 삽입점 = `core/tools/bash_tool.py`의 `aexecute`(현 `asyncio.create_subprocess_shell(command, cwd=...)` + regex deny-list `validate`) — `command`를 래핑.

- **macOS**: `sandbox-exec -p <sbpl> -D WRITABLE_ROOT_0=<cwd> -- /bin/sh -c <cmd>`. codex `seatbelt_base_policy.sbpl` 본뜬 `(deny default)` + cwd(+TMPDIR) writable + network 규칙 없음.
- **Linux**: `bwrap --unshare-user --unshare-pid --unshare-net --die-with-parent --ro-bind / / --bind <cwd> <cwd> --proc /proc --dev /dev -- /bin/sh -c <cmd>`. seccomp syscall-deny는 Phase F+1(Python에서 `libseccomp` ctypes 필요 — `--unshare-net`이 이미 네트워크 차단하니 위협모델이 요구할 때만).
- **knob**: `GEODE_BASH_SANDBOX` 기본 **off**(호환) — `bwrap`은 userns 필요(WSL1/CI/하드닝 호스트 부재 가능, codex도 warn+fallback), `sandbox-exec`은 호출마다 deprecation 경고+미래 macOS에서 깨질 수 있음. 런타임에 바이너리 존재 확인(`shutil.which`/`os.path.exists`) — 부재 시 non-strict=fail-loud 경고 후 unsandboxed, strict=raise. `supports=True` 하드코딩 금지.

---

## 3. 검증 경계 (live env 필요 — `unverified — live test required`)

샌드박스의 본질은 격리이고, 격리는 정적/CI로 입증 불가다(CI에 Docker/userns 없음, 크로스플랫폼 불가). 따라서:

- **단위 테스트 가능(라이브 불요)**: argv/프로필 **builder**는 순수 함수 — codex도 이렇게 테스트(`seatbelt_tests.rs` 등). 생성된 `sandbox-exec -p ...`/`bwrap` argv에 `(deny default)`·cwd writable·`--unshare-net`·network-allow 부재가 들었는지 assert. knob 게이팅(off→원본 명령, on→래핑), 바이너리 부재 분기(monkeypatch `which`)도 단위 가능.
- **live 전용(입증 전까지 `unverified`)**: cwd 밖 쓰기 실제 차단·network 실제 차단·정상 명령 성공 — 실제 macOS(Seatbelt)/Linux+userns(bwrap) 필요. GUI Phase E도: in-container harness가 Xvfb 실제 구동·shim 왕복·noVNC 렌더는 live Docker 전용. **격리 "보장"을 입증 전 SemVer 안정/완료로 표기 금지.**

---

## 4. plan 반영

본 리서치로 `docs/plans/2026-06-14-computer-use-enhancement.md` Phase E를 모델 (d)→(c)로 정정, Phase F를 codex-수렴 shell-out으로 구체화(아래 plan 문서에 반영). 구현 시 `_anthropic_common.py:140-141` 주석도 in-container shim 모델로 수정 필요(코드 변경은 구현 PR에서).

## 출처

frontier(이번 세션 fetch/search): [Anthropic computer-use-demo](https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/README.md) · [OpenAI computer-use guide](https://developers.openai.com/api/docs/guides/tools-computer-use) · [trycua/cua](https://github.com/trycua/cua) ([WS API](https://cua.ai/docs/libraries/computer-server/WebSocket-API), [macOS Operator](https://cua.ai/blog/build-your-own-operator-on-macos-1)) · [e2b-dev/desktop](https://github.com/e2b-dev/desktop) ([computer-use docs](https://e2b.dev/docs/use-cases/computer-use)) · [Scrapybara Act SDK](https://docs.scrapybara.com/act-sdk) · [HUD](https://docs.hud.ai/) · [browser-use](https://docs.browser-use.com/examples/templates/playwright-integration) · [coding-agent-sandboxes(wincent gist)](https://gist.github.com/wincent/2752d8d97727577050c043e4ff9e386e) · [Landlock](https://docs.kernel.org/userspace-api/landlock.html) · [gVisor](https://northflank.com/blog/what-is-gvisor) · [Firecracker vs gVisor](https://northflank.com/blog/firecracker-vs-gvisor) · [sandbox-exec deprecation(HN)](https://news.ycombinator.com/item?id=44283454).
로컬 1차 소스: `~/workspace/codex/codex-rs/sandboxing/`, `~/workspace/codex/codex-rs/linux-sandbox/`, `~/workspace/claude-code-ref/src/config/permissions.ts` (file:line 본문 인용).
