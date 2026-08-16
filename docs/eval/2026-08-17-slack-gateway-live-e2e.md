---
eval_id: slack-gateway-live-e2e-20260817
eval_family: slack-gateway-live-e2e
eval_kind: ledger
eval_status: historical
eval_authority: routing-and-behavior-diagnostic
eval_summary: Three live Slack Socket Mode cases covering ordinary conversation, fail-closed computer_use, and a provider-safe browser DOM fallback.
eval_triggers:
  - Slack gateway E2E
  - Slack Socket Mode
  - browser UI
  - computer use
  - subscription route
eval_contracts:
  - docs/eval/external-artifact-repository.md
eval_latest_valid_release: https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/41e15ca262d5953d1c88f4767777331875c57c9f/reports/e2e-validation/2026-08-17-slack-gateway-live-e2e.json
---

# Slack gateway live conversation and computer-use diagnostic

## 판정

2026-08-17 KST에 PR
[#3007](https://github.com/mangowhoiscloud/geode/pull/3007)의 exact head
`e54bde2254c4503662c59d3ac2a927b2483f0573`를 프로젝트 설정으로 실행해,
Slack Socket Mode에서 들어온 세 요청을 GEODE가 직접 처리하도록 했다. 사람이
GEODE의 답변이나 tool result를 수정하지 않았다.

| Case | 결과 | 관측 |
|---|---|---|
| 일상 대화 | PASS | `gpt-5.6-sol` / Codex OAuth subscription, 1 round, 0 tools, `DAILY-CHAT-OK` |
| strict `computer_use` | BLOCKED AS DESIGNED | macOS helper 캡처 성공. OpenAI subscription source에 visual locate가 없어 provider를 몰래 바꾸지 않고 중단 |
| browser UI fallback | PASS | Playwright MCP로 실제 `example.com` 새 탭을 열고 DOM/접근성 snapshot에서 `Example Domain` 확인 |

이는 세 사례의 live behavior diagnostic이다. benchmark 점수, 신뢰구간,
provider leaderboard 또는 승격 근거가 아니며 `promotion_authority=none`이다.

## Route boundary

세 primary AgenticLoop 답변은 모두 `openai / codex-oauth / subscription` 경로를
사용했다. 다만 세 세션 모두 primary session 종료 후 Slack processor가 답을
반환하기 전에 `glm-payg` auxiliary text-completion이 한 번씩 성공했다. 따라서
**주 답변은 subscription route였지만 전체 lifecycle은 subscription-only가
아니다.** 이 경계를 숨기거나 API 비용이 없었다고 표현하면 안 된다.

## Computer-use boundary

OpenAI subscription backend에는 이 실행에서 source-safe visual grounding이
구성되지 않았다. `computer_use.capture`는 1710×1107 화면 observation을 만들었지만
function-tool wire에는 raw screenshot base64를 넣지 않는다. `locate`는 implicit GLM
fallback을 거부했고, GEODE는 좌표를 추측해 클릭하거나 타이핑하지 않았다.

웹 작업에는 같은 provider/source를 유지하면서 구조화된 browser DOM 경로를
사용할 수 있다. 다음 case에서 GEODE는 `browser_tabs`로 `https://example.com/`을
열고 `browser_snapshot`으로 URL, document title, visible H1을 교차 확인했다.
이 결과는 pixel grounding 성공이 아니라 안전한 perception-ladder fallback의
성공이다.

## Evidence

- Artifact repository PR:
  [geode-eval-artifacts#27](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/27)
- Immutable receipt:
  [`2026-08-17-slack-gateway-live-e2e.json`](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/41e15ca262d5953d1c88f4767777331875c57c9f/reports/e2e-validation/2026-08-17-slack-gateway-live-e2e.json)
- Artifact merge commit:
  [`41e15ca262d5953d1c88f4767777331875c57c9f`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/41e15ca262d5953d1c88f4767777331875c57c9f)
- Receipt SHA-256:
  `7f706bfde3b95f186caa12c3efc9f11b5dc7332c2212e3f8d0e105732e2e5fa7`
- Canonical develop merge:
  `76ca740ee39100f8477c551f125086896c03fe26`

Remote read-back from the exact artifact merge reproduced the receipt digest
and its three-case, no-promotion, non-subscription-only boundary.

## Privacy and limitations

공개 파일에는 Slack workspace/channel ID, local username/path, session ID,
credential, email/phone, provider reasoning body가 없다. Raw `messages.json`,
`tools.json`, runtime log와 screenshot body는 공개하지 않고 크기와 SHA-256만
receipt에 남겼다.

단일 macOS host와 하나의 Slack workspace에서 수행한 세 사례다. Discord,
Telegram, 다른 desktop driver, 다른 provider의 native computer tool, 로그인
페이지, destructive UI action은 범위 밖이다.
