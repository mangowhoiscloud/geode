# I2 — Paperclip 패턴 `claude -p` subprocess adapter 검토

- **Date**: 2026-05-18
- **Status**: Deferred (PAYG path 충분, 재검토 trigger 명시)
- **Decision**: 현 시점 production chat 에 `claude -p` subprocess adapter 도입 보류.

## Background

v0.99.9 까지 6회 시도된 owned-PKCE flow (`9d1c250a-…` first-party 전용 OAuth client 와 2026-04-04 Anthropic third-party block 충돌) 가 모두 실패한 후 v0.99.10 에서 `/login anthropic` 을 Anthropic Console PAYG API key path 단일화. 동시에 시도된 `claude /login` subprocess delegate 는 사용자가 spawn 된 Claude Code REPL 안에 갇히는 UX 문제로 폐기. Claude subscription path 는 Petri audit 전용 (`plugins/petri_audit/claude_code_provider.py`, in-process keychain read) 로만 잔존.

I2 의 검토 대상은 **subprocess login** 이 아닌 **subprocess invocation** — paperclip / crumb 가 채택한 `claude -p "<prompt>" --output-format stream-json` non-interactive 호출 패턴을 GEODE 의 production chat / agent loop 에 도입할지 여부.

## Current state (v0.99.13)

| 경로 | 인증 | 위치 | 상태 |
|------|------|------|------|
| Production chat / agent | `sk-ant-api…` PAYG | `core/llm/providers/anthropic.py` (stock SDK) | OK |
| Petri audit/judge | Claude subscription OAuth (keychain in-process) | `plugins/petri_audit/claude_code_provider.py` | OK (macOS only) |
| `/login anthropic` | API key 입력만 | `core/cli/commands/login.py:_login_anthropic_api_key` | OK (v0.99.10) |

## Paperclip / Crumb 패턴 분석

참조 — `~/workspace/crumb/src/adapters/claude-local.ts` (163 라인):

```ts
const args = [
  '-p', resolvePromptWithVideoRefs(req),
  '--append-system-prompt', sandwich,
  '--add-dir', req.sessionDir,
  '--dangerously-skip-permissions',
  '--output-format', 'stream-json',
  '--verbose',
];
spawn('claude', args, { cwd: req.sessionDir, env, stdio: ['ignore', 'pipe', 'pipe'] });
```

핵심 특성:
1. **Non-interactive single-turn** — `-p` 플래그로 REPL 진입 차단. login subprocess 의 UX 함정 회피.
2. **System prompt overlay** — `--append-system-prompt @<file>` 로 호출자가 role spec injection.
3. **Sandbox 경계** — `--add-dir <session_dir>` 로 working dir 제한.
4. **Stream telemetry** — `--output-format stream-json` 으로 tokens_in/out + cache + cost 회수.
5. **인증 우회 없음** — claude CLI 가 자체적으로 keychain 에서 OAuth 토큰을 읽음 (호출자는 credential 을 다루지 않음).

paperclip (`github.com/paperclipai/paperclip`) 도 동일한 ACP-style delegation 패턴이라고 GEODE 의 N1 (v0.99.10) 폐기 노트에 기록 (`core/auth/oauth_login.py:524`).

## 적용 시 트레이드오프

### Pro

- **Subscription cost-zero**. Claude Max/Pro 가입자가 PAYG 비용 없이 production chat 수행 가능. Petri 의 cost-zero path 와 동일 메커니즘.
- **Provider-managed refresh**. Claude CLI 가 자체 OAuth refresh 책임. GEODE 가 token lifecycle 코드를 보유할 필요 없음.
- **Cross-platform 향후 확장**. crumb 가 검증한 패턴 — macOS/Linux/Windows 모두 claude CLI 가 keyring 추상화 처리.

### Con

- **ToS 회색지대**. Anthropic Consumer ToS §3 (Acceptable Use) 의 "automated access" 정의가 OAuth-routed subprocess 호출에 적용되는지 모호. 문자 그대로의 위반은 없으나 정신적 위반 가능 (좁은 해석 시). 외부 배포/PR 데모/공개 호스팅에는 부적합.
- **Latency penalty**. subprocess fork + node runtime warm-up 비용 (crumb 기준 cold start ~600-800ms 추가). PAYG SDK 직접 호출 대비 perceptible.
- **Multi-turn 한계**. `-p` 는 single-turn. multi-turn conversation state 는 호출자가 prompt history 를 매 호출마다 직렬화해야 함 — GEODE 의 AgenticLoop 구조와 mismatch (현재 SDK 가 conversation state 보유).
- **Tool calling 우회**. claude CLI 의 internal tool set 과 GEODE 의 tool registry 가 충돌. GEODE 의 native tool calling (`definitions.json`) 가 subprocess 안에서 미작동.
- **Streaming surface 재구현**. SDK 의 SSE → GEODE event bus 변환 path 가 이미 hook system 에 통합되어 있는 반면, `stream-json` 라인 파싱은 별도 어댑터 작성 필요.
- **Sandbox + permission 위협**. `--dangerously-skip-permissions` 사용은 user-facing CLI 의 안전망 우회. GEODE serve 모드에서는 정책 갈등.
- **Petri 와 중복 path**. 이미 `claude_code_provider.py` 가 in-process 로 동일한 OAuth 토큰을 사용. subprocess path 추가 시 두 path 의 일관성 유지 부담.

## 결정 — Deferred

PAYG path (현재 production default) 가 cost/latency/tool-calling/multi-turn/ToS 모든 차원에서 더 단순. subscription path 의 cost-zero 매력은 cost-sensitive 사용자에게 의미 있으나, 그 use case 는 이미 Petri (audit 전용) 에서 처리. **production chat 에 subprocess adapter 도입 보류**.

## 재검토 trigger 조건

다음 중 하나가 발생하면 본 결정을 재검토:

1. **Anthropic 이 user:inference scope 또는 동등 OAuth client 를 third-party 에 공개 발급** (PKCE flow 재가능). subprocess 불필요해짐.
2. **Anthropic Consumer ToS 가 OAuth-routed automation 을 명시 허용**. ToS 회색지대 소거.
3. **claude CLI 가 multi-turn conversation state 를 외부에서 inject 가능한 API/flag 추가** (e.g. `--conversation-id`). multi-turn mismatch 해소.
4. **GEODE 사용자가 cost-zero production chat 을 강하게 요청** + 위 조건 1-2 중 하나가 충족.
5. **paperclip / crumb 이 multi-turn / tool-calling 한계를 해결한 패턴을 공개**. 참조 구현 등장.

## 작업 항목 (재검토 시)

도입 결정 시:
1. `core/llm/providers/claude_cli.py` — paperclip subprocess adapter (crumb 패턴 차용).
2. `core/llm/routing/plans.py` — `claude-cli-sub` plan kind 추가.
3. `core/cli/commands/login.py:_login_oauth_anthropic` 에 picker UX 복원 (paths: api-key / claude-cli) — 단 v0.99.9 의 REPL-trap 회피 필요.
4. ToS notice — 첫 활성화 시 사용자 경고 (정신적 위반 가능성 + 외부 배포 부적합).
5. tool calling fallback — subprocess path 에서 GEODE native tool 차단 + degrade-to-text mode.
6. E2E test — `tests/integration/test_claude_cli_adapter.py` (가능 시 mock claude CLI 사용).

## References

- Crumb claude-local adapter: `~/workspace/crumb/src/adapters/claude-local.ts:1-163`
- Paperclip: `github.com/paperclipai/paperclip`
- v0.99.10 폐기 노트: `core/auth/oauth_login.py:515-525`
- Petri provider (in-process keychain): `plugins/petri_audit/claude_code_provider.py:1-100`
- Anthropic Consumer ToS §3: `https://www.anthropic.com/legal/consumer-terms`
- Session handoff (`paperclip reference` 인용): `docs/audits/2026-05-15-session-handoff-codex-verify.md:143`
